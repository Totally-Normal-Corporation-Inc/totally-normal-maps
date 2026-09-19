"""Synthetic evidence checks; never fetch or silently approve real source data."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import MultiPolygon, Polygon, box

from totally_normal_maps.catalogue import CatalogueError, propose_repair, read_json, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.topology_review import repair_release, validate_ring_repair
from .api_fixture import make_release


class RingReviewTests(unittest.TestCase):
    def setUp(self):
        # Two square exclusions sharing one vertex, encoded as one invalid ring.
        ring = [(2, 2), (4, 2), (4, 4), (6, 4), (6, 6), (4, 6), (4, 4), (2, 4), (2, 2)]
        self.original = Polygon(box(0, 0, 10, 10).exterior, [ring])
        self.enclave = MultiPolygon([box(2, 2, 4, 4), box(4, 4, 6, 6)])
        self.candidate, metrics = propose_repair(self.original)
        self.review = {**metrics, 'enclave': {'sha256': hashlib.sha256(self.enclave.wkb).hexdigest()}}

    def test_exact_enclave_corroborates_hole_split_without_changing_extent(self):
        repaired, metrics = validate_ring_repair(self.original, self.enclave, self.review)
        self.assertTrue(repaired.is_valid)
        self.assertEqual(metrics['area_change_m2'], 0)
        self.assertEqual(len(repaired.interiors), 2)
        self.assertTrue(repaired.exterior.equals(self.original.exterior))
        self.assertTrue(repaired.disjoint(self.enclave.representative_point()))
        self.assertTrue(repaired.covers(box(8, 8, 9, 9)))

    def test_unpinned_source_candidate_or_enclave_is_rejected(self):
        for key in ['source_sha256', 'candidate_sha256']:
            with self.subTest(key=key), self.assertRaises(CatalogueError):
                validate_ring_repair(self.original, self.enclave, {**self.review, key: '0' * 64})
        with self.assertRaises(CatalogueError):
            validate_ring_repair(self.original, box(2, 2, 6, 6), self.review)

    def test_equal_area_and_valid_geometry_are_insufficient(self):
        # Same area as the actual enclave, but entirely different territory.
        wrong = box(1, 7, 5, 9)
        review = {**self.review, 'enclave': {'sha256': hashlib.sha256(wrong.wkb).hexdigest()}}
        with self.assertRaises(CatalogueError):
            validate_ring_repair(self.original, wrong, review)

    def test_valid_sources_are_not_reclassified_as_repairs(self):
        with self.assertRaises(CatalogueError):
            validate_ring_repair(self.candidate, self.enclave, self.review)


class RepairReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, self.release, _ = make_release(self.root)
        self.uid, self.region = '2401001', 'ca-qc-test-region'
        ring = [(-109.75,50.25),(-109.5,50.25),(-109.5,50.5),(-109.25,50.5),
                (-109.25,50.75),(-109.5,50.75),(-109.5,50.5),(-109.75,50.5),(-109.75,50.25)]
        original = Polygon(box(-110,50,-109,51).exterior, [ring])
        self.candidate, self.metrics = propose_repair(original)
        with closing(sqlite3.connect(self.release/'catalogue.sqlite3')) as db, db:
            for table, uid in [('csd', self.uid), ('region', self.region)]:
                record = json.loads(db.execute(f'SELECT record FROM {table} WHERE id=?', (uid,)).fetchone()[0])
                record.update(assignment_status='unreviewed_repair', issues=['synthetic original defect'])
                if table == 'csd': record['repair'] = self.metrics
                else: record['unreviewed_member_ids'] = [self.uid]
                db.execute(f'UPDATE {table} SET record=?, geometry=NULL, repair_candidate=? WHERE id=?',
                           (json.dumps(record), self.candidate.wkb, uid))
        report = read_json(self.release/'report.json')
        report['quebec_refresh'] = {'active_municipality_count': report['feature_count'], 'sources': {},
            'repair_review': [{'csd_id': self.uid, 'decision': 'retain_unapproved_repair', 'reason': 'old review'}],
            'unresolved': [{'scope': 'Québec municipal repairs', 'ids': ['ca-csd-'+self.uid]}]}
        report['catalogue_sha256'] = sha256(self.release/'catalogue.sqlite3')
        write_json(self.release/'report.json', report)
        manifest = read_json(self.release/'manifest.json')
        for name in manifest['files']:
            file = self.release/name
            manifest['files'][name] = {'sha256': sha256(file), 'bytes': file.stat().st_size}
        write_json(self.release/'manifest.json', manifest)
        self.digest = sha256(self.release/'manifest.json')
        self.review = {'manifest_sha256': self.digest, 'csd_id': self.uid, 'region_id': self.region,
                      'name': 'Synthetic municipality', 'decision': 'approve_topology_only',
                      'reason': 'Synthetic exact enclave evidence', 'scope': 'Synthetic test'}
        self.plan = self.root/'review.json'; write_json(self.plan, self.review)
        self.source_manifest = report['source']

    def apply(self, output, candidate=None):
        with patch('totally_normal_maps.topology_review.PLAN', self.plan), \
             patch('totally_normal_maps.topology_review.reviewed_source',
                   return_value=(candidate if candidate is not None else self.candidate, self.metrics, self.source_manifest)):
            return repair_release(self.release, self.root/'not-downloaded.zip', output)

    def test_new_release_promotes_only_the_pinned_candidate_and_parent(self):
        before = {p.relative_to(self.release): p.read_bytes() for p in self.release.rglob('*') if p.is_file()}
        output = self.root/'corrected'
        result = self.apply(output)
        dataset = Dataset(output, result['manifest_sha256'])
        self.assertEqual(dataset.geometries['ca-csd-'+self.uid].wkb, self.candidate.wkb)
        self.assertIn(self.region, dataset.geometries)
        self.assertIn('ca-csd-1201001', dataset.pending_ids)
        self.assertEqual(dataset.areas['ca-csd-'+self.uid]['repair']['original_issues'], ['synthetic original defect'])
        self.assertEqual(dataset.report['quebec_refresh']['repair_review'][0]['prior_decision']['reason'], 'old review')
        self.assertEqual(dataset.report['quebec_refresh']['unresolved'][0]['ids'], [])
        for path, content in before.items(): self.assertEqual((self.release/path).read_bytes(), content)
        with self.assertRaises(CatalogueError): self.apply(output)

    def test_changed_candidate_or_parent_never_leaves_partial_output(self):
        with self.assertRaises(CatalogueError): self.apply(self.release/'nested-output')
        self.assertFalse((self.release/'nested-output').exists())
        output = self.root/'bad-candidate'
        with self.assertRaises(CatalogueError): self.apply(output, box(-110,50,-109,51))
        self.assertFalse(output.exists())
        write_json(self.plan, {**self.review, 'manifest_sha256': '0'*64})
        output = self.root/'bad-parent'
        with self.assertRaises(CatalogueError): self.apply(output)
        self.assertFalse(output.exists())
