"""Synthetic topology evidence: no source downloads, real-data approvals or cloud."""
import unittest
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

import shapely
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import transform

from totally_normal_maps.boundary_review import surface_checks, minor_correction, current_overlap_correction, audit, apply_review, update_reports, WGS84, digest, validated_review, source_face_proof, retraced_segments
from totally_normal_maps.catalogue import CatalogueError, propose_repair, read_json, write_json, sha256
from totally_normal_maps.dataset import Dataset
from tests.api_fixture import make_release


def seal(root):
    report = read_json(root / 'report.json')
    report['catalogue_sha256'] = sha256(root / 'catalogue.sqlite3')
    write_json(root / 'report.json', report)
    manifest = read_json(root / 'manifest.json')
    for name in manifest['files']:
        manifest['files'][name] = {'bytes': (root / name).stat().st_size, 'sha256': sha256(root / name)}
    write_json(root / 'manifest.json', manifest)


class SurfaceReviewTests(unittest.TestCase):
    def test_source_faces_preserve_an_explicit_unowned_exclusion(self):
        original = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0),
                            (2, 2), (2, 4), (4, 4), (4, 2), (2, 2), (0, 0)])
        candidate, _ = propose_repair(original)
        proof = source_face_proof(original, candidate)
        self.assertTrue(proof['verified'])
        self.assertEqual(proof['excluded_faces'], 1)
        self.assertFalse(source_face_proof(original, box(0, 0, 10, 10))['verified'])

    def test_long_exact_retrace_can_be_removed_without_moving_territory(self):
        original = Polygon([(0, 0), (1000, 0), (1000, 1000), (500, 1000),
                            (500, 2000), (500, 1000), (0, 1000), (0, 0)])
        candidate, _ = propose_repair(original)
        evidence = surface_checks(original, candidate, {}, crs='EPSG:3347')
        evidence['source_faces'] = source_face_proof(original, candidate)
        fixed, review = minor_correction(original, candidate, {}, 'EPSG:3347', evidence)
        self.assertTrue(all(review['checks'].values()), review)
        self.assertTrue(fixed.equals(box(0, 0, 1000, 1000)))
        self.assertEqual(review['total_affected_area_m2'], 0)

    def test_a_thin_positive_area_spike_is_not_an_exact_retrace(self):
        original = Polygon([(0, 0), (1000, 0), (1000, 1000), (501, 1000),
                            (500, 2000), (500, 1000), (0, 1000), (0, 0)])
        self.assertTrue(retraced_segments(original).is_empty)
        self.assertFalse(source_face_proof(original, box(0, 0, 1000, 1000))['verified'])

    def test_source_faces_reject_method_disagreement_and_overlapping_surfaces(self):
        bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
        candidate, _ = propose_repair(bowtie)
        self.assertFalse(source_face_proof(bowtie, candidate)['verified'])
        overlapping = MultiPolygon([box(0, 0, 10, 10), box(5, 0, 15, 10)])
        self.assertFalse(source_face_proof(overlapping, shapely.union_all(list(overlapping.geoms)))['verified'])

    def setUp(self):
        ring = [(2, 2), (4, 2), (4, 4), (6, 4), (6, 6), (4, 6), (4, 4), (2, 4), (2, 2)]
        self.original = Polygon(box(0, 0, 10, 10).exterior, [ring])
        self.candidate, _ = propose_repair(self.original)
        self.neighbours = {'a': box(2, 2, 4, 4), 'b': box(4, 4, 6, 6)}

    def check(self, neighbours=None, original=None):
        original = self.original if original is None else original
        candidate, _ = propose_repair(original)
        return surface_checks(original, candidate, self.neighbours if neighbours is None else neighbours, crs='EPSG:3347')

    def test_exact_exclusions_qualify_and_are_deterministic(self):
        evidence = self.check()
        self.assertTrue(all(evidence['checks'].values()))
        self.assertEqual(evidence['overlap_area_m2'], 0)
        self.assertEqual(evidence, self.check(dict(reversed(list(self.neighbours.items())))))
        self.assertEqual(len(evidence['exclusion_evidence']), 2)

    def test_equal_area_elsewhere_does_not_corroborate_exclusions(self):
        evidence = self.check({'wrong': box(12, 12, 14, 16)})
        self.assertFalse(evidence['checks']['exclusions_corroborated'])

    def test_unreviewed_neighbour_cannot_corroborate_an_exclusion(self):
        evidence = self.check({'invalid': self.original})
        self.assertFalse(evidence['checks']['exclusions_corroborated'])
        self.assertFalse(evidence['checks']['neighbour_overlap_bounded'])

    def test_overlap_requires_both_absolute_and_relative_bounds(self):
        evidence = self.check({**self.neighbours, 'conflict': box(0, 0, .1, .1)})
        self.assertLess(evidence['overlap_area_m2'], 1)
        self.assertFalse(evidence['checks']['neighbour_overlap_bounded'])

    def test_lost_linework_is_not_approved_as_zero_area_cleanup(self):
        spike = Polygon([(0, 0), (10, 0), (10, 10), (5, 10), (5, 12), (5, 10), (0, 10), (0, 0)])
        evidence = self.check({}, spike)
        self.assertFalse(evidence['checks']['no_discarded_coordinates'])
        self.assertFalse(evidence['checks']['boundary_unchanged'])

    def test_bow_tie_does_not_qualify_merely_because_repair_is_valid(self):
        evidence = self.check({}, Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)]))
        self.assertFalse(all(evidence['checks'].values()))

    def test_valid_source_is_not_a_repair(self):
        self.assertFalse(self.check({}, box(0, 0, 10, 10))['checks']['invalid_source'])

    def test_whole_components_of_multipart_neighbour_corroborate_separate_holes(self):
        result = self.check({'islands': MultiPolygon(list(self.neighbours.values()))})
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual(result['exclusion_evidence'][0]['basis'], 'same_source_complete_components')

    def test_unchanged_original_hole_does_not_require_another_area_to_fill_it(self):
        rings = [list(self.original.interiors[0].coords), list(box(7, 7, 8, 8).exterior.coords)]
        result = self.check(original=Polygon(self.original.exterior, rings))
        self.assertTrue(all(result['checks'].values()))
        self.assertIn('unchanged_source_hole', [r['basis'] for r in result['exclusion_evidence']])

    def test_partial_neighbour_component_cannot_be_clipped_to_fit_a_hole(self):
        result = self.check({'oversized': box(1, 1, 5, 5)})
        self.assertFalse(result['checks']['exclusions_corroborated'])

    def test_partition_preserves_own_island_inside_an_exclusion(self):
        island = box(2.5, 2.5, 3.5, 3.5)
        original = MultiPolygon([self.original, island])
        candidate, _ = propose_repair(original)
        neighbours = {'a': self.neighbours['a'].difference(island), 'b': self.neighbours['b']}
        old = surface_checks(original, candidate, neighbours, crs='EPSG:3347')
        self.assertFalse(old['checks']['exclusions_corroborated'])
        reviewed = surface_checks(original, candidate, neighbours, crs='EPSG:3347', partition_members={})
        self.assertTrue(all(reviewed['checks'].values()))
        self.assertEqual(sum(p.get('retained_island_area_m2', 0) for p in reviewed['exclusion_evidence']), 1)
        self.assertTrue(candidate.covers(island))

    def test_partition_still_rejects_clipping_a_neighbour_to_manufacture_proof(self):
        result = surface_checks(self.original, self.candidate, {'oversized': box(1, 1, 5, 5)},
                                crs='EPSG:3347', partition_members={})
        self.assertFalse(result['checks']['exclusions_corroborated'])

    def test_partition_rejects_an_unexplained_gap_even_when_other_checks_agree(self):
        neighbours = {**self.neighbours, 'a': box(2, 2, 3.9, 4)}
        result = surface_checks(self.original, self.candidate, neighbours,
                                crs='EPSG:3347', partition_members={})
        self.assertFalse(result['checks']['exclusions_corroborated'])

    def test_old_narrative_unresolved_notes_survive_report_updates(self):
        report = {'quebec_refresh': {'unresolved': ['Existing source-vintage note.',
            {'scope': 'Québec municipal repairs', 'ids': ['ca-csd-1', 'ca-csd-2']}]}}
        update_reports(report, {'csd': {'1': {'record': {'assignment_status': 'validated_derived'}}}}, {('csd', '1')})
        self.assertEqual(report['quebec_refresh']['unresolved'][0], 'Existing source-vintage note.')
        self.assertEqual(report['quebec_refresh']['unresolved'][1]['ids'], ['ca-csd-2'])

    def test_all_copies_of_city_coverage_reflect_approved_assignments(self):
        scope = {'source': 'test', 'kind': 'neighbourhood', 'expected_count': 1,
                 'assignment_boundary_count': 0, 'unapproved_repair_count': 1}
        report = {'ontario_refresh': {'coverage': [copy.deepcopy(scope)]},
                  'city_areas': {'municipalities': [copy.deepcopy(scope)]}}
        rows = {'csd': {}, 'city_area': {'a': {'id': 'a', 'geometry': box(-75, 45, -74.99, 45.01).wkb,
            'record': {'source': 'test', 'kind': 'neighbourhood', 'assignment_status': 'validated_derived'}}}}
        update_reports(report, rows, {('city_area', 'a')})
        first = report['ontario_refresh']['coverage'][0]
        self.assertEqual(first, report['city_areas']['municipalities'][0])
        self.assertEqual(first['assignment_boundary_count'], 1)
        self.assertEqual(first['unapproved_repair_count'], 0)
        self.assertFalse(first['coverage_measure_includes_unapproved_candidates'])
        self.assertEqual(first['assignment_sibling_overlap_m2'], 0)


class ReleaseReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, self.release, _ = make_release(self.root)
        self.uid = 'ca-qc-test-west'
        ring = [(-109.9, 50.2), (-109.8, 50.2), (-109.8, 50.3), (-109.7, 50.3),
                (-109.7, 50.4), (-109.8, 50.4), (-109.8, 50.3), (-109.9, 50.3), (-109.9, 50.2)]
        self.original = Polygon(box(-109.95, 50.1, -109.6, 50.5).exterior, [ring])
        self.candidate, ledger = propose_repair(self.original)
        with closing(sqlite3.connect(self.release / 'catalogue.sqlite3')) as db, db:
            record = json.loads(db.execute('SELECT record FROM city_area WHERE id=?', (self.uid,)).fetchone()[0])
            record.update(assignment_status='unreviewed_repair', repair=ledger, uncertainty_basis='source_bbox',
                          bbox=list(self.original.bounds), issues=['invalid_geometry: synthetic', 'Unapproved source repair; display only'])
            db.execute('UPDATE city_area SET record=?, geometry=NULL WHERE id=?', (json.dumps(record), self.uid))
        seal(self.release)
        self.data = Dataset(self.release)
        self.sources = [('city_area', 'synthetic', 'a'*64, 'EPSG:4326', {
            self.uid: self.original, 'enclave-a': box(-109.9, 50.2, -109.8, 50.3),
            'enclave-b': box(-109.8, 50.3, -109.7, 50.4)})]

    def run_audit(self):
        with patch('totally_normal_maps.boundary_review.source_groups', return_value=iter(self.sources)):
            return audit(self.data)[0]

    def apply(self, result, output):
        with patch('totally_normal_maps.boundary_review.source_groups', return_value=iter(self.sources)):
            return apply_review(self.data, output, result)

    def test_atomic_release_preserves_existing_assignments_and_display_coordinates(self):
        result = self.run_audit()
        self.assertEqual(result['counts']['approve_topology_only'], 1)
        out = self.root / 'reviewed'
        self.apply(result, out)
        after = Dataset(out)
        self.assertEqual(after.geometries[self.uid].wkb, self.candidate.wkb)
        self.assertNotIn(self.uid, after.pending_ids)
        self.assertNotIn(self.uid, self.data.geometries)
        self.assertEqual(after.displays[self.uid], self.data.displays[self.uid])
        for uid, g in self.data.geometries.items():
            self.assertEqual(after.geometries[uid].wkb, g.wkb)
        p = self.candidate.representative_point()
        self.assertIn(self.uid, after.lookup(p.x, p.y)['direct_match_ids'])
        for ring in self.candidate.interiors:
            p = Polygon(ring).representative_point()
            self.assertNotIn(self.uid, after.lookup(p.x, p.y)['direct_match_ids'])
        with self.assertRaises((CatalogueError, FileExistsError)):
            self.apply(result, out)

    def test_modified_audit_fails_without_output_or_input_changes(self):
        result = self.run_audit(); result['dataset_version'] = '0'*64
        out = self.root / 'failed'
        with self.assertRaises(CatalogueError): self.apply(result, out)
        self.assertFalse(out.exists())
        self.assertEqual(Dataset(self.release).version, self.data.version)

    def test_changed_source_and_ledger_fail_closed(self):
        self.sources[0][-1][self.uid] = box(-109.95, 50.1, -109.6, 50.5)
        with self.assertRaises(CatalogueError): self.run_audit()

    def test_startup_rejects_forged_approval_even_after_manifest_resealed(self):
        result = self.run_audit(); out = self.root / 'reviewed'
        self.apply(result, out)
        report = read_json(out / 'report.json')
        next(r for r in report['boundary_review']['inventory'] if r['id'] == self.uid)['decision'] = 'retain_unapproved'
        write_json(out / 'report.json', report); seal(out)
        with self.assertRaises(CatalogueError): Dataset(out)

    def test_interrupted_staging_leaves_original_usable(self):
        result = self.run_audit(); out = self.root / 'interrupted'
        with patch('totally_normal_maps.boundary_review.shutil.copyfile', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError): self.apply(result, out)
        self.assertFalse(out.exists())
        self.assertEqual(Dataset(self.release).version, self.data.version)

    def test_prepared_packages_must_be_rebuilt_after_repairs(self):
        # The guard itself must reject even before source processing begins.
        prepared = copy.copy(self.data)
        prepared.manifest = {**self.data.manifest, 'files': {**self.data.manifest['files'], 'packages/index.json': {}}}
        with self.assertRaisesRegex(CatalogueError, 'pre-package'):
            apply_review(prepared, self.root / 'bad', {})

    def test_csd_approval_rebinds_only_missing_population_and_qualifies_complete_region(self):
        from tests.test_population import census_source
        from totally_normal_maps.population import eligible, import_population, territory_fingerprint
        _, ledger = propose_repair(self.original)
        with closing(sqlite3.connect(self.release / 'catalogue.sqlite3')) as db, db:
            for table, uid in [('csd', '2401001'), ('region', 'ca-qc-test-region')]:
                record = json.loads(db.execute(f'SELECT record FROM {table} WHERE id=?', (uid,)).fetchone()[0])
                record.update(assignment_status='unreviewed_repair', issues=['invalid_geometry: synthetic'])
                if table == 'csd': record['repair'] = ledger
                else: record.update(unreviewed_member_ids=['2401001'], evidence=[{'claim': 'synthetic source'}])
                db.execute(f'UPDATE {table} SET record=?, geometry=NULL, repair_candidate=? WHERE id=?',
                           (json.dumps(record), self.candidate.wkb, uid))
        seal(self.release); data = Dataset(self.release)
        ids = sorted(eligible(data))
        source = census_source(self.root, [('2021A0005' + data.areas[u]['source_id'], '1', '') for u in ids])
        plan = {'schema_version': 1, 'base_dataset_version': data.version, 'reviewed_on': '2026-09-28',
                'reference_year': 2021, 'sources': {'census': source}, 'matches': {},
                'unavailable': {u: {'reason': 'incompatible_boundary', 'target_sha256': territory_fingerprint(data, u),
                                    'evidence': ['Synthetic unresolved population match.']} for u in ids}}
        plan_path = self.root / 'population-plan.json'; write_json(plan_path, plan)
        populated = self.root / 'populated'
        import_population(self.release, populated, expected_sha256=data.version, plan_path=plan_path, source_dir=self.root)
        self.data = Dataset(populated)
        self.sources.append(('csd', 'synthetic', 'b'*64, 'EPSG:4326', {
            '2401001': self.original, 'enclave-a': box(-109.9, 50.2, -109.8, 50.3),
            'enclave-b': box(-109.8, 50.3, -109.7, 50.4)}))
        result = self.run_audit(); out = self.root / 'with-population'
        self.apply(result, out); after = Dataset(out)
        self.assertIn('ca-qc-test-region', after.geometries)
        self.assertIn('ca-csd-2401001', after.geometries)
        for uid in ids:
            self.assertEqual(after.populations[uid]['metadata'], self.data.populations[uid]['metadata'])
        self.assertNotEqual(after.populations['ca-csd-2401001']['target_sha256'],
                            self.data.populations['ca-csd-2401001']['target_sha256'])

    def test_prior_approval_remains_verifiable_in_a_later_batch_history(self):
        result = self.run_audit(); out = self.root / 'reviewed'
        self.apply(result, out)
        report = read_json(out / 'report.json')
        report['boundary_review_history'] = [report.pop('boundary_review')]
        write_json(out / 'report.json', report); seal(out)
        self.assertIn(self.uid, Dataset(out).geometries)


