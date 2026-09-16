"""Build an immutable, review-only catalogue from a pinned StatCan GeoPackage.

Assignment geometries are full precision WGS84 WKB; display shapes are separately
simplified in the source's metre-based CRS. No application database is opened.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from zipfile import ZipFile

import pyogrio
from pyogrio.raw import read
from pyproj import CRS, Transformer
import shapely
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import transform


ROOT = Path(__file__).resolve().parent
PROVINCES = {
    "10": ("NL", "Newfoundland and Labrador"), "11": ("PE", "Prince Edward Island"),
    "12": ("NS", "Nova Scotia"), "13": ("NB", "New Brunswick"),
    "24": ("QC", "Quebec"), "35": ("ON", "Ontario"), "46": ("MB", "Manitoba"),
    "47": ("SK", "Saskatchewan"), "48": ("AB", "Alberta"),
    "59": ("BC", "British Columbia"), "60": ("YT", "Yukon"),
    "61": ("NT", "Northwest Territories"), "62": ("NU", "Nunavut"),
}
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_FEATURES = 10_000
MAX_VERTICES_PER_FEATURE = 2_000_000
MAX_TOTAL_VERTICES = 15_000_000
MAX_SECONDS = 900
# Legacy consumer editing thresholds, reported rather than applied.
EDITING_CHAR_LIMIT = 50_000
EDITING_VERTEX_LIMIT = 10_000
FIELDS = ["PRUID", "PRNAME", "CDUID", "CDNAME", "CDTYPE", "CSDUID", "CSDNAME", "CSDTYPE"]


class CatalogueError(ValueError):
    """An expected rejected input; the CLI reports it and returns nonzero."""


def sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path, max_bytes=10_000_000):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise CatalogueError("JSON input exceeds its size limit.")
    return json.loads(path.read_text(encoding="utf-8"))


def read_province_reference(path):
    manifest = read_json(ROOT / "province-display-2021.json")
    path = Path(path).resolve()
    if path.stat().st_size > MAX_SOURCE_BYTES or sha256(path) != manifest["sha256"]:
        raise CatalogueError("Province display source checksum differs from the pinned reference.")
    member = manifest["member"]
    if not re.fullmatch(r"[A-Za-z0-9_]+\.shp", member):
        raise CatalogueError("Invalid province display archive member.")
    with ZipFile(path) as archive:
        matching = [entry for entry in archive.infolist() if entry.filename == member]
        if len(matching) != 1 or matching[0].file_size > MAX_SOURCE_BYTES or matching[0].flag_bits & 1:
            raise CatalogueError("Invalid province display archive.")
    uri = f"/vsizip/{path}/{member}"
    info = pyogrio.read_info(uri)
    if info["features"] != 13 or not info["crs"] or not CRS(info["crs"]).equals(CRS(manifest["crs"])) or "PRUID" not in info["fields"]:
        raise CatalogueError("Province display identities or CRS differ from the pinned reference.")
    _, _, geometries, columns = read(uri, columns=["PRUID"])
    records = {}
    total_vertices = 0
    started = time.perf_counter()
    transformer = Transformer.from_crs(manifest["crs"], 4326, always_xy=True)
    for uid, raw in zip(columns[0], geometries):
        if uid not in PROVINCES or uid in records:
            raise CatalogueError("Invalid or duplicate province display identity.")
        geometry = shapely.from_wkb(raw)
        total_vertices += int(shapely.get_num_coordinates(geometry))
        if total_vertices > MAX_TOTAL_VERTICES or time.perf_counter() - started > MAX_SECONDS:
            raise CatalogueError("Province display exceeded its processing budget.")
        row = {"issues": [], "assignment_status": "display_reference", "display_reference_year": "2021"}
        problem = geometry_issue(geometry)
        if problem:
            if not problem.startswith("invalid_geometry:"):
                raise CatalogueError("Invalid province cartographic display geometry.")
            geometry, metrics = propose_repair(geometry)
            if geometry_issue(geometry):
                raise CatalogueError("Province display repair has no valid polygon candidate.")
            row.update({"issues": [problem, "Unapproved repair of the province display reference"],
                        "repair": metrics, "assignment_status": "unreviewed_repair"})
        # Country overview only: retain large islands/holes, omit features too
        # small for this scale. Original source stays in the private archive.
        parts = []
        for part in polygon_parts(geometry):
            if part.area >= manifest["minimum_display_area_m2"]:
                holes = [ring for ring in part.interiors if Polygon(ring).area >= manifest["minimum_display_area_m2"]]
                parts.append(Polygon(part.exterior, holes))
        display = shapely.union_all(parts).simplify(manifest["display_tolerance_metres"], preserve_topology=True)
        display = transform(transformer.transform, display)
        if geometry_issue(display):
            raise CatalogueError("Invalid simplified province cartographic display.")
        west, south, east, north = display.bounds
        if not (-142 <= west <= east <= -50 and 40 <= south <= north <= 84):
            raise CatalogueError("Unexpected province cartographic extent.")
        label = max(polygon_parts(display), key=lambda part: part.area).representative_point()
        row.update({"geometry": display, "bbox": list(display.bounds), "label_point": [label.y, label.x]})
        records[uid] = row
    return records


def build_province_preview(run, public, tolerance, province_source=None):
    """Dissolve full municipal shapes before simplifying display-only provinces.

    Candidate repairs remain labelled; this creates no assignment geometry and
    never publishes a partial outline when a member has no usable boundary.
    """
    records, features = [], []
    cartography = None
    if province_source is not None:
        if Path(province_source).stat().st_size > MAX_SOURCE_BYTES:
            raise CatalogueError("Province display archive exceeds 512 MiB.")
        retained = Path(run) / "province-source.zip"
        shutil.copyfile(province_source, retained)
        cartography = read_province_reference(retained)
    forward = Transformer.from_crs(4326, 3347, always_xy=True)
    inverse = Transformer.from_crs(3347, 4326, always_xy=True)
    started = time.perf_counter()
    with open_catalogue(run) as db:
        for uid, (code, name) in PROVINCES.items():
            if time.perf_counter() - started > MAX_SECONDS:
                raise CatalogueError("Province preview exceeded its processing budget.")
            members = db.execute("SELECT geometry, repair_candidate FROM csd WHERE province=? ORDER BY id", (uid,)).fetchall()
            pending = sum(r["geometry"] is None for r in members)
            row = {"id": uid, "code": code, "name": name, "level": "province",
                   "kind": "territory" if int(uid) >= 60 else "province",
                   "count": len(members), "issues": [], "assignment_status": "unavailable"}
            records.append(row)
            if cartography is not None:
                # This reference is only the clickable country overview. It is
                # never used for assignments or to change 2025 memberships.
                display = cartography[uid]["geometry"]
                row.update({key: value for key, value in cartography[uid].items() if key != "geometry"})
                if pending:
                    row["issues"].append(f"{pending} municipal boundaries require review")
                features.append({"type": "Feature", "properties": row.copy(), "geometry": mapping(display)})
                continue
            if pending:
                row["issues"].append(f"{pending} municipal boundaries require review; province outline is an unapproved display candidate")
            if not members or any(r["geometry"] is None and r["repair_candidate"] is None for r in members):
                row["issues"].append("Missing member geometry; no partial province outline published")
                continue
            shapes = [shapely.from_wkb(r["geometry"] or r["repair_candidate"]) for r in members]
            if any(geometry_issue(g) for g in shapes):
                raise CatalogueError("Cannot dissolve invalid province member geometry.")
            full = shapely.union_all(shapes)
            if geometry_issue(full):
                raise CatalogueError("Invalid derived province outline.")
            display = transform(inverse.transform, transform(forward.transform, full).simplify(tolerance, preserve_topology=True))
            if geometry_issue(display):
                display = full
                row["issues"].append("Display simplification rejected; displaying full geometry")
            row.update({"bbox": list(full.bounds), "assignment_status": "unreviewed_repair" if pending else "validated_derived"})
            features.append({"type": "Feature", "properties": row.copy(), "geometry": mapping(display)})
    (Path(public) / "provinces.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features},
        ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return records


def identity_digest(ids):
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode()).hexdigest()


@contextmanager
def new_directory(destination):
    """Publish only a finished artifact directory; never replace a previous run."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise CatalogueError("Output already exists. Choose a new run directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".canada-building-", dir=destination.parent) as scratch:
        staging = Path(scratch) / "run"
        staging.mkdir(mode=0o700)
        yield staging
        staging.rename(destination)


