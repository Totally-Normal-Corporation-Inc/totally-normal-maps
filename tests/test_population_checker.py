"""Offline envelope tests for the population acceptance command."""
import copy
import json
import unittest

from tools.check_population_api import check
from tools.check_reference_api import CheckFailure
from totally_normal_maps.catalogue import CatalogueError


class FixtureClient:
    version = 'a' * 64

    def __init__(self, change=None):
        self.change = change

    def request(self, path, *, headers=None, expected=200, authenticate=True, budget=128 * 1024):
        if expected != 200:
            return b'', {'ETag': '"fixture"'} if expected == 304 else {}
        h = {'X-Maps-Dataset-Version': self.version, 'ETag': '"fixture"',
             'Cache-Control': 'no-store', 'Vary': 'Authorization'}
        if '/summary' in path:
            h['Cache-Control'] = 'private, no-cache'
            value = {'dataset_version': self.version, 'representation_revision': 1, 'qualification': 'review_required',
                     'selection': {'layer': 'administrative'}}
        elif '/v1/areas?' in path:
            offset = int(path.split('offset=')[1])
            value = {'dataset_version': self.version, 'total': 200, 'offset': offset, 'limit': 100,
                     'next_offset': 100 if offset == 0 else None,
                     'items': [{'id': f'fixture-{i}', 'population': None, 'population_unavailable_reason': 'no_source'}
                               for i in range(offset, offset + 100)]}
        else:
            uid = path.rsplit('/', 1)[1]
            count = {'ca-csd-2481017': 291041, 'ca-csd-2484050': 229, 'ca-csd-6204019': 0}[uid]
            value = {'dataset_version': self.version, 'area': {'id': uid, 'population_unavailable_reason': None,
                'population': {'count': count, 'reference_year': 2021,
                    'measure': 'usual_residents', 'method': 'census_count_boundary_adjusted' if uid == 'ca-csd-2481017' else 'census_count', 'quality_flags': [],
                    'geography_reference': 'statcan-csd-2025-01-01' if uid == 'ca-csd-2481017' else 'statcan-csd-2021-01-01',
                    'source': {'publisher': 'Statistics Canada', 'dataset': '98-10-0002-01',
                        'record_id': '2021A0005' + uid.removeprefix('ca-csd-'),
                        'url': 'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810000201'}}}}
        if self.change:
            self.change(path, value)
        return json.dumps(value).encode(), h


class PopulationCheckerTests(unittest.TestCase):
    def test_valid_pinned_reference_pages(self):
        result = check(FixtureClient(), FixtureClient.version)
        self.assertIn('true_zero', result['checks'])
        self.assertLess(result['decoded_bytes']['catalogue_0'], 2 * 1024 * 1024)

    def test_rejects_mixed_short_duplicate_or_invalid_metadata(self):
        def mutate(change):
            def apply(path, value):
                if '/v1/areas?' in path:
                    change(value)
            return apply
        changes = [lambda v: v.update(dataset_version='b' * 64),
                   lambda v: v['items'].pop(),
                   lambda v: v['items'].__setitem__(1, copy.deepcopy(v['items'][0])),
                   lambda v: v.update(next_offset=199),
                   lambda v: v.update(offset=False),
                   lambda v: v['items'][0].update(population_unavailable_reason=None)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises((CheckFailure, CatalogueError)):
                check(FixtureClient(mutate(change)))

    def test_rejects_wrong_known_count_or_source_identity(self):
        for change in (lambda p: p.update(count=100), lambda p: p['source'].update(record_id='2021S0503505'),
                       lambda p: p.update(method='census_count'), lambda p: p.update(geography_reference='wrong')):
            def mutate(path, value):
                if path == '/v1/areas/ca-csd-2481017':
                    change(value['area']['population'])
            with self.subTest(change=change), self.assertRaises(CheckFailure):
                check(FixtureClient(mutate))


if __name__ == '__main__':
    unittest.main()
