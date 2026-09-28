"""Read-only population HTTP acceptance; no request bodies, keys or full reports printed."""
import argparse
import json
import os
import re

try:
    from .check_reference_api import Client, CheckFailure, require
except ImportError:
    from check_reference_api import Client, CheckFailure, require

from totally_normal_maps.population import Metadata, validate
from totally_normal_maps.catalogue import CatalogueError

# Expected public facts independently verified against the pinned census and
# reviewed crosswalk, not importer overrides. Re-review after official corrections.
PUBLIC_SAMPLES = {
    'ca-csd-2481017': (291041, 'census_count_boundary_adjusted', 'statcan-csd-2025-01-01'),
    'ca-csd-2484050': (229, 'census_count', 'statcan-csd-2021-01-01'),
    'ca-csd-6204019': (0, 'census_count', 'statcan-csd-2021-01-01'),
}


def check(client, expected_version=None):
    pinned = {'If-Match': '"' + expected_version + '"'} if expected_version else {}
    path = '/v1/datasets/current/summary?layer=administrative'
    body, headers = client.request(path, headers=pinned, budget=16 * 1024)
    summary = json.loads(body); version = summary.get('dataset_version')
    require(isinstance(version, str) and bool(re.fullmatch('[0-9a-f]{64}', version)), 'Invalid dataset version.')
    require(expected_version is None or version == expected_version, 'Unexpected dataset version.')
    require(type(summary.get('representation_revision')) is int and summary['representation_revision'] == 1
            and summary.get('qualification') == 'review_required', 'Summary contract changed.')
    require(summary['selection']['layer'] == 'administrative', 'Wrong summary selection.')
    require(headers.get('X-Maps-Dataset-Version') == version and bool(headers.get('ETag')), 'Summary version/cache metadata missing.')
    require(headers.get('Cache-Control') == 'private, no-cache' and 'authorization' in headers.get('Vary', '').lower(),
            'Summary credential isolation changed.')
    pinned = {'If-Match': '"' + version + '"'}
    cached, cache_headers = client.request(path, headers={**pinned, 'If-None-Match': headers['ETag']}, expected=304)
    require(not cached and cache_headers.get('ETag') == headers['ETag'], 'Invalid summary 304 response.')
    client.request(path, headers={'If-None-Match': headers['ETag']}, expected=401, authenticate=False)
    metrics, ids = {'summary': len(body)}, []
    total = None
    for offset in (0, 100):
        body, h = client.request('/v1/areas?layer=administrative&include_historical=false&limit=100&offset=' + str(offset),
                                  headers=pinned, budget=2 * 1024 * 1024)
        page = json.loads(body)
        require(page.get('dataset_version') == version and h.get('X-Maps-Dataset-Version') == version, 'Mixed catalogue versions.')
        require(type(page.get('total')) is int and page['total'] >= 0 and (total is None or total == page['total']), 'Unstable catalogue total.')
        total = page['total']
        require(type(page['offset']) is int and type(page['limit']) is int and page['offset'] == offset
                and page['limit'] == 100 and len(page['items']) == min(100, max(0, total-offset)), 'Incomplete catalogue page.')
        end = offset + len(page['items'])
        require(page['next_offset'] == (end if end < total else None), 'Invalid catalogue continuation.')
        require(h.get('Cache-Control') == 'no-store', 'Catalogue cache policy changed.')
        for row in page['items']:
            validate(Metadata, {k: row[k] for k in ('population', 'population_unavailable_reason')})
            require(isinstance(row['id'], str) and 1 <= len(row['id']) <= 100, 'Invalid catalogue identity.')
            ids.append(row['id'])
        require(len(ids) == len(set(ids)), 'Duplicated catalogue identities.')
        metrics['catalogue_' + str(offset)] = len(body)
    for uid, (count, method, geography) in PUBLIC_SAMPLES.items():
        body, h = client.request('/v1/areas/' + uid, headers=pinned, budget=64 * 1024)
        page = json.loads(body)
        require(page.get('dataset_version') == version and h.get('X-Maps-Dataset-Version') == version
                and page['area']['id'] == uid, 'Area detail identity/version mismatch.')
        value = validate(Metadata, {k: page['area'][k] for k in ('population', 'population_unavailable_reason')})
        require(value.population is not None and value.population.reference_year == 2021, 'Public population sample is unavailable or changed vintage.')
        population = value.population
        require((population.count, population.method, population.geography_reference) == (count, method, geography)
                and population.source.publisher == 'Statistics Canada' and population.source.dataset == '98-10-0002-01'
                and population.source.record_id == '2021A0005' + uid.removeprefix('ca-csd-')
                and population.source.url == 'https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810000201',
                'Public population count or provenance changed; re-review the authoritative fixture.')
        require(h.get('Cache-Control') == 'no-store', 'Area detail cache policy changed.')
        metrics[uid] = len(body)
    stale = ('0' if version != '0' * 64 else 'f') * 64
    client.request('/v1/areas?offset=100&limit=100', expected=412, headers={'If-Match': '"' + stale + '"'})
    client.request(path, expected=412, headers={'If-Match': '"' + stale + '"', 'If-None-Match': headers['ETag']})
    return {'dataset_version': version, 'decoded_bytes': metrics,
            'checks': ['population_metadata', 'true_zero', 'pinned_catalogue_pages', 'bounded_summary_v1', 'etag_304', 'authentication', 'stale_pin_412']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://maps.totallynormal.io')
    parser.add_argument('--expected-version')
    args = parser.parse_args()
    try:
        require(args.expected_version is None or bool(re.fullmatch('[0-9a-f]{64}', args.expected_version)), 'Invalid expected version.')
        report = check(Client(args.url, os.environ.get('MAPS_ACCEPTANCE_TOKEN', '')), args.expected_version)
    except (CheckFailure, CatalogueError, ValueError, KeyError, TypeError):
        parser.exit(1, 'Population acceptance failed; response and credential details suppressed.\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
