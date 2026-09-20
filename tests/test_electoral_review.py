"""Regression cases found in the full electoral implementation review."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform

from totally_normal_maps.catalogue import CatalogueError, identity_digest, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.electoral import build_electoral
from tests.test_electoral import electoral_fixture


class ElectoralReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, self.release, self.path, self.plan = electoral_fixture(self.root)

    def build(self, plan, name='review', base=None):
        path = self.root / (name + '.json')
        write_json(path, plan)
        output = self.root / name
        build_electoral(base or self.base, self.root, output, plan_path=path)
        return Dataset(output)

    def one_source(self, geometry, **properties):
        source = self.root / 'review-source.geojson'
        write_json(source, {'type':'FeatureCollection', 'features': [
            {'type':'Feature', 'properties':{'code':'1','name':'Test', **properties}, 'geometry':mapping(geometry)}]})
        plan = copy.deepcopy(self.plan)
        plan['sources']['test'].update(filename=source.name, sha256=sha256(source), expected_count=1,
                                      province_counts={'24':1}, identity_sha256=identity_digest(['1']))
        plan['editions'] = [{**plan['editions'][1], 'expected_count':1}]
        plan['coverage'] = {}
        return plan

    def test_selected_coverage_and_missing_default_jurisdictions(self):
        data = Dataset(self.release)
        old = data.lookup(-110.5, 50, layers=['provincial'], editions={'provincial':['qc-old']})
        coverage = old['layers']['provincial']['coverage']
        self.assertEqual(coverage['24']['edition'], 'qc-old')
        self.assertEqual(coverage['24']['expected_count'], 2)
        self.assertEqual(coverage['35']['status'], 'not_selected')
        missing = data.lookup(-80, 45, layers=['provincial'])
        self.assertEqual(missing['status'], 'review_required')
        self.assertEqual(missing['layers']['provincial']['coverage']['35']['status'], 'unavailable')
        for kwargs in ({'layers':[]}, {'layers':['federal','federal']}, {'editions':[]},
                       {'layers':['provincial'], 'editions':{'provincial':[]}},
                       {'layers':['provincial'], 'editions':{'provincial':['qc-old','qc-old']}}):
            with self.subTest(selection=kwargs), self.assertRaises(CatalogueError):
                data.lookup(-110.5,50,**kwargs)

    def test_upcoming_edition_can_be_activated_without_reidentifying_geometry(self):
        plan = copy.deepcopy(self.plan)
        plan['editions'] = [{**plan['editions'][1], 'id':'qc-future', 'status':'upcoming', 'default':False}]
        future = self.build(plan, 'future', base=self.release)
        promotion = {'schema_version':1, 'reviewed_on':'2026-10-01', 'release_label':'promoted',
                     'sources':{}, 'editions':[], 'edition_updates':[
                         {'id':'qc-future', 'status':'current', 'default':True,
                          'effective_date':'2026-10-01', 'evidence_url':'https://example.test/current'},
                         {'id':'qc-current', 'status':'historical', 'default':False,
                          'valid_to':'2026-10-01', 'evidence_url':'https://example.test/previous'}]}
        current = self.build(promotion, 'promoted', base=future.root)
        self.assertEqual(current.lookup(-110.5,50,layers=['provincial'])['direct_match_ids'], ['ca-qc-future-1'])
        self.assertEqual(current.areas['ca-qc-current-1']['edition_status'], 'historical')
        for uid, row in future.areas.items():
            if row['level'] == 'electoral_district':
                self.assertEqual(future.geometries[uid].wkb, current.geometries[uid].wkb)
        self.assertFalse(Dataset(future.root).editions['qc-future']['default'])

    def test_output_cannot_be_inside_immutable_input(self):
        nested = self.base / 'nested-release'
        with self.assertRaises(CatalogueError):
            build_electoral(self.base, self.root, nested, plan_path=self.path)
        self.assertFalse(nested.exists())

    def test_collapsed_polygon_retains_identity_without_approving_geometry(self):
        plan = self.one_source(Polygon([(-111,49),(-110,50),(-109,51),(-111,49)]))
        data = self.build(plan)
        row = data.areas['ca-qc-current-1']
        self.assertEqual(row['assignment_status'], 'missing_geometry')
        self.assertFalse(row['geometry_available'])
        self.assertIn(row['id'], data.lookup(-110,50,layers=['provincial'])['review_candidate_ids'])

    def test_reprojection_cannot_approve_an_invalid_source(self):
        plan = self.one_source(Polygon([(-111,49),(-109,51),(-111,51),(-109,49),(-111,49)]))
        def rounded_transform(operation, geometry):
            # Model a coordinate round trip that removes the source crossing.
            return box(-111,49,-109,51) if not geometry.is_valid else transform(operation, geometry)
        with patch('totally_normal_maps.electoral.transform', side_effect=rounded_transform):
            data = self.build(plan)
        self.assertNotIn('ca-qc-current-1', data.geometries)
        self.assertIn('ca-qc-current-1', data.lookup(-110,50,layers=['provincial'])['review_candidate_ids'])

    def test_source_identifier_survives_mapping_prefix_and_padding(self):
        plan = self.one_source(box(-111,49,-109,51), code='Publisher name')
        plan['sources']['test'].update(identity_map={'Publisher name':'1'}, id_width=2, id_prefix='local-',
                                      identity_sha256=identity_digest(['local-01']))
        data = self.build(plan)
        self.assertEqual(data.areas['ca-qc-current-local-01']['source_id'], 'Publisher name')

    def test_invalid_names_and_predecessor_layers_are_rejected(self):
        plan = self.one_source(box(-111,49,-109,51), name=None)
        with self.assertRaises(CatalogueError): self.build(plan, 'null-name')
        plan = self.one_source(box(-111,49,-109,51))
        plan['editions'][0].update(id='qc-next', predecessors={'1':['ca-fed-test-1']},
                                  relationship_evidence=['https://example.test/relationship'])
        plan['sources'] = {'next':plan['sources']['test']}
        plan['editions'][0]['sources'] = ['next']
        with self.assertRaises(CatalogueError): self.build(plan, 'wrong-predecessor', base=self.release)

    def test_coverage_and_source_specification_drift_are_rejected(self):
        plan = copy.deepcopy(self.plan)
        plan['coverage']['provincial']['24']['edition'] = 'fed-test'
        with self.assertRaises(CatalogueError): self.build(plan, 'coverage-drift')
        plan = copy.deepcopy(self.plan)
        plan['editions'] = [{**plan['editions'][1], 'id':'qc-next'}]
        # Same source bytes but a changed parsing contract must use a new key.
        plan['sources']['test']['id_width'] = 1
        with self.assertRaises(CatalogueError): self.build(plan, 'source-drift', base=self.release)

    def test_import_checks_actual_lookup_results(self):
        with patch.object(Dataset, 'lookup', return_value={'direct_match_ids':[]}):
            with self.assertRaises(CatalogueError): self.build(self.plan, 'broken-lookup')
        self.assertFalse((self.root/'broken-lookup').exists())

    def test_match_does_not_hide_another_selected_editions_partial_coverage(self):
        plan = self.one_source(box(-115,49,-113,51))
        plan['editions'][0].update(id='qc-limited', default=False, status='historical', valid_to='2026-01-01')
        plan['sources'] = {'limited':plan['sources']['test']}
        plan['editions'][0]['sources'] = ['limited']
        plan['coverage'] = {'provincial':{'24':{'edition':'qc-limited', 'status':'partial'}}}
        data = self.build(plan, 'limited', base=self.release)
        self.assertEqual(data.areas['ca-qc-limited-1']['valid_to'], '2026-01-01')
        result = data.lookup(-110.5,50,layers=['provincial'], editions={'provincial':['qc-current','qc-limited']})
        self.assertEqual(result['direct_match_ids'], ['ca-qc-current-1'])
        self.assertEqual(result['status'], 'review_required')