class JointMunicipalExclusionTests(unittest.TestCase):
    def review(self, broken=False):
        x, y = 5_000_000, 2_000_000
        ring = [(x+2,y+2),(x+4,y+2),(x+4,y+4),(x+6,y+4),(x+6,y+6),
                (x+4,y+6),(x+4,y+4),(x+2,y+4),(x+2,y+2)]
        originals = {'1': Polygon(box(x,y,x+10,y+10).exterior,[ring]), '2': Polygon(ring)}
        if broken:
            originals['2'] = Polygon([*ring[:-1], (x-10,y+4), (x+2,y+4), ring[-1]])
        rows = {'csd': {}}
        for uid, original in originals.items():
            candidate, ledger = propose_repair(original)
            rows['csd'][uid] = {'id': uid, 'geometry': None, 'repair_candidate': transform(WGS84,candidate).wkb,
                'record': {'id':uid,'name':uid,'assignment_status':'unreviewed_repair','repair':ledger}}
        data = SimpleNamespace(version='a'*64, areas={'ca-csd-'+u: {'level':'municipality'} for u in originals},
                               populations={}, geometries={}, tree=shapely.STRtree([]), geometry_ids=[])
        sources = [('csd','synthetic','b'*64,'EPSG:3347',originals)]
        with patch('totally_normal_maps.boundary_review.load_rows', return_value=rows), \
                patch('totally_normal_maps.boundary_review.source_groups', return_value=iter(sources)):
            result, candidates = audit(data,csd_exclusions_only=True)
        return result,candidates,rows

    def test_joint_review_qualifies_every_member_and_is_reproducible(self):
        result,candidates,_ = self.review()
        self.assertEqual(result['counts'], {'approve_topology_only':2})
        self.assertEqual(result['csd_exclusion_partition']['member_ids'], ['1','2'])
        self.assertEqual(set(candidates), {('csd','1'),('csd','2')})
        self.assertEqual(result,self.review()[0])

    def test_one_failed_member_rejects_the_entire_joint_approval(self):
        with self.assertRaisesRegex(CatalogueError,'partition is incomplete'):
            self.review(broken=True)

    def test_startup_rejects_partial_joint_evidence_even_with_rebound_audit_hash(self):
        result,candidates,rows = self.review()
        def record():
            row=copy.deepcopy(rows['csd']['1']['record']);row['assignment_status']='validated_derived'
            row['repair'].update(status='reviewed_topology_batch',review={'audit_sha256':digest(result),
                'original_record_sha256':result['inventory'][0]['record_sha256'],'decision':'approve_topology_only'})
            return row
        self.assertTrue(validated_review(record(),candidates['csd','1'],{'boundary_review':result}))
        group = result.pop('csd_exclusion_partition')
        with self.assertRaisesRegex(CatalogueError,'lacks its joint approval'):
            validated_review(record(),candidates['csd','1'],{'boundary_review':result})
        result['csd_exclusion_partition'] = group
        result['inventory'][1]['decision']='retain_unapproved'
        with self.assertRaisesRegex(CatalogueError,'joint municipal exclusion approval'):
            validated_review(record(),candidates['csd','1'],{'boundary_review':result})


