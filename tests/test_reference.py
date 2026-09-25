"""Bounded evidence, geographic scope and conditional HTTP, entirely offline."""
import base64
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import identity_digest, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.municipal_elections import build_municipal
from totally_normal_maps.reference import (
    BASE, CACHE_BYTES, ITEM_BYTES, PAGE_BYTES, SUMMARY_BYTES, ReferenceIndex, encoded,
)
from tests.test_electoral import electoral_fixture


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        _, base, _, _ = electoral_fixture(root)
        source = root / 'districts.geojson'
        editions = [dict(id=uid, layer='municipal', authority_id='ca-csd-2401001',
            provinces=['24'], status=status, default=default, scheme='council-wards',
            label=uid, authority='Synthetic council', boundary_set=uid,
            electoral_event='Synthetic election', evidence_url='https://example.test/election',
            expected_count=2, sources=['wards'], id_fields=['code'], name_field='name',
            identity_sha256=identity_digest(['1', '2']))
            for uid, status, default in [('mun-current', 'reference', True), ('mun-old', 'historical', False)]]
        plan = {'schema_version': 1, 'reviewed_on': '2026-09-19', 'release_label': 'reference-tests',
            'sources': {'wards': {'filename': source.name, 'sha256': sha256(source), 'expected_count': 2,
                'crs': 'EPSG:4326', 'authority': 'Synthetic council', 'licence': 'https://example.test/licence',
                'attribution': 'Synthetic credit; no endorsement.', 'redistribution_status': 'permitted'}},
            'editions': editions, 'coverage': {
                'ca-csd-3501001': {'status': 'unavailable', 'reviewed_on': '2026-09-19',
                    'evidence_url': 'https://example.test/standby', 'note': 'Permission pending.'}}}
        plan_path = root / 'municipal-plan.json'; write_json(plan_path, plan)
        cls.release = root / 'municipal'
        build_municipal(base, root, cls.release, plan_path=plan_path)
        cls.settings = Settings(cls.release, sha256(cls.release / 'manifest.json'), mode='production',
            tokens={'consumer-a': 'a' * 40, 'consumer-b': 'b' * 40},
            allowed_hosts=('testserver',), requests_per_minute=10000)
        cls.client = TestClient(create_app(cls.settings))
        cls.client.__enter__()
        cls.client.headers['Authorization'] = 'Bearer ' + 'a' * 40
        cls.data = cls.client.app.state.dataset
        cls.index = cls.client.app.state.references
        assert cls.index is not None

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def get(self, path, **kwargs):
        response = self.client.get(path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text[:500])
        self.assertEqual(response.headers['x-maps-dataset-version'], self.data.version)
        self.assertEqual(response.json()['dataset_version'], self.data.version)
        self.assertEqual(response.json()['qualification'], 'review_required')
        return response

    def test_summary_selection_counts_and_qualification(self):
        summary = self.get(BASE + '/summary').json()
        self.assertEqual(summary['selection']['layer'], 'administrative')
        counts = summary['counts']
        self.assertEqual(counts['hierarchy_only_entries'], 14)
        self.assertEqual(counts['catalogue_entries'], counts['assignment_geometries'] +
                         counts['unavailable_assignment_geometries'] + counts['hierarchy_only_entries'])
        self.assertGreater(counts['unavailable_assignment_geometries'], 0)
        self.assertIn('assignment_geometry_unavailable', [w['code'] for w in summary['limitations']])
        for layer in ('federal', 'provincial', 'municipal'):
            item = self.get(BASE + '/summary?layer=' + layer).json()
            self.assertEqual(item['counts']['catalogue_entries'], 2)
            self.assertEqual(item['selection']['edition_ids'], [])
            self.assertEqual(item['selection']['edition_count'], 1)
            self.assertEqual(item['selection']['edition_mode'], 'defaults')
        municipal = self.get(BASE + '/summary?layer=municipal').json()
        self.assertIn('reference_editions', [w['code'] for w in municipal['limitations']])
        self.assertIn('municipal_coverage_gaps', [w['code'] for w in municipal['limitations']])
        old = self.get(BASE + '/summary?layer=provincial&edition=qc-old').json()
        both = self.get(BASE + '/summary?layer=provincial&edition=qc-old&edition=qc-current').json()
        self.assertEqual(old['selection']['edition_ids'], ['qc-old'])
        self.assertEqual(both['counts']['catalogue_entries'], 4)
        federal = self.get(BASE + '/summary?layer=federal').json()
        self.assertIn('electoral_coverage_gaps', [w['code'] for w in federal['limitations']])

    def test_large_reports_do_not_expand_summary_or_nested_pages(self):
        large = copy.copy(self.data)
        large.report = copy.deepcopy(self.data.report)
        huge_notice = '\u0000é🌎' * 30000
        large.report['jurisdiction_refreshes'] = {'24': {
            'audit': [{'csd_id': '2401001', 'findings': ['x' * 2000] * 20} for _ in range(350)],
            'sources': {'large': {'authority': 'Synthetic large source', 'licence': huge_notice,
                'attribution': huge_notice, 'metadata': ['x' * 2000] * 1000}}}}
        # Hundreds of retained municipal defaults must be counted, not inlined.
        large.editions = copy.deepcopy(self.data.editions)
        for i in range(600):
            uid = 'synthetic-' + str(i).zfill(3) + 'x' * 65
            large.editions[uid] = {**large.editions['mun-current'], 'id': uid}
        index = ReferenceIndex(large)
        for layer in ('administrative', 'federal', 'provincial', 'municipal'):
            body, _ = index.summary(layer)
            self.assertLessEqual(len(body), SUMMARY_BYTES)
            summary = json.loads(body)
            self.assertNotIn('sources', summary)
            self.assertNotIn(huge_notice, body.decode())
        body, _ = index.summary('municipal', sorted(large.editions)[-30:])
        self.assertLessEqual(len(body), SUMMARY_BYTES)
        self.assertGreater(json.loads(index.summary('municipal')[0])['selection']['edition_count'], 600)
        coverage = json.loads(index.records('coverage', area_id='ca-csd-2401001', limit=100)[0])
        self.assertGreater(coverage['total'], 350)
        self.assertLessEqual(len(encoded(coverage)), PAGE_BYTES)
        sources = json.loads(index.records('sources', area_id='ca', descendants=True)[0])
        source = next(s for s in sources['items'] if s['authority'] == 'Synthetic large source')
        self.assertEqual(source['metadata_not_inlined'], ['licence', 'attribution'])
        self.assertIsNone(source['licence'])
        node = json.loads(index.evidence(source['id'])[0])
        notice = next(r for r in node['items'] if r['name'] == 'attribution')
        uid = notice['evidence_url'].rsplit('/', 1)[1]
        fragments, cursor = [], None
        byte_limited = False
        while True:
            body, _ = index.evidence(uid, 100, cursor)
            self.assertLessEqual(len(body), PAGE_BYTES)
            page = json.loads(body)
            byte_limited |= bool(page['next']) and len(page['items']) < 100
            for item in page['items']:
                self.assertLessEqual(len(encoded(item)), ITEM_BYTES)
                self.assertEqual(item['character_offset'], len(''.join(fragments)))
                fragments.append(item['value'])
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(''.join(fragments), huge_notice)
        self.assertTrue(byte_limited)
        # Serialization is cached; serving a known summary cannot traverse reports.
        with patch('totally_normal_maps.reference.encoded', side_effect=lambda v: encoded(v) if isinstance(v, dict) and 'edition_mode' in v else self.fail('Reserialized cached summary')):
            self.assertIs(index.summary(), index.summary())
        self.assertLessEqual(index.cache_size, CACHE_BYTES)

    def test_scopes_are_explicit_and_siblings_do_not_leak(self):
        path = BASE + '/coverage?area_id=ca-csd-2401001'
        direct = self.get(path).json()
        descendants = self.get(path + '&include_descendants=true').json()
        self.assertGreater(descendants['total'], direct['total'])
        for item in direct['items']:
            self.assertIn(item['relation'], {'direct', 'inherited'})
        qc = self.get(BASE + '/coverage?layer=municipal&area_id=ca-csd-2401001').json()
        ontario = self.get(BASE + '/coverage?layer=municipal&area_id=ca-csd-3501001').json()
        self.assertTrue(qc['items']); self.assertTrue(ontario['items'])
        self.assertFalse({r['id'] for r in qc['items']} & {r['id'] for r in ontario['items']})
        inventory = next(r for r in ontario['items'] if r['basis'] == 'authority_inventory')
        node = self.get(inventory['evidence_url']).json()
        self.assertEqual(next(r['value'] for r in node['items'] if r['name'] == 'status'), 'unavailable')
        self.assertEqual(qc['scope']['edition_count'], 1)
        old = self.get(BASE + '/coverage?layer=municipal&area_id=ca-csd-2401001&edition=mun-old').json()
        self.assertTrue(all(r['edition_id'] in {None, 'mun-old'} for r in old['items']))
        self.assertTrue(any(r['basis'] == 'authority_inventory' for r in old['items']))
        empty = self.get(BASE + '/sources?layer=federal&area_id=ca-on').json()
        self.assertEqual(empty['evidence_status'], 'no_records_for_selection')
        self.assertEqual(empty['items'], [])
        self.assertEqual(empty['qualification'], 'review_required')
        missing = self.get(BASE + '/coverage?layer=federal&area_id=ca-on').json()
        self.assertEqual(missing['items'][0]['basis'], 'default_selection')
        status = self.get(missing['items'][0]['evidence_url']).json()
        self.assertEqual(next(r['value'] for r in status['items'] if r['name'] == 'status'), 'unavailable')

    def test_source_deduplication_editions_and_attribution(self):
        sources = self.get(BASE + '/sources?layer=municipal&area_id=ca-csd-2401001&edition=mun-current&edition=mun-old').json()
        self.assertEqual(sources['total'], 1)
        self.assertEqual(sources['items'][0]['attribution'], self.data.report['municipal_elections']['sources']['wards']['attribution'])
        self.assertEqual(sources['items'][0]['roles'], ['electoral_boundary'])
        editions = self.get(BASE + '/editions?layer=municipal&area_id=ca-csd-2401001').json()
        self.assertEqual(editions['scope']['edition_mode'], 'all')
        self.assertEqual([e['id'] for e in editions['items']], ['mun-current', 'mun-old'])
        self.assertEqual([e['default'] for e in editions['items']], [True, False])

    def test_unsupported_missing_and_wrong_scopes(self):
        bad = [('/coverage', 422), ('/sources', 422),
            ('/summary?layer=wrong', 422), ('/summary?area_id=ca-qc', 422),
            ('/summary?layer=municipal&layer=federal', 422), ('/summary?edition=mun-old', 422),
            ('/summary?layer=municipal&edition=mun-old&edition=mun-old', 422),
            ('/coverage?area_id=unknown', 404), ('/evidence/unknown', 404),
            ('/coverage?area_id=ca&limit=101', 422), ('/coverage?area_id=ca&limit=0', 422),
            ('/coverage?area_id=ca-csd-2401001&layer=federal', 422),
            ('/coverage?area_id=ca-fed-test-1', 422),
            ('/coverage?area_id=ca-on&layer=municipal&edition=mun-old', 422),
            ('/coverage?area_id=ca-qc-current-1&layer=provincial&edition=qc-old', 422),
            ('/editions?layer=municipal&edition=mun-old', 422),
            ('/sources?area_id=ca&overlap=true', 422), ('/sources?area_id=ca&cursor=bad', 422)]
        for suffix, expected in bad:
            with self.subTest(suffix=suffix):
                response = self.client.get(BASE + suffix)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_deterministic_pagination_and_bound_continuations(self):
        start = BASE + '/coverage?area_id=ca&include_descendants=true&limit=3'
        first = self.get(start)
        ids, path, etags = [], start, set()
        while path:
            result = self.get(path)
            page = result.json()
            self.assertNotIn(result.headers['etag'], etags)
            etags.add(result.headers['etag'])
            ids.extend(r['id'] for r in page['items'])
            path = page['next']
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), first.json()['total'])
        self.assertEqual(self.get(start).content, first.content)
        next_url = first.json()['next']
        for changed in (next_url.replace('limit=3', 'limit=4'), next_url.replace('area_id=ca&', 'area_id=ca-qc&'),
                        next_url.replace('/coverage?', '/sources?')):
            self.assertEqual(self.client.get(changed).status_code, 422)
        cursor = first.json()['next_cursor']
        raw = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        raw[1] = '0' * 64
        stale = base64.urlsafe_b64encode(encoded(raw)).decode().rstrip('=')
        self.assertEqual(self.client.get(start + '&cursor=' + stale).status_code, 412)

    def test_conditional_requests_authentication_and_version_precedence(self):
        path = BASE + '/summary'
        result = self.get(path); etag = result.headers['etag']
        self.assertEqual(result.headers['cache-control'], 'private, no-cache')
        self.assertIn('Authorization', result.headers['vary'])
        for condition in (etag, 'W/' + etag, '"other,representation", W/' + etag, '*'):
            response = self.client.get(path, headers={'If-None-Match': condition, 'If-Match': '"' + self.data.version + '"'})
            self.assertEqual(response.status_code, 304)
            self.assertEqual(response.content, b'')
            self.assertEqual(response.headers['etag'], etag)
        for auth in ('', 'Bearer invalid'):
            response = self.client.get(path, headers={'Authorization': auth, 'If-None-Match': etag})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer ' + 'b' * 40, 'If-None-Match': etag}).status_code, 304)
        with patch.dict(self.settings.tokens, {'consumer-b': 'b' * 40}, clear=True):
            self.assertEqual(self.client.get(path, headers={'If-None-Match': etag}).status_code, 401)
        stale = self.client.get(path, headers={'If-Match': '"' + '0' * 64 + '"', 'If-None-Match': etag})
        self.assertEqual(stale.status_code, 412)
        self.assertEqual(stale.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get(path + '?layer=municipal', headers={'If-None-Match': etag}).status_code, 200)
        old = self.get(path + '?layer=provincial&edition=qc-old')
        current = self.get(path + '?layer=provincial&edition=qc-current')
        self.assertNotEqual(old.headers['etag'], current.headers['etag'])

    def test_source_pages_obey_byte_limits_and_preserve_unmapped_credits(self):
        large = copy.copy(self.data); large.report = copy.deepcopy(self.data.report)
        large.report['regions']['sources'] = [{'authority': 'Synthetic ' + str(i),
            'licence': 'x' * 4000, 'attribution': 'y' * 4000} for i in range(100)]
        index = ReferenceIndex(large)
        first = json.loads(index.records('sources', area_id='ca', descendants=True, limit=100)[0])
        self.assertLess(len(first['items']), 100)
        self.assertIsNotNone(first['next_cursor'])
        ids, cursor = [], None
        while True:
            body, _ = index.records('sources', area_id='ca', descendants=True, limit=100, cursor=cursor)
            self.assertLessEqual(len(body), PAGE_BYTES)
            page = json.loads(body)
            ids.extend(r['id'] for r in page['items'])
            for row in page['items']:
                self.assertLessEqual(len(encoded(row)), ITEM_BYTES)
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(len(set(ids)), first['total'])
        local = json.loads(index.records('sources', area_id='ca-csd-2401001')[0])
        self.assertTrue(all('unscoped_report_source' not in r['roles'] for r in local['items']))
        self.assertIn('unscoped_provenance_in_national_inventory', local['links'])
        self.assertFalse(index.compact_boundary(self.data.boundary('ca-csd-2401001'))['source_evidence']['local_source_mapping_complete'])

    def test_dataset_change_invalidates_preconditions_and_cursors(self):
        first = self.get(BASE + '/coverage?area_id=ca&include_descendants=true&limit=1')
        changed = copy.copy(self.data); changed.version = 'f' * 64
        state = self.client.app.state
        with patch.object(state, 'dataset', changed), patch.object(state, 'references', ReferenceIndex(changed)):
            response = self.client.get(BASE + '/summary', headers={
                'If-Match': '"' + self.data.version + '"', 'If-None-Match': '*'})
            self.assertEqual(response.status_code, 412)
            self.assertEqual(self.client.get(first.json()['next']).status_code, 412)
            response = self.client.get(BASE + '/summary')
            self.assertEqual(response.json()['dataset_version'], changed.version)
            self.assertEqual(response.headers['x-maps-dataset-version'], changed.version)

    def test_legacy_lookup_report_and_boundary_contracts(self):
        self.assertEqual(self.client.get(BASE).json(), self.data.summary)
        self.assertEqual(self.client.get(BASE).headers['cache-control'], 'no-store')
        # Lookup remains independent even when the reference index is unavailable.
        point = {'longitude': -109.5, 'latitude': 50.5, 'layers': ['administrative']}
        with patch.object(self.client.app.state, 'references', None):
            batch = self.client.post('/v1/lookup/batch', json={'points': [point]})
            self.assertEqual(batch.status_code, 200)
            self.assertEqual(batch.json()['results'][0]['dataset_version'], self.data.version)
            self.assertTrue(batch.json()['results'][0]['ambiguous'])
            self.assertEqual(batch.headers['cache-control'], 'no-store')
            self.assertEqual(self.client.get(BASE + '/summary', headers={'If-None-Match': '*'}).status_code, 503)
        for uid in ('ca-csd-2401001', 'ca-mun-old-1', 'ca-csd-1201001'):
            path = '/v1/areas/' + uid + '/boundary'
            legacy = self.client.get(path).json()
            compact = self.client.get(path + '?representation=compact').json()
            self.assertIn('sources', legacy); self.assertNotIn('sources', compact)
            for field in ('id', 'properties', 'geometry', 'dataset_version'):
                self.assertEqual(legacy[field], compact[field])
            source = self.get(compact['source_evidence']['sources_url'])
            self.assertTrue(source.json()['items'])
        self.assertEqual(self.client.get('/v1/areas/ca-csd-1201001/boundary?resolution=full&representation=compact').status_code, 409)
        for path in ('/v1/areas/boundaries?within_id=ca-qc', '/v1/areas/ca-qc/children/boundaries?limit=2'):
            legacy = self.client.get(path).json()
            compact = self.client.get(path + '&representation=compact').json()
            self.assertEqual(legacy['total'], compact['total'])
            self.assertEqual([f['geometry'] for f in legacy['features']], [f['geometry'] for f in compact['features']])
            self.assertTrue(all('sources' not in f for f in compact['features']))

    def test_index_failure_rate_limits_and_openapi(self):
        with patch('totally_normal_maps.api.ReferenceIndex', side_effect=RuntimeError('synthetic index failure')):
            with self.assertLogs('totally_normal_maps.api', level='ERROR'):
                with TestClient(create_app(self.settings)) as client:
                    client.headers['Authorization'] = 'Bearer ' + 'a' * 40
                    self.assertEqual(client.get(BASE + '/summary').status_code, 503)
                    self.assertEqual(client.post('/v1/lookup', json={'longitude': 0, 'latitude': 0}).status_code, 200)
        with TestClient(create_app(replace(self.settings, requests_per_minute=1))) as client:
            client.headers['Authorization'] = 'Bearer ' + 'a' * 40
            first = client.get(BASE + '/summary')
            self.assertEqual(client.get(BASE + '/summary', headers={'If-None-Match': first.headers['etag']}).status_code, 429)
        spec = self.client.get('/openapi.json').json()
        for resource in ('summary', 'coverage', 'sources', 'editions', 'evidence/{evidence_id}'):
            route = spec['paths'][BASE + '/' + resource]['get']
            self.assertEqual(route['security'], [{'BearerAuth': []}])
            self.assertIn('304', route['responses'])
            self.assertEqual({p['name'] for p in route['parameters'] if p['in'] == 'header'}, {'If-Match', 'If-None-Match'})
            self.assertIn('$ref', route['responses']['200']['content']['application/json']['schema'])

    def test_evidence_scalars_nested_links_and_long_field_names(self):
        value = {'flag': True, 'number': 1.25, 'null': None, 'empty': [], 'nested': {'other': [1, 2]},
                 'é' * 300: 'a long field name'}
        uid = self.index.node(('synthetic-types',), value)
        def restore(path):
            result, parts = self.get(path).json(), []
            page = result
            while True:
                parts.extend(page['items'])
                if not page['next']:
                    break
                page = self.get(page['next']).json()
            if result['scope']['node_type'] == 'string':
                return ''.join(p['value'] for p in parts)
            values = [restore(p['evidence_url']) if p['evidence_url'] else p['value'] for p in parts]
            if result['scope']['node_type'] == 'array':
                return values
            return {(restore(p['name_evidence_url']) if p['name_evidence_url'] else p['name']): v for p, v in zip(parts, values)}
        self.assertEqual(restore(self.index.evidence_url(uid) + '?limit=2'), value)


if __name__ == '__main__':
    unittest.main()
