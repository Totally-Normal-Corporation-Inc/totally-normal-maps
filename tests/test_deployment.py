"""Offline acceptance for the complete code/website/dataset deployment contract."""
from dataclasses import replace
import io
import json
from contextlib import redirect_stdout
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fastapi.testclient import TestClient

from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import CatalogueError, read_json, sha256, write_json
from totally_normal_maps.deployment import assemble_deployment, verify_deployment
from totally_normal_maps.distribution import asset_url, package_dataset, read_lock, unpack_dataset, validate_lock
from totally_normal_maps.releases import export_release
from .api_fixture import make_release


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)
        cls.source_run, cls.release, cls.digest = make_release(cls.root)
        cls.notice = cls.root/'NOTICE.md'; cls.notice.write_text('Synthetic fixture attribution; no external source downloads.\n')
        cls.package = cls.root/'package'
        package_dataset(cls.release, cls.package, manifest_sha256=cls.digest,
                        repository='example/maps', tag='dataset-test-1', notice=cls.notice)
        cls.lock_path = cls.package/'dataset.lock.json'; cls.lock = read_lock(cls.lock_path)
        cls.archive = cls.package/cls.lock['asset']
        cls.bundle = cls.root/'bundle'
        cls.record = assemble_deployment(cls.lock_path, cls.bundle, archive=cls.archive)
        cls.token = 'synthetic-access-' * 3
        cls.settings = Settings(cls.bundle/'dataset', cls.digest, bundle=cls.bundle,
                                mode='production', tokens={'fixture': cls.token})

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(); self.addCleanup(self.scratch.cleanup)
        self.work = Path(self.scratch.name)

    def client(self, settings=None):
        client = TestClient(create_app(settings or self.settings), base_url='http://localhost', client=('127.0.0.1', 12345))
        client.__enter__(); self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_packaging_is_deterministic_and_excludes_working_data(self):
        output = self.work/'package'
        # An unrelated file is never swept into a distribution.
        extra = self.release/'unpublished.txt'; extra.write_text('Must not be published')
        try:
            package_dataset(self.release, output, manifest_sha256=self.digest,
                            repository='example/maps', tag='dataset-test-1', notice=self.notice)
        finally: extra.unlink()
        self.assertEqual(sha256(output/self.lock['asset']), self.lock['archive_sha256'])
        with ZipFile(output/self.lock['asset']) as archive:
            self.assertFalse(any('unpublished' in n or 'source.zip' in n for n in archive.namelist()))
            self.assertEqual(archive.read('NOTICE.md'), self.notice.read_bytes())
        with self.assertRaises(CatalogueError):
            package_dataset(self.release, output, manifest_sha256=self.digest,
                            repository='example/maps', tag='dataset-test-1', notice=self.notice)

    def test_download_uses_exact_asset_and_creates_same_complete_bundle(self):
        opener = Mock(side_effect=lambda *a, **k: io.BytesIO(self.archive.read_bytes()))
        assembled = assemble_deployment(self.lock_path, self.work/'downloaded', opener=opener)
        opener.assert_called_once_with(asset_url(self.lock), timeout=30)
        self.assertEqual(assembled['deployment_version'], self.record['deployment_version'])
        data, _, _ = verify_deployment(self.work/'downloaded')
        self.assertEqual(data.version, self.digest)

    def test_locked_download_rejects_changed_or_oversized_bytes_atomically(self):
        for suffix in ('truncated', 'extra'):
            body = self.archive.read_bytes()[:-1] if suffix == 'truncated' else self.archive.read_bytes()+b'x'
            opener = Mock(return_value=io.BytesIO(body))
            with self.assertRaises(CatalogueError):
                assemble_deployment(self.lock_path, self.work/suffix, opener=opener)
            self.assertFalse((self.work/suffix).exists())

    def modified_archive(self, name, edit):
        target = self.work/(name+'.zip')
        with ZipFile(self.archive) as original:
            members = [(n, original.read(n)) for n in original.namelist()]
        members = edit(members)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with ZipFile(target, 'x', compression=ZIP_DEFLATED) as archive:
                for member, content in members: archive.writestr(member, content)
        lock = {**self.lock, 'archive_sha256': sha256(target), 'archive_bytes': target.stat().st_size}
        return target, lock

    def test_unsafe_archives_cannot_write_or_publish_partial_data(self):
        link = ZipInfo('dataset/link'); link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = {
            'traversal': lambda m: [*m, ('../escaped', b'bad')],
            'absolute': lambda m: [*m, ('/escaped', b'bad')],
            'backslash': lambda m: [*m, ('..\\escaped', b'bad')],
            'duplicate': lambda m: [*m, m[0]],
            'symlink': lambda m: [*m, (link, b'../../escaped')],
            'extra': lambda m: [*m, ('dataset/source.zip', b'raw')],
            'missing_notice': lambda m: [(n, b) for n, b in m if n != 'NOTICE.md'],
            'changed_database': lambda m: [(n, b[:-1]+b'x' if n == 'dataset/catalogue.sqlite3' else b) for n, b in m],
        }
        for name, edit in cases.items():
            with self.subTest(name=name):
                archive, lock = self.modified_archive(name, edit)
                output = self.work/(name+'-output')
                with self.assertRaises(CatalogueError): unpack_dataset(lock, output, archive=archive)
                self.assertFalse(output.exists())
        self.assertFalse((self.work/'escaped').exists())

    def test_lock_rejects_unpinned_or_arbitrary_download_targets(self):
        for key, value in [('tag', 'latest'), ('tag', '../main'), ('repository', 'https://example.com'),
                           ('asset', '../dataset.zip'), ('archive_bytes', True), ('manifest_sha256', 'bad')]:
            with self.subTest(key=key, value=value):
                lock = {**self.lock, key: value}
                with self.assertRaises(CatalogueError): validate_lock(lock)
        with self.assertRaises(CatalogueError): validate_lock({**self.lock, 'url': 'https://example.com'})

    def test_dataset_publication_requires_explicit_opt_in(self):
        from tools.publish_dataset import main, publication_command
        args = ['publish_dataset', '--package', str(self.package), '--commit', 'a'*40]
        with patch('sys.argv', args), patch('subprocess.run') as upload, patch('subprocess.check_output') as remote:
            with redirect_stdout(io.StringIO()) as output: main()
            self.assertFalse(json.loads(output.getvalue())['published'])
            upload.assert_not_called(); remote.assert_not_called()
        command = publication_command(self.lock, self.archive, self.lock_path, self.notice, 'a'*40)
        self.assertIn('--prerelease', command); self.assertIn('--latest=false', command)
        self.assertEqual(command[command.index('--target')+1], 'a'*40)
        self.assertEqual(command[command.index('--repo')+1], self.lock['repository'])
        self.assertNotIn('--clobber', command)

    def test_dataset_publication_refuses_existing_tags(self):
        from tools.publish_dataset import main
        args = ['publish_dataset', '--package', str(self.package), '--commit', 'a'*40, '--publish']
        with patch('sys.argv', args), patch('subprocess.run') as upload, patch('subprocess.check_output', return_value='existing-tag'):
            with self.assertRaisesRegex(CatalogueError, 'tag already exists'): main()
            upload.assert_not_called()

    def test_dataset_and_website_match_and_only_display_geometry_is_public(self):
        data, record, site = verify_deployment(self.bundle)
        catalogue = read_json(self.bundle/'site/catalogue.json')
        self.assertEqual(catalogue['dataset_version'], data.version)
        self.assertEqual(len(catalogue['areas']), data.summary['counts']['municipality'])
        child = next(r for r in catalogue['city_areas'] if r['id'] == 'ca-qc-test-west')
        self.assertEqual(child['parent_csd_id'], '2401001')
        self.assertEqual(child['region_id'], 'ca-qc-test-region')
        self.assertFalse(any('geometry' in row for key in ('areas', 'regions', 'city_areas') for row in catalogue[key]))
        for name, spec in data.manifest['files'].items():
            if name.startswith('display/'):
                self.assertEqual(sha256(self.bundle/'site'/Path(name).name), spec['sha256'])
        pending = next(r for r in catalogue['areas'] if r['id'] == '1201001')
        self.assertEqual(pending['assignment_status'], 'unreviewed_repair')
        self.assertNotIn('catalogue.sqlite3', site['files'])

    def test_public_website_and_authenticated_api_share_one_server(self):
        client = self.client()
        ready = client.get('/readyz').json()
        self.assertEqual(ready['dataset_manifest_sha256'], self.digest)
        self.assertEqual(ready['deployment_version'], self.record['deployment_version'])
        home = client.get('/', follow_redirects=False)
        prefix = '/maps/'+self.record['website_manifest_sha256']+'/'
        self.assertEqual(home.headers['location'], prefix+'index.html')
        html = client.get(prefix+'index.html')
        self.assertEqual(html.status_code, 200)
        self.assertIn('Canada, area by area', html.text)
        self.assertIn("frame-ancestors 'none'", html.headers['content-security-policy'])
        self.assertEqual(client.get(prefix+'catalogue.json').json()['dataset_version'], self.digest)
        for name in ('preview.js', 'leaflet.css', 'images/layers.png', '24.geojson', 'NOTICE.md'):
            self.assertEqual(client.get(prefix+name).status_code, 200)
        self.assertEqual(client.get('/v1/countries').status_code, 401)
        response = client.get('/v1/countries', headers={'Authorization': 'Bearer '+self.token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['dataset_version'], self.digest)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn(self.token, html.text+client.get(prefix+'catalogue.json').text)

    def test_public_routes_reject_private_files_traversal_stale_versions_and_writes(self):
        client = self.client(); prefix = '/maps/'+self.record['website_manifest_sha256']+'/'
        for path in ('dataset/catalogue.sqlite3', 'catalogue.sqlite3', 'report.json', 'site-manifest.json',
                     'deployment.json', 'dataset.lock.json', '%2e%2e%2fdataset%2fcatalogue.sqlite3'):
            self.assertEqual(client.get(prefix+path).status_code, 404, path)
        self.assertEqual(client.get('/maps/'+'0'*64+'/catalogue.json').status_code, 404)
        self.assertEqual(client.get('/dataset/catalogue.sqlite3').status_code, 404)
        self.assertEqual(client.post(prefix+'catalogue.json').status_code, 405)
        self.assertEqual(client.get(prefix+'index.html', headers={'host': 'untrusted.example'}).status_code, 400)

    def test_website_versioned_cache_and_head_requests(self):
        client = self.client(); url = '/maps/'+self.record['website_manifest_sha256']+'/preview.js'
        response = client.get(url)
        self.assertIn('immutable', response.headers['cache-control'])
        self.assertEqual(client.get(url, headers={'If-None-Match': response.headers['etag']}).status_code, 304)
        head = client.head(url)
        self.assertEqual(head.status_code, 200); self.assertEqual(head.content, b'')

    def test_startup_rejects_tampering_code_drift_and_unexpected_files(self):
        for name in ('site/preview.js', 'dataset/catalogue.sqlite3', 'NOTICE.md', 'deployment.json', 'extra.txt'):
            with self.subTest(name=name):
                bundle = self.work/name.replace('/', '-')
                shutil.copytree(self.bundle, bundle)
                path = bundle/name
                if path.exists(): path.write_bytes(path.read_bytes()+b'changed')
                else: path.write_text('unexpected')
                with self.assertRaises((CatalogueError, json.JSONDecodeError)):
                    verify_deployment(bundle)
        with patch('totally_normal_maps.deployment.code_digest', return_value='0'*64):
            with self.assertRaisesRegex(CatalogueError, 'running code'): verify_deployment(self.bundle)

    def test_environment_pins_bundle_and_rejects_external_data_overrides(self):
        environment = {'MAPS_BUNDLE': str(self.bundle), 'MAPS_MODE': 'production',
                       'MAPS_API_TOKENS': json.dumps({'fixture': self.token})}
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()
            self.assertEqual(settings.manifest_sha256, self.digest)
            self.assertEqual(settings.dataset, self.bundle/'dataset')
        for key, value in [('MAPS_DATASET', '/different'), ('MAPS_MANIFEST_SHA256', '0'*64), ('MAPS_DATASET_S3_URI', 's3://example/old')]:
            with patch.dict(os.environ, {**environment, key: value}, clear=True):
                with self.assertRaises(CatalogueError): Settings.from_env()

    def test_rollback_restores_the_whole_previous_bundle(self):
        second = self.work/'second-release'
        release = export_release(self.source_run, second, label='synthetic-second')
        output = self.work/'package'
        package_dataset(second, output, manifest_sha256=release['manifest_sha256'], repository='example/maps',
                        tag='dataset-test-2', notice=self.notice)
        lock = read_lock(output/'dataset.lock.json')
        record = assemble_deployment(output/'dataset.lock.json', self.work/'second-bundle', archive=output/lock['asset'])
        self.assertNotEqual(record['deployment_version'], self.record['deployment_version'])
        second_settings = replace(self.settings, bundle=self.work/'second-bundle', dataset=self.work/'second-bundle/dataset',
                                  manifest_sha256=lock['manifest_sha256'])
        second_client = self.client(second_settings)
        self.assertEqual(second_client.get('/readyz').json()['dataset_manifest_sha256'], lock['manifest_sha256'])
        self.assertEqual(second_client.get('/maps/'+self.record['website_manifest_sha256']+'/catalogue.json').status_code, 404)
        rolled_back = self.client()
        self.assertEqual(rolled_back.get('/readyz').json()['deployment_version'], self.record['deployment_version'])
        self.assertEqual(rolled_back.get('/maps/'+self.record['website_manifest_sha256']+'/catalogue.json').json()['dataset_version'], self.digest)
