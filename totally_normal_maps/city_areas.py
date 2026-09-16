"""Pinned Québec city subdivisions for the disposable local geography lab.

Source boundaries remain intact. Parent/child drift is measured in EPSG:3347;
no snapping, clipping, inferred neighbourhoods or application writes occur.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import time

from pyproj import Transformer
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import transform

from .catalogue import (CatalogueError, MAX_SECONDS, MAX_TOTAL_VERTICES,
                        MAX_VERTICES_PER_FEATURE, PROVINCES, ROOT, geometry_issue,
                        identity_digest, new_directory, open_catalogue, read_json,
                        sha256, write_json)

PLAN = ROOT / "city-areas-quebec-2026-09.json"
MAX_CITY_SOURCE_BYTES = 16 * 1024 * 1024
# Reject grossly wrong parent links. Smaller differences remain review evidence,
# including water/shoreline differences between independent boundary releases.
MIN_CHILD_PARENT_OVERLAP = .90
REVIEW_OUTSIDE_FRACTION = .01
MIN_CITYWIDE_COVERAGE = .90


def validate_plan(plan, report, members):
    if (plan.get("schema_version") != 1 or
            plan.get("base_source_sha256") != report["source"]["sha256"] or
            plan.get("base_identity_sha256") != report["identity_sha256"] or
            identity_digest(members) != report["identity_sha256"]):
        raise CatalogueError("City-area plan does not match the checked municipality release.")
    areas = plan.get("areas", [])
    if not 1 <= len(areas) <= 1000 or len(areas) != plan.get("expected_count"):
        raise CatalogueError("City-area count differs from the plan.")
    sources = plan.get("sources", {})
    if not sources or not set(sources) <= {"quebec", "gatineau"}:
        raise CatalogueError("Unsupported city-area source.")
    parents, ids, source_ids = {}, set(), set()
    for parent in plan.get("municipalities", []):
        uid = parent["parent_csd_id"]
        if (uid in parents or uid not in members or members[uid]["province"] != "24" or
                json.loads(members[uid]["record"])["name"] != parent["name"] or
                parent.get("coverage_policy") not in {"partial", "citywide"}):
            raise CatalogueError("Invalid, duplicate or changed city-area parent.")
        parents[uid] = parent
    for row in areas:
        key, code, uid = row["source"], row["source_id"], row["parent_csd_id"]
        if key not in sources or uid not in parents or row["parent_name"] != parents[uid]["name"]:
            raise CatalogueError("Unknown source or city-area parent.")
        if (row["id"] in ids or (key, code) in source_ids or
                not re.fullmatch(r"ca-qc-(arr-re[a-z][0-9]{2}|2481017-sector-[0-9]{1,2})", row["id"])):
            raise CatalogueError("Duplicate or invalid city-area identity.")
        ids.add(row["id"]); source_ids.add((key, code))
        props = row["expected_properties"]
        if key == "quebec":
            correct = (row["id"] == f"ca-qc-arr-{code.lower()}" and row["kind"] == "arrondissement" and
                       row["type"] == "Arrondissement" and props.get("ARS_CO_ARR") == code and
                       props.get("ARS_NM_ARR") == row["name"] and props.get("ARS_NM_MUN") == row["parent_name"] and
                       props.get("ARS_CO_VER") == sources[key]["release"])
        else:
            correct = (uid == "2481017" and row["id"] == f"ca-qc-2481017-sector-{code}" and
                       row["kind"] == "sector" and row["type"] == "Secteur" and props.get("CODEID") == code and
                       props.get("NOM") == row["name"] and props.get("MUNID") == 81017 and props.get("TYPE") == "Ex ville")
        if not correct or not isinstance(row["name"], str) or not 1 <= len(row["name"]) <= 200:
            raise CatalogueError("City-area identity, type or source attributes disagree.")
    for key, source in sources.items():
        if source.get("crs") != "EPSG:4326" or source.get("expected_count") != sum(r["source"] == key for r in areas):
            raise CatalogueError("City-area source CRS or count mismatch.")
    for uid, parent in parents.items():
        if parent["expected_count"] != sum(r["parent_csd_id"] == uid for r in areas) or not parent["expected_count"]:
            raise CatalogueError("City-area parent count mismatch.")


def read_source(path, key, manifest, definitions):
    path = Path(path)
    if path.stat().st_size > MAX_CITY_SOURCE_BYTES or sha256(path) != manifest["sha256"]:
        raise CatalogueError("City-area source checksum or byte budget mismatch.")
    data = read_json(path, MAX_CITY_SOURCE_BYTES)
    if (data.get("type") != "FeatureCollection" or data.get("exceededTransferLimit") or
            len(data.get("features", [])) != manifest["expected_count"] or data.get("crs") is not None):
        raise CatalogueError("Incomplete city-area source or unexpected GeoJSON CRS declaration.")
    expected = {r["source_id"]: r for r in definitions if r["source"] == key}
    result, total = {}, 0
    for feature in data["features"]:
        props = feature["properties"]
        code = props.get("ARS_CO_ARR" if key == "quebec" else "CODEID")
        if code not in expected or code in result or any(props.get(k) != v for k, v in expected[code]["expected_properties"].items()):
            raise CatalogueError("Changed, duplicate or unexpected city-area source identity.")
        geom = shape(feature["geometry"])
        vertices = int(shapely.get_num_coordinates(geom)); total += vertices
        if vertices > MAX_VERTICES_PER_FEATURE or total > MAX_TOTAL_VERTICES or geometry_issue(geom):
            raise CatalogueError("Invalid city-area geometry or vertex budget exceeded; qualify a new source explicitly.")
        west, south, east, north = geom.bounds
        if not (-81 <= west <= east <= -56 and 44 <= south <= north <= 64):
            raise CatalogueError("City-area source is outside the expected WGS84 Québec extent.")
        result[code] = geom
    if set(result) != set(expected):
        raise CatalogueError("Incomplete city-area identity set.")
    return result


def check_relationships(records, projected, members, parents, forward):
    evidence = []
    for parent in parents:
        uid = parent["parent_csd_id"]
        member = members[uid]
        wkb = member["geometry"] or member["repair_candidate"]
        if wkb is None:
            raise CatalogueError("Cannot check city areas without a complete parent boundary.")
        full = transform(forward.transform, shapely.from_wkb(wkb))
        if geometry_issue(full):
            raise CatalogueError("Invalid parent geometry for city-area comparison.")
        children = [r for r in records if r["parent_csd_id"] == uid]
        for row in children:
            g = projected[row["id"]]
            outside = g.difference(full).area
            fraction = outside / g.area
            if fraction > 1 - MIN_CHILD_PARENT_OVERLAP:
                raise CatalogueError(f"City-area boundary disagrees with its parent: {row['id']}.")
            row["parent_overlap"] = {"outside_m2": outside, "outside_fraction": fraction,
                                     "parent_uses_unreviewed_repair": member["geometry"] is None,
                                     "status": "evidence_for_review"}
            if fraction > REVIEW_OUTSIDE_FRACTION:
                row["issues"].append(f"{fraction:.1%} of this source boundary falls outside the national city boundary; review the source difference")
            if member["geometry"] is None:
                row["issues"].append("Parent comparison uses an unapproved municipal repair candidate")
        union = shapely.union_all([projected[r["id"]] for r in children])
        coverage = union.intersection(full).area / full.area
        overlap = max(0, sum(projected[r["id"]].area for r in children) - union.area)
        if parent["coverage_policy"] == "citywide" and coverage < MIN_CITYWIDE_COVERAGE:
            raise CatalogueError(f"Unexpectedly incomplete citywide coverage for {uid}.")
        if overlap > max(1, union.area * .000001):
            raise CatalogueError(f"City-area siblings overlap for {uid}; review source topology.")
        evidence.append({**parent, "covered_parent_fraction": coverage,
                         "uncovered_parent_m2": full.difference(union).area,
                         "outside_parent_m2": union.difference(full).area,
                         "sibling_overlap_m2": overlap,
                         "parent_uses_unreviewed_repair": member["geometry"] is None,
                         "status": "evidence_for_review"})
    return evidence


def build_city_areas(run, destination, *, sources, plan_path=None, tolerance=20.0):
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 200:
        raise CatalogueError("City-area display tolerance must be between 0 and 200 metres.")
    run = Path(run)
    plan = read_json(plan_path or PLAN)
    base_report = read_json(run / "report.json")
    if "city_areas" in base_report or "regions" not in base_report:
        raise CatalogueError("Use a regional run without city areas.")
    if set(sources) != set(plan["sources"]):
        raise CatalogueError("Supply each pinned city-area source.")
    started = time.perf_counter()
    with open_catalogue(run) as db:
        members = {r["id"]: dict(r) for r in db.execute("SELECT * FROM csd ORDER BY id")}
        regions = [json.loads(r["record"]) for r in db.execute("SELECT * FROM region ORDER BY id")]
        membership = dict(db.execute("SELECT csd_id, region_id FROM csd_region"))
    validate_plan(plan, base_report, members)
    forward = Transformer.from_crs(4326, 3347, always_xy=True)
    inverse = Transformer.from_crs(3347, 4326, always_xy=True)
    with new_directory(destination) as staging:
        # Preserve complete prior sources/displays without expensive new dissolves.
        if any(p.is_symlink() for p in run.rglob("*")):
            raise CatalogueError("A base run may not contain symlinks.")
        shutil.copytree(run, staging, dirs_exist_ok=True)
        if sha256(staging / "catalogue.sqlite3") != base_report["catalogue_sha256"]:
            raise CatalogueError("Base catalogue changed during the city-area build.")
        source_dir = staging / "city-area-sources"
        source_dir.mkdir()
        write_json(source_dir / "plan.json", plan)
        shapes = {}
        for key, source in plan["sources"].items():
            if Path(sources[key]).stat().st_size > MAX_CITY_SOURCE_BYTES:
                raise CatalogueError("City-area source exceeds its byte budget.")
            snapshot = source_dir / f"{key}.geojson"
            shutil.copyfile(sources[key], snapshot)
            shapes[key] = read_source(snapshot, key, source, plan["areas"])
        records, displays, projected = [], [], {}
        for definition in plan["areas"]:
            if time.perf_counter() - started > MAX_SECONDS:
                raise CatalogueError("City-area build exceeded its processing budget.")
            full = shapes[definition["source"]][definition["source_id"]]
            metric = transform(forward.transform, full)
            if geometry_issue(metric):
                raise CatalogueError("Invalid projected city-area geometry.")
            projected[definition["id"]] = metric
            display = transform(inverse.transform, metric.simplify(tolerance, preserve_topology=True))
            if geometry_issue(display):
                display = full
            row = {**definition, "province": "24", "code": "QC", "level": "city_area",
                   "region_id": membership.get(definition["parent_csd_id"]),
                   "assignment_status": "validated_source", "issues": [], "bbox": list(full.bounds),
                   "vertices": int(shapely.get_num_coordinates(full)),
                   "display_vertices": int(shapely.get_num_coordinates(display))}
            records.append(row)
            displays.append({"type": "Feature", "properties": {k: row[k] for k in ("id", "name", "type", "parent_csd_id")},
                             "geometry": mapping(display)})
        coverage = check_relationships(records, projected, members, plan["municipalities"], forward)
        with closing(sqlite3.connect(staging / "catalogue.sqlite3")) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("CREATE TABLE city_area (id TEXT PRIMARY KEY, parent_csd_id TEXT NOT NULL REFERENCES csd(id), record TEXT NOT NULL, geometry BLOB NOT NULL)")
            db.execute("CREATE INDEX city_area_parent ON city_area(parent_csd_id)")
            for row in records:
                full = shapes[row["source"]][row["source_id"]]
                db.execute("INSERT INTO city_area VALUES (?, ?, ?, ?)",
                           (row["id"], row["parent_csd_id"], json.dumps(row, ensure_ascii=False), full.wkb))
        report = {**base_report, "schema_version": 3, "state": "review_required",
                  "city_area_base_catalogue_sha256": base_report["catalogue_sha256"],
                  "catalogue_sha256": sha256(staging / "catalogue.sqlite3"),
                  "city_areas": {"state": "draft_for_local_review", "feature_count": len(records),
                      "municipality_count": len(coverage), "kind_counts": dict(Counter(r["kind"] for r in records)),
                      "sources": plan["sources"], "plan_sha256": sha256(source_dir / "plan.json"),
                      "municipalities": coverage, "display_tolerance_metres": tolerance,
                      "issues": [{"id": r["id"], "name": r["name"], "issues": r["issues"]} for r in records if r["issues"]],
                      "qualification": {"source_identity": "passed", "source_geometry": "passed",
                          "parent_comparison": "evidence_for_review", "production_approval": "not_evaluated", "activation": "unavailable"},
                      "created_at": datetime.now(timezone.utc).isoformat(),
                      "elapsed_seconds": round(time.perf_counter() - started, 3)}}
        public = staging / "preview"
        previous = read_json(public / "catalogue.json")
        if {r["id"] for r in previous["provinces"]} != set(PROVINCES):
            raise CatalogueError("Incomplete base province preview.")
        areas = [{**json.loads(r["record"]), "level": "municipality", "region_id": membership.get(uid)} for uid, r in members.items()]
        write_json(staging / "report.json", report)
        write_json(public / "catalogue.json", {"report": report, "areas": areas, "regions": regions,
                                              "provinces": previous["provinces"], "city_areas": records})
        write_json(public / "city-areas-24.geojson", {"type": "FeatureCollection", "features": displays})
        for name in ("index.html", "preview.js", "preview.css"):
            shutil.copyfile(ROOT / "web" / name, public / name)
    return report
