"""Add explicitly selected regional groupings to a fresh, local review artifact.

Outlines are dissolved from complete CSD members, keeping the national boundary
vintage consistent. Membership is geographic, not municipal jurisdiction.
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

from .catalogue import (
    CatalogueError, EDITING_CHAR_LIMIT, EDITING_VERTEX_LIMIT, MAX_SECONDS,
    MAX_TOTAL_VERTICES, MAX_VERTICES_PER_FEATURE, PROVINCES, ROOT,
    geometry_issue, identity_digest, new_directory, open_catalogue, read_json,
    sha256, write_json, build_province_preview,
)

PLAN = ROOT / "regions-2026-09.json"
MAX_REGION_SOURCE_BYTES = 64 * 1024 * 1024


def validate_plan(plan, report, members):
    if plan.get("schema_version") != 1:
        raise CatalogueError("Unsupported regional plan version.")
    if (plan.get("base_source_sha256") != report["source"]["sha256"] or
            plan.get("base_identity_sha256") != report["identity_sha256"]):
        raise CatalogueError("Regional plan does not match the base municipality release.")
    if len(members) != report["feature_count"] or identity_digest(members) != report["identity_sha256"]:
        raise CatalogueError("Base municipality identities differ from the checked report.")
    divisions = {}
    for row in members.values():
        p = row["properties"]
        key = (p["PRUID"], p["CDNAME"], p["CDTYPE"])
        if p["CDUID"] in divisions and divisions[p["CDUID"]] != key:
            raise CatalogueError("Inconsistent source census-division metadata.")
        divisions[p["CDUID"]] = key
    regions = plan.get("regions", [])
    if not 1 <= len(regions) <= 1000 or len(regions) != plan.get("expected_region_count"):
        raise CatalogueError("Regional feature count differs from the plan.")
    ids, assigned = set(), set()
    for region in regions:
        uid, province = region["id"], region["province"]
        if (province not in PROVINCES or not re.fullmatch(r"ca-[a-z]{2}-(cd-\d{4}|ra-\d{2})", uid)
                or not uid.startswith(f"ca-{PROVINCES[province][0].lower()}-")):
            raise CatalogueError("Invalid regional identity or province.")
        if uid in ids:
            raise CatalogueError("Duplicate regional identity.")
        ids.add(uid)
        for field in ("name", "kind", "source_type", "relationship_basis"):
            if not isinstance(region.get(field), str) or not 1 <= len(region[field]) <= 500:
                raise CatalogueError("Missing or oversized regional label.")
        cds = region["cd_ids"]
        if not cds or len(set(cds)) != len(cds) or assigned.intersection(cds):
            raise CatalogueError("Duplicate or empty regional census-division membership.")
        for cd in cds:
            if cd not in divisions or divisions[cd][0] != province:
                raise CatalogueError("Missing or cross-province regional membership.")
        expected = [{"id": cd, "name": divisions[cd][1], "type": divisions[cd][2]} for cd in cds]
        if region["source_divisions"] != expected:
            raise CatalogueError("Regional census-division attributes changed.")
        assigned.update(cds)
        member_ids = [uid for uid, row in members.items() if row["properties"]["CDUID"] in cds]
        if (len(member_ids) != region["expected_member_count"] or
                identity_digest(member_ids) != region["member_identity_sha256"]):
            raise CatalogueError("Regional member identity manifest mismatch.")
    jurisdictions = plan["jurisdictions"]
    if len(jurisdictions) != 13 or {j["province"] for j in jurisdictions} != set(PROVINCES):
        raise CatalogueError("The regional decision ledger must cover all 13 jurisdictions.")
    for entry in jurisdictions:
        pr = entry["province"]
        count = sum(r["province"] == pr for r in regions)
        if count != entry["expected_region_count"]:
            raise CatalogueError("Regional jurisdiction count mismatch.")
        skipped = sorted(cd for cd, p in divisions.items() if p[0] == pr and cd not in assigned)
        if skipped != entry["excluded_cd_ids"]:
            raise CatalogueError("An unassigned census division is missing from the decision ledger.")
        if entry["status"] not in {"included", "partial", "deferred"} or not entry["reason"]:
            raise CatalogueError("Regional decisions need explicit statuses and reasons.")
        if ((entry["status"] == "included" and (not count or skipped)) or
                (entry["status"] == "deferred" and count) or
                (entry["status"] == "partial" and (not count or not skipped))):
            raise CatalogueError("Regional coverage status contradicts the selected divisions.")


def check_quebec_crosswalk(plan, source, members, started):
    """Recheck each pinned QC division against the independent SDA polygons.

    A generous minimum accommodates different river/coastal boundaries. Actual
    fractions are reported; this is evidence for review, not automatic approval.
    """
    manifest = plan.get("quebec_source")
    if not manifest:
        return []
    if manifest.get("crs") != "EPSG:4326":
        raise CatalogueError("Québec crosswalk source must be WGS84 GeoJSON.")
    if source is None or sha256(source) != manifest["sha256"]:
        raise CatalogueError("Québec source checksum differs from the regional manifest.")
    data = read_json(source, MAX_REGION_SOURCE_BYTES)
    if (data.get("type") != "FeatureCollection" or data.get("exceededTransferLimit") or
            len(data.get("features", [])) != manifest["expected_count"]):
        raise CatalogueError("Incomplete Québec region source.")
    forward = Transformer.from_crs(4326, 3347, always_xy=True)
    shapes, excluded, vertices = {}, 0, 0
    expected = {r["source_region_code"]: r for r in plan["regions"] if r["province"] == "24"}
    for feature in data["features"]:
        props = feature["properties"]
        if props["RES_CO_VER"] != manifest["release"]:
            raise CatalogueError("Québec regional source version changed.")
        if props["RES_NM_REG"] == manifest["excluded_feature_name"] and props["RES_CO_REG"] == "09":
            excluded += 1
            continue
        code = props["RES_CO_REG"]
        if code in shapes or code not in expected or props["RES_NM_REG"] != expected[code]["name"]:
            raise CatalogueError("Unexpected or duplicate Québec regional identity.")
        geom = shape(feature["geometry"])
        vertices += int(shapely.get_num_coordinates(geom))
        if vertices > MAX_TOTAL_VERTICES or geometry_issue(geom):
            raise CatalogueError("Invalid Québec source geometry or vertex budget exceeded.")
        west, south, east, north = geom.bounds
        if not (-81 <= west <= east <= -56 and 44 <= south <= north <= 64):
            raise CatalogueError("Québec geometry is not in the expected WGS84 extent.")
        shapes[code] = transform(forward.transform, geom)
    if excluded != 1 or set(shapes) != set(expected) or len(shapes) != manifest["expected_region_count"]:
        raise CatalogueError("Incomplete Québec regional identity set.")
    evidence = plan["quebec_crosswalk_evidence"]
    planned = {cd: r["source_region_code"] for r in expected.values() for cd in r["cd_ids"]}
    if len(evidence) != len(planned) or {r["cd"]: r["region"] for r in evidence} != planned:
        raise CatalogueError("Québec crosswalk evidence differs from planned membership.")
    results = []
    for cd, code in sorted(planned.items()):
        if time.perf_counter() - started > MAX_SECONDS:
            raise CatalogueError("Regional build exceeded its processing budget.")
        geometries = []
        for row in members.values():
            if row["properties"]["CDUID"] == cd:
                wkb = row["geometry"] or row["repair_candidate"]
                if wkb is None:
                    raise CatalogueError("Québec crosswalk cannot be checked with missing member geometry.")
                geometries.append(transform(forward.transform, shapely.from_wkb(wkb)))
        division = shapely.union_all(geometries)
        scores = sorted(((division.intersection(g).area / division.area, key)
                         for key, g in shapes.items() if division.intersects(g)), reverse=True)
        runner_up = scores[1][0] if len(scores) > 1 else 0
        if not scores or scores[0][1] != code or scores[0][0] < .90 or runner_up > .10:
            raise CatalogueError(f"Ambiguous Québec regional crosswalk for division {cd}.")
        results.append({"cd": cd, "region": code, "overlap_fraction": scores[0][0],
                        "runner_up_fraction": runner_up, "status": "evidence_for_review"})
    return results


def dissolve_region(definition, members, tolerance):
    rows = [row for row in members.values() if row["properties"]["CDUID"] in definition["cd_ids"]]
    row = {**definition, "code": PROVINCES[definition["province"]][0], "type": definition["kind"],
           "level": "region", "member_count": len(rows), "issues": [], "assignment_status": "unavailable"}
    pending = [r["id"] for r in rows if r["geometry"] is None]
    missing = [r["id"] for r in rows if r["geometry"] is None and r["repair_candidate"] is None]
    row["unreviewed_member_ids"] = pending
    if pending:
        row["issues"].append(f"{len(pending)} member boundaries require review; regional geometry is an unapproved candidate")
    if missing:
        row["issues"].append("Missing member geometry; no partial regional outline published")
        return row, None, None, None
    shapes = [shapely.from_wkb(r["geometry"] or r["repair_candidate"]) for r in rows]
    if any(geometry_issue(g) for g in shapes):
        raise CatalogueError("Cannot dissolve an invalid assignment or repair candidate.")
    full = shapely.union_all(shapes)
    issue = geometry_issue(full)
    if issue:
        row["issues"].append(issue)
        return row, None, None, None
    vertices = int(shapely.get_num_coordinates(full))
    if vertices > MAX_VERTICES_PER_FEATURE:
        raise CatalogueError("Region exceeds the per-feature vertex budget.")
    forward = Transformer.from_crs(4326, 3347, always_xy=True)
    inverse = Transformer.from_crs(3347, 4326, always_xy=True)
    display = transform(inverse.transform, transform(forward.transform, full).simplify(tolerance, preserve_topology=True))
    if geometry_issue(display):
        display = full
        row["issues"].append("Display simplification rejected; displaying full geometry")
    chars = len(json.dumps(mapping(full), separators=(",", ":")))
    row.update({"vertices": vertices, "bbox": list(full.bounds), "geojson_chars": chars,
                "display_vertices": int(shapely.get_num_coordinates(display)),
                "exceeds_editing_limits": chars > EDITING_CHAR_LIMIT or vertices > EDITING_VERTEX_LIMIT,
                "assignment_status": "unreviewed_repair" if pending else "validated_derived"})
    return row, None if pending else full, display, full if pending else None


def build_regions(run, destination, *, quebec_source=None, plan_path=None, tolerance=200.0, province_source=None):
    run = Path(run)
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 2000:
        raise CatalogueError("Display tolerance must be between 0 and 2,000 metres.")
    plan_path = Path(plan_path or PLAN)
    plan = read_json(plan_path)
    base_report = read_json(run / "report.json")
    if "regions" in base_report:
        raise CatalogueError("Use an original municipality run; regional runs cannot be extended twice.")
    started = time.perf_counter()
    with open_catalogue(run) as connection:
        members = {r["id"]: {**dict(r), "properties": json.loads(r["properties"])}
                   for r in connection.execute("SELECT * FROM csd ORDER BY id")}
    validate_plan(plan, base_report, members)
    with new_directory(destination) as staging:
        sources = staging / "regional-sources"
        sources.mkdir()
        write_json(sources / "plan.json", plan)
        checked_source = None
        if plan.get("quebec_source"):
            if quebec_source is None or Path(quebec_source).stat().st_size > MAX_REGION_SOURCE_BYTES:
                raise CatalogueError("Supply the pinned Québec GeoJSON under 64 MiB.")
            checked_source = sources / "quebec.geojson"
            shutil.copyfile(quebec_source, checked_source)
        qc_evidence = check_quebec_crosswalk(plan, checked_source, members, started)
        public = staging / "preview"
        public.mkdir()
        for name in ["source.zip", "catalogue.sqlite3"]:
            shutil.copyfile(run / name, staging / name)
        if (sha256(staging / "catalogue.sqlite3") != base_report["catalogue_sha256"] or
                sha256(staging / "source.zip") != base_report["source"]["sha256"]):
            raise CatalogueError("Base artifact changed during regional build.")
        records, displays, memberships = [], {pr: [] for pr in PROVINCES}, {}
        total_vertices = 0
        with closing(sqlite3.connect(staging / "catalogue.sqlite3")) as db, db:
            db.execute("CREATE TABLE region (id TEXT PRIMARY KEY, province TEXT NOT NULL, record TEXT NOT NULL, geometry BLOB, repair_candidate BLOB)")
            db.execute("CREATE TABLE csd_region (csd_id TEXT PRIMARY KEY REFERENCES csd(id), region_id TEXT NOT NULL REFERENCES region(id), basis TEXT NOT NULL)")
            db.execute("CREATE INDEX csd_region_region ON csd_region(region_id)")
            db.execute("PRAGMA foreign_keys=ON")
            for definition in plan["regions"]:
                if time.perf_counter() - started > MAX_SECONDS:
                    raise CatalogueError("Regional build exceeded its processing budget.")
                record, full, display, candidate = dissolve_region(definition, members, tolerance)
                total_vertices += record.get("vertices", 0)
                if total_vertices > MAX_TOTAL_VERTICES:
                    raise CatalogueError("Regional dataset exceeds its vertex budget.")
                records.append(record)
                db.execute("INSERT INTO region VALUES (?, ?, ?, ?, ?)", (record["id"], record["province"],
                           json.dumps(record, ensure_ascii=False), full.wkb if full is not None else None,
                           candidate.wkb if candidate is not None else None))
                for uid, row in members.items():
                    if row["properties"]["CDUID"] in definition["cd_ids"]:
                        memberships[uid] = record["id"]
                        db.execute("INSERT INTO csd_region VALUES (?, ?, ?)", (uid, record["id"], definition["relationship_basis"]))
                if display is not None:
                    displays[record["province"]].append({"type": "Feature", "properties": {
                        key: record[key] for key in ("id", "name", "type", "code", "issues", "assignment_status")},
                        "geometry": mapping(display)})
        decisions = []
        for item in plan["jurisdictions"]:
            ids = [uid for uid, row in members.items() if row["province"] == item["province"]]
            decisions.append({**item, "member_count": sum(uid in memberships for uid in ids),
                              "unassigned_member_count": sum(uid not in memberships for uid in ids)})
        regional_report = {
            "state": "draft_for_local_review", "feature_count": len(records),
            "plan_sha256": sha256(sources / "plan.json"), "outline_method": plan["outline_method"],
            "sources": [base_report["source"]] + ([plan["quebec_source"]] if plan.get("quebec_source") else []),
            "province_counts": dict(Counter(r["province"] for r in records)), "jurisdictions": decisions,
            "geometry_status_counts": dict(Counter(r["assignment_status"] for r in records)),
            "issues": [{"id": r["id"], "name": r["name"], "issues": r["issues"]} for r in records if r["issues"]],
            "membership_count": len(memberships), "unassigned_member_count": len(members) - len(memberships),
            "quebec_crosswalk_evidence": qc_evidence,
            "qualification": {"source_identity": "passed", "quebec_crosswalk": "evidence_for_review" if qc_evidence else "not_applicable",
                              "geographic_not_governance_membership": True, "topology_gaps_overlaps": "not_evaluated",
                              "production_approval": "not_evaluated", "activation": "unavailable"},
            "created_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        report = {**base_report, "schema_version": 2, "state": "review_required",
                  "base_catalogue_sha256": base_report["catalogue_sha256"], "regions": regional_report,
                  "catalogue_sha256": sha256(staging / "catalogue.sqlite3")}
        # The country overview may use a separately pinned cartographic source.
        # Do not inherit a prior run's display-source claim when none is supplied.
        report.pop("province_display_source", None)
        if province_source is not None:
            report["province_display_source"] = read_json(ROOT / "province-display-2021.json")
        write_json(staging / "report.json", report)
        # Generate display metadata from the checked database, not an editable preview JSON.
        areas = [json.loads(r["record"]) for r in members.values()]
        for row in areas:
            row["region_id"] = memberships.get(row["id"])
            row["level"] = "municipality"
        provinces = build_province_preview(staging, public, tolerance, province_source)
        write_json(public / "catalogue.json", {"report": report, "areas": areas, "regions": records,
                   "provinces": provinces})
        for pr in PROVINCES:
            # Retain the prior simplified municipality display; check its identities.
            previous = run / "preview" / f"{pr}.geojson"
            # Municipality shapes are display-only; full assignments remain in the checked DB.
            payload = read_json(previous, MAX_REGION_SOURCE_BYTES)
            expected = {uid for uid, r in members.items() if r["province"] == pr and (r["geometry"] or r["repair_candidate"])}
            actual = [f["properties"]["id"] for f in payload["features"]]
            if len(actual) != len(set(actual)) or set(actual) != expected:
                raise CatalogueError("Municipality preview identities differ from the base catalogue.")
            for feature in payload["features"]:
                feature["properties"]["region_id"] = memberships.get(feature["properties"]["id"])
            for name, features in [(f"{pr}.geojson", payload["features"]), (f"regions-{pr}.geojson", displays[pr])]:
                (public / name).write_text(json.dumps({"type": "FeatureCollection", "features": features},
                    ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        for name in ("index.html", "preview.js", "preview.css"):
            shutil.copyfile(ROOT / "web" / name, public / name)
        for name in ("leaflet.js", "leaflet.css"):
            shutil.copyfile(ROOT / "vendor" / "leaflet" / name, public / name)
    return report