class MinorCorrectionTests(unittest.TestCase):
    def original(self, length=1):
        return Polygon([(0, 0), (1000, 0), (1000, 1000), (500, 1000),
                        (500, 1000 + length), (500, 1000), (0, 1000), (0, 0)])

    def review(self, length=1, neighbours=None):
        original = self.original(length); candidate, _ = propose_repair(original)
        neighbours = neighbours or {}
        evidence = surface_checks(original, candidate, neighbours, crs='EPSG:3347')
        return minor_correction(original, candidate, neighbours, 'EPSG:3347', evidence)

    def test_one_metre_zero_area_spike_is_a_minor_correction(self):
        fixed, evidence = self.review()
        self.assertTrue(all(evidence['checks'].values()))
        self.assertTrue(fixed.equals(box(0, 0, 1000, 1000)))

    def test_long_exact_retrace_requires_explicit_linework_evidence(self):
        _, evidence = self.review(6)
        self.assertTrue(evidence['checks']['movement_bounded'])
        self.assertIn('retraced_linework_sha256', evidence)

    def test_tiny_overlap_goes_to_existing_valid_neighbour(self):
        neighbour = box(999.99, 0, 1100, 1000)
        fixed, evidence = self.review(neighbours={'existing': neighbour})
        self.assertTrue(all(evidence['checks'].values()))
        self.assertEqual(fixed.intersection(neighbour).area, 0)
        self.assertAlmostEqual(evidence['correction_area_m2'], 10)

    def test_large_overlap_is_not_fixed_under_minor_policy(self):
        _, evidence = self.review(neighbours={'existing': box(999, 0, 1100, 1000)})
        self.assertFalse(evidence['checks']['overlap_correction_bounded'])

    def test_pending_peer_cannot_win_an_overlap_by_accident(self):
        _, evidence = self.review(neighbours={'pending': self.original(.5)})
        self.assertFalse(evidence['checks']['overlap_owners_valid'])

    def test_current_wgs84_overlap_is_removed_without_moving_the_neighbour(self):
        candidate = box(-75, 45, -74.99, 45.01)
        neighbour = box(-74.9900001, 45, -74.98, 45.01)
        original = neighbour.wkb
        fixed, evidence = current_overlap_correction(candidate, {'neighbour': neighbour})
        self.assertTrue(all(evidence['checks'].values()))
        self.assertEqual(fixed.intersection(neighbour).area, 0)
        self.assertEqual(neighbour.wkb, original)
        self.assertLess(evidence['total_affected_area_m2'], 100)

    def test_sequential_corrections_share_one_total_budget(self):
        candidate = box(-75, 45, -74.99, 45.01)
        neighbour = box(-74.9900001, 45, -74.98, 45.01)
        _, evidence = current_overlap_correction(candidate, {'neighbour': neighbour}, prior_affected=100)
        self.assertFalse(evidence['checks']['correction_area_bounded'])

    def test_projection_does_not_invent_area_or_movement_from_added_collinear_vertices(self):
        candidate = box(-76, 44, -74, 46)
        touching = box(-77, 45, -76, 45.1)
        fixed, evidence = current_overlap_correction(candidate, {'touching': touching})
        self.assertTrue(fixed.equals(candidate))
        self.assertEqual(evidence['correction_area_m2'], 0)
        self.assertTrue(all(evidence['checks'].values()))