@contextmanager
def open_catalogue(run):
    path = (Path(run) / "catalogue.sqlite3").resolve()
    report = read_json(Path(run) / "report.json")
    if sha256(path) != report["catalogue_sha256"]:
        raise CatalogueError("Catalogue artifact checksum differs from its report; rebuild a fresh run.")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.row_factory = sqlite3.Row
        yield connection


def source_uri(source, manifest):
    source = Path(source).resolve()
    if not source.is_file() or source.stat().st_size > MAX_SOURCE_BYTES:
        raise CatalogueError("Expected a local source ZIP under 512 MiB.")
    if sha256(source) != manifest["sha256"]:
        raise CatalogueError("Source checksum differs from the pinned manifest; qualify a new release explicitly.")
    member = manifest["member"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.gpkg", member):
        raise CatalogueError("Manifest must name a single top-level GeoPackage.")
    with ZipFile(source) as archive:
        entries = archive.infolist()
        if sum(item.file_size for item in entries) > MAX_SOURCE_BYTES:
            raise CatalogueError("Uncompressed source exceeds 512 MiB.")
        if sum(item.filename == member for item in entries) != 1:
            raise CatalogueError("Expected exactly one manifest GeoPackage member.")
        if any(item.flag_bits & 1 for item in entries):
            raise CatalogueError("Encrypted archives are unsupported.")
    # GDAL reads only this pinned member; nothing from the ZIP is extracted.
    return f"/vsizip/{source}/{member}"


def validate_manifest(manifest):
    required = {"authority", "family", "release", "reference_date", "url", "licence", "sha256", "member", "layer", "crs", "expected_count", "identity_sha256", "province_counts"}
    if not isinstance(manifest, dict) or not required <= manifest.keys():
        raise CatalogueError("Incomplete dataset manifest.")
    for field in ("sha256", "identity_sha256"):
        if not isinstance(manifest[field], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest[field]):
            raise CatalogueError(f"Invalid {field} in manifest.")
    if manifest["crs"] != "EPSG:3347":
        raise CatalogueError("This importer qualifies only the StatCan EPSG:3347 digital CSD product.")
    counts = manifest["province_counts"]
    if not isinstance(counts, dict) or set(counts) != set(PROVINCES):
        raise CatalogueError("Manifest must cover all 13 provinces and territories.")
    if any(type(count) is not int or count <= 0 for count in counts.values()):
        raise CatalogueError("Invalid jurisdiction counts.")
    if type(manifest["expected_count"]) is not int or not 1 <= manifest["expected_count"] <= MAX_FEATURES:
        raise CatalogueError("Invalid expected feature count.")
    if sum(counts.values()) != manifest["expected_count"]:
        raise CatalogueError("Jurisdiction counts do not add up to the national count.")


def geometry_issue(geometry):
    if geometry is None or geometry.is_empty:
        return "missing_geometry"
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return "unsupported_geometry"
    if shapely.has_z(geometry):
        return "unexpected_z_coordinates"
    if not shapely.is_valid(geometry):
        return "invalid_geometry: " + shapely.is_valid_reason(geometry)
    if not all(math.isfinite(n) for n in geometry.bounds):
        return "nonfinite_coordinates"
    return None


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return [part for child in geometry.geoms for part in polygon_parts(child)]
    return []


def propose_repair(geometry):
    """Return an unapproved polygon candidate with an explicit change ledger."""
    repaired = shapely.make_valid(geometry)
    parts = polygon_parts(repaired)
    if not parts:
        return None, {"status": "no_polygon_candidate"}
    candidate = parts[0] if len(parts) == 1 else MultiPolygon(parts)
    metrics = {"status": "unreviewed", "method": "GEOS make_valid linework; polygon components only",
               "source_sha256": hashlib.sha256(geometry.wkb).hexdigest(),
               "source_area_m2": geometry.area, "candidate_area_m2": candidate.area,
               "area_change_m2": candidate.area - geometry.area,
               "source_parts": len(polygon_parts(geometry)), "candidate_parts": len(parts),
               "source_holes": sum(len(part.interiors) for part in polygon_parts(geometry)),
               "candidate_holes": sum(len(part.interiors) for part in parts),
               "source_vertices": int(shapely.get_num_coordinates(geometry)),
               "candidate_vertices": int(shapely.get_num_coordinates(candidate)),
               "nonpolygon_vertices": int(shapely.get_num_coordinates(repaired) - shapely.get_num_coordinates(candidate)),
               "candidate_sha256": hashlib.sha256(candidate.wkb).hexdigest()}
    return candidate, metrics


def feature_record(properties, geometry, transformer, tolerance):
    uid, province, division = (properties.get(k) for k in ("CSDUID", "PRUID", "CDUID"))
    if not isinstance(uid, str) or not re.fullmatch(r"\d{7}", uid):
        raise CatalogueError("A CSD has an invalid string identity.")
    if province not in PROVINCES or not uid.startswith(province):
        raise CatalogueError(f"CSD {uid} has inconsistent province identity.")
    if not isinstance(division, str) or not re.fullmatch(r"\d{4}", division) or not uid.startswith(division):
        raise CatalogueError(f"CSD {uid} has inconsistent census division identity.")
    if any(not isinstance(properties.get(k), str) or not properties[k].strip() or len(properties[k]) > 200 for k in FIELDS):
        raise CatalogueError(f"CSD {uid} has missing or oversized source attributes.")
    record = {"id": uid, "province": province, "code": PROVINCES[province][0],
              "name": properties["CSDNAME"], "type": properties["CSDTYPE"], "issues": [], "assignment_status": "unavailable"}
    vertices = int(shapely.get_num_coordinates(geometry)) if geometry is not None else 0
    if vertices > MAX_VERTICES_PER_FEATURE:
        raise CatalogueError(f"CSD {uid} exceeds the per-feature vertex budget.")
    record["vertices"] = vertices
    problem = geometry_issue(geometry)
    candidate = None
    if problem:
        record["issues"].append(problem)
        if problem.startswith("invalid_geometry:") and all(math.isfinite(n) for n in shapely.get_coordinates(geometry).ravel()):
            candidate, metrics = propose_repair(geometry)
            record["repair"] = metrics
            if candidate is None or geometry_issue(candidate):
                return record, None, None, None
        else:
            return record, None, None, None
    assignment_source = candidate if candidate is not None else geometry
    # Measure original full-coordinate serialization even when a repair is needed.
    full = transform(transformer.transform, geometry)
    record["geojson_chars"] = len(json.dumps(mapping(full), separators=(",", ":"), sort_keys=True))
    record["exceeds_editing_limits"] = record["geojson_chars"] > EDITING_CHAR_LIMIT or vertices > EDITING_VERTEX_LIMIT
    assignment = transform(transformer.transform, assignment_source)
    problem = geometry_issue(assignment)
    west, south, east, north = assignment.bounds
    # Full-extent digital northern CSDs include Arctic waters almost to the pole.
    if problem or not (-142 <= west <= east <= -50 and 40 <= south <= north <= 90):
        record["issues"].append(problem or "unexpected_canadian_extent")
        return record, None, None, None
    display = transform(transformer.transform, assignment_source.simplify(tolerance, preserve_topology=True))
    if geometry_issue(display):
        record["issues"].append("invalid_display_geometry")
        display = assignment
    record.update({"assignment_status": "unreviewed_repair" if candidate is not None else "validated_source",
                   "display_vertices": int(shapely.get_num_coordinates(display)), "bbox": list(assignment.bounds)})
    return record, assignment if candidate is None else None, display, assignment if candidate is not None else None


def build(source, destination, *, manifest_path=None, tolerance=200.0, province_source=None):
    manifest = read_json(manifest_path or ROOT / "statcan-2025.json")
    validate_manifest(manifest)
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 2000:
        raise CatalogueError("Display tolerance must be between 0 and 2,000 metres.")
    uri = source_uri(source, manifest)
    info = pyogrio.read_info(uri, layer=manifest["layer"])
    if info["driver"] != "GPKG" or not info["crs"] or not CRS(info["crs"]).equals(CRS(manifest["crs"])):
        raise CatalogueError("GeoPackage CRS differs from the manifest; coordinates cannot be relabelled.")
    if info["features"] != manifest["expected_count"] or not set(FIELDS) <= set(info["fields"]):
        raise CatalogueError("Source feature count or required attributes differ from the manifest.")
    transformer = Transformer.from_crs(manifest["crs"], "EPSG:4326", always_xy=True)
    started = time.perf_counter()
    records, ids, counts = [], set(), Counter()
    displays = {key: [] for key in PROVINCES}
    total_vertices = 0
    with new_directory(destination) as staging:
        public = staging / "preview"
        public.mkdir()
        with closing(sqlite3.connect(staging / "catalogue.sqlite3")) as db, db:
            db.execute("CREATE TABLE csd (id TEXT PRIMARY KEY, province TEXT NOT NULL, properties TEXT NOT NULL, record TEXT NOT NULL, geometry BLOB, repair_candidate BLOB)")
            for offset in range(0, info["features"], 100):
                if time.perf_counter() - started > MAX_SECONDS:
                    raise CatalogueError("Import exceeded its 15-minute processing budget.")
                meta, _, geometries, columns = read(uri, layer=manifest["layer"], columns=FIELDS, skip_features=offset, max_features=100)
                for index, raw in enumerate(geometries):
                    properties = {str(key): column[index] for key, column in zip(meta["fields"], columns)}
                    geometry = shapely.from_wkb(raw) if raw is not None else None
                    record, full, display, candidate = feature_record(properties, geometry, transformer, tolerance)
                    uid = record["id"]
                    if uid in ids:
                        raise CatalogueError(f"Duplicate CSD identity: {uid}.")
                    ids.add(uid)
                    counts[record["province"]] += 1
                    total_vertices += record.get("vertices", 0)
                    if total_vertices > MAX_TOTAL_VERTICES:
                        raise CatalogueError("Dataset exceeds the total vertex budget.")
                    records.append(record)
                    db.execute("INSERT INTO csd VALUES (?, ?, ?, ?, ?, ?)", (uid, record["province"], json.dumps(properties, ensure_ascii=False), json.dumps(record, ensure_ascii=False), full.wkb if full is not None else None, candidate.wkb if candidate is not None else None))
                    if display is not None:
                        displays[record["province"]].append({"type": "Feature", "properties": {k: record[k] for k in ("id", "name", "type", "code", "issues", "assignment_status")}, "geometry": mapping(display)})
            if len(ids) != manifest["expected_count"] or identity_digest(ids) != manifest["identity_sha256"]:
                raise CatalogueError("Source identity manifest mismatch (missing or unexpected CSDs).")
            if dict(counts) != manifest["province_counts"]:
                raise CatalogueError("Source jurisdiction distribution differs from the manifest.")
        records.sort(key=lambda row: row["id"])
        issues = [{"id": r["id"], "name": r["name"], "issues": r["issues"]} for r in records if r["issues"]]
        report = {
            "schema_version": 1, "state": "review_required" if issues else "ready_for_local_review",
            "created_at": datetime.now(timezone.utc).isoformat(), "source": manifest,
            "scope": "Draft geography only; collection and public release are not configured by this tool.",
            "feature_count": len(records), "valid_geometry_count": sum(r["assignment_status"] == "validated_source" for r in records),
            "repair_candidate_count": sum(r["assignment_status"] == "unreviewed_repair" for r in records),
            "catalogue_sha256": sha256(staging / "catalogue.sqlite3"),
            "province_counts": dict(counts), "identity_sha256": identity_digest(ids), "issues": issues,
            "total_vertices": total_vertices, "exceeds_editing_limits": sum(r.get("exceeds_editing_limits", False) for r in records),
            "max_geojson_chars": max((r.get("geojson_chars", 0) for r in records), default=0),
            "display_tolerance_metres": tolerance, "elapsed_seconds": round(time.perf_counter() - started, 3),
            "versions": {"shapely": shapely.__version__, "geos": shapely.geos_version_string, "pyogrio": pyogrio.__version__, "gdal": pyogrio.__gdal_version_string__},
            "qualification": {"feature_manifest": "passed", "geometry_validation": "failed" if issues else "passed",
                              "topology_gaps_overlaps": "not_evaluated", "existing_area_reconciliation": "not_evaluated",
                              "production_capacity": "not_evaluated", "activation": "unavailable"},
        }
        if province_source is not None:
            report["province_display_source"] = read_json(ROOT / "province-display-2021.json")
        write_json(staging / "report.json", report)
        provinces = build_province_preview(staging, public, tolerance, province_source)
        write_json(public / "catalogue.json", {"report": report, "areas": records, "provinces": provinces})
        for key, features in displays.items():
            # Compact display-only payload; full precision remains in the SQLite artifact.
            (public / f"{key}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        shutil.copyfile(source, staging / "source.zip")
        if sha256(staging / "source.zip") != manifest["sha256"]:
            raise CatalogueError("Source changed during the import.")
        for name in ("index.html", "preview.js", "preview.css"):
            shutil.copyfile(ROOT / "web" / name, public / name)
        vendor = ROOT / "vendor" / "leaflet"
        for name in ("leaflet.js", "leaflet.css"):
            shutil.copyfile(vendor / name, public / name)
    return report
