"""Read-only live acceptance with public sample coordinates and an environment-held key.

Prints only versions, decoded byte counts and check names; never bodies or keys.
Does not follow redirects, fetch source URLs, download full reports or publish.
"""
import argparse
import gzip
import io
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE = '/v1/datasets/current'
SUMMARY_BYTES = 16 * 1024
PAGE_BYTES = 128 * 1024
ITEM_BYTES = 16 * 1024
# Public central Gatineau coordinate, never a consumer export or a private place.
POINT = {'latitude': 45.4288, 'longitude': -75.7145, 'layers': ['administrative']}


class CheckFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailure(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, url, token):
        parts = urlsplit(url)
        require(bool(parts.hostname) and parts.path in {'', '/'} and not parts.query and not parts.fragment
                and not parts.username and not parts.password, 'Use a service origin without credentials or a path.')
        require(parts.scheme == 'https' or parts.scheme == 'http' and parts.hostname in {'localhost', '127.0.0.1', '::1'},
                'HTTPS is required except on loopback.')
        require(bool(re.fullmatch(r'[A-Za-z0-9._~-]{32,256}', token)), 'Set MAPS_ACCEPTANCE_TOKEN to a valid server-held API key.')
        self.url, self.token = url.rstrip('/'), token
        self.opener = build_opener(NoRedirect())

    def request(self, path, *, expected=200, budget=PAGE_BYTES, headers=None, body=None, authenticate=True):
        parts = urlsplit(path)
        require(path.startswith('/v1/') and not parts.scheme and not parts.netloc and not parts.fragment
                and '\\' not in path and not any(ord(c) < 32 for c in path), 'Unsafe reference link.')
        request_headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        if authenticate:
            request_headers['Authorization'] = 'Bearer ' + self.token
        request_headers.update(headers or {})
        data = None if body is None else json.dumps(body, separators=(',', ':')).encode()
        if data is not None:
            request_headers['Content-Type'] = 'application/json'
        try:
            try:
                response = self.opener.open(Request(self.url + path, data=data, headers=request_headers), timeout=30)
            except HTTPError as error:
                response = error
            with response:
                # Do not include the URL, body, reason or exception text in errors.
                require(response.code == expected, f'Expected HTTP {expected}; received HTTP {response.code}.')
                wire = response.read(budget + 4097)
                require(len(wire) <= budget + 4096, 'Wire response exceeded its bounded read.')
                encoding = response.headers.get('Content-Encoding', 'identity').lower()
                require(encoding in {'identity', 'gzip'}, 'Unsupported response encoding.')
                decoded = gzip.GzipFile(fileobj=io.BytesIO(wire)).read(budget + 1) if encoding == 'gzip' else wire
                require(len(decoded) <= budget, 'Decoded response exceeded its byte budget.')
                return decoded, response.headers
        except (URLError, TimeoutError, ConnectionError, OSError, ValueError):
            raise CheckFailure('Transport or decoding failed; response and credential details suppressed.') from None


