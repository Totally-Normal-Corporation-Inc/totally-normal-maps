"""Smoke-test the combined image offline, read-only, and without data mounts."""
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

    body, headers = get('/readyz')
    ready = json.loads(body)
    assert headers['Cache-Control'] == 'no-store'
    assert ready['deployment_version'] == hashlib.sha256(
        (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest()
    for key in ('code_sha256', 'dataset_manifest_sha256', 'website_manifest_sha256'):
        assert ready[key] == record[key], key
    assert b'Canada, area by area' in get('/')[0]
    prefix = '/maps/' + record['website_manifest_sha256'] + '/'
    catalogue = json.loads(get(prefix + 'catalogue.json')[0])
    assert catalogue['dataset_version'] == record['dataset_manifest_sha256']
    assert b'L.' in get(prefix + 'preview.js')[0]
    private = ('catalogue.sqlite3', 'dataset/catalogue.sqlite3', 'report.json',
               'manifest.json', 'site-manifest.json', 'deployment.json', 'dataset.lock.json',
               '%2e%2e%2fdataset%2fcatalogue.sqlite3')
    forbidden = [('/v1/countries', 401)]
    forbidden += [(base + name, 404) for base in ('/', prefix) for name in private]
    for path, expected in forbidden:
        try:
            get(path)
        except HTTPError as error:
            with error:
                assert error.code == expected, (path, error.code)
        else:
            raise AssertionError('Protected or private content was accessible: ' + path)
    for path in ('/v1/countries', '/v1/areas/ca/children',
                 '/v1/lookup?longitude=-75.72&latitude=45.43'):
        body, headers = get(path, Authorization='Bearer ' + token)
        assert json.loads(body)['dataset_version'] == record['dataset_manifest_sha256']
        assert headers['Cache-Control'] == 'no-store'


def check_lock(record, path):
    # Assembly normalizes the lock's JSON; whitespace is not dataset identity.
    lock = json.loads(path.read_text())
    canonical = (json.dumps(lock, ensure_ascii=False, indent=2) + '\n').encode()
    assert record['lock_sha256'] == hashlib.sha256(canonical).hexdigest(), 'Image differs from selected lock'
    assert record['dataset_manifest_sha256'] == lock['manifest_sha256'], 'Image differs from selected dataset'


def wait_until_ready(url):
    deadline = time.monotonic() + 120
    while True:
        try:
            with urlopen(url + '/readyz', timeout=3) as response:
                if response.status == 200: return
        except HTTPError as error:
            error.close()
        except (URLError, TimeoutError, ConnectionError):
            # Startup resets/disconnects can escape urllib directly.
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Combined container did not become ready.')
        time.sleep(1)


def probe():
    """Run through stdin inside the container; only stdlib and loopback are used."""
    record = json.loads(Path('/opt/maps/bundle/deployment.json').read_text())
    token = next(iter(json.loads(os.environ['MAPS_API_TOKENS']).values()))
    url = 'http://127.0.0.1:8000'
    wait_until_ready(url)
    print('ready', flush=True)
    check_service(url, token, record)
    print('passed', flush=True)


def run_probe(container, started):
    # A pipe keeps the checker out of the image and its read-only filesystem.
    # Receipt of the readiness line measures startup on the host's own clock.
    with subprocess.Popen(['docker', 'exec', '--interactive', container, 'python', '-', '--probe'],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
        try:
            process.stdin.write(Path(__file__).read_text())
            process.stdin.close()
            if process.stdout.readline().strip() != 'ready':
                raise RuntimeError('Combined container did not become ready; see probe error above.')
            startup = time.monotonic() - started
            if process.stdout.readline().strip() != 'passed' or process.wait(timeout=30) != 0:
                raise RuntimeError('Combined container service checks failed.')
            return startup
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def memory_readings(container):
    # Docker stats sampling can miss the peak. Read the kernel high-water mark.
    script = """import json
from pathlib import Path
root = Path('/sys/fs/cgroup')
if (root / 'memory.peak').exists():
    peak, limit = root / 'memory.peak', root / 'memory.max'
else:
    peak, limit = root / 'memory/memory.max_usage_in_bytes', root / 'memory/memory.limit_in_bytes'
print(json.dumps({'peak_memory_bytes': int(peak.read_text()),
                  'memory_limit_bytes': int(limit.read_text())}))
"""
    return json.loads(docker('exec', container, 'python', '-c', script))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--lock', type=Path, help='Compare the image against the selected checkout or fixture lock')
    parser.add_argument('--receipt', type=Path, help='Write the verified deployment record for release promotion')
    parser.add_argument('--memory-mib', type=int, help='Test with this memory limit and no swap (Linux memory cgroups required)')
    parser.add_argument('--report', type=Path, help='Write startup, image identity and optional memory readings separately from the receipt')
    args = parser.parse_args()
    if args.memory_mib is not None and args.memory_mib <= 0:
        parser.error('--memory-mib must be positive')
    if args.receipt and args.report and args.receipt.resolve() == args.report.resolve():
        parser.error('--receipt and --report must use different paths')
    # Resolve the tag once so inspection, probing and the receipt use one image.
    image = docker('image', 'inspect', '--format', '{{.Id}}', args.image)
    record_text = docker('run', '--rm', '--network', 'none', '--entrypoint', 'cat', image,
                         '/opt/maps/bundle/deployment.json')
    record = json.loads(record_text)
    if args.lock:
        check_lock(record, args.lock)
    token = secrets.token_urlsafe(32)
    environment = {**os.environ, 'MAPS_API_TOKENS': json.dumps({'container-check': token})}
    limits = [] if args.memory_mib is None else [
        '--memory', str(args.memory_mib) + 'm', '--memory-swap', str(args.memory_mib) + 'm']
    started = time.monotonic()
    container = docker('run', '--detach', '--read-only', '--cap-drop=ALL',
                       '--security-opt=no-new-privileges', '--network', 'none', *limits,
                       '--env', 'MAPS_API_TOKENS', image, env=environment)
    try:
        startup = run_probe(container, started)
        report = {'image_id': image, 'deployment': record, 'startup_seconds': round(startup, 2),
                  'architecture': docker('image', 'inspect', '--format', '{{.Architecture}}', image),
                  'read_only': True, 'network': 'none', 'dataset_mounts': False,
                  'memory_limit_mib': args.memory_mib, 'cpu_limit': 'none',
                  'swap_enabled': False if args.memory_mib is not None else None,
                  'host': json.loads(docker('info', '--format', '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}')),
                  'checks': 'website, authentication, private files, fingerprints, readiness caching, hierarchy and lookup'}
        if args.memory_mib is not None:
            report.update(memory_readings(container))
            assert report['memory_limit_bytes'] == args.memory_mib * 1024 * 1024, 'Memory limit was not enforced'
        state = json.loads(docker('inspect', '--format', '{{json .State}}', container))
        assert state['Running'] and not state['OOMKilled'], 'Container exited or exhausted memory'
        report['oom_killed'] = state['OOMKilled']
        report['result'] = 'passed'
        if args.receipt:
            args.receipt.write_text(record_text + '\n')
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(f'Combined image passed: public website, protected API, pinned dataset, offline read-only runtime. Startup: {startup:.2f}s.')
        if args.memory_mib is not None:
            print(f"Peak container memory: {report['peak_memory_bytes'] / 1024**2:.1f} MiB / {args.memory_mib} MiB (includes probe).")
    finally:
        docker('rm', '--force', container)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--probe']:
        probe()
    else:
        main()
