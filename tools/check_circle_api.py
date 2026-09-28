"""Read-only HTTP acceptance for municipal circles using public sample points.

No redirects, full reports, private coordinates, credential output or writes.
The key must be supplied server-side through MAPS_ACCEPTANCE_TOKEN.
"""
import argparse
import json
import os
import re

try:
    from .check_reference_api import Client, CheckFailure, require
except ImportError:  # Direct script invocation from the repository root.
    from check_reference_api import Client, CheckFailure, require


PATH = '/v1/lookup/circle'
BUDGET = 128 * 1024
QUERY = {'latitude': 45.4, 'longitude': -75.8, 'radius_m': 30000,
         'level': 'municipality', 'layer': 'administrative'}


def page(body, headers, *, query, offset, limit, version):
    value = json.loads(body)
    require(isinstance(value, dict) and len(body) <= BUDGET, 'Malformed or oversized circle page.')
    actual = value.get('dataset_version')
    require(isinstance(actual, str) and bool(re.fullmatch('[0-9a-f]{64}', actual)), 'Invalid dataset version.')
    require(version is None or version == actual, 'Mixed or unexpected dataset versions.')
    require(headers.get('X-Maps-Dataset-Version') == actual, 'Circle header/body version disagreement.')
    require(headers.get('Cache-Control') == 'no-store' and not headers.get('ETag'), 'Circle cache policy changed.')
    require(type(value.get('representation_revision')) is int and value['representation_revision'] == 1
            and value.get('qualification') == 'review_required', 'Circle revision or qualification changed.')
    require(value.get('status') == 'complete' and value.get('coverage_complete') is True, 'Incomplete circle result.')
    require(value.get('match_semantics') == 'area_intersects_circle'
            and value.get('distance_model') == 'wgs84_ellipsoid' and value.get('edge_model') == 'linear_lon_lat'
            and value.get('distance_tolerance_m') == .01
            and value.get('coverage_basis') == 'active_catalogue_municipalities', 'Circle distance or population semantics changed.')
    echo = value.get('query')
    require(echo == query and type(echo['radius_m']) is int
            and all(type(echo[k]) in (int, float) for k in ('latitude', 'longitude')),
            'Circle query echo changed.')
    require(type(value.get('offset')) is int and type(value.get('limit')) is int
            and value['offset'] == offset and value['limit'] == limit, 'Circle page echo changed.')
    total = value.get('total')
    require(type(total) is int and total >= offset, 'Invalid circle total.')
    items = value.get('items')
    require(isinstance(items, list) and len(items) == min(limit, total - offset), 'Short circle page.')
    require(all(isinstance(item, dict) and set(item) == {'id', 'level'} and item['level'] == 'municipality'
                and isinstance(item['id'], str) and 1 <= len(item['id']) <= 100 for item in items),
            'Unexpected circle item representation.')
    end = offset + len(items)
    require('next_offset' in value and (value['next_offset'] is None or type(value['next_offset']) is int)
            and value['next_offset'] == (end if end < total else None), 'Invalid circle continuation.')
    return value


def check(client, expected_version=None):
    version, offset, total, ids, sizes = expected_version, 0, None, [], []
    # Small pages deliberately exercise continuation; 20 requests is an
    # acceptance budget, not the API's result limit or the consumer's 500 cap.
    for _ in range(20):
        pinned = {'If-Circle-Revision': '1'}
        if version:
            pinned['If-Match'] = '"' + version + '"'
        body, headers = client.request(PATH, body={**QUERY, 'offset': offset, 'limit': 3},
                                       headers=pinned, budget=BUDGET)
        value = page(body, headers, query=QUERY, offset=offset, limit=3, version=version)
        version = value['dataset_version']
        require(total is None or total == value['total'], 'Unstable circle total.')
        total = value['total']
        ids.extend(item['id'] for item in value['items'])
        require(ids == sorted(set(ids)), 'Duplicate or unordered circle identities.')
        sizes.append(len(body))
        if value['next_offset'] is None:
            break
        offset = value['next_offset']
    else:
        raise CheckFailure('Public sample exceeded the acceptance request budget; result was not truncated into success.')
    require(len(ids) == total and len(sizes) > 1, 'Public sample did not exercise complete multi-page discovery.')
    pinned = {'If-Match': '"' + version + '"', 'If-Circle-Revision': '1'}
    outside = {**QUERY, 'latitude': 0, 'longitude': 0}
    body, headers = client.request(PATH, body=outside, headers=pinned, budget=BUDGET)
    empty = page(body, headers, query=outside, offset=0, limit=100, version=version)
    require(empty['total'] == 0, 'Outside circle was not a complete empty result.')
    stale = ('0' if version != '0' * 64 else 'f') * 64
    client.request(PATH, body=QUERY, expected=412, headers={**pinned, 'If-Match': '"' + stale + '"'})
    client.request(PATH, body=QUERY, expected=412, headers={**pinned, 'If-Circle-Revision': '0'})
    client.request(PATH, body=QUERY, expected=401, authenticate=False, headers={'If-None-Match': '*'})
    client.request(PATH, body={**QUERY, 'offset': 1}, expected=428)
    return {'dataset_version': version, 'representation_revision': 1, 'public_sample_total': total,
            'decoded_page_bytes': sizes, 'checks': ['direct_discovery_without_metadata', 'all_pinned_pages',
            'closed_circle_semantics', 'complete_empty', 'stale_dataset_412', 'revision_412', 'authentication', 'continuation_428']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://maps.totallynormal.io', help='HTTPS origin; HTTP only on loopback')
    parser.add_argument('--expected-version', help='Optional required dataset manifest SHA-256')
    args = parser.parse_args()
    try:
        require(args.expected_version is None or bool(re.fullmatch('[0-9a-f]{64}', args.expected_version)), 'Invalid expected version.')
        report = check(Client(args.url, os.environ.get('MAPS_ACCEPTANCE_TOKEN', '')), args.expected_version)
    except (CheckFailure, ValueError, KeyError, TypeError):
        import sys
        failure = sys.exc_info()[1]
        parser.exit(1, (str(failure) if isinstance(failure, CheckFailure) else 'Malformed API response; details suppressed.') + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