def check(client, expected_version=None):
    metrics = {}
    initial_headers = {'If-Match': '"' + expected_version + '"'} if expected_version else {}
    # Prove that lookup has no summary/report prerequisite.
    body, headers = client.request('/v1/lookup/batch', body={'points': [POINT]}, headers=initial_headers, budget=256 * 1024)
    lookup = json.loads(body); version = lookup.get('dataset_version')
    require(isinstance(version, str) and bool(re.fullmatch('[0-9a-f]{64}', version)), 'Missing dataset identity.')
    require(expected_version is None or version == expected_version, 'Unexpected dataset version.')
    require(headers.get('X-Maps-Dataset-Version') == version, 'Lookup header/body version disagreement.')
    require(headers.get('Cache-Control') == 'no-store', 'Coordinate lookup cache policy changed.')
    require(len(lookup.get('results', [])) == 1, 'Lookup result count changed.')
    point = lookup['results'][0]
    require(point.get('dataset_version') == version and point.get('latitude') == POINT['latitude']
            and point.get('longitude') == POINT['longitude'], 'Lookup result identity/order mismatch.')
    require(point.get('qualification') == 'review_required' and point.get('status') in
            {'matched', 'no_match', 'ambiguous', 'review_required'}, 'Lookup qualification/status missing.')
    require(all(k in point for k in ('matches', 'direct_match_ids', 'ambiguous', 'review_candidate_ids',
            'unlocated_missing_geometry_ids', 'hierarchy_geometry_disagreements')), 'Lookup uncertainty fields missing.')
    metrics['lookup_batch'] = len(body)
    pinned = {'If-Match': '"' + version + '"'}

    def reference(path, name, summary=False):
        body, headers = client.request(path, headers=pinned, budget=SUMMARY_BYTES if summary else PAGE_BYTES)
        value = json.loads(body)
        require(value.get('dataset_version') == version and headers.get('X-Maps-Dataset-Version') == version,
                'Reference version disagreement.')
        require(value.get('qualification') == 'review_required', 'Reference qualification missing.')
        require(headers.get('Cache-Control') == 'private, no-cache'
                and 'authorization' in headers.get('Vary', '').lower(), 'Reference credential isolation changed.')
        require(bool(headers.get('ETag')), 'Reference ETag missing.')
        if not summary:
            require(len(value['items']) <= value['limit'] and all(len(json.dumps(i, ensure_ascii=False,
                    separators=(',', ':')).encode()) <= ITEM_BYTES for i in value['items']), 'Page/item bound changed.')
        metrics[name] = len(body)
        return value, headers['ETag']

    summary, etag = reference(BASE + '/summary', 'summary_administrative', True)
    require(summary['selection']['layer'] == 'administrative', 'Administrative default changed.')
    body, headers = client.request(BASE + '/summary', expected=304,
                                  headers={**pinned, 'If-None-Match': 'W/' + etag})
    require(not body and headers.get('ETag') == etag, 'Invalid 304 response.')
    client.request(BASE + '/summary', expected=401, authenticate=False, headers={'If-None-Match': etag})
    stale = ('0' if version != '0' * 64 else 'f') * 64
    client.request(BASE + '/summary', expected=412,
                   headers={'If-Match': '"' + stale + '"', 'If-None-Match': etag})
    etags = {etag}
    for layer in summary['available_layers']:
        if layer != 'administrative':
            selected, tag = reference(BASE + '/summary?layer=' + layer, 'summary_' + layer, True)
            require(tag not in etags, 'Layer representations share an ETag.'); etags.add(tag)
            require(selected['selection']['layer'] == layer, 'Wrong summary selection.')
        area = 'ca-csd-2481017' if layer in {'administrative', 'municipal'} else 'ca-qc'
        for resource in ('coverage', 'sources', 'editions'):
            path = BASE + '/' + resource + '?layer=' + layer + '&area_id=' + area + '&limit=2'
            page, tag = reference(path, resource + '_' + layer)
            require(page['scope']['layer'] == layer and page['scope']['area_id'] == area, 'Page scope mismatch.')
            if page['next']:
                following, next_tag = reference(page['next'], resource + '_' + layer + '_next')
                require(tag != next_tag and page['scope'] == following['scope'], 'Continuation representation mismatch.')
                require(not {r['id'] for r in page['items']} & {r['id'] for r in following['items']}, 'Repeated page items.')
            if resource == 'coverage' and page['items']:
                reference(page['items'][0]['evidence_url'], 'evidence_' + layer)
    return {'dataset_version': version, 'decoded_json_bytes': metrics,
            'checks': ['lookup_without_metadata', 'scoped_reference_pages', 'bounded_evidence',
                       'private_cache_validation', 'authentication_before_304', 'stale_version_412']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://maps.totallynormal.io', help='HTTPS origin; HTTP permitted only on loopback')
    parser.add_argument('--expected-version', help='Optional required dataset manifest SHA-256')
    args = parser.parse_args()
    try:
        require(args.expected_version is None or bool(re.fullmatch('[0-9a-f]{64}', args.expected_version)), 'Invalid expected version.')
        report = check(Client(args.url, os.environ.get('MAPS_ACCEPTANCE_TOKEN', '')), args.expected_version)
    except (CheckFailure, ValueError, KeyError, TypeError):
        # CheckFailure messages contain only fixed check names / status numbers.
        import sys
        failure = sys.exc_info()[1]
        parser.exit(1, (str(failure) if isinstance(failure, CheckFailure) else 'Malformed API response; details suppressed.') + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
