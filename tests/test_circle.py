"""Offline circle geometry, completeness, pagination and protected API contract."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pyproj import Geod
from shapely.geometry import Point, Polygon, MultiPolygon, box

from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import CatalogueError, propose_repair
from totally_normal_maps.circle import (Budget, CircleIndex, CircleInput, CirclePredicate,
    CircleResult, CircleIncomplete, CircleUnavailable, MAX_RESPONSE_BYTES, circle_envelopes)
from tests.api_fixture import make_release

GEOD = Geod(ellps='WGS84')


def synthetic(shapes, *, missing=None, other=None, pending=None):
    rows = {uid: {'id': uid, 'level': 'municipality', 'layer': 'administrative'} for uid in shapes}
    rows.update(missing or {}); rows.update(other or {})
    review = pending or {}
    return SimpleNamespace(version='a' * 64, areas=rows, geometries=shapes,
        pending_ids=list(review), pending_shapes=list(review.values()), unknown_ids=[])


def request(lon=-75., lat=45., radius=30000, **kwargs):
    return CircleInput(longitude=lon, latitude=lat, radius_m=radius, **kwargs)


class CircleGeometryTests(unittest.TestCase):
    def ids(self, shapes, point, **kwargs):
        result = CircleIndex(synthetic(shapes, **kwargs)).lookup(point)
        self.assertIsInstance(result, CircleResult)
        return [r.id for r in result.items]

    def test_containment_partial_and_centres_outside(self):
        shapes = {'contains': box(-80, 40, -70, 50),
                  'partial': box(-74.999, 44.99, -70, 45.01),
                  'inside_circle': box(-74.998, 45, -74.997, 45.001),
                  'distant': box(-60, 40, -59, 41)}
        self.assertEqual(self.ids(shapes, request(radius=1000)), ['contains', 'inside_circle', 'partial'])

    def test_closed_circle_tangency_inside_and_outside(self):
        # At the equator the nearest point on a meridian is known independently.
        for separation, expected in ((999.9, True), (1000, True), (1000.1, False)):
            lon, _, _ = GEOD.fwd(-75, 0, 90, separation)
            with self.subTest(separation=separation):
                ids = self.ids({'edge': box(lon, -.05, lon + .01, .05)}, request(-75, 0, 1000))
                self.assertEqual(bool(ids), expected)
        # The nearest point is deep inside a long edge, not a stored vertex or
        # its midpoint. A fixed set of samples cannot establish this answer.
        _, lat, _ = GEOD.fwd(-73.33, 0, 180, 1000)
        self.assertEqual(self.ids({'long': box(-160, 0, -20, 1)}, request(-73.33, lat, 1000)), ['long'])

    def test_bbox_candidate_is_refined_and_display_is_irrelevant(self):
        geom = box(.008, .008, .009, .009)
        predicate = CirclePredicate(0, 0, 1000, Budget())
        self.assertTrue(any(geom.intersects(b) for b in predicate.boxes))
        self.assertFalse(predicate.intersects(geom))
        data = synthetic({'full': box(-75.001, 44.999, -74.999, 45.001)})
        data.displays = {'full': box(-50, 60, -49, 61)}
        self.assertEqual(CircleIndex(data).lookup(request()).total, 1)

    def test_holes_and_multipart_deduplication(self):
        outer = box(-80, 40, -70, 50)
        hole = box(-76, 44, -74, 46)
        donut = Polygon(outer.exterior.coords, [hole.exterior.coords])
        self.assertEqual(self.ids({'donut': donut}, request(radius=1000)), [])
        self.assertEqual(self.ids({'donut': donut}, request(radius=100000)), ['donut'])
        islands = MultiPolygon([box(-75.01, 45, -75.005, 45.005), box(-74.99, 45, -74.985, 45.005)])
        self.assertEqual(self.ids({'islands': islands}, request(radius=10000)), ['islands'])

    def test_northern_coordinate_linear_edges_and_poles(self):
        # A long constant-latitude edge is a parallel, not a geodesic bowing
        # towards the pole. The minimum distance is along this meridian.
        _, lat, _ = GEOD.fwd(-90, 80, 180, 30000)
        self.assertEqual(self.ids({'north': box(-120, 80, -60, 81)}, request(-90, lat, 30000)), ['north'])
        self.assertEqual(self.ids({'arctic': box(-120, 89.9, -60, 90)}, request(40, 90, 1000)), ['arctic'])
        self.assertEqual(self.ids({'arctic': box(-120, 89.9, -60, 90)}, request(40, -90, 1000)), [])

    def test_antimeridian_and_outside_centre(self):
        shapes = {'west': box(-179.99, 49.99, -179.97, 50.01)}
        self.assertEqual(self.ids(shapes, request(179.99, 50, 10000)), ['west'])
        shapes = {'canadian_side': box(-75.1, 49, -74.9, 50)}
        self.assertEqual(self.ids(shapes, request(-75, 48.99, 10000)), ['canadian_side'])
        self.assertEqual(self.ids(shapes, request(0, 0)), [])

    def test_conservative_envelopes_include_geodesic_extrema(self):
        for lon, lat in ((-75, 45), (-100, 80), (179.99, 50), (-179.99, -50), (15, 89.8), (0, -90)):
            bounds = [box(*r) for r in circle_envelopes(lon, lat, 100000)]
            for bearing in range(360):
                x, y, _ = GEOD.fwd(lon, lat, bearing, 100000)
                self.assertTrue(any(b.covers(Point(x, y)) for b in bounds), (lon, lat, bearing))

    def test_known_geodesic_witnesses_across_latitudes_and_bearings(self):
        # Independent witnesses from the forward geodesic calculation, including
        # a pole-crossing and antimeridian query. Tiny filled polygons contain
        # each witness, so every tangent or nearer polygon must be included.
        for lon, lat in ((-75, 45), (-100, 80), (179.99, 50), (20, 89.8), (-40, -80)):
            for radius in (1000, 100000):
                shapes = {}
                for bearing in range(0, 360, 30):
                    x, y, _ = GEOD.fwd(lon, lat, bearing, radius)
                    shapes[str(bearing)] = box(x - 1e-7, y - 1e-7, x + 1e-7, y + 1e-7)
                with self.subTest(lon=lon, lat=lat, radius=radius):
                    self.assertEqual(self.ids(shapes, request(lon, lat, radius)), sorted(shapes))

    def test_unapproved_repair_uses_whole_envelope_not_candidate_mask(self):
        invalid = Polygon([(-75.1, 44.9), (-74.9, 45.1), (-74.9, 44.9), (-75.1, 45.1), (-75.1, 44.9)])
        candidate, ledger = propose_repair(invalid)
        uid = 'missing'
        row = {'id': uid, 'level': 'municipality', 'repair': ledger, 'bbox': list(candidate.bounds)}
        index = CircleIndex(synthetic({}, missing={uid: row}, pending={uid: candidate}))
        self.assertEqual(index.unlocated, [])
        # North-middle is outside both candidate triangles, but inside the
        # original source envelope, so candidate nonintersection proves nothing.
        self.assertFalse(candidate.covers(Point(-75, 45.09)))
        result = index.lookup(request(-75, 45.09, 1000))
        self.assertIsInstance(result, CircleIncomplete)
        self.assertEqual(result.reasons[0].code, 'municipal_geometry_unavailable')
        self.assertEqual(index.lookup(request(0, 0)).total, 0)

    def test_lossy_or_missing_provenance_cannot_prove_absence(self):
        row = {'id': 'missing', 'level': 'municipality', 'bbox': [-76, 44, -74, 46],
               'repair': {'method': 'GEOS make_valid linework; polygon components only',
                          'nonpolygon_vertices': 2, 'source_vertices': 5, 'candidate_vertices': 6}}
        index = CircleIndex(synthetic({}, missing={'missing': row}, pending={'missing': box(-76, 44, -74, 46)}))
        result = index.lookup(request(0, 0))
        self.assertIsInstance(result, CircleIncomplete)
        self.assertEqual(result.reasons[0].code, 'municipal_extent_unlocated')

    def test_neighbourhoods_review_labels_and_historical_areas(self):
        data = synthetic({'current': box(-76, 44, -74, 46), 'old': box(-76, 44, -74, 46)},
                         other={'no-neighbourhood': {'level': 'city_area'}})
        data.areas['old']['lifecycle_status'] = 'superseded'
        data.areas['current']['issues'] = ['source_vintage_requires_review']
        result = CircleIndex(data).lookup(request())
        self.assertEqual([r.id for r in result.items], ['current'])
        self.assertEqual(result.qualification, 'review_required')
        self.assertTrue(result.coverage_complete)

    def test_boundary_difference_is_local_uncertainty(self):
        data = synthetic({'municipality': box(-76, 44, -74, 46)}, pending={'municipality': box(-74.01, 44, -74, 46)})
        index = CircleIndex(data)
        self.assertEqual(index.lookup(request(radius=1000)).total, 1)
        result = index.lookup(request(-74.005, 45, 1000))
        self.assertIsInstance(result, CircleIncomplete)
        self.assertEqual(result.reasons[0].code, 'boundary_disagreement')

    def test_cross_province_query_uses_stable_catalogue_ids(self):
        data = synthetic({'ca-csd-2400001': box(-75.01, 44.99, -75, 45.01),
                          'ca-qc-mun-10001': box(-75, 44.99, -74.99, 45.01),
                          'ca-csd-3500001': box(-75.01, 44.98, -74.99, 44.99)})
        data.areas['ca-csd-3500001']['province_id'] = 'ca-on'
        result = CircleIndex(data).lookup(request(radius=10000))
        self.assertEqual([r.id for r in result.items], sorted(data.areas))

    def test_incomplete_evidence_is_bounded_as_missing_population_grows(self):
        missing = {f'ca-csd-{i:07}': {'level': 'municipality'} for i in range(2000)}
        result = CircleIndex(synthetic({}, missing=missing)).lookup(request())
        self.assertEqual(result.affected_count, 2000)
        self.assertEqual(result.reasons[0].count, 2000)
        self.assertEqual(result.sample_area_ids, sorted(missing)[:20])
        self.assertFalse(result.sample_is_complete)
        self.assertLess(len(result.model_dump_json().encode()), 4096)

    def test_complete_pagination_exceeds_consumer_500_limit(self):
        shapes = {f'ca-csd-{i:07}': box(-76, 44, -74, 46) for i in reversed(range(620))}
        index = CircleIndex(synthetic(shapes))
        ids, offset = [], 0
        while offset is not None:
            result = index.lookup(request(offset=offset))
            self.assertEqual(result.total, 620)
            self.assertEqual(len(result.items), min(100, 620 - offset))
            self.assertLessEqual(len(result.model_dump_json().encode()), MAX_RESPONSE_BYTES)
            ids.extend(r.id for r in result.items)
            offset = result.next_offset
        self.assertEqual(ids, sorted(shapes))
        self.assertEqual(index.lookup(request(offset=620)).items, [])
        with self.assertRaises(CatalogueError):
            index.lookup(request(offset=621))

    def test_work_and_concurrency_limits_release_slots(self):
        index = CircleIndex(synthetic({'corner': box(.008, .008, .009, .009)}))
        with patch('totally_normal_maps.circle.MAX_EVALUATIONS', 0):
            with self.assertRaises(CircleUnavailable):
                index.lookup(request(0, 0, 1000))
        self.assertEqual(index.lookup(request(0, 0, 1000)).total, 0)
        index.slots.acquire(); index.slots.acquire()
        try:
            with self.assertRaisesRegex(CircleUnavailable, 'circle_query_busy'):
                index.lookup(request())
        finally:
            index.slots.release(); index.slots.release()
        with patch('totally_normal_maps.circle.MAX_SECONDS', -1):
            with self.assertRaises(CircleUnavailable):
                index.lookup(request())


class CircleAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        _, cls.release, cls.digest = make_release(Path(cls.temp.name))
        cls.settings = Settings(cls.release, cls.digest, mode='production', tokens={'test': 'a' * 40},
                                allowed_hosts=('testserver',), requests_per_minute=10000)
        cls.client = TestClient(create_app(cls.settings))
        cls.client.__enter__()
        cls.client.headers['Authorization'] = 'Bearer ' + 'a' * 40
        cls.path = '/v1/lookup/circle'

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def post(self, **changes):
        return self.client.post(self.path, json={**request(-109.5, 50.5, 1000).model_dump(), **changes})

    def test_success_envelope_and_complete_empty(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        value = response.json()
        self.assertEqual(value['dataset_version'], self.digest)
        self.assertEqual(response.headers['x-maps-dataset-version'], self.digest)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('etag', response.headers)
        self.assertEqual(value['items'], [{'id': 'ca-csd-2401001', 'level': 'municipality'}])
        self.assertEqual(value['query'], request(-109.5, 50.5, 1000).query())
        self.assertEqual(value['match_semantics'], 'area_intersects_circle')
        self.assertEqual(value['representation_revision'], 1)
        value = self.post(latitude=0, longitude=0).json()
        self.assertEqual((value['status'], value['coverage_complete'], value['total'], value['items'], value['next_offset']),
                         ('complete', True, 0, [], None))

    def test_incomplete_coverage_has_no_success_items_or_total(self):
        response = self.post(longitude=-119.5, latitude=50.5)
        self.assertEqual(response.status_code, 409)
        value = response.json()
        self.assertEqual(value['error'], 'coverage_incomplete')
        self.assertEqual(value['status'], 'incomplete')
        self.assertFalse(value['coverage_complete'])
        self.assertEqual(value['dataset_version'], self.digest)
        self.assertNotIn('items', value); self.assertNotIn('total', value)
        self.assertEqual(value['sample_area_ids'], ['ca-csd-1201001'])
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_strict_validation_and_scope(self):
        for changes in ({'latitude': True}, {'longitude': '45'}, {'latitude': 91}, {'longitude': -181},
                        {'radius_m': 999}, {'radius_m': 100001}, {'radius_m': 30000.5}, {'radius_m': True},
                        {'offset': -1}, {'offset': True}, {'offset': 100001}, {'limit': 101}, {'limit': 0},
                        {'level': 'city_area'}, {'layer': 'municipal'}, {'edition': 'unknown'}):
            with self.subTest(changes=changes):
                response = self.post(**changes)
                self.assertEqual(response.status_code, 422)
                for detail in response.json().get('details', []):
                    self.assertNotIn('input', detail)
        response = self.client.post(self.path, content='{"longitude":NaN,"latitude":45,"radius_m":30000}',
                                    headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(self.path).status_code, 405)
        self.assertEqual(self.client.post(self.path + '?radius_m=3000', json=request().model_dump()).status_code, 422)

    def test_auth_dataset_revision_and_continuations(self):
        body = request(-109.5, 50.5, 1000).model_dump()
        for headers, status in (({'Authorization': ''}, 401), ({'Authorization': 'Bearer invalid'}, 401),
            ({'If-Match': '"' + '0' * 64 + '"'}, 412), ({'If-Circle-Revision': '2'}, 412),
            ({'If-Match': '"' + self.digest + '"', 'If-Circle-Revision': '1'}, 200), ({'If-None-Match': '*'}, 200)):
            self.assertEqual(self.client.post(self.path, json=body, headers=headers).status_code, status)
        self.assertEqual(self.post(offset=1).status_code, 428)
        body['offset'] = 1
        response = self.client.post(self.path, json=body, headers={'If-Match': '"' + self.digest + '"'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'], [])
        changed = copy.copy(self.client.app.state.dataset); changed.version = 'f' * 64
        with patch.object(self.client.app.state, 'dataset', changed), patch.object(self.client.app.state, 'circles', CircleIndex(changed)):
            self.assertEqual(self.client.post(self.path, json=body, headers={'If-Match': '"' + self.digest + '"'}).status_code, 412)
            response = self.client.post(self.path, json=body, headers={'If-Match': '"' + changed.version + '"'})
            self.assertEqual(response.json()['dataset_version'], changed.version)

    def test_unavailability_and_rate_limit_do_not_become_empty_results(self):
        state = self.client.app.state
        with patch.object(state, 'circles', None):
            self.assertEqual(self.post().status_code, 503)
            self.assertEqual(self.client.post('/v1/lookup', json={'longitude': 0, 'latitude': 0}).status_code, 200)
        with patch.object(state.circles, 'lookup', side_effect=CircleUnavailable('circle_query_busy')):
            response = self.post()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['retry-after'], '5')
            self.assertNotIn('items', response.json())
        with TestClient(create_app(replace(self.settings, requests_per_minute=1))) as client:
            client.headers['Authorization'] = 'Bearer ' + 'a' * 40
            client.post('/v1/lookup', json={'longitude': 0, 'latitude': 0})
            response = client.post(self.path, json=request().model_dump())
            self.assertEqual(response.status_code, 429)
            self.assertIn('retry-after', response.headers)

    def test_body_and_response_budgets_and_duplicate_preconditions(self):
        with patch('totally_normal_maps.api.MAX_BODY_BYTES', 128):
            response = self.client.post(self.path, content=b' ' * 129, headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 413)
        with patch('totally_normal_maps.api.CIRCLE_RESPONSE_BYTES', 1):
            response = self.post()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers.get('retry-after'), '5')
            self.assertNotIn('items', response.json())
        body = request(-109.5, 50.5, 1000).model_dump()
        response = self.client.post(self.path, json=body,
                                    headers=[('If-Circle-Revision', '1'), ('If-Circle-Revision', '1')])
        self.assertEqual(response.status_code, 422)
        for first in ('"' + self.digest + '"', '"' + 'f' * 64 + '"'):
            response = self.client.post(self.path, json=body,
                headers=[('If-Match', first), ('If-Match', '"' + self.digest + '"')])
            self.assertEqual(response.status_code, 422)

    def test_index_startup_failure_preserves_other_routes_and_openapi(self):
        with patch('totally_normal_maps.api.CircleIndex', side_effect=RuntimeError('synthetic failure')):
            with self.assertLogs('totally_normal_maps.api', level='ERROR'):
                with TestClient(create_app(self.settings)) as client:
                    client.headers['Authorization'] = 'Bearer ' + 'a' * 40
                    self.assertEqual(client.post(self.path, json=request().model_dump()).status_code, 503)
                    self.assertEqual(client.post('/v1/lookup', json={'longitude': 0, 'latitude': 0}).status_code, 200)
        operation = self.client.get('/openapi.json').json()['paths'][self.path]['post']
        self.assertEqual(operation['security'], [{'BearerAuth': []}])
        self.assertIn('409', operation['responses'])
        self.assertEqual({p['name'] for p in operation['parameters']}, {'If-Match', 'If-Circle-Revision'})


if __name__ == '__main__':
    unittest.main()
