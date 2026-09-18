"""Smoke-test the combined image with a read-only filesystem and no data mounts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def docker(*args, **kwargs):
    return subprocess.check_output(['docker', *args], text=True, **kwargs).strip()


def check_service(url, token, record):
    def get(path, **headers):
        with urlopen(Request(url + path, headers=headers), timeout=10) as response:
            return response.read(), response.headers

    ready = json.loads(get('/readyz')[0])
    assert ready['deployment_version'] == hashlib.sha256(
        (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()
    for key in ('code_sha256', 'dataset_manifest_sha256', 'website_manifest_sha256'):
        assert ready[key] == record[key], key
    assert b'Canada, area by area' in get('/')[0]
    prefix = '/maps/' + record['website_manifest_sha256'] + '/'
    catalogue = json.loads(get(prefix + 'catalogue.json')[0])
    assert catalogue['dataset_version'] == record['dataset_manifest_sha256']
    assert b'L.' in get(prefix + 'preview.js')[0]
    for path, expected in [('/v1/countries', 401), (prefix + 'catalogue.sqlite3', 404)]:
        try:
            get(path)
        except HTTPError as error:
            assert error.code == expected, (path, error.code)
        else:
            raise AssertionError('Protected or private content was accessible: ' + path)
    body, headers = get('/v1/countries', Authorization='Bearer ' + token)
    assert json.loads(body)['dataset_version'] == record['dataset_manifest_sha256']
    assert headers['Cache-Control'] == 'no-store'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--receipt', type=Path, help='Write the verified deployment record for release promotion')
    args = parser.parse_args()
    record_text = docker('run', '--rm', '--network', 'none', '--entrypoint', 'cat', args.image,
                         '/opt/maps/bundle/deployment.json')
    record = json.loads(record_text)
    token = secrets.token_urlsafe(32)
    environment = {**os.environ, 'MAPS_API_TOKENS': json.dumps({'container-check': token})}
    container = docker('run', '--detach', '--read-only', '--cap-drop=ALL',
                       '--security-opt=no-new-privileges', '--publish', '127.0.0.1::8000',
                       '--env', 'MAPS_API_TOKENS', args.image, env=environment)
    try:
        port = docker('port', container, '8000/tcp').split(':')[-1]
        url = 'http://127.0.0.1:' + port
        deadline = time.monotonic() + 120
        while True:
            try:
                with urlopen(url + '/readyz', timeout=3) as response:
                    if response.status == 200: break
            except (URLError, TimeoutError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Combined container did not become ready.')
            time.sleep(1)
        check_service(url, token, record)
        if args.receipt:
            args.receipt.write_text(record_text + '\n')
        print('Combined image passed: public website, protected API, pinned dataset, read-only runtime.')
    finally:
        docker('rm', '--force', container)


if __name__ == '__main__': main()