class ReviewedParentTests(unittest.TestCase):
    def setUp(self):
        from totally_normal_maps.boundary_review import BOROUGH_SOURCE, BOROUGH_SHA256
        self.original = {'id': 'child', 'source_id': '1.1', 'parent_id': 'city',
                         'authority_id': 'city', 'edition': 'edition', 'source': BOROUGH_SOURCE}
        self.geometry = box(0, 0, 1, 1).wkb
        import hashlib
        self.batch = {'inventory': [{'id': 'parent', 'decision': 'approve_minor_correction',
            'evidence': {'source_child_partition': {'child_ids': ['child']}}}],
            'municipal_hierarchy': {'contract': 'source-borough-partition.v1',
                'source': BOROUGH_SOURCE, 'source_sha256': BOROUGH_SHA256,
                'changes': {'child': {'parent_id': 'parent', 'previous_parent_id': 'city',
                    'record_sha256': digest(self.original),
                    'geometry_sha256': hashlib.sha256(self.geometry).hexdigest()}}}}
        self.record = {**self.original, 'parent_id': 'parent', 'parent_review': {'audit_sha256': digest(self.batch)}}
        self.report = {'boundary_review': self.batch,
            'municipal_elections': {'sources': {BOROUGH_SOURCE: {'sha256': BOROUGH_SHA256}}}}
        self.parents = {'parent': {'source_id': '1', 'parent_id': 'city', 'edition': 'edition', 'source': BOROUGH_SOURCE}}

    def check(self):
        from totally_normal_maps.boundary_review import validated_parent_review
        return validated_parent_review(self.record, self.geometry, self.report, self.parents)

    def test_exact_reviewed_parent_and_unchanged_child(self):
        self.assertTrue(self.check())

    def test_changed_geometry_fails(self):
        self.geometry = box(0, 0, 2, 2).wkb
        with self.assertRaises(CatalogueError): self.check()

    def test_unrelated_metadata_change_fails(self):
        self.record['name'] = 'changed'
        with self.assertRaises(CatalogueError): self.check()

    def test_cross_edition_parent_fails(self):
        self.parents['parent']['edition'] = 'other'
        with self.assertRaises(CatalogueError): self.check()

    def test_changed_source_or_missing_child_evidence_fails(self):
        self.batch['inventory'][0]['evidence']['source_child_partition']['child_ids'] = []
        self.record['parent_review']['audit_sha256'] = digest(self.batch)
        with self.assertRaises(CatalogueError): self.check()

