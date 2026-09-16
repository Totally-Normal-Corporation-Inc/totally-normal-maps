"""Focused tests: python -m unittest totally_normal_maps.tests -v."""
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

try:
    import pyogrio.raw
    from pyproj import Transformer
except ModuleNotFoundError as exc:
    if exc.name not in {"pyogrio", "pyproj", "numpy"}:
        raise
    raise unittest.SkipTest("Optional Canada lab dependencies are not installed; see tools/canada_catalogue/requirements.txt") from exc

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import transform

from totally_normal_maps import catalogue
from totally_normal_maps.benchmark import benchmark, compare_postgis, postgis_options
from totally_normal_maps.catalogue import CatalogueError, PROVINCES, build, feature_record, identity_digest, open_catalogue, read_json, sha256, write_json
from totally_normal_maps.preview import make_server
from totally_normal_maps.reconcile import reconcile


def fixture_source(root, *, crs="EPSG:3347", duplicate=False, invalid=False, wrong_identity=False):
    source = root / "source.zip"
    forward = Transformer.from_crs("EPSG:4326", "EPSG:3347", always_xy=True)
    shapes, rows = [], []
    for index, province in enumerate(PROVINCES):
        lon = -130 + index * 5
        if index == 0:
            shape = Polygon([(lon, 50), (lon+1, 50), (lon+1, 51), (lon, 51)],
                            [[(lon+.3, 50.3), (lon+.7, 50.3), (lon+.7, 50.7), (lon+.3, 50.7)]])
        elif index == 1:
            shape = MultiPolygon([box(lon, 50, lon+.5, 50.5), box(lon+.7, 50.7, lon+.8, 50.8)])
        elif invalid and index == 2:
            shape = Polygon([(lon, 50), (lon+1, 51), (lon+1, 50), (lon, 51), (lon, 50)])
        else:
            shape = box(lon, 50, lon+1, 51)
        shapes.append(transform(forward.transform, shape))
        uid = province + "01001"
        if wrong_identity and index == 0:
            uid = province + "01002"
        rows.append({"PRUID": province, "PRNAME": PROVINCES[province][1], "CDUID": province+"01", "CDNAME": "Division", "CDTYPE": "CD", "CSDUID": uid, "CSDNAME": "Gatineau" if province == "24" else "Sample "+province, "CSDTYPE": "V"})
    if duplicate:
        rows[-1] = dict(rows[-2])
    gpkg = root / "fixture.gpkg"
    pyogrio.raw.write(gpkg, np.array([s.wkb for s in shapes], dtype=object),
                      [np.array([r[field] for r in rows], dtype=object) for field in catalogue.FIELDS],
                      fields=catalogue.FIELDS, driver="GPKG", layer="csd", crs=crs,
                      geometry_type="Unknown")
    with ZipFile(source, "w") as archive:
        archive.write(gpkg, "fixture.gpkg")
    manifest = {"authority": "Synthetic test", "family": "CSD", "release": "test", "reference_date": "2025-01-01", "url": "https://example.invalid/fixture", "licence": "test", "sha256": sha256(source), "member": "fixture.gpkg", "layer": "csd", "crs": "EPSG:3347", "expected_count": 13, "identity_sha256": identity_digest([province+"01001" for province in PROVINCES]), "province_counts": {key: 1 for key in PROVINCES}}
    write_json(root / "manifest.json", manifest)
    return source, root / "manifest.json", shapes, rows


class CatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source, cls.manifest, cls.shapes, cls.rows = fixture_source(cls.root)
        cls.run_path = cls.root / "run"
        cls.report = build(cls.source, cls.run_path, manifest_path=cls.manifest)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_complete_manifest_and_original_are_retained(self):
        self.assertEqual(self.report["feature_count"], 13)
        self.assertEqual(self.report["valid_geometry_count"], 13)
        self.assertEqual(self.report["state"], "ready_for_local_review")
        self.assertEqual(sha256(self.run_path / "source.zip"), sha256(self.source))
        self.assertEqual(self.report["qualification"]["activation"], "unavailable")
        self.assertEqual(self.report["qualification"]["topology_gaps_overlaps"], "not_evaluated")

    def test_full_geometry_transformed_without_losing_holes_or_islands(self):
        inverse = Transformer.from_crs(3347, 4326, always_xy=True)
        with open_catalogue(self.run_path) as db:
            rows = db.execute("SELECT id, geometry FROM csd ORDER BY id").fetchall()
        full = shapely.from_wkb(rows[0]["geometry"])
        self.assertEqual(len(full.interiors), 1)
        self.assertTrue(full.equals_exact(transform(inverse.transform, self.shapes[0]), 1e-10))
        self.assertFalse(full.covers(Point(-129.5, 50.5)))
        self.assertEqual(len(shapely.from_wkb(rows[1]["geometry"]).geoms), 2)

    def test_reader_cannot_write_catalogue(self):
        with open_catalogue(self.run_path) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM csd")

    def test_repeat_import_never_replaces_previous_run(self):
        original = sha256(self.run_path / "catalogue.sqlite3")
        with self.assertRaisesRegex(CatalogueError, "Output already exists"):
            build(self.source, self.run_path, manifest_path=self.manifest)
        self.assertEqual(original, sha256(self.run_path / "catalogue.sqlite3"))

    def test_same_source_builds_same_assignments_and_display(self):
        with tempfile.TemporaryDirectory() as root:
            second = Path(root) / "repeat"
            build(self.source, second, manifest_path=self.manifest)
            self.assertEqual(sha256(second / "catalogue.sqlite3"), sha256(self.run_path / "catalogue.sqlite3"))
            self.assertEqual(sha256(second / "preview/10.geojson"), sha256(self.run_path / "preview/10.geojson"))

    def test_failed_processing_leaves_no_completed_run(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "failed"
            with patch.object(catalogue, "feature_record", side_effect=RuntimeError("unexpected parser failure")):
                with self.assertRaisesRegex(RuntimeError, "unexpected parser failure"):
                    build(self.source, output, manifest_path=self.manifest)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_checksum_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = read_json(self.manifest)
            manifest["sha256"] = "0" * 64
            path = Path(root) / "manifest.json"
            write_json(path, manifest)
            with self.assertRaisesRegex(CatalogueError, "checksum"):
                build(self.source, Path(root) / "run", manifest_path=path)

    def test_same_count_with_different_identity_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source, manifest, _, _ = fixture_source(Path(root), wrong_identity=True)
            with self.assertRaisesRegex(CatalogueError, "identity manifest mismatch"):
                build(source, Path(root) / "run", manifest_path=manifest)
            self.assertFalse((Path(root) / "run").exists())

    def test_duplicate_identity_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source, manifest, _, _ = fixture_source(Path(root), duplicate=True)
            with self.assertRaisesRegex(CatalogueError, "Duplicate CSD"):
                build(source, Path(root) / "run", manifest_path=manifest)

    def test_wrong_source_crs_is_never_relabelled(self):
        with tempfile.TemporaryDirectory() as root:
            source, manifest, _, _ = fixture_source(Path(root), crs="EPSG:4326")
            with self.assertRaisesRegex(CatalogueError, "CRS differs"):
                build(source, Path(root) / "run", manifest_path=manifest)

    def test_invalid_shape_is_visible_and_not_repaired(self):
        with tempfile.TemporaryDirectory() as root:
            source, manifest, _, _ = fixture_source(Path(root), invalid=True)
            output = Path(root) / "run"
            report = build(source, output, manifest_path=manifest)
            self.assertEqual(report["state"], "review_required")
            self.assertEqual(report["valid_geometry_count"], 12)
            self.assertEqual(report["repair_candidate_count"], 1)
            self.assertEqual(report["issues"][0]["id"], "1201001")
            with open_catalogue(output) as db:
                self.assertIsNone(db.execute("SELECT geometry FROM csd WHERE id='1201001'").fetchone()[0])
                self.assertIsNotNone(db.execute("SELECT repair_candidate FROM csd WHERE id='1201001'").fetchone()[0])
            with self.assertRaisesRegex(CatalogueError, "invalid assignment"):
                benchmark(output, count=20, rounds=2)
            fixture = Path(root) / "points.json"
            write_json(fixture, [{"label": "outside", "lon": 0, "lat": 0, "expected_ids": []}])
            comparison = benchmark(output, count=20, rounds=2, fixtures_path=fixture, include_repair_candidates=True)
            self.assertEqual(comparison["status"], "passed")
            self.assertFalse(comparison["geography_qualified"])
            self.assertEqual(comparison["unreviewed_repair_candidates_used"], 1)

    def test_large_shapes_are_preserved_and_editor_limits_reported(self):
        shape = Point(6000000, 2000000).buffer(1000, quad_segs=3000)
        record, full, display, candidate = feature_record(self.rows[0], shape, Transformer.from_crs(3347, 4326, always_xy=True), 100)
        self.assertTrue(record["exceeds_editing_limits"])
        self.assertGreater(record["vertices"], 10_000)
        self.assertEqual(shapely.get_num_coordinates(full), shapely.get_num_coordinates(shape))
        self.assertLess(shapely.get_num_coordinates(display), shapely.get_num_coordinates(full))
        self.assertIsNone(candidate)

    def test_northern_digital_extents_above_85_degrees_are_valid(self):
        forward = Transformer.from_crs(4326, 3347, always_xy=True)
        northern = transform(forward.transform, box(-115, 86, -110, 89))
        record, full, _, candidate = feature_record(self.rows[-1], northern, Transformer.from_crs(3347, 4326, always_xy=True), 200)
        self.assertEqual(record["issues"], [])
        self.assertIsNotNone(full)
        self.assertIsNone(candidate)

    def test_modified_artifact_cannot_be_compared_under_old_report(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "report.json").write_bytes((self.run_path / "report.json").read_bytes())
            (root / "catalogue.sqlite3").write_bytes(b"modified artifact")
            with self.assertRaisesRegex(CatalogueError, "checksum differs"):
                with open_catalogue(root):
                    self.fail("Modified geometry must not be opened")

    def test_invalid_province_identity_rejected(self):
        row = {**self.rows[0], "PRUID": "24"}
        with self.assertRaisesRegex(CatalogueError, "inconsistent province"):
            feature_record(row, self.shapes[0], Transformer.from_crs(3347, 4326, always_xy=True), 200)

    def test_benchmark_compares_holes_edges_islands_and_interior(self):
        fixtures = [
            {"label": "hole", "lon": -129.5, "lat": 50.5, "expected_ids": []},
            {"label": "island", "lon": -124.25, "lat": 50.75, "expected_ids": ["1101001"]},
            {"label": "outside", "lon": 0, "lat": 0, "expected_ids": []},
        ]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "points.json"
            write_json(path, fixtures)
            report = benchmark(self.run_path, count=20, rounds=2, fixtures_path=path)
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["postgis"], "not_evaluated")
        self.assertEqual(report["engines"]["bbox_loop"]["first_pass"]["queries"], 20)
        self.assertIn("source_vertex", {p["kind"] for p in report["points"]})

    def test_wrong_expected_membership_fails_benchmark(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "points.json"
            write_json(path, [{"label": "wrong", "lon": 0, "lat": 0, "expected_ids": ["1001001"]}])
            report = benchmark(self.run_path, count=20, rounds=2, fixtures_path=path)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any(f["reason"] == "fixture_mismatch" for f in report["failures"]))

    def test_reconciliation_preserves_sector_even_when_name_matches_city(self):
        snapshot = [
            {"id": "province", "kind": "province", "code": "QC", "parent_id": None, "names": ["Québec"]},
            {"id": "city", "kind": "municipality", "parent_id": "province", "names": ["Gatineau"]},
            {"id": "sector", "kind": "sector", "parent_id": "city", "names": ["Gatineau"]},
        ]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "areas.json"
            write_json(path, snapshot)
            report = reconcile(self.run_path, path)
            sector, city = report["results"][2], report["results"][1]
            self.assertEqual(sector["status"], "preserve_existing_layer")
            self.assertIn("name_collision_is_not_municipal_identity", sector["issues"])
            self.assertEqual(city["status"], "candidate_requires_identity_review")
            self.assertEqual(city["candidate_csd_ids"], ["2401001"])
            snapshot[0]["code"] = "ON"
            write_json(path, snapshot)
            self.assertEqual(reconcile(self.run_path, path)["results"][1]["candidate_csd_ids"], [])

    def test_loopback_postgis_guard_rejects_other_databases_and_service_files(self):
        for dsn in ("host=production dbname=maps_lab", "host=127.0.0.1 dbname=application", "service=production", "host=127.0.0.1 hostaddr=8.8.8.8 dbname=maps_lab"):
            with self.subTest(dsn=dsn), self.assertRaises(CatalogueError):
                postgis_options(dsn)
        self.assertEqual(postgis_options("host=127.0.0.1 dbname=maps_lab")["dbname"], "maps_lab")

    def test_postgis_failure_rolls_back_temporary_work_and_closes_connection(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("PostGIS test fixture",)
        with patch("psycopg2.connect", return_value=connection) as connect, patch("psycopg2.extras.execute_values", side_effect=RuntimeError("load failed")):
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                compare_postgis(["1001001"], [box(-80, 45, -79, 46)], [{"lon": -79.5, "lat": 45.5}], 2, "host=127.0.0.1 dbname=maps_lab")
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()
        self.assertEqual(connect.call_args.kwargs["hostaddr"], "127.0.0.1")
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any(sql.startswith("CREATE TEMP TABLE") for sql in statements))
        self.assertFalse(any("CREATE EXTENSION" in sql or "CREATE DATABASE" in sql for sql in statements))

    def test_preview_only_serves_whitelisted_display_artifacts(self):
        with make_server(self.run_path, 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                for path, status in (("/", 200), ("/catalogue.json", 200), ("/10.geojson", 200), ("/provinces.geojson", 200),
                                     ("/../catalogue.sqlite3", 404), ("/%2e%2e/source.zip", 404), ("/source.zip", 404), ("/", 403)):
                    headers = {"Host": "evil.example"} if status == 403 else {}
                    connection.request("GET", path, headers=headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
                    response.read()
                connection.request("POST", "/", body="{}")
                self.assertEqual(connection.getresponse().status, 501)
                connection.close()
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
