"""Focused synthetic city-area import, parent-link and preview isolation tests."""
import copy
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from .test_catalogue import fixture_source  # skips cleanly without the optional GIS stack
import shapely
from shapely.geometry import Polygon, box, mapping

from totally_normal_maps.catalogue import CatalogueError, PROVINCES, identity_digest, open_catalogue, read_json, sha256, write_json
from totally_normal_maps.city_areas import build_city_areas, validate_plan
from totally_normal_maps.preview import make_server


class CityAreaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        public = self.base / "preview"
        public.mkdir(parents=True)
        self.parent_id = "2481017"
        self.parent = box(-76, 45, -75, 46)
        record = {"id": self.parent_id, "province": "24", "name": "Gatineau", "code": "QC", "type": "V", "issues": []}
        with closing(sqlite3.connect(self.base / "catalogue.sqlite3")) as db, db:
            db.execute("CREATE TABLE csd (id TEXT PRIMARY KEY, province TEXT, properties TEXT, record TEXT, geometry BLOB, repair_candidate BLOB)")
            db.execute("INSERT INTO csd VALUES (?, '24', '{}', ?, ?, NULL)", (self.parent_id, json.dumps(record), self.parent.wkb))
            db.execute("CREATE TABLE region (id TEXT PRIMARY KEY, record TEXT)")
            db.execute("INSERT INTO region VALUES ('ca-qc-ra-07', ?)", (json.dumps({"id": "ca-qc-ra-07", "province": "24", "name": "Outaouais"}),))
            db.execute("CREATE TABLE csd_region (csd_id TEXT PRIMARY KEY, region_id TEXT)")
            db.execute("INSERT INTO csd_region VALUES (?, 'ca-qc-ra-07')", (self.parent_id,))
        self.report = {"source": {"sha256": "a" * 64}, "identity_sha256": identity_digest([self.parent_id]),
                       "catalogue_sha256": sha256(self.base / "catalogue.sqlite3"), "feature_count": 1,
                       "regions": {"feature_count": 1}, "issues": []}
        write_json(self.base / "report.json", self.report)
        write_json(public / "catalogue.json", {"provinces": [{"id": pr} for pr in PROVINCES]})
        (public / "24.geojson").write_text('{"type":"FeatureCollection","features":[]}')
        (self.base / "source.zip").write_bytes(b"synthetic retained source")
        self.plan = {"schema_version": 1, "base_source_sha256": self.report["source"]["sha256"],
                     "base_identity_sha256": self.report["identity_sha256"], "expected_count": 2,
                     "sources": {"gatineau": {"crs": "EPSG:4326", "expected_count": 2}},
                     "municipalities": [{"parent_csd_id": self.parent_id, "name": "Gatineau", "expected_count": 2, "coverage_policy": "citywide"}], "areas": []}
        features = []
        for code, name, geom in [("20", "Hull", box(-76, 45, -75.5, 46)), ("25", "Aylmer", box(-75.5, 45, -75, 46))]:
            props = {"MUNID": 81017, "CODEID": code, "NOM": name, "TYPE": "Ex ville", "ENTITEID": code}
            self.plan["areas"].append({"id": f"ca-qc-2481017-sector-{code}", "source": "gatineau", "source_id": code,
                "parent_csd_id": self.parent_id, "parent_name": "Gatineau", "name": name, "kind": "sector", "type": "Secteur", "expected_properties": props})
            features.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
        self.payload = {"type": "FeatureCollection", "features": features}
        self.source = self.root / "gatineau.geojson"
        self.plan_path = self.root / "plan.json"
        self.save_inputs()

    def save_inputs(self):
        write_json(self.source, self.payload)
        self.plan["sources"]["gatineau"]["sha256"] = sha256(self.source)
        write_json(self.plan_path, self.plan)

    def build(self, name="output", **kwargs):
        return build_city_areas(self.base, self.root / name, sources={"gatineau": self.source}, plan_path=self.plan_path, **kwargs)

    def members(self):
        with open_catalogue(self.base) as db:
            return {r["id"]: dict(r) for r in db.execute("SELECT * FROM csd")}

    def test_additive_artifact_preserves_parents_and_complete_source_shapes(self):
        report = self.build()
        self.assertEqual(sha256(self.base / "catalogue.sqlite3"), self.report["catalogue_sha256"])
        with open_catalogue(self.base) as before, open_catalogue(self.root / "output") as after:
            for table in ("csd", "region", "csd_region"):
                self.assertEqual([tuple(r) for r in before.execute(f"SELECT * FROM {table}")], [tuple(r) for r in after.execute(f"SELECT * FROM {table}")])
            result = after.execute("SELECT * FROM city_area ORDER BY id").fetchall()
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["geometry"], shapely.geometry.shape(self.payload["features"][0]["geometry"]).wkb)
        data = read_json(self.root / "output/preview/catalogue.json")
        self.assertEqual({r["type"] for r in data["city_areas"]}, {"Secteur"})
        self.assertEqual(data["areas"][0]["region_id"], "ca-qc-ra-07")
        self.assertEqual(sha256(self.root / "output/city-area-sources/gatineau.geojson"), sha256(self.source))
        self.assertEqual((self.root / "output/preview/24.geojson").read_bytes(), (self.base / "preview/24.geojson").read_bytes())
        self.assertEqual(report["city_areas"]["qualification"]["activation"], "unavailable")

    def test_checksum_mismatch_and_repeat_build_never_overwrite(self):
        self.source.write_text(self.source.read_text() + " ")
        with self.assertRaisesRegex(CatalogueError, "checksum"):
            self.build()
        self.assertFalse((self.root / "output").exists())
        self.save_inputs(); self.build()
        with self.assertRaisesRegex(CatalogueError, "already exists"):
            self.build()
        with self.assertRaisesRegex(CatalogueError, "without city areas"):
            build_city_areas(self.root / "output", self.root / "nested", sources={"gatineau": self.source}, plan_path=self.plan_path)

    def test_quebec_arrondissement_version_and_identity_are_pinned(self):
        self.plan["sources"] = {"quebec": {"crs": "EPSG:4326", "expected_count": 2, "release": "VTEST"}}
        for index, row in enumerate(self.plan["areas"], 1):
            code = f"REM{index:02d}"
            props = {"ARS_CO_ARR": code, "ARS_NM_ARR": row["name"], "ARS_NM_MUN": "Gatineau", "ARS_CO_VER": "VTEST"}
            row.update(source="quebec", source_id=code, id=f"ca-qc-arr-{code.lower()}", kind="arrondissement", type="Arrondissement", expected_properties=props)
            self.payload["features"][index-1]["properties"] = dict(props)
        write_json(self.source, self.payload)
        self.plan["sources"]["quebec"]["sha256"] = sha256(self.source)
        write_json(self.plan_path, self.plan)
        kwargs = {"sources": {"quebec": self.source}, "plan_path": self.plan_path}
        report = build_city_areas(self.base, self.root / "quebec", **kwargs)
        self.assertEqual(report["city_areas"]["kind_counts"], {"arrondissement": 2})
        # Even an explicitly re-pinned download cannot change the source version
        # or source parent/name without updating and reviewing the identity plan.
        for field in ("ARS_CO_VER", "ARS_NM_MUN", "ARS_NM_ARR"):
            payload = copy.deepcopy(self.payload)
            payload["features"][0]["properties"][field] = "Changed"
            write_json(self.source, payload)
            self.plan["sources"]["quebec"]["sha256"] = sha256(self.source)
            write_json(self.plan_path, self.plan)
            with self.assertRaisesRegex(CatalogueError, "source identity"):
                build_city_areas(self.base, self.root / field, **kwargs)

    def test_plan_rejects_duplicate_wrong_parent_type_or_release(self):
        for change in ("duplicate", "parent", "type", "base", "count", "crs"):
            with self.subTest(change=change):
                plan = copy.deepcopy(self.plan)
                if change == "duplicate": plan["areas"][1] = copy.deepcopy(plan["areas"][0])
                elif change == "parent": plan["areas"][0]["parent_csd_id"] = "3506008"
                elif change == "type": plan["areas"][0]["kind"] = "electoral_district"
                elif change == "base": plan["base_source_sha256"] = "b" * 64
                elif change == "count": plan["municipalities"][0]["expected_count"] = 3
                else: plan["sources"]["gatineau"]["crs"] = "EPSG:3857"
                with self.assertRaises(CatalogueError): validate_plan(plan, self.report, self.members())

    def test_source_rejects_changed_identity_duplicates_missing_and_transfer_limits(self):
        original = copy.deepcopy(self.payload)
        for change in ("name", "parent", "duplicate", "missing", "transfer", "crs"):
            with self.subTest(change=change):
                self.payload = copy.deepcopy(original)
                if change == "name": self.payload["features"][0]["properties"]["NOM"] = "Changed"
                elif change == "parent": self.payload["features"][0]["properties"]["MUNID"] = 66023
                elif change == "duplicate": self.payload["features"][1] = copy.deepcopy(self.payload["features"][0])
                elif change == "missing": self.payload["features"].pop()
                elif change == "transfer": self.payload["exceededTransferLimit"] = True
                else: self.payload["crs"] = {"properties": {"name": "EPSG:3857"}}
                self.save_inputs()
                with self.assertRaises(CatalogueError): self.build(change)
                self.assertFalse((self.root / change).exists())

    def test_invalid_geometry_and_wrong_coordinate_extent_fail_closed(self):
        for name, geom in [("invalid", Polygon([(-76,45),(-75,46),(-75,45),(-76,46),(-76,45)])), ("extent", box(1,1,2,2))]:
            self.payload["features"][0]["geometry"] = mapping(geom); self.save_inputs()
            with self.assertRaises(CatalogueError): self.build(name)
            self.assertFalse((self.root / name).exists())

    def test_wrong_spatial_parent_and_sibling_overlaps_rejected(self):
        for name, geom in [("wrong-parent", box(-70,45,-69.5,46)), ("overlap", box(-76,45,-75.4,46))]:
            self.payload["features"][0]["geometry"] = mapping(geom); self.save_inputs()
            with self.assertRaisesRegex(CatalogueError, "disagrees|siblings overlap"): self.build(name)

    def test_partial_coverage_is_explicit_but_not_a_fake_remainder_area(self):
        self.payload["features"][0]["geometry"] = mapping(box(-76,45,-75.9,46))
        self.payload["features"][1]["geometry"] = mapping(box(-75.9,45,-75.8,46))
        self.save_inputs()
        with self.assertRaisesRegex(CatalogueError, "incomplete citywide"): self.build("failed")
        self.plan["municipalities"][0]["coverage_policy"] = "partial"; self.save_inputs()
        report = self.build()
        self.assertEqual(report["city_areas"]["feature_count"], 2)
        self.assertAlmostEqual(report["city_areas"]["municipalities"][0]["covered_parent_fraction"], .2, places=2)

    def test_parent_repair_is_disclosed_without_rewriting_valid_child_shapes(self):
        with closing(sqlite3.connect(self.base / "catalogue.sqlite3")) as db, db:
            db.execute("UPDATE csd SET repair_candidate=geometry, geometry=NULL")
        self.report["catalogue_sha256"] = sha256(self.base / "catalogue.sqlite3")
        write_json(self.base / "report.json", self.report)
        report = self.build()
        self.assertTrue(report["city_areas"]["municipalities"][0]["parent_uses_unreviewed_repair"])
        data = read_json(self.root / "output/preview/catalogue.json")
        self.assertTrue(all(r["issues"] and r["assignment_status"] == "validated_source" for r in data["city_areas"]))

    def test_small_parent_drift_is_measured_and_not_clipped(self):
        self.payload["features"][0]["geometry"] = mapping(box(-76.02,45,-75.5,46)); self.save_inputs()
        self.build()
        data = read_json(self.root / "output/preview/catalogue.json")["city_areas"][0]
        self.assertGreater(data["parent_overlap"]["outside_fraction"], .01)
        self.assertEqual(data["bbox"][0], -76.02)
        self.assertTrue(data["issues"])

    def test_preview_serves_only_fixed_display_file(self):
        self.build()
        with make_server(self.root / "output", 0) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                for path, expected in [("/city-areas-24.geojson", 200), ("/city-areas-35.geojson", 404),
                    ("/city-area-sources/gatineau.geojson", 404), ("/city-area-sources/plan.json", 404), ("/catalogue.sqlite3", 404)]:
                    connection.request("GET", path); response = connection.getresponse()
                    self.assertEqual(response.status, expected); response.read()
                connection.close()
            finally: server.shutdown()

    def test_tolerance_and_source_size_budgets(self):
        for tolerance in (float('nan'), -1, 201):
            with self.assertRaises(CatalogueError): self.build(tolerance=tolerance)
        from unittest.mock import patch
        with patch('totally_normal_maps.city_areas.MAX_CITY_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(CatalogueError, 'byte budget'): self.build()
