import unittest
from unittest.mock import patch

from tests import test_display_packages as fixtures
from tests.test_display_packages import QC, ON
from totally_normal_maps import display_packages


class GroupHTTPTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PackageTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.PackageTests.tearDownClass.__func__)
    client = fixtures.PackageHTTPTests.client
    def test_metadata_catalogue(self):
        client = self.client()
        with patch.object(display_packages.PackageIndex, 'artifact', side_effect=AssertionError('geometry access')):
            response = client.get('/v1/display-groups/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['items'][0]['municipality_ids'], [QC, ON])
        self.assertEqual(payload['items'][0]['membership_status'], 'complete')
        self.assertEqual(payload['total'], 1)
        self.assertIsNone(payload['next_offset'])
        self.assertNotIn('geometry', payload['items'][0])
        self.assertEqual(client.head('/v1/display-groups/').content, b'')
        self.assertEqual(client.get('/v1/display-groups/', headers={'If-None-Match': response.headers['etag']}).status_code, 304)
        self.assertEqual(client.get('/v1/display-groups/', headers={'If-Match': '"wrong"', 'If-None-Match': '*'}).status_code, 412)
        self.assertEqual(client.get('/v1/display-groups/?offset=1').status_code, 428)
        self.assertEqual(client.get('/v1/display-groups/?limit=26').status_code, 422)
        self.assertEqual(client.get('/v1/display-groups/?limit=1&limit=2').status_code, 422)
        self.assertEqual(client.get('/v1/datasets/current/summary').json()['links']['display_groups'], '/v1/display-groups/')
        client.headers.pop('Authorization')
        self.assertEqual(client.get('/v1/display-groups/').status_code, 401)

    def test_catalogue_not_built(self):
        self.assertEqual(self.client(self.base).get('/v1/display-groups/').json()['code'], 'package_not_built')

    def test_published_national_definitions_are_complete(self):
        plan = display_packages.read_plan(display_packages.PLAN)
        groups = {group['id']: group for group in plan['groups']}
        self.assertEqual(len(groups), 152)
        self.assertEqual(len(groups['ca-sac-2021-505']['municipality_ids']), 25)
        self.assertEqual(len(groups['ca-sac-2021-462']['municipality_ids']), 93)

    def test_unresolved_membership_and_oversized_geometry_are_independent(self):
        import copy
        import json
        from totally_normal_maps.display_groups import page
        data = copy.deepcopy(self.data)
        group = data.packages.index['plan']['groups'][0]
        data.packages.index['bundles'][group['id']] = {'status': 'unsupported', 'reason': 'scope_too_large'}
        value = json.loads(page(data)[0])['items'][0]
        self.assertEqual(value['membership_status'], 'complete')
        self.assertEqual(value['map']['status'], 'unsupported')
        group['municipality_ids'].append('ca-missing')
        value = json.loads(page(data)[0])['items'][0]
        self.assertEqual(value['membership_status'], 'unresolved')
        self.assertIn('ca-missing', value['municipality_ids'])
        self.assertEqual(value['missing_ids'], ['ca-missing'])
