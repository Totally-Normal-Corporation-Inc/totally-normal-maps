from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import check_publication, check_secrets
from tools.check_artifacts import check_archive
from tools.publication_files import publication_files


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git('init', '-q')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT)

    def run_check(self, module, *args):
        output = io.StringIO()
        with patch.object(module, 'ROOT', self.root), patch('sys.argv', ['check', *args]), redirect_stdout(output), redirect_stderr(output):
            result = module.main()
        return result, output.getvalue()

    def test_index_bytes_survive_working_tree_edits_and_deletions(self):
        path = self.root / 'config.txt'
        path.write_text('private staged payload')
        self.git('add', 'config.txt')
        path.write_text('clean working copy')
        self.assertEqual(list(publication_files(self.root, staged=True))[0].data, b'private staged payload')
        self.assertEqual(list(publication_files(self.root))[0].data, b'clean working copy')
        path.unlink()
        self.assertEqual(list(publication_files(self.root, staged=True))[0].data, b'private staged payload')
        self.assertIsNotNone(list(publication_files(self.root))[0].problem)

    def test_ignored_but_staged_private_file_is_rejected(self):
        (self.root / '.gitignore').write_text('.env\n')
        (self.root / '.env').write_text('configuration')
        self.git('add', '-f', '.env')
        result, output = self.run_check(check_publication, '--staged')
        self.assertEqual(result, 1)
        self.assertIn('.env:', output)

    def test_symlink_target_is_never_scanned(self):
        (self.root / 'target').write_text('private target')
        (self.root / 'linked').symlink_to('target')
        self.git('add', 'linked')
        entry = list(publication_files(self.root, staged=True))[0]
        self.assertIsNone(entry.data)
        self.assertIsNotNone(entry.problem)

    def test_secret_in_index_cannot_be_hidden_by_clean_working_copy(self):
        # Synthetic key assembled here so this regression itself is publishable.
        token = 'AK' + 'IA' + 'Q' * 16
        path = self.root / 'config.txt'
        path.write_text('aws_access_key_id = ' + token)
        self.git('add', 'config.txt')
        path.write_text('clean working copy')
        self.assertEqual(self.run_check(check_secrets)[0], 0)
        result, output = self.run_check(check_secrets, '--staged')
        self.assertEqual(result, 1)
        self.assertIn('config.txt:', output)
        self.assertNotIn(token, output)

    def test_package_cannot_include_ignored_or_changed_files(self):
        path = self.root / 'test.whl'
        files = {'totally_normal_maps/__init__.py': b'public code'}
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('totally_normal_maps/__init__.py', b'public code')
        self.assertEqual(check_archive(path, files), 1)
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('totally_normal_maps/credentials.json', b'private data')
        with self.assertRaisesRegex(ValueError, 'not in reviewed public file set'):
            check_archive(path, files)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('totally_normal_maps/__init__.py', b'changed code')
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            check_archive(path, files)

    def test_package_rejects_traversal_and_symlinks(self):
        path = self.root / 'test.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('../private.txt', b'private data')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            check_archive(path, {})
        with zipfile.ZipFile(path, 'w') as archive:
            info = zipfile.ZipInfo('linked')
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, b'private-target')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            check_archive(path, {})


if __name__ == '__main__':
    unittest.main()
