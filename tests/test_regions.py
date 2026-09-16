"""Focused regional lab regressions; synthetic geometry, no network downloads."""
import copy
from contextlib import closing
import http.client
import json
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from .test_catalogue import fixture_source  # also skips when the optional GIS stack is absent
import numpy as np
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import transform
from zipfile import ZipFile

from totally_normal_maps.catalogue import (CatalogueError, PROVINCES, build, identity_digest,
                        open_catalogue, read_json, sha256, write_json, build_province_preview, read_province_reference)
from totally_normal_maps.preview import make_server
from totally_normal_maps.regions import PLAN, build_regions, check_quebec_crosswalk, dissolve_region, validate_plan


def fixture_plan(report, rows):
    regions, decisions = [], []
    for row in rows:
        pr, cd, uid = row["PRUID"], row["CDUID"], row["CSDUID"]
        include = pr in {"11", "12", "24", "35", "59", "62"}
        if include:
            regions.append({"id": f"ca-{PROVINCES[pr][0].lower()}-cd-{cd}", "province": pr,
                "name": "Region " + pr, "kind": "Geographic region", "source_type": "CD",
                "relationship_basis": "Synthetic geographic membership", "cd_ids": [cd],
                "expected_member_count": 1, "member_identity_sha256": identity_digest([uid]),
                "source_divisions": [{"id": cd, "name": row["CDNAME"], "type": row["CDTYPE"]}]})
        decisions.append({"province": pr, "code": PROVINCES[pr][0], "status": "included" if include else "deferred",
            "reason": "Synthetic test decision", "reference_url": "https://example.invalid",
            "expected_region_count": int(include), "excluded_cd_ids": [] if include else [cd]})
    return {"schema_version": 1, "base_source_sha256": report["source"]["sha256"],
            "base_identity_sha256": report["identity_sha256"], "regions": regions,
            "expected_region_count": len(regions), "jurisdictions": decisions,
            "outline_method": "Union of member boundaries", "quebec_source": None}


class RegionalBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        source, manifest, _, rows = fixture_source(cls.root, invalid=True)
        cls.base = cls.root / "base"
        cls.base_report = build(source, cls.base, manifest_path=manifest)
        cls.plan = fixture_plan(cls.base_report, rows)
        cls.plan_path = cls.root / "plan.json"
        write_json(cls.plan_path, cls.plan)
        cls.run_path = cls.root / "regions"
        cls.report = build_regions(cls.base, cls.run_path, plan_path=cls.plan_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def members(self):
        with open_catalogue(self.base) as db:
            return {r["id"]: {**dict(r), "properties": json.loads(r["properties"])} for r in db.execute("SELECT * FROM csd")}

    def test_original_run_and_municipal_rows_remain_unchanged(self):
        self.assertEqual(sha256(self.base / "catalogue.sqlite3"), self.base_report["catalogue_sha256"])
        with open_catalogue(self.base) as base, open_catalogue(self.run_path) as result:
            self.assertEqual([tuple(r) for r in base.execute("SELECT * FROM csd ORDER BY id")],
                             [tuple(r) for r in result.execute("SELECT * FROM csd ORDER BY id")])
            self.assertEqual(result.execute("SELECT count(*) FROM region").fetchone()[0], 6)
            self.assertEqual(result.execute("SELECT count(*) FROM csd_region").fetchone()[0], 6)
        self.assertEqual(self.report["regions"]["qualification"]["activation"], "unavailable")

    def test_inherited_repair_never_becomes_approved_regional_geometry(self):
        with open_catalogue(self.run_path) as db:
            r = db.execute("SELECT * FROM region WHERE province='12'").fetchone()
        self.assertIsNone(r["geometry"])
        self.assertTrue(shapely.is_valid(shapely.from_wkb(r["repair_candidate"])))
        record = json.loads(r["record"])
        self.assertEqual(record["assignment_status"], "unreviewed_repair")
        self.assertEqual(record["unreviewed_member_ids"], ["1201001"])

    def test_preview_contains_regions_memberships_and_explicit_deferrals(self):
        data = read_json(self.run_path / "preview/catalogue.json")
        self.assertEqual(len(data["regions"]), 6)
        self.assertEqual(len(data["report"]["regions"]["jurisdictions"]), 13)
        rows = {r["id"]: r for r in data["areas"]}
        self.assertIsNone(rows["1001001"]["region_id"])
        self.assertEqual(rows["2401001"]["region_id"], "ca-qc-cd-2401")
        self.assertEqual(read_json(self.run_path / "preview/regions-10.geojson")["features"], [])
        self.assertEqual(data["report"]["regions"]["unassigned_member_count"], 7)
        provinces = read_json(self.run_path / "preview/provinces.geojson")["features"]
        self.assertEqual({p["properties"]["id"] for p in provinces}, set(PROVINCES))
        self.assertTrue(all(shapely.is_valid(shape(p["geometry"])) for p in provinces))
        self.assertEqual(next(p for p in data["provinces"] if p["id"] == "12")["assignment_status"], "unreviewed_repair")

    def test_repeat_or_nested_regional_build_is_rejected(self):
        with self.assertRaisesRegex(CatalogueError, "already exists"):
            build_regions(self.base, self.run_path, plan_path=self.plan_path)
        with self.assertRaisesRegex(CatalogueError, "cannot be extended twice"):
            build_regions(self.run_path, self.root / "nested", plan_path=self.plan_path)

    def test_cross_province_duplicate_or_unaccounted_membership_rejected(self):
        for mutation in ("cross_province", "duplicate", "missing_decision", "member_identity", "base_release"):
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(self.plan)
                if mutation == "cross_province":
                    plan["regions"][0]["cd_ids"] = ["2401"]
                elif mutation == "duplicate":
                    plan["regions"][1] = copy.deepcopy(plan["regions"][0])
                elif mutation == "missing_decision":
                    plan["jurisdictions"][0]["excluded_cd_ids"] = []
                elif mutation == "member_identity":
                    plan["regions"][0]["member_identity_sha256"] = "0" * 64
                else:
                    plan["base_source_sha256"] = "0" * 64
                with self.assertRaises(CatalogueError):
                    validate_plan(plan, self.base_report, self.members())

    def test_failed_validation_never_publishes_output(self):
        plan = copy.deepcopy(self.plan)
        plan["quebec_source"] = {"sha256": "0" * 64}
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            write_json(p / "plan.json", plan)
            with self.assertRaisesRegex(CatalogueError, "Supply the pinned"):
                build_regions(self.base, p / "failed", plan_path=p / "plan.json")
            self.assertFalse((p / "failed").exists())

    def test_regional_preview_is_read_only_and_does_not_expose_sources(self):
        with make_server(self.run_path, 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = http.client.HTTPConnection("127.0.0.1", server.server_port)
                for path, expected in [("/regions-24.geojson", 200), ("/provinces.geojson", 200), ("/regions-99.geojson", 404),
                                       ("/regional-sources/quebec.geojson", 404), ("/catalogue.sqlite3", 404)]:
                    client.request("GET", path)
                    response = client.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                client.close()
            finally:
                server.shutdown()
                thread.join()


class ProvincePreviewTests(unittest.TestCase):
    def preview(self, members):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "catalogue.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE csd (id TEXT, province TEXT, geometry BLOB, repair_candidate BLOB)")
                for i, (full, candidate) in enumerate(members):
                    db.execute("INSERT INTO csd VALUES (?, '24', ?, ?)",
                               (str(i), full.wkb if full is not None else None, candidate.wkb if candidate is not None else None))
            original = sha256(path)
            write_json(root / "report.json", {"catalogue_sha256": original})
            records = build_province_preview(root, root, 0)
            self.assertEqual(sha256(path), original)
            return next(r for r in records if r["id"] == "24"), read_json(root / "provinces.geojson")["features"]

    def test_province_dissolve_removes_internal_edges_and_preserves_holes_and_islands(self):
        first = Polygon([(-80, 45), (-79, 45), (-79, 46), (-80, 46)],
                        [[(-79.8, 45.2), (-79.2, 45.2), (-79.2, 45.8), (-79.8, 45.8)]])
        second, island = box(-79, 45, -78, 46), box(-81, 45, -80.9, 45.1)
        row, features = self.preview([(g, None) for g in [first, second, island]])
        outline = shape(features[0]["geometry"])
        self.assertEqual(row["count"], 3)
        self.assertEqual(row["assignment_status"], "validated_derived")
        self.assertEqual(len(outline.geoms), 2)
        self.assertFalse(outline.covers(Point(-79.5, 45.5)))
        self.assertTrue(outline.covers(Point(-79, 45.5)))
        self.assertLess(outline.symmetric_difference(shapely.union_all([first, second, island])).area, 1e-10)

    def test_province_display_keeps_repair_unapproved(self):
        row, features = self.preview([(box(-80, 45, -79, 46), None), (None, box(-79, 45, -78, 46))])
        self.assertEqual(row["assignment_status"], "unreviewed_repair")
        self.assertTrue(row["issues"])
        self.assertEqual(features[0]["properties"]["assignment_status"], "unreviewed_repair")

    def test_missing_member_never_publishes_partial_province(self):
        row, features = self.preview([(box(-80, 45, -79, 46), None), (None, None)])
        self.assertEqual(row["assignment_status"], "unavailable")
        self.assertEqual(row["count"], 2)
        self.assertEqual(features, [])


class ProvinceReferenceTests(unittest.TestCase):
    def reference(self, root, duplicate=False, invalid=False):
        path = root / "provinces.shp"
        forward = Transformer.from_crs(4326, 3347, always_xy=True)
        ids = list(PROVINCES)
        if duplicate:
            ids[-1] = ids[0]
        geometries = [transform(forward.transform, box(-130 + i * 5, 50, -129 + i * 5, 51)).wkb for i in range(13)]
        if invalid:
            geometries[0] = transform(forward.transform, Polygon([(-130, 50), (-129, 51), (-129, 50), (-130, 51), (-130, 50)])).wkb
        pyogrio.raw.write(path, np.array(geometries, dtype=object), [np.array(ids, dtype=object)],
                         fields=["PRUID"], driver="ESRI Shapefile", crs="EPSG:3347", geometry_type="Polygon")
        archive = root / "reference.zip"
        with ZipFile(archive, "w") as output:
            for member in root.glob("provinces.*"):
                output.write(member, member.name)
        return archive, {"sha256": sha256(archive), "member": path.name, "crs": "EPSG:3347",
                         "minimum_display_area_m2": 2000000, "display_tolerance_metres": 1000}

    def test_cartographic_reference_has_all_13_identities_and_display_only_status(self):
        with tempfile.TemporaryDirectory() as temp:
            path, manifest = self.reference(Path(temp))
            with patch("totally_normal_maps.catalogue.read_json", return_value=manifest):
                records = read_province_reference(path)
            self.assertEqual(set(records), set(PROVINCES))
            self.assertTrue(all(row["assignment_status"] == "display_reference" for row in records.values()))
            self.assertTrue(all(shapely.is_valid(row["geometry"]) for row in records.values()))

    def test_changed_reference_or_duplicate_province_is_rejected(self):
        for duplicate in [False, True]:
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as temp:
                path, manifest = self.reference(Path(temp), duplicate=duplicate)
                if not duplicate:
                    manifest["sha256"] = "0" * 64
                with patch("totally_normal_maps.catalogue.read_json", return_value=manifest):
                    with self.assertRaisesRegex(CatalogueError, "duplicate|checksum"):
                        read_province_reference(path)

    def test_cartographic_repair_stays_explicit_and_unapproved(self):
        with tempfile.TemporaryDirectory() as temp:
            path, manifest = self.reference(Path(temp), invalid=True)
            with patch("totally_normal_maps.catalogue.read_json", return_value=manifest):
                row = read_province_reference(path)["10"]
            self.assertEqual(row["assignment_status"], "unreviewed_repair")
            self.assertEqual(row["repair"]["status"], "unreviewed")
            self.assertTrue(row["issues"])
            self.assertTrue(shapely.is_valid(row["geometry"]))


class RegionalGeometryTests(unittest.TestCase):
    def definition(self):
        return {"id": "ca-on-cd-3501", "province": "35", "kind": "Geographic county", "cd_ids": ["3501"]}

    def member(self, uid, geometry, candidate=None):
        return {"id": uid, "properties": {"CDUID": "3501"}, "geometry": geometry.wkb if geometry is not None else None,
                "repair_candidate": candidate.wkb if candidate is not None else None}

    def test_dissolve_preserves_holes_islands_and_shared_edge(self):
        first = Polygon([(-80, 45), (-79, 45), (-79, 46), (-80, 46)],
                        [[(-79.8, 45.2), (-79.2, 45.2), (-79.2, 45.8), (-79.8, 45.8)]])
        second = box(-79, 45, -78, 46)
        island = box(-81, 45, -80.9, 45.1)
        rows = {str(i): self.member(str(i), g) for i, g in enumerate([first, second, island])}
        record, full, display, candidate = dissolve_region(self.definition(), rows, 200)
        self.assertIsNone(candidate)
        self.assertEqual(record["member_count"], 3)
        self.assertTrue(full.covers(Point(-79, 45.5)))
        self.assertFalse(full.covers(Point(-79.5, 45.5)))
        self.assertTrue(full.covers(Point(-80.95, 45.05)))
        self.assertTrue(shapely.is_valid(display))
        self.assertTrue(full.equals(shapely.union_all([first, second, island])))

    def test_missing_member_never_produces_partial_outline(self):
        rows = {"a": self.member("a", box(-80, 45, -79, 46)), "b": self.member("b", None)}
        record, full, display, candidate = dissolve_region(self.definition(), rows, 200)
        self.assertIsNone(full)
        self.assertIsNone(display)
        self.assertIsNone(candidate)
        self.assertEqual(record["assignment_status"], "unavailable")

    def test_quebec_ambiguous_crosswalk_and_changed_source_are_rejected(self):
        shapes = [("01", "First", box(-76, 45, -75, 46)), ("02", "Second", box(-75, 45, -74, 46)),
                  ("09", "Côte-Nord (Tracé de 1927)", box(-60, 52, -59, 53))]
        source = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
            "RES_CO_REG": code, "RES_NM_REG": name, "RES_CO_VER": "test"}, "geometry": mapping(g)} for code, name, g in shapes]}
        plan = {"regions": [{"province": "24", "name": "First", "source_region_code": "01", "cd_ids": ["2401"]},
                            {"province": "24", "name": "Second", "source_region_code": "02", "cd_ids": ["2402"]}],
                "quebec_crosswalk_evidence": [{"cd": "2401", "region": "01"}, {"cd": "2402", "region": "02"}]}
        rows = {"a": {"properties": {"CDUID": "2401"}, "geometry": box(-75.5, 45, -74.5, 46).wkb, "repair_candidate": None},
                "b": {"properties": {"CDUID": "2402"}, "geometry": box(-74.4, 45.1, -74.1, 45.4).wkb, "repair_candidate": None}}
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "quebec.geojson"
            write_json(p, source)
            plan["quebec_source"] = {"sha256": sha256(p), "release": "test", "expected_count": 3, "crs": "EPSG:4326",
                "expected_region_count": 2, "excluded_feature_name": "Côte-Nord (Tracé de 1927)"}
            with self.assertRaisesRegex(CatalogueError, "Ambiguous"):
                check_quebec_crosswalk(plan, p, rows, time.perf_counter())
            plan["quebec_source"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(CatalogueError, "checksum"):
                check_quebec_crosswalk(plan, p, rows, time.perf_counter())

    def test_real_plan_contains_known_geographic_exceptions(self):
        plan = read_json(PLAN)
        by_cd = {cd: r for r in plan["regions"] for cd in r["cd_ids"]}
        self.assertEqual(by_cd["2481"]["name"], "Outaouais")
        self.assertEqual(by_cd["2446"]["name"], "Estrie")
        self.assertEqual(by_cd["2447"]["name"], "Estrie")
        self.assertEqual(by_cd["2466"]["name"], "Montréal")
        self.assertNotIn("3506", by_cd)  # Ottawa stays municipal; no invented county.
        self.assertNotIn("3520", by_cd)  # Toronto likewise.
        self.assertNotIn("5959", by_cd)  # Northern Rockies is a municipality.
        self.assertEqual(by_cd["5957"]["kind"], "Unincorporated region")
        self.assertEqual(len([r for r in plan["regions"] if r["province"] == "13"]), 12)
