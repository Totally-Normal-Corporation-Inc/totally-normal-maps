"""Release automation acceptance: synthetic data, local Git, no external writes."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from totally_normal_maps.catalogue import CatalogueError, sha256, write_json
from totally_normal_maps.distribution import package_dataset, read_lock
from tools import package_release as release
from tools.publish_dataset import check_redistribution
from .api_fixture import make_release


class PackageReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        _, cls.source, cls.digest = make_release(Path(cls.fixture.name))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()
        self.remote = Path(self.temp.name) / 'remote.git'
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Synthetic fixture')
        subprocess.run(['git', 'init', '--bare', '-q', str(self.remote)], check=True)
        self.git('remote', 'add', 'origin', str(self.remote))
        (self.root / '.gitignore').write_text('.local/\n')
        self.notice = self.root / 'NOTICE.md'
        self.notice.write_text('Synthetic data for offline release acceptance.\n')
        self.dataset = self.root / '.local/releases/fixture'
        shutil.copytree(self.source, self.dataset)
        self.spec = {'schema_version': 1, 'directory': '.local/releases/fixture', 'manifest_sha256': self.digest}
        write_json(self.root / 'dataset.source.json', self.spec)
        self.package = self.root / '.local/fixture-package'
        self.tag = release.version_tag(self.digest, sha256(self.notice), 1)
        package_dataset(self.dataset, self.package, manifest_sha256=self.digest,
                        repository='example/maps', tag=self.tag, notice=self.notice)
        self.lock = read_lock(self.package / 'dataset.lock.json')
        write_json(self.root / 'dataset.lock.json', {**self.lock, 'tag': 'dataset-previous'})
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic baseline')
        self.git('push', '-q', 'origin', 'main')
        self.base = self.git('rev-parse', 'HEAD')
        self.publisher = release.Publisher(self.root, timeout=1)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True, stderr=subprocess.PIPE).strip()

    def test_selection_is_pinned_and_never_chooses_latest_directory(self):
        other = self.root / '.local/releases/newer'
        shutil.copytree(self.source, other)
        self.assertEqual(release.selected_source(self.root), (self.dataset, self.digest))
        write_json(self.root / 'dataset.source.json', {**self.spec, 'manifest_sha256': '0' * 64})
        with self.assertRaisesRegex(CatalogueError, 'pinned digest'):
            release.selected_source(self.root)
        for directory in ('../outside', '/tmp/data', '.local/releases/../../outside'):
            write_json(self.root / 'dataset.source.json', {**self.spec, 'directory': directory})
            with self.assertRaisesRegex(CatalogueError, 'inside this repository'):
                release.selected_source(self.root)

    def test_missing_corrupt_or_symlinked_source_is_rejected(self):
        (self.dataset / 'report.json').write_text('{}')
        with self.assertRaisesRegex(CatalogueError, 'integrity validation'):
            release.selected_source(self.root)
        shutil.rmtree(self.dataset)
        with self.assertRaisesRegex(CatalogueError, 'Missing local dataset'):
            release.selected_source(self.root)
        self.dataset.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(CatalogueError, 'symlinks'):
            release.selected_source(self.root)

    def test_versions_are_stable_and_include_data_notice_and_revision(self):
        self.assertEqual(release.version_tag(self.digest, sha256(self.notice), 1), self.tag)
        self.assertNotEqual(release.version_tag('0' * 64, sha256(self.notice), 1), self.tag)
        self.assertNotEqual(release.version_tag(self.digest, '0' * 64, 1), self.tag)
        self.assertNotEqual(release.version_tag(self.digest, sha256(self.notice), 2), self.tag)

    def test_redistribution_guard_covers_both_electoral_layers(self):
        for part in ('electoral', 'municipal_elections'):
            for status in (None, 'unconfirmed', 'prohibited'):
                with self.assertRaisesRegex(CatalogueError, 'Public upload blocked'):
                    check_redistribution({part: {'sources': {'fixture': {'redistribution_status': status}}}})
            check_redistribution({part: {'sources': {'fixture': {'redistribution_status': 'permitted'}}}})

    def test_offline_check_never_calls_github_and_reports_permission_block(self):
        with patch.object(release, 'ROOT', self.root), patch('sys.argv', ['package', '--check']), \
                patch.object(release, 'command', side_effect=AssertionError('No external commands allowed')), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(release.main(), 0)
            with patch.object(release, 'check_redistribution', side_effect=CatalogueError('Public upload blocked')), \
                    redirect_stderr(io.StringIO()) as output:
                self.assertEqual(release.main(), 1)
                self.assertIn('Public upload blocked', output.getvalue())

    def test_main_cleanliness_and_remote_are_checked_before_network(self):
        with self.assertRaisesRegex(CatalogueError, 'origin must'):
            self.publisher.clean_main()
        self.git('remote', 'set-url', 'origin', 'https://github.com/example/maps.git')
        self.assertEqual(self.publisher.clean_main(), self.base)
        self.git('remote', 'set-url', '--push', 'origin', 'https://github.com/wrong/maps.git')
        with self.assertRaisesRegex(CatalogueError, 'origin must'):
            self.publisher.clean_main()
        self.git('config', '--unset-all', 'remote.origin.pushurl')
        (self.root / 'untracked').write_text('pending work')
        with self.assertRaisesRegex(CatalogueError, 'must be clean'):
            self.publisher.clean_main()
        (self.root / 'untracked').unlink()
        self.git('switch', '-qc', 'feature')
        with self.assertRaisesRegex(CatalogueError, 'from main'):
            self.publisher.clean_main()

    def test_cache_is_verified_and_corruption_is_not_overwritten(self):
        self.assertEqual(release.verify_package(self.package, self.digest, self.notice, 'example/maps', self.tag), self.lock)
        archive = self.package / self.lock['asset']
        archive.write_bytes(archive.read_bytes()[:-1])
        with self.assertRaisesRegex(CatalogueError, 'checksum or size'):
            release.verify_package(self.package, self.digest, self.notice, 'example/maps', self.tag)

    def test_one_file_commit_preserves_checkout_and_reuses_remote_branch(self):
        branch = 'data/' + self.tag
        before_index = (self.root / '.git/index').read_bytes()
        commit = self.publisher.lock_commit(self.lock, self.base, branch)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual((self.root / '.git/index').read_bytes(), before_index)
        self.assertEqual(self.git('diff', '--name-only', self.base, commit), 'dataset.lock.json')
        self.assertEqual(json.loads(self.git('show', commit + ':dataset.lock.json')), self.lock)
        self.assertEqual(self.publisher.lock_commit(self.lock, self.base, branch), commit)
        with self.assertRaisesRegex(CatalogueError, 'expected one-file'):
            self.publisher.lock_commit({**self.lock, 'tag': 'dataset-other'}, self.base, branch)

    def test_branch_with_extra_changes_is_never_merged(self):
        branch = 'data/' + self.tag
        self.git('switch', '-qc', branch)
        write_json(self.root / 'dataset.lock.json', self.lock)
        (self.root / 'extra').write_text('unexpected extra commit content')
        self.git('add', '.')
        self.git('commit', '-qm', 'Unexpected branch changes')
        self.git('push', '-q', 'origin', branch)
        self.git('switch', '-q', 'main')
        with self.assertRaisesRegex(CatalogueError, 'expected one-file'):
            self.publisher.lock_commit(self.lock, self.base, branch)

    def test_ci_failure_missing_runs_and_success(self):
        run = {'databaseId': 1, 'status': 'completed', 'conclusion': 'failure', 'url': 'https://example.invalid/ci'}
        with patch.object(self.publisher, 'gh', return_value=json.dumps([run])):
            with self.assertRaisesRegex(CatalogueError, 'CI did not pass'):
                self.publisher.wait_for_ci(self.base, 'push', 'main')
        with patch.object(self.publisher, 'gh', return_value='[]'), \
                patch.object(release.time, 'monotonic', side_effect=[0, 0, 2]), patch.object(release.time, 'sleep'):
            with self.assertRaisesRegex(CatalogueError, 'Timed out'):
                self.publisher.wait_for_ci(self.base, 'push', 'main')
        with patch.object(self.publisher, 'gh', return_value=json.dumps([{**run, 'conclusion': 'success'}])):
            self.publisher.wait_for_ci(self.base, 'push', 'main')

    def test_existing_release_is_verified_without_upload_or_overwrite(self):
        with patch.object(self.publisher, 'api', return_value={'draft': False, 'prerelease': True}), \
                patch.object(self.publisher, 'verify_remote') as verify, \
                patch.object(release, 'command', side_effect=AssertionError('No reupload allowed')):
            self.publisher.publish(self.package, self.base)
            verify.assert_called_once()
        with patch.object(self.publisher, 'api', return_value={'draft': True, 'prerelease': True}):
            with self.assertRaisesRegex(CatalogueError, 'already exists'):
                self.publisher.publish(self.package, self.base)

    def test_new_upload_targets_exact_main_and_requires_remote_verification(self):
        with patch.object(self.publisher, 'api', return_value=None), \
                patch.object(release, 'command') as publish, \
                patch.object(self.publisher, 'verify_remote', side_effect=CatalogueError('download incomplete')):
            with self.assertRaisesRegex(CatalogueError, 'download incomplete'):
                self.publisher.publish(self.package, self.base)
            args = publish.call_args.args[0]
            self.assertIn('--publish', args)
            self.assertEqual(args[args.index('--commit') + 1], self.base)

    def test_interrupted_pr_is_reused_and_head_changes_are_rejected(self):
        commit = self.publisher.lock_commit(self.lock, self.base, 'data/' + self.tag)
        pr = {'number': 1, 'url': 'https://github.com/example/maps/pull/1',
              'state': 'OPEN', 'headRefOid': commit, 'isCrossRepository': False}
        status = {'state': 'MERGED', 'headRefOid': commit, 'mergeCommit': {'oid': commit}}
        with patch.object(self.publisher, 'gh', side_effect=[json.dumps([pr]), json.dumps(status), json.dumps(status)]) as gh:
            self.assertEqual(self.publisher.lock_pr(self.lock, self.base, self.package), (commit, pr['url']))
            self.assertNotIn(('pr', 'create'), [call.args[:2] for call in gh.call_args_list])
            self.assertNotIn(('pr', 'merge'), [call.args[:2] for call in gh.call_args_list])
        for changed in ({**pr, 'headRefOid': 'f' * 40}, {**pr, 'state': 'CLOSED'}):
            with patch.object(self.publisher, 'gh', return_value=json.dumps([changed])):
                with self.assertRaisesRegex(CatalogueError, 'changed or was closed'):
                    self.publisher.lock_pr(self.lock, self.base, self.package)
        with patch.object(self.publisher, 'gh', side_effect=[json.dumps([pr]), json.dumps({**status, 'headRefOid': 'f' * 40})]):
            with self.assertRaisesRegex(CatalogueError, 'head changed'):
                self.publisher.lock_pr(self.lock, self.base, self.package)

    def test_required_approval_failure_preserves_pr_and_never_bypasses_rules(self):
        commit = self.publisher.lock_commit(self.lock, self.base, 'data/' + self.tag)
        pr = {'number': 1, 'url': 'https://github.com/example/maps/pull/1',
              'state': 'OPEN', 'headRefOid': commit, 'isCrossRepository': False}
        status = {'state': 'OPEN', 'headRefOid': commit, 'mergeCommit': None}
        with patch.object(self.publisher, 'wait_for_ci'), \
                patch.object(self.publisher, 'gh', side_effect=[json.dumps([pr]), json.dumps(status), CatalogueError('review required')]) as gh:
            with self.assertRaisesRegex(CatalogueError, 'Required approvals and branch protections'):
                self.publisher.lock_pr(self.lock, self.base, self.package)
            args = gh.call_args.args
            self.assertEqual(args[:2], ('pr', 'merge'))
            self.assertNotIn('--admin', args)
            self.assertIn('--match-head-commit', args)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)

    def test_remote_download_verifies_lock_and_archive(self):
        def download_lock(*args):
            destination = Path(args[args.index('--dir') + 1])
            write_json(destination / 'dataset.lock.json', self.lock)
        opener = Mock(return_value=io.BytesIO((self.package / self.lock['asset']).read_bytes()))
        scratch = self.root / '.local/download'
        scratch.mkdir()
        with patch.object(self.publisher, 'gh', side_effect=download_lock), \
                patch('totally_normal_maps.distribution.build_opener', return_value=Mock(open=opener)):
            self.publisher.verify_remote(self.lock, scratch)
        self.assertEqual(sha256(scratch / self.lock['asset']), self.lock['archive_sha256'])
        shutil.rmtree(scratch)
        scratch.mkdir()
        opener = Mock(return_value=io.BytesIO(b'truncated'))
        with patch.object(self.publisher, 'gh', side_effect=download_lock), \
                patch('totally_normal_maps.distribution.build_opener', return_value=Mock(open=opener)):
            with self.assertRaisesRegex(CatalogueError, 'checksum or size'):
                self.publisher.verify_remote(self.lock, scratch)
        with patch.object(self.publisher, 'gh'), \
                patch.object(release, 'read_lock', return_value={**self.lock, 'tag': 'dataset-wrong'}):
            with self.assertRaisesRegex(CatalogueError, 'Published lock differs'):
                self.publisher.verify_remote(self.lock, scratch)

    def test_complete_workflow_and_repeat_use_local_git_and_fake_github(self):
        state = {'pr': None, 'merged': False}
        calls = []

        def gh(*args):
            calls.append(args[:2])
            if args[:2] == ('pr', 'list'):
                return '[]'
            if args[:2] == ('pr', 'create'):
                state['pr'] = 'https://github.com/example/maps/pull/1'
                return state['pr']
            commit = self.git('ls-remote', '--heads', 'origin', 'refs/heads/data/' + self.tag).split()[0]
            if args[:2] == ('pr', 'view'):
                return json.dumps({'state': 'MERGED' if state['merged'] else 'OPEN',
                                   'headRefOid': commit, 'mergeCommit': {'oid': commit} if state['merged'] else None})
            if args[:2] == ('pr', 'merge'):
                self.assertIn('--match-head-commit', args)
                self.assertNotIn('--admin', args)
                self.git('push', '-q', 'origin', commit + ':refs/heads/main')
                state['merged'] = True
                return ''
            self.fail(f'Unexpected fake GitHub command: {args}')

        original_command = release.command

        def run_command(args, **kwargs):
            if args[:3] == ['gh', 'auth', 'status']:
                return ''
            return original_command(args, **kwargs)

        with patch.object(self.publisher, 'clean_main', side_effect=lambda: self.git('rev-parse', 'HEAD')), \
                patch.object(self.publisher, 'gh', side_effect=gh), \
                patch.object(self.publisher, 'wait_for_ci') as ci, \
                patch.object(self.publisher, 'publish') as publish, \
                patch.object(release, 'command', side_effect=run_command):
            receipt = self.publisher.run(self.dataset, self.digest, 1)
            self.assertEqual(read_lock(self.root / 'dataset.lock.json'), self.lock)
            self.assertEqual(self.git('rev-parse', 'HEAD'), receipt['commit'])
            self.assertEqual(self.git('status', '--porcelain'), '')
            self.assertEqual(ci.call_count, 3)
            self.assertEqual(calls.count(('pr', 'create')), 1)
            again = self.publisher.run(self.dataset, self.digest, 1)
            self.assertEqual(again['commit'], receipt['commit'])
            self.assertEqual(calls.count(('pr', 'create')), 1)
            self.assertEqual(publish.call_count, 2)  # Each run re-verifies the remote asset.

    def test_failed_upload_cannot_create_lock_pr(self):
        with patch.object(self.publisher, 'clean_main', return_value=self.base), \
                patch.object(self.publisher, 'fetch_main', return_value=self.base), \
                patch.object(self.publisher, 'wait_for_ci'), \
                patch.object(release, 'command', return_value=''), \
                patch.object(self.publisher, 'publish', side_effect=CatalogueError('upload failed')), \
                patch.object(self.publisher, 'lock_pr') as pr:
            with self.assertRaisesRegex(CatalogueError, 'upload failed'):
                self.publisher.run(self.dataset, self.digest, 1)
            pr.assert_not_called()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.base)
        self.assertEqual(read_lock(self.root / 'dataset.lock.json')['tag'], 'dataset-previous')

    def test_only_http_404_is_treated_as_missing_release(self):
        for error, missing in [('gh: Not Found (HTTP 404)', True), ('gh: HTTP 403 forbidden', False), ('connection failed', False)]:
            result = subprocess.CompletedProcess([], 1, stdout='', stderr=error)
            with patch.object(release.subprocess, 'run', return_value=result):
                if missing:
                    self.assertIsNone(release.command(['gh', 'api', 'endpoint'], allow_missing=True))
                else:
                    with self.assertRaises(CatalogueError):
                        release.command(['gh', 'api', 'endpoint'], allow_missing=True)

    def test_concurrent_runs_cannot_publish(self):
        with release.exclusive_run(self.root):
            with self.assertRaisesRegex(CatalogueError, 'Another package.sh'):
                with release.exclusive_run(self.root):
                    self.fail('Second publisher must not enter')


if __name__ == '__main__':
    unittest.main()
