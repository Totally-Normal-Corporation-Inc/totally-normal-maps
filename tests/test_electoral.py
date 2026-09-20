"""Synthetic independent layers, editions, immutable imports and API selection."""
import copy
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from shapely.geometry import box, mapping, Polygon

from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import CatalogueError, identity_digest, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.electoral import build_electoral
from totally_normal_maps.website import export_website, checked_website
from tests.api_fixture import make_release


def electoral_fixture(root):
    _, base, _ = make_release(root)
    source = root / 'districts.geojson'
    write_json(source, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'code': str(i), 'name': name}, 'geometry': mapping(geom)}
        for i, name, geom in [(1, 'West', box(-111, 49, -110, 51)), (2, 'East', box(-110, 49, -109, 51))]]})
    spec = {'filename': source.name, 'sha256': sha256(source), 'identity_sha256': identity_digest(['1', '2']),
            'expected_count': 2, 'province': '24', 'province_counts': {'24': 2}, 'crs': 'EPSG:4326',
            'id_field': 'code', 'name_field': 'name', 'authority': 'Synthetic authority',
            'licence': 'https://example.test/licence', 'redistribution_status': 'permitted'}
    editions = [dict(id=uid, layer=layer, provinces=['24'], status=status, default=default,
                     label=uid, authority='Synthetic authority', boundary_set=uid,
                     electoral_event='Synthetic election', evidence_url='https://example.test/edition',
                     sources=['test'], expected_count=2)
                for uid, layer, status, default in [('fed-test', 'federal', 'current', True),
                    ('qc-current', 'provincial', 'current', True), ('qc-old', 'provincial', 'historical', False)]]
    plan = {'schema_version': 1, 'reviewed_on': '2026-09-19', 'release_label': 'electoral-synthetic',
            'sources': {'test': spec}, 'editions': editions, 'coverage': {
                key: {'24': {'status': 'included'}} for key in ['federal', 'provincial']}}
    path = root / 'plan.json'; write_json(path, plan)
    output = root / 'electoral'
    build_electoral(base, root, output, plan_path=path)
    return base, output, path, plan


class ElectoralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.base, cls.release, cls.plan_path, cls.plan = electoral_fixture(cls.root)
        cls.data = Dataset(cls.release)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_default_compatibility_and_independent_matches(self):
        before = Dataset(self.base).lookup(-110.5, 50)
        after = self.data.lookup(-110.5, 50)
        for key in ('status', 'direct_match_ids', 'review_candidate_ids', 'ambiguous', 'unlocated_missing_geometry_ids'):
            self.assertEqual(before[key], after[key])
        self.assertEqual([m['id'] for m in before['matches']], [m['id'] for m in after['matches']])
        result = self.data.lookup(-110.5, 50, layers=['administrative', 'federal', 'provincial'])
        self.assertEqual(result['layers']['federal']['status'], 'matched')
        self.assertEqual(result['layers']['provincial']['direct_match_ids'], ['ca-qc-current-1'])
        self.assertFalse(result['ambiguous'])

    def test_boundary_ties_and_multiple_editions(self):
        r = self.data.lookup(-110, 50, layers=['federal'])
        self.assertTrue(r['layers']['federal']['ambiguous'])
        r = self.data.lookup(-110.5, 50, layers=['provincial'], editions={'provincial': ['qc-current', 'qc-old']})
        self.assertFalse(r['ambiguous'])
        self.assertEqual(len(r['direct_match_ids']), 2)

    def test_national_and_province_browsing(self):
        self.assertEqual(self.data.page(layer='federal', level='electoral_district', within_id='ca')['total'], 2)
        self.assertEqual(self.data.page(layer='provincial', parent_id='ca-qc')['total'], 2)
        self.assertEqual(self.data.page(layer='provincial', editions=['qc-old'], parent_id='ca-qc')['total'], 2)
        self.assertEqual([a['id'] for a in self.data.ancestors('ca-fed-test-1')], ['ca', 'ca-qc'])
        self.assertFalse(any(r['level']=='electoral_district' for r in self.data.page(parent_id='ca-qc')['items']))

    def test_invalid_selection_and_immutable_editions(self):
        with self.assertRaises(CatalogueError): self.data.lookup(-110, 50, layers=['federal'], editions={'federal':['qc-old']})
        with self.assertRaises(CatalogueError): build_electoral(self.release, self.root, self.root/'duplicate', plan_path=self.plan_path)
        bad = copy.deepcopy(self.plan); bad['sources']['test']['sha256'] = '0'*64
        path = self.root/'bad.json'; write_json(path, bad)
        with self.assertRaises(CatalogueError): build_electoral(self.base, self.root, self.root/'bad-release', plan_path=path)
        self.assertFalse((self.root/'bad-release').exists())

    def test_website_is_display_only(self):
        output = self.root/'website'
        digest = export_website(self.data, output, notice=Path(__file__).parents[1]/'NOTICE.md')
        checked_website(output, expected_sha256=digest, dataset_sha256=self.data.version)
        self.assertTrue((output/'electoral-24.geojson').is_file())
        self.assertFalse((output/'catalogue.sqlite3').exists())

    def test_appending_future_edition_preserves_defaults_and_provenance(self):
        plan = copy.deepcopy(self.plan)
        edition = {**plan['editions'][1], 'id': 'qc-future', 'status': 'upcoming', 'default': False}
        plan['editions'] = [edition]
        path = self.root/'future.json'; write_json(path, plan)
        output = self.root/'future-release'
        build_electoral(self.release, self.root, output, plan_path=path)
        future = Dataset(output)
        self.assertEqual(future.lookup(-110.5, 50, layers=['provincial'])['direct_match_ids'], ['ca-qc-current-1'])
        selected = future.lookup(-110.5, 50, layers=['provincial'], editions={'provincial':['qc-future']})
        self.assertEqual(selected['direct_match_ids'], ['ca-qc-future-1'])
        self.assertEqual(future.geometries['ca-qc-old-1'].wkb, self.data.geometries['ca-qc-old-1'].wkb)
        plan['sources']['test']['authority'] = 'Changed publisher'
        write_json(path, plan)
        with self.assertRaises(CatalogueError):
            build_electoral(self.release, self.root, self.root/'changed-source', plan_path=path)

    def test_unapproved_electoral_geometry_is_independent_uncertainty(self):
        plan = copy.deepcopy(self.plan)
        source = self.root/'invalid.geojson'
        geometry = Polygon([(-111,49),(-109,51),(-111,51),(-109,49),(-111,49)])
        write_json(source, {'type':'FeatureCollection', 'features': [
            {'type':'Feature', 'properties':{'code':'1','name':'Invalid district'}, 'geometry':mapping(geometry)}]})
        plan['sources'] = {'invalid': {**plan['sources']['test'], 'filename':source.name, 'sha256':sha256(source),
            'identity_sha256':identity_digest(['1']), 'expected_count':1, 'province_counts':{'24':1}}}
        plan['editions'] = [{**plan['editions'][1], 'id':'qc-review', 'sources':['invalid'], 'expected_count':1}]
        path = self.root/'invalid-plan.json'; write_json(path, plan)
        output = self.root/'invalid-release'
        build_electoral(self.release, self.root, output, plan_path=path)
        review = Dataset(output)
        uid = 'ca-qc-review-1'
        self.assertTrue(review.areas[uid]['display_available'])
        self.assertNotIn(uid, review.geometries)
        result = review.lookup(-110.5, 50.75, layers=['federal','provincial'])
        self.assertEqual(result['layers']['federal']['status'], 'matched')
        self.assertEqual(result['layers']['provincial']['status'], 'review_required')
        self.assertIn(uid, result['review_candidate_ids'])
        with TestClient(create_app(Settings(dataset=output)), base_url='http://127.0.0.1', client=('127.0.0.1',12345)) as client:
            self.assertEqual(client.get(f'/v1/areas/{uid}/boundary?resolution=full').status_code,409)

    def test_api_contract(self):
        with TestClient(create_app(Settings(dataset=self.release)), base_url="http://127.0.0.1", client=('127.0.0.1', 12345)) as client:
            self.assertEqual(len(client.get('/v1/layers').json()['items']), 4)
            r = client.get('/v1/areas?layer=federal&level=electoral_district&within_id=ca')
            self.assertEqual(r.status_code, 200); self.assertEqual(r.json()['total'], 2)
            r = client.post('/v1/lookup', json={'longitude':-110.5,'latitude':50,'layers':['federal','provincial']})
            self.assertEqual(r.status_code, 200); self.assertFalse(r.json()['ambiguous'])
            self.assertEqual(set(r.json()['layers']), {'federal','provincial'})
            self.assertEqual(client.get('/v1/areas?layer=federal&edition=qc-old').status_code, 422)
            self.assertEqual(client.get('/v1/areas?within_id=unknown').status_code, 404)
            self.assertEqual(client.get('/v1/areas/ca-qc/children/boundaries?layer=federal').json()['total'], 2)
            self.assertEqual(client.get('/v1/areas/boundaries?layer=federal&within_id=ca').json()['total'], 2)
            self.assertNotIn('layers', client.get('/v1/lookup?longitude=-110.5&latitude=50').json())
