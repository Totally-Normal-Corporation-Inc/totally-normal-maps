import copy
import json
import unittest
from unittest.mock import patch

from tests import test_display_packages as fixtures
from tests.test_display_packages import QC, ON
from totally_normal_maps import display_packages, display_groups


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

    def metadata_heavy_data(self):
        data = copy.deepcopy(self.data)
        plan = data.packages.index['plan']
        original = copy.deepcopy(plan['groups'][0])
        plan['sources'] = [{**plan['sources'][0], 'authority': 'é' * 1000,
                            'attribution': 'b' * 2000} for _ in range(3)]
        plan['groups'] = [{**original, 'id': f'group-{i:02d}',
                           'municipality_ids': [f'missing-{i:02d}']} for i in range(25)]
        display_packages.validate_plan(plan)
        data.packages.index['bundles'] = {g['id']: {'status': 'unsupported',
            'reason': 'membership_unresolved', 'missing_ids': g['municipality_ids']} for g in plan['groups']}
        return data

    def test_unavailable_reason_comes_from_verified_descriptor(self):
        data = copy.deepcopy(self.data)
        _, _, specs, _ = display_packages.scope_plan(data, data.packages.index['plan'])
        bid, kind, roots, grouping = specs[-1]
        for uid in display_packages.scope_members(data, roots):
            data.displays.pop(uid, None)
            data.areas[uid]['assignment_status'] = 'missing_geometry'
        base, body, _ = display_packages.base_descriptor(data, bid, kind, roots, grouping,
                                                         display_packages.Provenance(data))
        self.assertIsNone(body)
        data.packages.index['bundles'][bid] = {'status': 'unavailable', 'descriptor': 'verified-record.json'}
        for uid in roots:
            data.packages.responses[uid] = display_packages.envelope(data, uid, base,
                data.packages.index['selections'][uid])
        client = self.client(); client.app.state.dataset = data
        response = client.get('/v1/display-groups/')
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()['items'][0]
        self.assertEqual(item['membership_status'], 'complete')
        self.assertEqual(item['map']['status'], 'unavailable')
        self.assertEqual(item['map']['reason'], 'no_display_geometry')
        self.assertIsNone(item['map']['bbox'])

    def test_byte_limited_pages_preserve_every_group_and_metadata(self):
        data = self.metadata_heavy_data()
        client = self.client(); client.app.state.dataset = data
        offset = 0; found = []
        while offset is not None:
            url = '/v1/display-groups/?offset=' + str(offset)
            headers = {'If-Match': '"' + data.version + '"'}
            response = client.get(url, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertLessEqual(len(response.content), display_groups.MAX_PAGE_BYTES)
            payload = response.json()
            self.assertTrue(payload['items'])
            if offset == 0:
                self.assertLess(len(payload['items']), 25)
                self.assertEqual(payload['next_offset'], len(payload['items']))
                head = client.head(url, headers=headers)
                self.assertEqual(dict(head.headers), dict(response.headers))
                self.assertEqual(head.content, b'')
                self.assertEqual(client.get(url, headers={**headers, 'If-None-Match': response.headers['etag']}).status_code, 304)
            for item in payload['items']:
                self.assertEqual(item['provenance']['sources'], data.packages.index['plan']['sources'])
                self.assertEqual(len(item['municipality_ids']), 1)
                self.assertEqual(item['missing_ids'], item['municipality_ids'])
                found.append(item['id'])
            offset = payload['next_offset']
        self.assertEqual(found, [g['id'] for g in data.packages.index['plan']['groups']])
        empty = client.get('/v1/display-groups/?offset=25', headers=headers).json()
        self.assertEqual(empty['items'], []); self.assertIsNone(empty['next_offset'])

    def test_exact_byte_limit_and_individually_oversized_item(self):
        data = self.metadata_heavy_data()
        for offset in (0, 9, 24):
            expected, etag = display_groups.page(data, offset=offset, limit=1)
            with self.subTest(offset=offset), patch.object(display_groups, 'MAX_PAGE_BYTES', len(expected)):
                self.assertEqual(display_groups.page(data, offset=offset), (expected, etag))
            with patch.object(display_groups, 'MAX_PAGE_BYTES', len(expected) - 1):
                with self.assertRaises(display_packages.PackageError) as error:
                    display_groups.page(data, offset=offset)
                self.assertEqual((error.exception.status, error.exception.code), (413, 'group_page_too_large'))
        client = self.client(); client.app.state.dataset = data
        with patch.object(display_groups, 'MAX_PAGE_BYTES', 1000):
            for method in (client.get, client.head):
                response = method('/v1/display-groups/')
                self.assertEqual(response.status_code, 413)
                self.assertIn('no-store', response.headers['cache-control'])
            self.assertEqual(client.get('/v1/display-groups/').json()['code'], 'group_page_too_large')

    def test_openapi_exposes_complete_models_and_actual_errors(self):
        spec = self.client().get('/openapi.json').json()
        for method in ('get', 'head'):
            operation = spec['paths']['/v1/display-groups/'][method]
            responses = operation['responses']
            self.assertEqual(responses['200']['content']['application/json']['schema']['$ref'],
                             '#/components/schemas/DisplayGroupPage')
            self.assertTrue({'409', '413', '428'} <= set(responses))
            self.assertNotIn('406', responses)
            self.assertEqual(operation['security'], [{'BearerAuth': []}])
        schemas = spec['components']['schemas']
        self.assertEqual(set(schemas['DisplayGroupPage']['required']),
                         {'contract', 'dataset_version', 'revision', 'offset', 'total', 'next_offset', 'items'})
        self.assertEqual(set(schemas['GroupMap']['required']), {'status', 'reason', 'anchor_id', 'bbox'})
        self.assertEqual(schemas['GroupMap']['properties']['status']['enum'], ['ready', 'unavailable', 'unsupported'])