class ProvenSliverTests(unittest.TestCase):
    def review(self, width, length, proven=True):
        original = Polygon([(0, 0), (20000, 0), (20000, 20000),
            (10000, 20000), (10000, 20001), (10000, 20000), (0, 20000), (0, 0)])
        candidate, _ = propose_repair(original)
        neighbours = {'owner': box(20000-width, 0, 20001, length)}
        evidence = surface_checks(original, candidate, neighbours, crs='EPSG:3347')
        if proven: evidence['source_faces'] = source_face_proof(original, candidate)
        return minor_correction(original, candidate, neighbours, 'EPSG:3347', evidence)[1]

    def test_accumulated_narrow_strips_require_source_proof(self):
        self.assertTrue(all(self.review(2, 2000)['checks'].values()))
        self.assertFalse(all(self.review(2, 2000, False)['checks'].values()))

    def test_six_thousand_square_metre_limit(self):
        self.assertTrue(all(self.review(2, 3000)['checks'].values()))
        self.assertFalse(all(self.review(2, 3001)['checks'].values()))

    def test_small_area_does_not_excuse_wide_strip(self):
        self.assertFalse(all(self.review(10, 50)['checks'].values()))

class OwnedMicroSliverTests(unittest.TestCase):
    def review(self, width):
        main = Polygon([(0, 0), (1000, 0), (1000, 1000), (500, 1000),
                        (500, 1001), (500, 1000), (0, 1000), (0, 0)])
        remote = Polygon([(0, 2000), (width, 2000), (0, 4000), (0, 2000)])
        original = MultiPolygon([main, remote]); candidate, _ = propose_repair(original)
        neighbours = {'valid_owner': box(-1, 1999, 1, 4001)}
        evidence = surface_checks(original, candidate, neighbours, crs='EPSG:3347')
        return minor_correction(original, candidate, neighbours, 'EPSG:3347', evidence)[1]

    def test_tiny_removed_component_keeps_its_existing_validated_owner(self):
        review = self.review(.0001)
        self.assertTrue(all(review['checks'].values()), review)
        self.assertAlmostEqual(review['owned_sliver_m2'], .1)

    def test_larger_remote_component_does_not_bypass_movement_check(self):
        self.assertFalse(all(self.review(.101)['checks'].values()))

