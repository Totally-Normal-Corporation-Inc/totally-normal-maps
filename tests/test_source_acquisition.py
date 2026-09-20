"""Synthetic pagination/snapshot tests; no external operations."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from totally_normal_maps.catalogue import CatalogueError
from totally_normal_maps.source_acquisition import arcgis_snapshot, wfs_snapshot


class SourceAcquisitionTests(unittest.TestCase):
    def test_wfs_complete_canonical_identity_snapshot(self):
        source = {'expected_count': 2, 'id_field': 'code', 'acquisition': {
            'kind': 'wfs', 'url': 'https://example.invalid/wfs?request=GetFeature', 'fields': ['code', 'name']}}
        def payload():
            return {'type': 'FeatureCollection', 'numberMatched': 2, 'numberReturned': 2,
                    'features': [{'type': 'Feature', 'id': f'transport-{i}', 'geometry': None,
                                  'properties': {'code': str(i), 'name': f'Area {i}', 'timestamp': 'unstable'}}
                                 for i in (2, 1)]}
        original = wfs_snapshot(source, request=lambda url: payload())
        changed = payload(); changed['features'].reverse()
        for row in changed['features']: row['id'] += '-new'
        self.assertEqual(original, wfs_snapshot(source, request=lambda url: changed))
        result = json.loads(original)
        self.assertEqual([f['properties']['code'] for f in result['features']], ['1', '2'])
        self.assertNotIn('id', result['features'][0])
        self.assertNotIn('timestamp', result['features'][0]['properties'])
        for failure in ('missing', 'truncated', 'duplicate', 'field', 'null_identity', 'malformed', 'nonfinite'):
            broken = payload()
            if failure == 'missing': broken['features'].pop()
            elif failure == 'truncated': broken['numberMatched'] = 3
            elif failure == 'duplicate': broken['features'][1]['properties']['code'] = '2'
            elif failure == 'field': del broken['features'][1]['properties']['name']
            elif failure == 'null_identity': broken['features'][1]['properties']['code'] = None
            elif failure == 'malformed': broken['features'][1]['properties'] = None
            elif failure == 'nonfinite': broken['features'][1]['geometry'] = {'coordinates':[float('nan')]}
            with self.subTest(failure=failure), self.assertRaises(CatalogueError):
                wfs_snapshot(source, request=lambda url: broken)

    def test_full_pages_and_rejected_inconsistent_snapshots(self):
        source = {'expected_count': 205, 'acquisition': {'kind': 'arcgis',
                  'layer_url': 'https://example.invalid/FeatureServer/0', 'layer_name': 'Communities'}}
        for failure in (None, 'truncated', 'duplicate', 'changed', 'wrong_layer'):
            with self.subTest(failure=failure):
                metadata_calls = 0
                page_sizes = []
                def request(url):
                    nonlocal metadata_calls
                    query = parse_qs(urlsplit(url).query)
                    if not urlsplit(url).path.endswith('/query'):
                        metadata_calls += 1
                        return {'name': 'Fire Service' if failure == 'wrong_layer' else 'Communities',
                                'geometryType': 'esriGeometryPolygon',
                                'editingInfo': {'lastEditDate': metadata_calls if failure == 'changed' else 1}}
                    if 'returnIdsOnly' in query:
                        return {'objectIds': list(range(205)), 'objectIdFieldName': 'OBJECTID'}
                    if 'returnCountOnly' in query: return {'count': 205}
                    ids = [int(i) for i in query['objectIds'][0].split(',')]
                    page_sizes.append(len(ids))
                    if failure == 'duplicate': ids[-1] = ids[0]
                    return {'type': 'FeatureCollection', 'exceededTransferLimit': failure == 'truncated',
                            'features': [{'type': 'Feature', 'properties': {'OBJECTID': i},
                                          'geometry': {'type': 'Polygon', 'coordinates': [[[-100,50],[-99,50],[-99,51],[-100,50]]]}}
                                         for i in reversed(ids)]}
                if failure:
                    with self.assertRaises(CatalogueError): arcgis_snapshot(source, request=request)
                else:
                    payload = json.loads(arcgis_snapshot(source, request=request))
                    self.assertEqual(page_sizes, [100, 100, 5])
                    self.assertEqual([f['properties']['OBJECTID'] for f in payload['features']], list(range(205)))
