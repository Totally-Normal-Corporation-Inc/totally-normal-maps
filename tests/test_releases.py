import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock

from totally_normal_maps.catalogue import CatalogueError, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.releases import checked_release, export_release, fetch_s3, source_metadata, validate_manifest
from .api_fixture import make_release


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.run_path, cls.release, cls.digest = make_release(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_export_contains_only_serving_artifacts_and_is_immutable(self):
        _, manifest, digest = checked_release(self.release, self.digest)
        self.assertEqual(digest, self.digest)
        self.assertNotIn('source.zip', manifest['files'])
        self.assertNotIn('preview/catalogue.json', manifest['files'])
        self.assertNotIn('elapsed_seconds', json.loads((self.release / 'report.json').read_text()))
        with self.assertRaises(CatalogueError):
            export_release(self.run_path, self.release)
        with self.assertRaises(CatalogueError):
            export_release(self.run_path, self.run_path / 'nested')

    def test_public_source_metadata_preserves_credit_without_operator_fields(self):
        metadata = source_metadata({'authority': 'Statistics Canada', 'family': 'Boundary File',
            'reference_date': '2025-01-01', 'dataset_url': 'https://example.invalid/source',
            'retrieved_on': '2026-09-16', 'operator_notes': 'private local context'})
        self.assertIn('Boundary File, 2025-01-01', metadata['attribution'])
        self.assertIn('does not constitute an endorsement', metadata['attribution'])
        self.assertEqual(metadata['retrieved_on'], '2026-09-16')
        self.assertEqual(metadata['dataset_url'], 'https://example.invalid/source')
        self.assertNotIn('operator_notes', metadata)
        self.assertIn('modifications', metadata)

    def test_corrupted_release_or_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'release'
            shutil.copytree(self.release, target)
            (target / 'report.json').write_text('{}')
            with self.assertRaises(CatalogueError):
                checked_release(target)
        with tempfile.TemporaryDirectory() as root:
            link = Path(root) / 'linked'
            link.symlink_to(self.release, target_is_directory=True)
            with self.assertRaises(CatalogueError):
                checked_release(link)

    def test_manifest_cannot_fetch_arbitrary_paths_or_exceed_budget(self):
        original = json.loads((self.release / 'manifest.json').read_text())
        for name in ['../secret', '/etc/passwd', 'display/../../secret.geojson', 'credentials.json']:
            candidate = json.loads(json.dumps(original))
            candidate['files'][name] = {'bytes': 1, 'sha256': '0' * 64}
            with self.subTest(name=name), self.assertRaises(CatalogueError):
                validate_manifest(candidate)
        candidate = json.loads(json.dumps(original))
        candidate['files']['catalogue.sqlite3']['bytes'] = 2**32
        with self.assertRaises(CatalogueError):
            validate_manifest(candidate)
        candidate = json.loads(json.dumps(original))
        candidate['qualification'] = 'approved'
        with self.assertRaises(CatalogueError):
            validate_manifest(candidate)

    def test_checksummed_release_with_missing_display_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'release'
            shutil.copytree(self.release, target)
            name = 'display/city-areas-24.geojson'
            path = target / name
            collection = json.loads(path.read_text())
            collection['features'].pop()
            write_json(path, collection)
            manifest = json.loads((target / 'manifest.json').read_text())
            manifest['files'][name] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}
            write_json(target / 'manifest.json', manifest)
            checked_release(target)
            with self.assertRaisesRegex(CatalogueError, 'missing its display representation'):
                Dataset(target)

    def client(self, corrupt=None):
        client = Mock()
        def get_object(Bucket, Key):
            self.assertEqual(Bucket, 'example-maps')
            name = Key.removeprefix('releases/test/')
            body = (self.release / name).read_bytes()
            if name == corrupt:
                body += b'corrupted'
            return {'ContentLength': len(body), 'Body': io.BytesIO(body)}
        client.get_object.side_effect = get_object
        return client

    def test_s3_fetch_verifies_every_artifact_without_writes_to_cloud(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'download'
            client = self.client()
            result = fetch_s3('s3://example-maps/releases/test/manifest.json', target, expected_sha256=self.digest, client=client)
            self.assertEqual(result['manifest_sha256'], self.digest)
            self.assertEqual(Dataset(target).version, self.digest)
            self.assertTrue(all(call[0] == 'get_object' for call in client.method_calls))

    def test_failed_s3_fetch_publishes_no_partial_release(self):
        for digest, corrupt in [('0' * 64, None), (self.digest, 'catalogue.sqlite3')]:
            with tempfile.TemporaryDirectory() as root:
                target = Path(root) / 'download'
                with self.assertRaises(CatalogueError):
                    fetch_s3('s3://example-maps/releases/test/manifest.json', target, expected_sha256=digest, client=self.client(corrupt))
                self.assertFalse(target.exists())
        with self.assertRaises(CatalogueError):
            fetch_s3('https://example.com/manifest.json', 'unused', expected_sha256=self.digest, client=Mock())


if __name__ == '__main__':
    unittest.main()
