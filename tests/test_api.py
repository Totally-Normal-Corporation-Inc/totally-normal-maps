from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import shapely

from totally_normal_maps.api import MAX_BODY_BYTES, Settings, create_app
from totally_normal_maps.catalogue import CatalogueError
from .api_fixture import make_release


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.run_path, cls.release, cls.digest = make_release(cls.temp.name)
        cls.settings = Settings(cls.release, cls.digest, requests_per_minute=10000)
        cls.client = TestClient(create_app(cls.settings), base_url='http://localhost', client=('127.0.0.1', 12345))
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def test_health_and_contract(self):
        self.assertEqual(self.client.get('/healthz').json(), {'status': 'ok'})
        self.assertEqual(self.client.get('/readyz').status_code, 200)
        spec = self.client.get('/openapi.json').json()
        self.assertEqual(spec['paths']['/v1/lookup']['post']['security'], [{'BearerAuth': []}])
        self.assertIn('BatchInput', spec['components']['schemas'])
        self.assertEqual(self.client.get('/v1/datasets/current').json()['qualification'], 'review_required')

    def test_complete_hierarchy_and_namespaced_ids(self):
        self.assertEqual(self.client.get('/v1/countries').json()['items'][0]['id'], 'ca')
        provinces = self.client.get('/v1/areas/ca/children').json()
        self.assertEqual(provinces['total'], 13)
        self.assertEqual(provinces['dataset_version'], self.digest)
        regions = self.client.get('/v1/areas/ca-qc/children').json()
        self.assertEqual([r['id'] for r in regions['items']], ['ca-qc-test-region'])
        municipalities = self.client.get('/v1/areas/ca-qc-test-region/children').json()
        self.assertEqual(municipalities['items'][0]['id'], 'ca-csd-2401001')
        self.assertEqual(self.client.get('/v1/areas/ca-csd-2401001/children').json()['total'], 2)
        ancestors = self.client.get('/v1/areas/ca-qc-test-west/ancestors').json()['items']
        self.assertEqual([r['id'] for r in ancestors], ['ca', 'ca-qc', 'ca-qc-test-region', 'ca-csd-2401001'])

    def test_missing_regions_skip_level_and_search_normalizes_accents(self):
        self.assertEqual(self.client.get('/v1/areas/ca-on/children').json()['items'][0]['level'], 'municipality')
        result = self.client.get('/v1/areas', params={'q': 'region de test', 'level': 'region'}).json()
        self.assertEqual(result['total'], 1)
        self.assertEqual(self.client.get('/v1/areas', params={'q': 'Test Region'}).json()['total'], 1)
        page = self.client.get('/v1/areas/ca/children', params={'limit': 5}).json()
        self.assertEqual(len(page['items']), 5)
        self.assertEqual(page['next_offset'], 5)
        self.assertEqual(self.client.get('/v1/areas/not-an-area/children').status_code, 404)

    def test_boundaries_are_geojson_and_distinguish_display_from_assignment(self):
        result = self.client.get('/v1/areas/ca-csd-2401001/boundary')
        self.assertEqual(result.headers['content-type'], 'application/geo+json')
        self.assertFalse(result.json()['properties']['suitable_for_assignment'])
        self.assertIn('attribution', result.json()['sources'][0])
        self.assertIn('modifications', result.json()['sources'][0])
        self.assertEqual(result.headers['x-maps-dataset-version'], self.digest)
        self.assertEqual(self.client.get('/v1/areas/ca-csd-2401001/boundary', headers={'If-None-Match': result.headers['etag']}).status_code, 304)
        full = self.client.get('/v1/areas/ca-csd-2401001/boundary?resolution=full').json()
        self.assertTrue(full['properties']['suitable_for_assignment'])
        self.assertFalse(full['properties']['geography_qualified'])
        self.assertEqual(self.client.get('/v1/areas/ca-qc/boundary?resolution=full').status_code, 409)
        page = self.client.get('/v1/areas/ca/children/boundaries?limit=3').json()
        self.assertEqual(page['type'], 'FeatureCollection')
        self.assertEqual(len(page['features']), 3)
        self.assertEqual(page['next_offset'], 3)

    def test_lookup_uses_full_shapes_and_returns_evidence(self):
        point = {'longitude': -109.75, 'latitude': 50.5}
        result = self.client.post('/v1/lookup', json=point).json()
        self.assertEqual(result['status'], 'matched')
        by_id = {r['id']: r for r in result['matches']}
        self.assertEqual(by_id['ca-qc-test-west']['match_basis'], 'geometry')
        self.assertEqual(by_id['ca-qc']['match_basis'], 'hierarchy')
        self.assertEqual(self.client.get('/v1/lookup', params=point).json(), result)
        self.assertEqual(self.client.post('/v1/lookup', json={'longitude': -129.5, 'latitude': 50.5}).json()['status'], 'no_match')
        self.assertEqual(self.client.post('/v1/lookup', json={'longitude': 0, 'latitude': 0}).json()['matches'], [])

    def test_shared_edges_return_all_matches_without_arbitrary_winner(self):
        result = self.client.post('/v1/lookup', json={'longitude': -109.5, 'latitude': 50.5}).json()
        self.assertTrue(result['ambiguous'])
        self.assertIn('ca-qc-test-west', result['direct_match_ids'])
        self.assertIn('ca-qc-test-east', result['direct_match_ids'])

    def test_candidate_repair_does_not_become_assignment(self):
        data = self.client.app.state.dataset
        i = data.pending_ids.index('ca-csd-1201001')
        point = data.pending_shapes[i].representative_point()
        response = self.client.post('/v1/lookup', json={'longitude': point.x, 'latitude': point.y})
        result = response.json()
        self.assertEqual(result['status'], 'review_required')
        self.assertIn('ca-csd-1201001', result['review_candidate_ids'])
        self.assertNotIn('ca-csd-1201001', result['direct_match_ids'])
        self.assertEqual(self.client.get('/v1/areas/ca-csd-1201001/boundary?resolution=full').status_code, 409)
        self.assertEqual(self.client.get('/v1/areas/ca-csd-1201001/boundary').status_code, 200)

    def test_cross_source_parent_disagreement_is_explicit(self):
        result = self.client.post('/v1/lookup', json={'longitude': -108.995, 'latitude': 50.5}).json()
        self.assertEqual(result['status'], 'review_required')
        self.assertIn({'area_id': 'ca-qc-test-east', 'ancestor_id': 'ca-csd-2401001'}, result['hierarchy_geometry_disagreements'])
        self.assertNotIn('ca-csd-2401001', result['direct_match_ids'])

    def test_batch_order_and_input_limits(self):
        points = [{'longitude': 0, 'latitude': 0}, {'longitude': -109.75, 'latitude': 50.5}]
        result = self.client.post('/v1/lookup/batch', json={'points': points}).json()
        self.assertEqual([r['status'] for r in result['results']], ['no_match', 'matched'])
        for invalid in [{'points': []}, {'points': [points[0]] * 101}, {'points': points, 'unreviewed': True}]:
            self.assertEqual(self.client.post('/v1/lookup/batch', json=invalid).status_code, 422)
        for invalid in [{'longitude': True, 'latitude': 45}, {'longitude': 181, 'latitude': 0}, {'longitude': 0, 'latitude': -91}, {'longitude': '0', 'latitude': 0}]:
            response = self.client.post('/v1/lookup', json=invalid)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('input', response.text)
        self.assertEqual(self.client.post('/v1/lookup', content='{"longitude":NaN,"latitude":0}', headers={'Content-Type': 'application/json'}).status_code, 422)
        self.assertEqual(self.client.get('/v1/lookup?longitude=nan&latitude=0').status_code, 422)
        self.assertEqual(self.client.get('/v1/areas?limit=501').status_code, 422)
        self.assertEqual(self.client.post('/v1/lookup/batch', content=b'x' * (MAX_BODY_BYTES + 1)).status_code, 413)
        self.assertEqual(self.client.post('/v1/lookup', content=b'x', headers={'Content-Encoding': 'gzip'}).status_code, 415)

    def test_dataset_pinning(self):
        self.assertEqual(self.client.get('/v1/countries', headers={'If-Match': '"' + self.digest + '"'}).status_code, 200)
        self.assertEqual(self.client.get('/v1/countries', headers={'If-Match': '"wrong"'}).status_code, 412)

    def test_no_filesystem_or_write_endpoints(self):
        for path in ['/catalogue.sqlite3', '/report.json', '/manifest.json', '/source.zip', '/.env', '/v1/areas/%2e%2e%2f.env']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.delete('/v1/areas/ca').status_code, 405)
        self.assertEqual(self.client.get('/v1/countries', headers={'Host': 'attacker.invalid'}).status_code, 400)

    def test_token_authentication_host_guards_and_rate_limits(self):
        settings = replace(self.settings, mode='production', tokens={'test': 'synthetic-test-token-' + 'x' * 40}, requests_per_minute=2)
        with TestClient(create_app(settings), base_url='http://localhost', client=('203.0.113.5', 2345)) as client:
            self.assertEqual(client.get('/v1/countries').status_code, 401)
            self.assertEqual(client.get('/v1/countries', headers={'X-Forwarded-For': '127.0.0.1'}).status_code, 401)
            auth = {'Authorization': 'Bearer ' + settings.tokens['test']}
            self.assertEqual(client.get('/v1/countries', headers=auth).status_code, 200)
            self.assertEqual(client.get('/v1/countries', headers=auth).status_code, 200)
            response = client.get('/v1/countries', headers=auth)
            self.assertEqual(response.status_code, 429)
            self.assertIn('retry-after', response.headers)
            self.assertEqual(client.get('/healthz', headers={'Host': '10.0.0.1'}).status_code, 200)
        with TestClient(create_app(self.settings), base_url='http://localhost', client=('203.0.113.5', 2345)) as client:
            self.assertEqual(client.get('/v1/countries').status_code, 401)

    def test_cors_explicit_origins_only(self):
        settings = replace(self.settings, cors_origins=('https://example.com',))
        with TestClient(create_app(settings), base_url='http://localhost', client=('127.0.0.1', 2345)) as client:
            headers = {'Origin': 'https://example.com', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'}
            self.assertEqual(client.options('/v1/lookup', headers=headers).headers['access-control-allow-origin'], 'https://example.com')
            headers['Origin'] = 'https://attacker.invalid'
            self.assertEqual(client.options('/v1/lookup', headers=headers).status_code, 400)

    def test_startup_fails_closed_on_missing_or_changed_release(self):
        with self.assertRaises(CatalogueError):
            with TestClient(create_app(replace(self.settings, manifest_sha256='0' * 64))):
                pass
        with self.assertRaises(CatalogueError):
            replace(self.settings, mode='production', tokens={})

    def test_encoded_routes_and_duplicate_headers_do_not_bypass_auth(self):
        settings = replace(self.settings, mode='production', tokens={'test': 'synthetic-test-token-' + 'x' * 40})
        with TestClient(create_app(settings), base_url='http://localhost', client=('203.0.113.5', 2345)) as client:
            for path in ['/v1/%63ountries', '/%76%31/countries', '/v1/countries/']:
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 401)
            token = 'Bearer ' + settings.tokens['test']
            for headers in [[('Authorization', token), ('Authorization', token)],
                            [('Authorization', token), ('Host', 'localhost'), ('Host', 'attacker.invalid')]]:
                self.assertEqual(client.get('/v1/countries', headers=headers).status_code, 400)
            self.assertEqual(client.get('/v1/countries', headers={'Authorization': token.lower()}).status_code, 200)
            self.assertNotIn(settings.tokens['test'], client.get('/openapi.json').text)

    def test_streamed_body_without_content_length_is_still_bounded(self):
        chunks = iter([b'x' * (MAX_BODY_BYTES // 2), b'x' * MAX_BODY_BYTES])
        response = self.client.post('/v1/lookup', content=chunks, headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)

    def test_unexpected_errors_do_not_expose_diagnostics(self):
        with TestClient(create_app(self.settings), base_url='http://localhost', client=('127.0.0.1', 12345),
                        raise_server_exceptions=False) as client:
            with patch.object(client.app.state.dataset, 'lookup', side_effect=RuntimeError('private diagnostic marker')):
                with self.assertLogs('totally_normal_maps.api', level='ERROR') as logs:
                    response = client.post('/v1/lookup', json={'longitude': -75, 'latitude': 45})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json(), {'error': 'Internal service error.'})
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(len(logs.records), 1)

    def test_validation_responses_do_not_echo_submitted_values(self):
        response = self.client.post('/v1/lookup', json={'longitude': 'private coordinate marker', 'latitude': 45})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('private coordinate marker', response.text)


if __name__ == '__main__':
    unittest.main()