class SourceChildUnionTests(unittest.TestCase):
    def run_review(self, mismatch=False):
        from totally_normal_maps.boundary_review import BOROUGH_SOURCE, BOROUGH_SHA256
        a = box(-75, 45, -74.99, 45.01)
        b = box(-74.995, 45.005, -74.985, 45.015)
        original = MultiPolygon([a, b]); candidate, ledger = propose_repair(original)
        shapes = {'parent': original, 'child-a': a, 'child-b': b.difference(a)}
        common = {'level': 'electoral_district', 'layer': 'municipal', 'edition': 'test',
                  'source': BOROUGH_SOURCE, 'authority_id': 'city', 'parent_id': 'city'}
        rows = {'csd': {}, 'municipal_electoral_area': {}}
        for uid, g in shapes.items():
            record = {**common, 'id': uid, 'name': uid,
                      'source_id': {'parent': '1', 'child-a': '1.1', 'child-b': '1.2'}[uid],
                      'assignment_status': 'unreviewed_repair' if uid == 'parent' else 'validated_source'}
            if uid == 'parent': record['repair'] = ledger
            rows['municipal_electoral_area'][uid] = {'id': uid, 'record': record,
                'geometry': None if uid == 'parent' else g.wkb,
                'repair_candidate': candidate.wkb if uid == 'parent' else None}
        if mismatch:
            rows['municipal_electoral_area']['child-b']['geometry'] = b.wkb
        geoms = {u: shapely.from_wkb(r['geometry']) for u, r in rows['municipal_electoral_area'].items() if r['geometry']}
        data = SimpleNamespace(version='a'*64, report={}, populations={},
            areas={u:r['record'] for u,r in rows['municipal_electoral_area'].items()},
            geometries=geoms, geometry_ids=list(geoms), tree=shapely.STRtree(list(geoms.values())))
        with patch('totally_normal_maps.boundary_review.load_rows', return_value=rows), \
             patch('totally_normal_maps.boundary_review.source_groups', return_value=iter([
                 ('municipal_electoral_area', BOROUGH_SOURCE, BOROUGH_SHA256, 'EPSG:4326', shapes)])):
            result, approved = audit(data)
        return result, approved, rows, shapely.union_all([a, b])

    def test_child_union_resolves_method_conflict_with_explicit_hierarchy(self):
        result, approved, _, union = self.run_review()
        self.assertEqual(result['inventory'][0]['decision'], 'approve_source_child_union')
        self.assertTrue(approved['municipal_electoral_area', 'parent'].equals(union))
        self.assertEqual(set(result['municipal_hierarchy']['changes']), {'child-a', 'child-b'})

    def test_changed_child_assignment_cannot_supply_partition_proof(self):
        result, approved, _, _ = self.run_review(mismatch=True)
        self.assertEqual(approved, {})
        self.assertEqual(result['inventory'][0]['decision'], 'retain_unapproved')

    def test_startup_requires_complete_child_partition(self):
        result, approved, rows, _ = self.run_review()
        def record():
            r = copy.deepcopy(rows['municipal_electoral_area']['parent']['record'])
            r['assignment_status'] = 'validated_derived'
            r['repair'].update(status='reviewed_topology_batch', review={'audit_sha256': digest(result),
                'original_record_sha256': result['inventory'][0]['record_sha256'],
                'decision': 'approve_source_child_union'})
            return r
        shape = approved['municipal_electoral_area', 'parent']
        self.assertTrue(validated_review(record(), shape, {'boundary_review': result}))
        del result['municipal_hierarchy']['changes']['child-b']
        with self.assertRaisesRegex(CatalogueError, 'Incomplete source child partition'):
            validated_review(record(), shape, {'boundary_review': result})
