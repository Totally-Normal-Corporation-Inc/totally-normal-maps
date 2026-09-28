"""Offline tests for the read-only live checker; no network or real keys."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from shapely.geometry import box

from tests.api_fixture import make_release
from tests.test_circle import synthetic
from tools.check_circle_api import check, PATH
from tools.check_reference_api import CheckFailure, require
from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.circle import CircleIndex


class Adapter:
    def __init__(self, client, change=None):
        self.client, self.change = client, change

    def request(self, path, *, body=None, headers=None, budget=128 * 1024, expected=200, authenticate=True):
        require(path == PATH, 'Checker requested an unrelated resource.')
        request_headers = dict(headers or {})
        if authenticate:
            request_headers['Authorization'] = 'Bearer ' + 'x' * 40
        response = self.client.post(path, json=body, headers=request_headers)
        require(response.status_code == expected, 'Unexpected test HTTP status.')
        require(len(response.content) <= budget, 'Test response exceeded budget.')
        value = response.json()
        if expected == 200 and self.change:
            self.change(value)
        return json.dumps(value).encode(), response.headers


class CircleCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        _, root, cls.version = make_release(Path(cls.temp.name))
        settings = Settings(root, cls.version, mode='production', tokens={'test': 'x' * 40},
                            allowed_hosts=('testserver',), requests_per_minute=10000)
        cls.client = TestClient(create_app(settings))
        cls.client.__enter__()
        data = synthetic({f'ca-csd-{i:07}': box(-76, 45, -75, 46) for i in range(8)})
        data.version = cls.version
        cls.client.app.state.circles = CircleIndex(data)

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def test_complete_public_sample_and_preconditions(self):
        report = check(Adapter(self.client), self.version)
        self.assertEqual(report['public_sample_total'], 8)
        self.assertEqual(len(report['decoded_page_bytes']), 3)
        self.assertEqual(report['dataset_version'], self.version)

    def test_rejects_bad_pages_revisions_and_qualification(self):
        def duplicate(value):
            value['items'][1] = value['items'][0]

        def short(value):
            value['items'].pop()

        def mixed(value):
            if value['offset']:
                value['dataset_version'] = 'e' * 64

        for mutate in (duplicate, short, mixed, lambda v: v.update(representation_revision=2),
                       lambda v: v.update(representation_revision=True), lambda v: v.update(offset=False),
                       lambda v: v.update(coverage_complete=False), lambda v: v.pop('qualification')):
            with self.subTest(mutate=mutate), self.assertRaises(CheckFailure):
                check(Adapter(self.client, mutate))

    def test_empty_probe_requires_the_same_complete_contract(self):
        for change in (lambda v: v.pop('query'), lambda v: v.pop('qualification'),
                       lambda v: v.update(total=False), lambda v: v.pop('next_offset'),
                       lambda v: v.update(match_semantics='bbox_only'),
                       lambda v: v['query'].update(latitude=False)):
            def mutate(value):
                if value.get('total') == 0:
                    change(value)
            with self.subTest(change=change), self.assertRaises(CheckFailure):
                check(Adapter(self.client, mutate))

    def test_incomplete_coverage_is_never_cached_as_empty(self):
        data = synthetic({}, missing={'missing': {'level': 'municipality'}})
        data.version = self.version
        with patch.object(self.client.app.state, 'circles', CircleIndex(data)):
            with self.assertRaises(CheckFailure):
                check(Adapter(self.client))


if __name__ == '__main__':
    unittest.main()
