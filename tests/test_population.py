"""Offline population ingestion, atomic snapshots and additive API contracts."""
import copy
from contextlib import closing
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from shapely.geometry import box

from tests.api_fixture import make_release
from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import CatalogueError, sha256, write_json
from totally_normal_maps.circle import CircleIndex, CircleInput
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.population import (Population, Metadata, Plan, Source, coverage, digest, eligible,
    identity_hash, import_population, prepare_records, source_rows, territory_fingerprint, validate)
from tools.prepare_population import equivalent


def census_source(root, entries):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['REF_DATE', 'GEO', 'DGUID', 'Coordinate',
                     'Population and dwelling counts (13): Population, 2021 [1]', 'Symbols'] + [f'Other {i}' for i in range(24)])
    for index, (uid, count, symbol) in enumerate(entries):
        # Intentionally the same name for every municipality: identity is by DGUID.
        writer.writerow(['2021', 'Same name', uid, str(index), count, symbol] + [''] * 24)
    path = root / 'census.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr('98100002.csv', out.getvalue())
        archive.writestr('98100002_MetaData.csv', 'Synthetic metadata')
    ids = [uid for uid, _, _ in entries if uid.startswith('2021A0005')]
    return {'publisher': 'Statistics Canada', 'dataset': '98-10-0002-01',
        'url': 'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810000201',
        'download_url': 'https://www150.statcan.gc.ca/n1/tbl/csv/98100002-eng.zip',
        'filename': path.name, 'sha256': sha256(path), 'release': 'synthetic', 'retrieved_on': '2026-09-28',
        'reference_date': '2021-05-11', 'geography_reference': 'statcan-csd-2021-01-01',
        'licence': 'https://www.statcan.gc.ca/en/terms-conditions/open-licence',
        'format': 'statcan_98100002_zip', 'expected_count': len(ids), 'identity_sha256': identity_hash(ids)}


def fixture(root):
    _, base, version = make_release(root)
    data = Dataset(base)
    ids = sorted(eligible(data))
    entries = [('2021A0005' + data.areas[uid]['source_id'], str(i * 100), '') for i, uid in enumerate(ids)]
    entries[1] = (entries[1][0], '', 'x')
    entries[2] = (entries[2][0], '', '..')
    source = census_source(root, entries)
    plan = {'schema_version': 1, 'base_dataset_version': version, 'reviewed_on': '2026-09-28', 'reference_year': 2021,
            'sources': {'census': source}, 'matches': {}, 'unavailable': {}}
    for uid in ids:
        plan['matches'][uid] = {'source': 'census', 'record_id': '2021A0005' + data.areas[uid]['source_id'],
            'target_sha256': territory_fingerprint(data, uid), 'basis': 'reviewed_equivalence',
            'geography_reference': 'statcan-csd-2021-01-01', 'evidence': ['Synthetic authoritative crosswalk.']}
    uid = ids[-1]; plan['matches'].pop(uid)
    plan['unavailable'][uid] = {'reason': 'incompatible_boundary', 'target_sha256': territory_fingerprint(data, uid),
                               'evidence': ['Synthetic boundary change.']}
    write_json(root / 'plan.json', plan)
    return data, plan, ids


class PopulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data, self.plan, self.ids = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, plan=None, base=None, output='population', **options):
        plan = self.plan if plan is None else plan
        write_json(self.root / 'plan.json', plan)
        return import_population(base or self.data.root, self.root / output, plan_path=self.root / 'plan.json',
                                 source_dir=self.root, expected_sha256=plan['base_dataset_version'], **options)

    def test_counts_zero_missing_provenance_and_atomic_repeat(self):
        original = sha256(self.data.root / 'catalogue.sqlite3')
        report = self.build()
        loaded = Dataset(report['output'], report['dataset_version'])
        self.assertNotEqual(loaded.version, self.data.version)
        self.assertEqual(loaded.populations[self.ids[0]]['metadata']['population']['count'], 0)
        self.assertEqual(loaded.populations[self.ids[1]]['metadata']['population_unavailable_reason'], 'suppressed')
        self.assertEqual(loaded.populations[self.ids[2]]['metadata']['population_unavailable_reason'], 'not_available')
        self.assertEqual(loaded.populations[self.ids[-1]]['metadata']['population_unavailable_reason'], 'incompatible_boundary')
        self.assertEqual(loaded.areas, self.data.areas)
        self.assertEqual(loaded.geometries, self.data.geometries)
        self.assertEqual(original, sha256(self.data.root / 'catalogue.sqlite3'))
        self.assertEqual(report['coverage']['by_level']['municipality']['zero'], 1)
        again = self.build()
        self.assertEqual((again['status'], again['dataset_version']), ('unchanged', loaded.version))
        redated = copy.deepcopy(self.plan)
        redated['sources']['census']['retrieved_on'] = '2026-09-29'
        self.assertEqual(self.build(redated)['dataset_version'], loaded.version)
        plan = copy.deepcopy(self.plan); plan['base_dataset_version'] = loaded.version
        plan['reviewed_on'] = '2026-09-29'; plan['sources']['census']['retrieved_on'] = '2026-09-29'
        again = self.build(plan, loaded.root, 'noop')
        self.assertEqual((again['status'], again['dataset_version']), ('unchanged', loaded.version))
        self.assertFalse((self.root / 'noop').exists())

    def test_failed_sources_and_partial_crosswalk_preserve_snapshot(self):
        successful = self.build()
        plans = []
        p = copy.deepcopy(self.plan); p['matches'].pop(self.ids[0]); plans.append(p)
        p = copy.deepcopy(self.plan); p['sources']['census']['sha256'] = '0' * 64; plans.append(p)
        p = copy.deepcopy(self.plan); p['sources']['census']['filename'] = 'missing.zip'; plans.append(p)
        p = copy.deepcopy(self.plan); p['sources']['census']['expected_count'] += 1; plans.append(p)
        p = copy.deepcopy(self.plan); p['base_dataset_version'] = 'f' * 64; plans.append(p)
        p = copy.deepcopy(self.plan); p['matches'][self.ids[0]]['target_sha256'] = 'e' * 64; plans.append(p)
        for plan in plans:
            with self.subTest(plan=plan.keys()), self.assertRaises(CatalogueError):
                self.build(plan, output='failed')
            self.assertFalse((self.root / 'failed').exists())
            self.assertEqual(Dataset(successful['output']).version, successful['dataset_version'])
        with patch('totally_normal_maps.population.write_json', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.build(output='failed')
        self.assertFalse((self.root / 'failed').exists())

    def test_malformed_counts_symbols_and_inventory(self):
        for value, flag in (('-1', ''), ('1.5', ''), ('true', ''), ('', ''), ('9', 'x'), ('2', 'UNKNOWN')):
            with self.subTest(value=value, flag=flag):
                source = census_source(self.root, [('2021A00052401001', value, flag)])
                with self.assertRaises(CatalogueError):
                    source_rows(self.root / 'census.zip', validate(Source, source))
        source = census_source(self.root, [('2021A00052401001', '10', ''), ('2021A00052401001', '10', '')])
        with self.assertRaises(CatalogueError):
            source_rows(self.root / 'census.zip', validate(Source, source))

    def test_strict_public_models_and_quality(self):
        sample = prepare_records(self.data, validate(Plan, self.plan), {'census': source_rows(self.root / 'census.zip', validate(Source, self.plan['sources']['census']))})
        value = sample[self.ids[0]]['metadata']
        for count in (True, -1, 2.5, '2', 1000000001):
            changed = copy.deepcopy(value); changed['population']['count'] = count
            with self.subTest(count=count), self.assertRaises(CatalogueError):
                validate(Metadata, changed)
        for change in ({'population_unavailable_reason': 'no_source'}, {'population': None}):
            with self.assertRaises(CatalogueError): validate(Metadata, {**value, **change})
        value['population']['source']['url'] = 'http://invalid.test'
        with self.assertRaises(CatalogueError): validate(Metadata, value)
        source = census_source(self.root, [('2021A00052401001', '10', 'E'), ('2021A00053501001', '12', 'r')])
        facts = source_rows(self.root / 'census.zip', validate(Source, source))
        self.assertEqual(facts['2021A00052401001']['quality_flags'], ['use_with_caution'])
        self.assertEqual(facts['2021A00053501001']['quality_flags'], ['revised'])

    def test_no_name_metro_sector_or_duplicate_identity_matches(self):
        plan = copy.deepcopy(self.plan)
        plan['matches'][self.ids[0]]['record_id'] = '2021S0503505'
        with self.assertRaises(CatalogueError): self.build(plan)
        plan = copy.deepcopy(self.plan)
        plan['matches']['ca-qc-test-west'] = plan['matches'][self.ids[0]]
        with self.assertRaises(CatalogueError): self.build(plan)
        plan = copy.deepcopy(self.plan)
        plan['matches'][self.ids[0]]['record_id'] = plan['matches'][self.ids[3]]['record_id']
        with self.assertRaises(CatalogueError): self.build(plan)
        plan = copy.deepcopy(self.plan)
        plan['sources']['second_census'] = copy.deepcopy(plan['sources']['census'])
        with self.assertRaises(CatalogueError): self.build(plan)
        result = self.build()
        loaded = Dataset(result['output'])
        self.assertNotEqual(loaded.populations[self.ids[3]]['metadata']['population']['count'],
                            loaded.populations[self.ids[4]]['metadata']['population']['count'])

    def test_changed_geography_invalidates_stored_count(self):
        result = self.build()
        path = self.root / 'population'
        with closing(sqlite3.connect(path / 'catalogue.sqlite3')) as db, db:
            row = json.loads(db.execute('SELECT record FROM csd WHERE id=?', (self.ids[3].removeprefix('ca-csd-'),)).fetchone()[0])
            row['boundary_basis'] = 'synthetic_changed_territory'
            db.execute('UPDATE csd SET record=? WHERE id=?', (json.dumps(row), self.ids[3].removeprefix('ca-csd-')))
        report = json.loads((path / 'report.json').read_text()); report['catalogue_sha256'] = sha256(path / 'catalogue.sqlite3')
        write_json(path / 'report.json', report)
        manifest = json.loads((path / 'manifest.json').read_text())
        for name in ('catalogue.sqlite3', 'report.json'):
            manifest['files'][name] = {'bytes': (path / name).stat().st_size, 'sha256': sha256(path / name)}
        write_json(path / 'manifest.json', manifest)
        with self.assertRaisesRegex(CatalogueError, 'stale'):
            Dataset(path)

    def test_stored_population_revalidates_identity_and_source_citations(self):
        # Rehashing a malformed release must not bypass semantic validation.
        for mutation in ('metro_identity', 'reused_census_identity', 'source_citation'):
            with self.subTest(mutation=mutation):
                result = self.build(output=mutation)
                path = Path(result['output']); loaded = Dataset(path)
                records = copy.deepcopy(loaded.populations)
                report = copy.deepcopy(loaded.report)
                row = records[self.ids[3]]
                if mutation == 'source_citation':
                    report['population']['sources']['census']['url'] = 'https://www.statcan.gc.ca/wrong-table'
                else:
                    record_id = ('2021S0503505' if mutation == 'metro_identity'
                                 else records[self.ids[4]]['evidence']['record_id'])
                    row['evidence']['record_id'] = record_id
                    row['metadata']['population']['source']['record_id'] = record_id
                with closing(sqlite3.connect(path / 'catalogue.sqlite3')) as db, db:
                    db.executemany('UPDATE area_population SET record=? WHERE area_id=?',
                                   [(json.dumps(row), uid) for uid, row in records.items()])
                report['population']['records_sha256'] = digest(records)
                report['catalogue_sha256'] = sha256(path / 'catalogue.sqlite3')
                write_json(path / 'report.json', report)
                manifest = copy.deepcopy(loaded.manifest)
                for name in ('catalogue.sqlite3', 'report.json'):
                    manifest['files'][name] = {'bytes': (path / name).stat().st_size, 'sha256': sha256(path / name)}
                write_json(path / 'manifest.json', manifest)
                with self.assertRaises(CatalogueError):
                    Dataset(path)

    def test_equivalence_needs_coordinates_and_does_not_approve_repairs(self):
        uid = self.ids[3]; full = self.data.geometries[uid]
        self.assertTrue(equivalent(self.data, uid, full, full))
        self.assertFalse(equivalent(self.data, uid, full, box(0, 0, 1, 1)))
        missing = self.ids[2]
        self.assertNotIn(missing, self.data.geometries)
        self.assertFalse(equivalent(self.data, missing, full, full))

    def test_official_adjustments_zero_and_unavailable_transfers(self):
        uid = self.ids[3]; code = self.data.areas[uid]['source_id']
        columns = ['Gaining CSDuid', 'Losing CSDuid', 'Census Population Affected', 'Effective Date', 'File Number']
        row = dict(zip(columns, [code, '9900001', '0', '01/01/2024', '240001']))
        path = self.root / 'interim.csv'
        def source_for(value):
            row['Census Population Affected'] = value
            with path.open('w', newline='') as f:
                writer = csv.DictWriter(f, columns); writer.writeheader(); writer.writerow(row)
            source = {**self.plan['sources']['census'], 'dataset': '92F0009X-2024', 'format': 'statcan_interim_csv',
                      'filename': path.name, 'sha256': sha256(path), 'expected_count': 1, 'identity_sha256': identity_hash([digest(row)])}
            return source
        plan = copy.deepcopy(self.plan)
        for count, expected in [('0', 300), ('20.0', 320)]:
            plan['sources']['interim'] = source_for(count)
            plan['matches'][uid].update(basis='official_adjustment', geography_reference='statcan-csd-2024-01-01',
                adjustments=[{'source': 'interim', 'record_id': digest(row), 'direction': 'gain'}])
            result = self.build(plan, output='adjustment-' + count)
            value = Dataset(result['output']).populations[uid]['metadata']['population']
            self.assertEqual(value['count'], expected)
            self.assertEqual(value['method'], 'census_count_boundary_adjusted')
            self.assertEqual(value['reference_year'], 2021)
        duplicated = copy.deepcopy(plan)
        duplicated['sources']['interim_alias'] = copy.deepcopy(duplicated['sources']['interim'])
        duplicated['matches'][uid]['adjustments'].append({**duplicated['matches'][uid]['adjustments'][0], 'source': 'interim_alias'})
        with self.assertRaises(CatalogueError):
            self.build(duplicated, output='double-counted-adjustment')
        for amount in ('...', '1.5'):
            plan['sources']['interim'] = source_for(amount)
            plan['matches'][uid]['adjustments'][0]['record_id'] = digest(row)
            with self.assertRaises(CatalogueError): self.build(plan, output='failed-adjustment')
            self.assertFalse((self.root / 'failed-adjustment').exists())

    def test_correction_and_explicit_withdrawal_change_only_population(self):
        first = self.build(); previous = Dataset(first['output'])
        plan = copy.deepcopy(self.plan); plan['base_dataset_version'] = previous.version
        entries = [('2021A0005' + self.data.areas[uid]['source_id'], str(i * 100), '') for i, uid in enumerate(self.ids)]
        plan['sources']['census'] = census_source(self.root, entries)
        result = self.build(plan, previous.root, 'corrected')
        corrected = Dataset(result['output'])
        self.assertNotEqual(previous.version, corrected.version)
        self.assertIsNotNone(corrected.populations[self.ids[1]]['metadata']['population'])
        self.assertNotIn(self.ids[2], corrected.geometries)
        self.assertEqual(corrected.populations[self.ids[2]]['metadata']['population']['count'], 200)
        self.assertEqual(previous.areas, corrected.areas)
        self.assertEqual(previous.geometries, corrected.geometries)
        plan['base_dataset_version'] = corrected.version
        uid = self.ids[0]; plan['matches'].pop(uid)
        plan['unavailable'][uid] = {'reason': 'withdrawn', 'target_sha256': territory_fingerprint(corrected, uid),
                                    'evidence': ['Explicit synthetic source withdrawal.']}
        result = self.build(plan, corrected.root, 'withdrawn')
        withdrawn = Dataset(result['output'])
        self.assertNotEqual(withdrawn.version, corrected.version)
        self.assertEqual(withdrawn.populations[uid]['metadata']['population_unavailable_reason'], 'withdrawn')

    def test_provenance_only_correction_changes_dataset(self):
        first = self.build(); previous = Dataset(first['output'])
        plan = copy.deepcopy(self.plan); plan['base_dataset_version'] = previous.version
        plan['sources']['census']['release'] = 'synthetic corrected provenance'
        result = self.build(plan, previous.root, 'provenance-correction')
        corrected = Dataset(result['output'])
        self.assertNotEqual(corrected.version, previous.version)
        self.assertEqual(corrected.populations, previous.populations)
        self.assertEqual(corrected.geometries, previous.geometries)
        plan['sources']['census']['retrieved_on'] = '2026-09-29'
        repeated = self.build(plan, previous.root, 'provenance-correction')
        self.assertEqual((repeated['status'], repeated['dataset_version']), ('unchanged', corrected.version))

    def test_deliberate_retrieval_date_correction_is_not_a_refresh_attempt(self):
        first = self.build(); previous = Dataset(first['output'])
        plan = copy.deepcopy(self.plan); plan['base_dataset_version'] = previous.version
        plan['sources']['census']['retrieved_on'] = '2026-09-27'
        self.assertEqual(self.build(plan, previous.root, 'ordinary-refresh')['status'], 'unchanged')
        result = self.build(plan, previous.root, 'corrected-date',
                            retrieval_date_correction_reason='Correct the date using the preserved retrieval receipt.')
        corrected = Dataset(result['output'])
        self.assertNotEqual(corrected.version, previous.version)
        self.assertEqual(corrected.populations, previous.populations)
        self.assertEqual(corrected.population_sources['census']['retrieved_on'], '2026-09-27')
        self.assertEqual(corrected.report['population']['retrieval_date_correction']['sources']['census'],
                         {'previous': '2026-09-28', 'corrected': '2026-09-27'})
        self.assertEqual(self.build(plan, previous.root, 'corrected-date',
            retrieval_date_correction_reason='Correct the date using the preserved retrieval receipt.')['status'], 'unchanged')
        for reason in ('   ', ' ' * 201 + 'x', True):
            with self.subTest(reason=type(reason)), self.assertRaises(CatalogueError):
                self.build(plan, previous.root, 'bad-date-reason', retrieval_date_correction_reason=reason)

    def test_download_failure_never_publishes_partial_source(self):
        from totally_normal_maps.__main__ import download
        with patch('totally_normal_maps.__main__.urlopen', return_value=io.BytesIO(b'partial')):
            with self.assertRaises(CatalogueError):
                download(self.root / 'download.zip', manifest={'url': self.plan['sources']['census']['download_url'], 'sha256': '0' * 64})
        self.assertFalse((self.root / 'download.zip').exists())


class PopulationAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        cls.base, cls.plan, cls.ids = fixture(cls.root)
        report = import_population(cls.base.root, cls.root / 'population', plan_path=cls.root / 'plan.json',
                                   source_dir=cls.root, expected_sha256=cls.base.version)
        cls.version = report['dataset_version']
        cls.settings = Settings(cls.root / 'population', cls.version, mode='production', tokens={'test': 'x' * 40},
                                allowed_hosts=('testserver',), requests_per_minute=10000)
        cls.client = TestClient(create_app(cls.settings)); cls.client.__enter__()
        cls.client.headers['Authorization'] = 'Bearer ' + 'x' * 40

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None); cls.temp.cleanup()

    def test_additive_metadata_stable_pagination_and_no_network(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('Request attempted source network')):
            response = self.client.get('/v1/areas?limit=100&layer=administrative')
            self.assertEqual(response.status_code, 200)
            value = response.json(); before = self.base.page(limit=100)
            self.assertEqual([r['id'] for r in value['items']], [r['id'] for r in before['items']])
            for row, old in zip(value['items'], before['items']):
                self.assertEqual({k: v for k, v in row.items() if k not in {'population', 'population_unavailable_reason'}}, old)
            self.assertLess(len(response.content), 2 * 1024 * 1024)
            for uid in (self.ids[0], self.ids[1], 'ca-qc-test-west'):
                detail = self.client.get('/v1/areas/' + uid).json()['area']
                self.assertEqual(detail, next(r for r in value['items'] if r['id'] == uid))
            self.assertEqual(self.client.get('/v1/areas/ca-qc-test-west').json()['area']['population_unavailable_reason'], 'no_source')
            lookup = self.client.post('/v1/lookup', json={'longitude': -109.5, 'latitude': 50.5}).json()
            self.assertTrue(all('population' not in r for r in lookup['matches']))
            boundary = self.client.get('/v1/areas/' + self.ids[0] + '/boundary').json()
            self.assertNotIn('population', boundary['properties'])
            circle = {'longitude': -109.5, 'latitude': 50.5, 'radius_m': 1000}
            before_circle = CircleIndex(self.base).lookup(CircleInput(**circle)).model_dump()
            after_circle = self.client.post('/v1/lookup/circle', json=circle).json()
            self.assertEqual(after_circle, {**before_circle, 'dataset_version': self.version})

    def test_summary_revision_etag_and_version_preconditions(self):
        url = '/v1/datasets/current/summary?layer=administrative'
        response = self.client.get(url); value = response.json()
        self.assertEqual(value['representation_revision'], 1)
        self.assertEqual(value['dataset_version'], self.version)
        self.assertLessEqual(len(response.content), 16 * 1024)
        self.assertEqual(self.client.get(url, headers={'If-None-Match': response.headers['etag']}).status_code, 304)
        self.assertEqual(self.client.get(url, headers={'If-None-Match': response.headers['etag'], 'If-Match': '"' + self.base.version + '"'}).status_code, 412)
        self.assertEqual(self.client.get('/v1/areas?offset=1', headers={'If-Match': '"' + self.base.version + '"'}).status_code, 412)
        with TestClient(create_app(replace(self.settings, dataset=self.base.root, manifest_sha256=self.base.version))) as old:
            old.headers['Authorization'] = 'Bearer ' + 'x' * 40
            self.assertNotEqual(old.get(url).headers['etag'], response.headers['etag'])

    def test_scoped_provenance_and_openapi(self):
        uid = self.ids[0]
        sources = self.client.get('/v1/datasets/current/sources', params={'layer': 'administrative', 'area_id': uid}).json()
        self.assertTrue(any('population' in s['roles'] for s in sources['items']))
        report = self.client.get('/v1/datasets/current/coverage', params={'layer': 'administrative', 'area_id': uid}).json()
        self.assertTrue(any(r['topic'] == 'population' for r in report['items']))
        spec = self.client.get('/openapi.json').json()
        self.assertIn('Population', spec['components']['schemas'])
        self.assertIn('population', spec['components']['schemas']['CatalogueArea']['properties'])


if __name__ == '__main__':
    unittest.main()
