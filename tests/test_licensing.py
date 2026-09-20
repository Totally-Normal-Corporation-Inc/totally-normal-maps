"""Publication decisions remain separate from licences and cannot change geography."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from totally_normal_maps.catalogue import CatalogueError, read_json, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.licensing import redistribution_approved
from totally_normal_maps.municipal_elections import build_municipal
from totally_normal_maps.releases import checked_release
from tools.publish_dataset import check_redistribution
from tools.review_source_licences import review_source_licences
from tests.test_electoral import electoral_fixture


def decision():
    return {'redistribution_status': 'unconfirmed',
            'publication_decision': {'status': 'approved_by_maintainer', 'source_type': 'government',
                                     'reviewed_on': '2026-09-20', 'basis': 'Explicit maintainer direction.',
                                     'contact': 'info@example.test'},
            'publication_disclaimer': 'Published in good faith. Contact info@example.test for licence issues.',
            'attribution_statement': 'Source: Synthetic council. No endorsement is implied.',
            'licence_review': 'No dataset-specific licence found; maintainer approved publication.',
            'licence_evidence': [{'url': 'https://example.test/wards', 'finding': 'No licence stated.'}]}


class LicensingTests(unittest.TestCase):
    def test_default_plan_keeps_unlicensed_municipal_sources_on_standby(self):
        from totally_normal_maps.municipal_elections import PLAN
        plan = read_json(PLAN)
        electoral = read_json(PLAN.with_name('electoral-2026-09.json'))
        check_redistribution({'municipal_elections': plan, 'electoral': electoral})
        deferred = [r for r in plan['source_inventory']['decisions'] if r['decision'] == 'standby_licensing']
        self.assertEqual(len({r['source'] for r in deferred}), 36)
        self.assertEqual(sum(r['excluded_district_count'] for r in deferred), 213)
        sources = set(plan['sources'])
        editions = {e['id'] for e in plan['editions']}
        for row in deferred:
            self.assertNotIn('rep-' + row['source'], sources)
            self.assertNotIn(row['excluded_edition'], editions)
        gaps = [r for r in plan['coverage'].values() if 'on standby' in r.get('note', '')]
        self.assertEqual(len(gaps), 36)
        self.assertTrue(all(r['status'] == 'unavailable' and r['reviewed_on'] == '2026-09-20' for r in gaps))

    def test_decision_does_not_change_licence_status(self):
        source = decision()
        for section in ('electoral', 'municipal_elections'):
            report = {section: {'sources': {'government': source}}}
            check_redistribution(report)
            self.assertEqual(source['redistribution_status'], 'unconfirmed')
            report[section]['sources']['private'] = {'redistribution_status': 'unconfirmed', 'authority': 'MuniSoft'}
            with self.assertRaisesRegex(CatalogueError, '1 electoral sources'):
                check_redistribution(report)

    def test_incomplete_or_non_government_decisions_do_not_pass(self):
        for field in ('publication_decision', 'publication_disclaimer', 'attribution_statement',
                      'licence_review', 'licence_evidence'):
            source = decision(); source.pop(field)
            self.assertFalse(redistribution_approved(source), field)
        for field, value in [('source_type', 'private'), ('status', 'draft'),
                             ('reviewed_on', 'bad-date'), ('basis', ''), ('contact', 'other@example.test')]:
            source = decision(); source['publication_decision'][field] = value
            self.assertFalse(redistribution_approved(source), field)
        for value in ('prohibited', None, 'unknown'):
            source = decision(); source['redistribution_status'] = value
            self.assertFalse(redistribution_approved(source))
        for evidence in ([], [{'url': 'file:///tmp/licence', 'finding': 'Found'}], [{}]):
            source = decision(); source['licence_evidence'] = evidence
            self.assertFalse(redistribution_approved(source))


class LicenceReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        _, electoral, cls.old_electoral_path, cls.old_electoral = electoral_fixture(cls.root)
        source = deepcopy(cls.old_electoral['sources']['test'])
        cls.old_municipal = {'schema_version': 1, 'reviewed_on': '2026-09-19',
            'release_label': 'municipal-licence-test', 'sources': {'wards': source}, 'coverage': {},
            'editions': [{'id': 'mun-test', 'authority_id': 'ca-csd-2401001', 'layer': 'municipal',
                'provinces': ['24'], 'status': 'current', 'default': True, 'scheme': 'council-wards',
                'label': 'Test wards', 'authority': 'Synthetic council', 'boundary_set': 'test',
                'electoral_event': 'Test', 'evidence_url': 'https://example.test/wards',
                'expected_count': 2, 'sources': ['wards'], 'id_fields': ['code'], 'name_field': 'name',
                'identity_sha256': source['identity_sha256']}]}
        cls.old_municipal_path = cls.root / 'municipal-plan.json'
        write_json(cls.old_municipal_path, cls.old_municipal)
        cls.base = cls.root / 'municipal'
        build_municipal(electoral, cls.root, cls.base, plan_path=cls.old_municipal_path)
        cls.digest = sha256(cls.base / 'manifest.json')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.directory = Path(self.work.name)
        self.plans = {}
        for section, old_path, old, key in (
                ('electoral', self.old_electoral_path, self.old_electoral, 'test'),
                ('municipal_elections', self.old_municipal_path, self.old_municipal, 'wards')):
            new = deepcopy(old)
            new['reviewed_on'] = '2026-09-20'
            new['sources'][key].update(decision())
            path = self.directory / (section + '.json'); write_json(path, new)
            self.plans[section] = (old_path, path)
        self.output = self.directory / 'reviewed'

    def review(self, **overrides):
        return review_source_licences(self.base, self.output, plans=self.plans,
                    expected_sha256=overrides.get('digest', self.digest), label='licence-review')

    def test_release_preserves_geometry_identity_and_previous_release(self):
        result = self.review()
        _, old, digest = checked_release(self.base)
        _, new, _ = checked_release(self.output, result['manifest_sha256'])
        self.assertEqual(digest, self.digest)
        for name, spec in old['files'].items():
            if name != 'report.json': self.assertEqual(spec, new['files'][name])
        before, after = Dataset(self.base), Dataset(self.output)
        self.assertEqual(before.lookup(-110.5, 50), {**after.lookup(-110.5, 50), 'dataset_version': before.version})
        check_redistribution(after.report)
        for section in self.plans:
            part = after.report[section]
            self.assertFalse(part['licence_reviews'][-1]['geometry_changed'])
            source = next(iter(part['sources'].values()))
            self.assertEqual(source['redistribution_status'], 'unconfirmed')
            self.assertIn('info@example.test', source['publication_disclaimer'])

    def test_rejects_parser_geometry_edition_and_coverage_changes(self):
        for field in ('filename', 'sha256', 'crs', 'id_field'):
            old_path, path = self.plans['electoral']
            original = read_json(path); altered = deepcopy(original)
            altered['sources']['test'][field] = 'changed'
            write_json(path, altered)
            with self.assertRaisesRegex(CatalogueError, 'acquisition or parsing'): self.review()
            self.assertFalse(self.output.exists())
            write_json(path, original)
        path = self.plans['municipal_elections'][1]
        original = read_json(path)
        for field in ('editions', 'coverage'):
            altered = deepcopy(original); altered[field] = []
            write_json(path, altered)
            with self.assertRaisesRegex(CatalogueError, 'only change source licence metadata'): self.review()
            write_json(path, original)

    def test_rejects_wrong_baseline_and_missing_review(self):
        with self.assertRaises(CatalogueError): self.review(digest='0' * 64)
        path = self.plans['electoral'][1]
        current = read_json(path); current['sources']['test'].pop('licence_evidence')
        write_json(path, current)
        with self.assertRaisesRegex(CatalogueError, 'requires evidence'): self.review()
        wrong_old = deepcopy(self.old_electoral); wrong_old['sources']['test']['licence'] = 'https://wrong.test/'
        old_path = self.directory / 'wrong-old.json'; write_json(old_path, wrong_old)
        self.plans['electoral'] = old_path, path
        with self.assertRaisesRegex(CatalogueError, 'does not match the release pin'): self.review()
