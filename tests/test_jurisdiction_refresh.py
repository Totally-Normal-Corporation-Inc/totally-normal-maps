"""Offline cross-jurisdiction, parent-pinning and audit completeness acceptance."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import shapely
from shapely.affinity import translate
from shapely.geometry import box, mapping

from totally_normal_maps.catalogue import CatalogueError, PROVINCES, open_catalogue, read_json, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.jurisdiction_refresh import build_refresh
from totally_normal_maps.releases import export_release
from .api_fixture import make_release


class JurisdictionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run, _, _ = make_release(self.root)
        public = read_json(self.run/'preview/catalogue.json')
        with open_catalogue(self.run) as db:
            for key, table in [('areas', 'csd'), ('regions', 'region'), ('city_areas', 'city_area')]:
                public[key] = [json.loads(r['record']) for r in db.execute('SELECT * FROM '+table)]
        write_json(self.run/'preview/catalogue.json', public)
        self.evidence = [{'publisher': 'Synthetic', 'url': 'https://example.invalid/catalogue', 'claim': 'Fixture audit'}]

    def plan(self, province):
        report = read_json(self.run/'report.json')
        with open_catalogue(self.run) as db:
            source_row = db.execute('SELECT * FROM csd WHERE province=?', (province,)).fetchone()
            row = json.loads(source_row['record'])
            geom = shapely.from_wkb(source_row['geometry']) if source_row['geometry'] else None
        plan = {'schema_version': 1, 'province': province, 'reviewed_on': '2026-09-18',
                'base_source_sha256': report['source']['sha256'], 'base_identity_sha256': report['identity_sha256'],
                'parent_catalogue_sha256': report['catalogue_sha256'], 'parent_report_sha256': sha256(self.run/'report.json'),
                'sources': {}, 'adjustments': [], 'city_layers': [], 'names': [], 'unresolved': [],
                'repair_review': [] if geom is not None else [{'csd_id': row['id'], 'name': row['name'],
                    'status': 'unapproved', 'repair': row['repair']}],
                'audit': {'municipalities': [{'csd_id': row['id'], 'name': row['name'], 'evidence': self.evidence,
                    'status': 'source_blocked' if geom is None else 'qualified_complete'}]}}
        if geom is not None:
            key = 'source-' + province
            payload = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'id': 'a', 'name': 'Area'}, 'geometry': mapping(geom)}]}
            write_json(self.root/(key+'.geojson'), payload)
            plan['sources'][key] = {'sha256': sha256(self.root/(key+'.geojson')), 'authority': 'Synthetic',
                'family': 'Community', 'release': 'fixture', 'url': 'https://example.invalid/source', 'licence': 'synthetic',
                'evidence': self.evidence, 'id_field': 'id', 'name_field': 'name', 'expected_count': 1,
                'bounds': [-141, 41, -52, 90], 'identities': [{'source_id': 'a', 'properties': {'id': 'a', 'name': 'Area'}}]}
            plan['city_layers'] = [{'source': key, 'parent_csd_id': row['id'], 'parent_name': row['name'],
                'kind': 'community', 'type': 'Community', 'scheme': 'community', 'coverage_policy': 'citywide',
                'id_prefix': 'ca-'+PROVINCES[province][0].lower()+'-test-', 'expected_count': 1, 'evidence': self.evidence}]
        return plan

    def build(self, plan, name):
        path = self.root/(name+'.json'); write_json(path, plan)
        return build_refresh(self.run, self.root/name, source_dir=self.root, plan_path=path, province=plan['province'])

    def test_all_remaining_jurisdictions_chain_without_losing_existing_rows(self):
        original_run = self.run
        for province in (p for p in PROVINCES if p not in {'24', '35'}):
            with self.subTest(province=province):
                plan = self.plan(province)
                self.build(plan, 'next-'+province)
                self.run = self.root/('next-'+province)
        export_release(self.run, self.root/'expanded')
        dataset = Dataset(self.root/'expanded')
        self.assertEqual(len(dataset.summary['coverage']['jurisdiction_refreshes']), 11)
        self.assertEqual(dataset.summary['counts']['city_area'], 12)
        with open_catalogue(original_run) as before, open_catalogue(self.run) as after:
            for table in ('csd', 'region', 'city_area'):
                for row in before.execute('SELECT * FROM '+table):
                    self.assertEqual(tuple(row), tuple(after.execute('SELECT * FROM '+table+' WHERE id=?', (row['id'],)).fetchone()))
        self.assertIn('display/city-areas-62.geojson', dataset.manifest['files'])
        self.assertNotIn('ca-csd-1201001', dataset.geometries)
        for uid, area in dataset.areas.items():
            if area['level'] == 'city_area' and area['province_id'] != 'ca-qc':
                point = dataset.geometries[uid].representative_point()
                self.assertIn(uid, dataset.lookup(point.x, point.y)['direct_match_ids'])

    def test_parent_audit_and_jurisdiction_mismatches_fail_atomically(self):
        original = self.plan('59')
        for case in ('parent', 'report', 'audit', 'name', 'city', 'false_completion', 'unsupported_migration'):
            with self.subTest(case=case):
                plan = copy.deepcopy(original)
                if case == 'parent': plan['parent_catalogue_sha256'] = '0'*64
                elif case == 'report': plan['parent_report_sha256'] = '0'*64
                elif case == 'audit': plan['audit']['municipalities'] = []
                elif case == 'name': plan['audit']['municipalities'][0]['name'] = 'Wrong'
                elif case == 'city': plan['city_layers'][0]['parent_csd_id'] = '4801001'
                elif case == 'false_completion':
                    plan['audit']['source_audit_complete'] = True
                    plan['audit']['municipalities'][0]['status'] = 'pending_municipal_site_review'
                else: plan['mergers'] = [{'id': 'unsupported'}]
                with self.assertRaises(CatalogueError): self.build(plan, case)
                self.assertFalse((self.root/case).exists())

    def test_parent_mismatch_is_review_only_and_requires_explicit_plan(self):
        plan = self.plan('59')
        source = plan['sources']['source-59']
        path = self.root/'source-59.geojson'
        payload = read_json(path)
        geom = translate(shapely.geometry.shape(payload['features'][0]['geometry']), xoff=.5)
        payload['features'][0]['geometry'] = mapping(geom)
        write_json(path, payload); source['sha256'] = sha256(path)
        layer = plan['city_layers'][0]
        layer.update(coverage_policy='partial', minimum_parent_fraction=.4, coverage_note='Synthetic parent mismatch')
        with self.assertRaisesRegex(CatalogueError, 'spatial parent'):
            self.build(plan, 'rejected')
        layer['unapproved_parent_ids'] = ['a']
        self.build(plan, 'review')
        export_release(self.root/'review', self.root/'review-release')
        ds = Dataset(self.root/'review-release'); uid = layer['id_prefix']+'a'
        self.assertNotIn(uid, ds.geometries)
        point = geom.representative_point()
        self.assertIn(uid, ds.lookup(point.x, point.y)['review_candidate_ids'])
        self.assertFalse(ds.boundary(uid)['properties']['suitable_for_assignment'])
        with self.assertRaises(CatalogueError): ds.boundary(uid, 'full')

    def test_source_exclusion_keeps_original_snapshot_and_complete_identity_check(self):
        plan = self.plan('59'); source = plan['sources']['source-59']; path = self.root/'source-59.geojson'
        payload = read_json(path)
        extra = copy.deepcopy(payload['features'][0]); extra['properties'] = {'id': 'outside', 'name': 'Planning envelope'}
        payload['features'].append(extra); write_json(path, payload)
        source.update(sha256=sha256(path), expected_count=2)
        source['identities'].append({'source_id': 'outside', 'properties': extra['properties']})
        plan['city_layers'][0]['excluded_source_ids'] = {'outside': 'Documented planning envelope; not a neighbourhood'}
        self.build(plan, 'excluded')
        self.assertEqual(sha256(self.root/'excluded/jurisdiction-refresh-59-sources/source-59.geojson'), sha256(path))
        with open_catalogue(self.root/'excluded') as db:
            self.assertEqual(db.execute("SELECT count(*) FROM city_area WHERE id LIKE 'ca-bc-%'").fetchone()[0], 1)

    def migration_plan(self):
        """Two neighbouring synthetic municipalities and an existing city area."""
        with closing(sqlite3.connect(self.run/'catalogue.sqlite3')) as db, db:
            db.row_factory = sqlite3.Row
            original = dict(db.execute("SELECT * FROM csd WHERE id='5901001'").fetchone())
            first = json.loads(original['record']); geom = shapely.from_wkb(original['geometry'])
            second_geom = translate(geom, xoff=geom.bounds[2]-geom.bounds[0])
            second = {**first, 'id': '5901002', 'name': 'Second', 'bbox': list(second_geom.bounds)}
            fields = list(original)
            values = {**original, 'id': '5901002', 'name': 'Second', 'record': json.dumps(second), 'geometry': second_geom.wkb}
            db.execute('INSERT INTO csd ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', [values[k] for k in fields])
            union = shapely.union_all([geom, second_geom])
            region = {'id': 'ca-bc-old-group', 'province': '59', 'name': 'Existing group', 'kind': 'regional_group',
                      'type': 'Regional group', 'assignment_status': 'validated_derived', 'bbox': list(union.bounds), 'issues': []}
            db.execute('INSERT INTO region VALUES (?, ?, ?, ?, NULL)', (region['id'], '59', json.dumps(region), union.wkb))
            for uid in ('5901001', '5901002'):
                db.execute('INSERT INTO csd_region VALUES (?, ?, ?)', (uid, region['id'], 'synthetic'))
            child = {'id': 'ca-bc-old-community', 'province': '59', 'name': 'Existing community', 'kind': 'community',
                     'type': 'Community', 'parent_csd_id': '5901001', 'assignment_status': 'validated_source', 'bbox': list(geom.bounds)}
            db.execute('INSERT INTO city_area VALUES (?, ?, ?, ?)', (child['id'], '5901001', json.dumps(child), geom.wkb))
        public = read_json(self.run/'preview/catalogue.json')
        public['areas'].append(second); public['regions'].append(region); public['city_areas'].append(child)
        write_json(self.run/'preview/catalogue.json', public)
        display = read_json(self.run/'preview/59.geojson')
        display['features'].append({'type': 'Feature', 'properties': {'id': second['id']}, 'geometry': mapping(second_geom)})
        write_json(self.run/'preview/59.geojson', display)
        for filename, uid, shape in [('regions-59.geojson', region['id'], union), ('city-areas-59.geojson', child['id'], geom)]:
            write_json(self.run/'preview'/filename, {'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'properties': {'id': uid}, 'geometry': mapping(shape)}]})
        report = read_json(self.run/'report.json')
        report['feature_count'] += 1; report['province_counts']['59'] += 1
        report['regions']['feature_count'] += 1; report['city_areas']['feature_count'] += 1
        report['catalogue_sha256'] = sha256(self.run/'catalogue.sqlite3'); write_json(self.run/'report.json', report)
        plan = self.plan('59'); plan['city_layers'] = []
        plan['audit']['municipalities'].append({'csd_id': '5901002', 'name': 'Second', 'evidence': self.evidence, 'status': 'qualified_complete'})
        payload = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'id': 'p001', 'name': 'Successor'}, 'geometry': mapping(union)}]}
        write_json(self.root/'source-59.geojson', payload)
        plan['sources']['source-59'].update(sha256=sha256(self.root/'source-59.geojson'),
            identities=[{'source_id': 'p001', 'properties': payload['features'][0]['properties']}])
        plan['mergers'] = [{'id': 'ca-bc-mun-p001', 'source_id': 'p001', 'source': 'source-59', 'name': 'Successor',
            'type': 'Municipality', 'predecessor_csd_ids': ['5901001', '5901002'], 'effective_date': '2026-01-01',
            'region_id': region['id'], 'evidence': self.evidence, 'city_area_ids': [child['id']]}]
        return plan, union

    def exported(self, plan, name):
        self.build(plan, name)
        export_release(self.root/name, self.root/(name+'-release'))
        return Dataset(self.root/(name+'-release'))

    def test_successor_preserves_full_extent_history_and_existing_city_identity(self):
        plan, union = self.migration_plan()
        ds = self.exported(plan, 'merged'); uid = 'ca-bc-mun-p001'
        self.assertTrue(ds.geometries[uid].equals(union))
        self.assertEqual(ds.summary['counts']['municipality'], 13)
        self.assertEqual(ds.summary['historical_counts']['municipality'], 2)
        self.assertEqual(ds.areas['ca-bc-old-community']['municipality_id'], uid)
        self.assertEqual(ds.areas['ca-bc-old-group']['member_count'], 1)
        for old in ('ca-csd-5901001', 'ca-csd-5901002'):
            self.assertEqual(ds.areas[old]['successor_ids'], [uid])
            self.assertFalse(ds.boundary(old, 'full')['properties']['suitable_for_assignment'])
            point = ds.geometries[old].representative_point()
            self.assertNotIn(old, ds.lookup(point.x, point.y)['direct_match_ids'])
            self.assertIn(uid, ds.lookup(point.x, point.y)['direct_match_ids'])
        with open_catalogue(self.run) as before, open_catalogue(self.root/'merged') as after:
            for table in ('csd', 'region', 'csd_region', 'city_area'):
                self.assertEqual([tuple(r) for r in before.execute('SELECT * FROM '+table)],
                                 [tuple(r) for r in after.execute('SELECT * FROM '+table)])

    def test_new_city_layer_can_explicitly_select_successor(self):
        plan, _ = self.migration_plan()
        plan['city_layers'] = [{'source': 'source-59', 'parent_csd_id': '5901001',
            'parent_municipality_id': 'ca-bc-mun-p001', 'parent_name': 'Successor', 'kind': 'community',
            'type': 'Community', 'scheme': 'community', 'coverage_policy': 'citywide',
            'id_prefix': 'ca-bc-new-community-', 'expected_count': 1, 'evidence': self.evidence}]
        ds = self.exported(plan, 'merged-children')
        self.assertEqual(ds.areas['ca-bc-new-community-p001']['parent_id'], 'ca-bc-mun-p001')
        self.assertEqual(ds.areas['ca-bc-new-community-p001']['municipality_id'], 'ca-bc-mun-p001')

    def test_poor_successor_comparison_defers_whole_succession(self):
        plan, union = self.migration_plan()
        payload = read_json(self.root/'source-59.geojson')
        west, south, east, north = union.bounds
        payload['features'][0]['geometry'] = mapping(box(west+.1, south+.1, west+.2, south+.2))
        write_json(self.root/'source-59.geojson', payload)
        plan['sources']['source-59']['sha256'] = sha256(self.root/'source-59.geojson')
        ds = self.exported(plan, 'deferred-merger')
        self.assertNotIn('ca-bc-mun-p001', ds.areas)
        self.assertEqual(ds.summary['counts']['municipality'], 14)
        migration = ds.summary['coverage']['jurisdiction_refreshes']['59']['migrations']
        self.assertEqual(len(migration['deferred_mergers']), 1)
        self.assertEqual(migration['added_municipality_count'], 0)
        self.assertEqual(ds.areas['ca-bc-old-community']['municipality_id'], 'ca-csd-5901001')

    def test_unsafe_succession_fails_atomically(self):
        original, _ = self.migration_plan()
        for case in ('future', 'missing_child', 'wrong_parent', 'duplicate_predecessor', 'wrong_source_name'):
            with self.subTest(case=case):
                plan = copy.deepcopy(original); merger = plan['mergers'][0]
                if case == 'future': merger['effective_date'] = '2027-01-01'
                elif case == 'missing_child': merger['city_area_ids'] = []
                elif case == 'wrong_parent': merger['region_id'] = 'ca-qc-test-region'
                elif case == 'duplicate_predecessor': merger['predecessor_csd_ids'] = ['5901001', '5901001']
                else: merger['name'] = 'Wrong'
                with self.assertRaises(CatalogueError): self.build(plan, case)
                self.assertFalse((self.root/case).exists())

    def test_new_region_requires_exact_membership_and_changes_hierarchy(self):
        plan, _ = self.migration_plan(); plan['mergers'] = []
        plan['region_updates'] = [{'id': 'ca-bc-new-group', 'operation': 'add', 'source_id': 'new-group',
            'name': 'New group', 'kind': 'regional_group', 'type': 'Regional group',
            'member_ids': ['ca-csd-5901001'], 'coverage_policy': 'selected_members',
            'coverage_note': 'One explicitly named synthetic municipality', 'effective_date': '2026-01-01', 'evidence': self.evidence}]
        plan['membership_updates'] = [{'municipality_id': 'ca-csd-5901001', 'previous_region_id': 'ca-bc-old-group',
            'region_id': 'ca-bc-new-group', 'effective_date': '2026-01-01', 'evidence': self.evidence}]
        bad = copy.deepcopy(plan); bad['region_updates'][0]['member_ids'].append('ca-csd-5901002')
        with self.assertRaisesRegex(CatalogueError, 'membership'): self.build(bad, 'bad-member-set')
        ds = self.exported(plan, 'regrouped')
        self.assertEqual(ds.summary['counts']['region'], 3)
        self.assertEqual(ds.areas['ca-csd-5901001']['parent_id'], 'ca-bc-new-group')
        self.assertEqual(ds.areas['ca-bc-old-group']['member_count'], 1)
        self.assertTrue(ds.geometries['ca-bc-new-group'].equals(ds.geometries['ca-csd-5901001']))
        self.assertIn('ca-bc-new-group', [r['id'] for r in ds.ancestors('ca-bc-old-community')])

    def test_region_retirement_requires_explicit_reassignment(self):
        plan, _ = self.migration_plan(); plan['mergers'] = []
        plan['region_updates'] = [{'id': 'ca-bc-old-group', 'operation': 'retire', 'member_ids': [],
                                  'effective_date': '2026-01-01', 'evidence': self.evidence}]
        with self.assertRaises(CatalogueError): self.build(plan, 'orphaned')
        plan['membership_updates'] = [{'municipality_id': 'ca-csd-'+uid, 'previous_region_id': 'ca-bc-old-group',
            'region_id': None, 'effective_date': '2026-01-01', 'evidence': self.evidence} for uid in ('5901001', '5901002')]
        ds = self.exported(plan, 'retired-region')
        self.assertEqual(ds.summary['counts']['region'], 1)
        self.assertEqual(ds.areas['ca-bc-old-group']['lifecycle_status'], 'superseded')
        self.assertEqual(ds.areas['ca-csd-5901001']['parent_id'], 'ca-bc')
        point = ds.geometries['ca-csd-5901001'].representative_point()
        self.assertNotIn('ca-bc-old-group', ds.lookup(point.x, point.y)['direct_match_ids'])

    def test_new_region_cannot_approve_an_unreviewed_member(self):
        plan, _ = self.migration_plan(); plan['mergers'] = []
        with closing(sqlite3.connect(self.run/'catalogue.sqlite3')) as db, db:
            record = json.loads(db.execute("SELECT record FROM csd WHERE id='5901001'").fetchone()[0])
            record.update(assignment_status='unreviewed_repair', repair={'status': 'unapproved'})
            db.execute("UPDATE csd SET record=?, repair_candidate=geometry, geometry=NULL WHERE id='5901001'", (json.dumps(record),))
        report = read_json(self.run/'report.json'); report['catalogue_sha256'] = sha256(self.run/'catalogue.sqlite3')
        write_json(self.run/'report.json', report)
        plan.update(parent_catalogue_sha256=report['catalogue_sha256'], parent_report_sha256=sha256(self.run/'report.json'),
                    repair_review=[{'csd_id': '5901001', 'name': record['name'], 'status': 'unapproved', 'repair': record['repair']}])
        plan['region_updates'] = [{'id': 'ca-bc-pending-group', 'operation': 'add', 'source_id': 'pending-group',
            'name': 'Pending group', 'kind': 'regional_group', 'type': 'Regional group',
            'member_ids': ['ca-csd-5901001'], 'coverage_policy': 'selected_members',
            'coverage_note': 'Synthetic unapproved member', 'effective_date': '2026-01-01', 'evidence': self.evidence}]
        plan['membership_updates'] = [{'municipality_id': 'ca-csd-5901001', 'previous_region_id': 'ca-bc-old-group',
            'region_id': 'ca-bc-pending-group', 'effective_date': '2026-01-01', 'evidence': self.evidence}]
        ds = self.exported(plan, 'pending-group')
        self.assertNotIn('ca-bc-pending-group', ds.geometries)
        self.assertIn('ca-bc-pending-group', ds.pending_ids)
        point = ds.geometries['ca-bc-old-community'].representative_point()
        self.assertIn('ca-bc-pending-group', ds.lookup(point.x, point.y)['review_candidate_ids'])
        with self.assertRaises(CatalogueError): ds.boundary('ca-bc-pending-group', 'full')

    def test_reader_rejects_truncated_successor_even_with_updated_artifact_hash(self):
        plan, _ = self.migration_plan(); self.build(plan, 'tampered')
        run = self.root/'tampered'
        with closing(sqlite3.connect(run/'catalogue.sqlite3')) as db, db:
            first = db.execute("SELECT geometry FROM csd WHERE id='5901001'").fetchone()[0]
            db.execute("UPDATE jurisdiction_revision SET geometry=? WHERE operation='new'", (first,))
        report = read_json(run/'report.json'); report['catalogue_sha256'] = sha256(run/'catalogue.sqlite3')
        write_json(run/'report.json', report)
        export_release(run, self.root/'tampered-release')
        with self.assertRaisesRegex(CatalogueError, 'complete predecessor'):
            Dataset(self.root/'tampered-release')
