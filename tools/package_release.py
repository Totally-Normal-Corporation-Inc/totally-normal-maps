"""Publish the selected data, merge its lock through CI, and report a deployable commit.

Run through ./package.sh. GitHub writes are the default; --check is entirely offline.
Only the generated lock is committed. The caller's index and branch are never used
to stage the release change. Failed runs can be repeated without replacing assets.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

from totally_normal_maps.catalogue import CatalogueError, read_json, sha256, write_json
from totally_normal_maps.distribution import download_archive, package_dataset, read_lock, unpack_dataset
from totally_normal_maps.releases import HEX, checked_release
from tools.publish_dataset import check_redistribution

ROOT = Path(__file__).resolve().parents[1]


def say(message):
    print(message, flush=True)


def command(args, *, cwd=ROOT, input=None, allow_missing=False):
    result = subprocess.run(args, cwd=cwd, input=input, capture_output=True, text=True,
                            env={**os.environ, 'GH_HOST': 'github.com'})
    if result.returncode:
        if allow_missing and '(HTTP 404)' in result.stderr:
            return None
        raise CatalogueError(f'{args[0]} {args[1]} failed: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout


class Publisher:
    def __init__(self, root, *, timeout=1800):
        self.root = Path(root)
        self.repository = read_lock(self.root / 'dataset.lock.json')['repository']
        self.timeout = timeout

    def git(self, *args, input=None):
        return command(['git', *args], cwd=self.root, input=input).strip()

    def gh(self, *args):
        return command(['gh', *args, '--repo', 'github.com/' + self.repository], cwd=self.root).strip()

    def api(self, path, *, missing=False):
        value = command(['gh', 'api', 'repos/' + self.repository + '/' + path],
                        cwd=self.root, allow_missing=missing)
        return None if value is None else json.loads(value)

    def clean_main(self):
        if self.git('branch', '--show-current') != 'main':
            raise CatalogueError('Run ./package.sh from main after merging your code and pulling main. '
                                 'Use ./package.sh --check for an offline data check on any branch.')
        if self.git('status', '--porcelain', '--untracked-files=all'):
            raise CatalogueError('Commit or stash working-tree changes before publishing; main must be clean.')
        for option in ((), ('--push',)):
            remote = self.git('remote', 'get-url', *option, '--all', 'origin')
            allowed = {f'https://github.com/{self.repository}', f'git@github.com:{self.repository}',
                       f'ssh://git@github.com/{self.repository}'}
            if remote.removesuffix('.git') not in allowed:
                raise CatalogueError('origin must fetch and push only the GitHub repository in dataset.lock.json.')
        return self.git('rev-parse', 'HEAD')

    def fetch_main(self):
        self.git('fetch', '--no-tags', 'origin', 'refs/heads/main')
        return self.git('rev-parse', 'FETCH_HEAD')

    def wait_for_ci(self, commit, event, branch):
        say(f'Waiting for ci.yml ({event}, {commit[:12]})…')
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            runs = json.loads(self.gh('run', 'list', '--workflow', 'ci.yml', '--commit', commit,
                                     '--branch', branch, '--event', event, '--limit', '20',
                                     '--json', 'databaseId,status,conclusion,url'))
            if runs:
                run = max(runs, key=lambda item: item['databaseId'])
                if run['status'] == 'completed':
                    if run['conclusion'] != 'success':
                        raise CatalogueError(f'CI did not pass: {run["url"]}. Fix or rerun CI, then rerun ./package.sh.')
                    return
            time.sleep(10)
        raise CatalogueError('Timed out waiting for CI. Rerun ./package.sh to resume; no assets are overwritten.')

    def verify_remote(self, lock, scratch):
        """Exercise the same anonymous download as Docker, not just upload metadata."""
        scratch = Path(scratch)
        self.gh('release', 'download', lock['tag'], '--pattern', 'dataset.lock.json', '--dir', str(scratch))
        if read_lock(scratch / 'dataset.lock.json') != lock:
            raise CatalogueError('Published lock differs from the local package. Existing releases are never replaced.')
        download_archive(lock, scratch / lock['asset'])

    def publish(self, package, commit):
        lock = read_lock(package / 'dataset.lock.json')
        release = self.api('releases/tags/' + lock['tag'], missing=True)
        if release is None:
            # The existing publisher verifies the ZIP, checks permissions, refuses
            # existing tags, and targets the exact reviewed Git commit.
            say(f'Uploading {lock["tag"]} ({lock["archive_bytes"] / 1_000_000:.1f} MB)…')
            command([sys.executable, '-m', 'tools.publish_dataset', '--package', str(package),
                     '--commit', commit, '--publish'], cwd=self.root)
        elif release.get('draft') or not release.get('prerelease'):
            raise CatalogueError('This version already exists as a draft or non-dataset release. '
                                 'Inspect it; use --revision 2 for a new immutable version if necessary.')
        else:
            say(f'Reusing {lock["tag"]}; verifying its published bytes…')
        with tempfile.TemporaryDirectory(dir=package.parent, prefix='download-') as scratch:
            self.verify_remote(lock, scratch)

    def lock_commit(self, lock, base, branch):
        """Make a one-file commit without changing the caller's checkout or index."""
        remote = self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + branch)
        if remote:
            self.git('fetch', '--no-tags', 'origin', 'refs/heads/' + branch)
            commit = self.git('rev-parse', 'FETCH_HEAD')
            parents = self.git('rev-list', '--parents', '-n', '1', commit).split()[1:]
            if (len(parents) != 1 or self.git('diff', '--name-only', parents[0], commit) != 'dataset.lock.json'
                    or json.loads(self.git('show', commit + ':dataset.lock.json')) != lock):
                raise CatalogueError('Existing release branch is not the expected one-file lock update.')
            self.git('merge-base', '--is-ancestor', parents[0], base)
            return commit
        content = json.dumps(lock, ensure_ascii=False, indent=2) + '\n'
        blob = self.git('hash-object', '-w', '--stdin', input=content)
        entries = self.git('ls-tree', '-z', base).split('\0')
        entries = [entry for entry in entries if entry]
        if sum(entry.split('\t', 1)[1] == 'dataset.lock.json' for entry in entries) != 1:
            raise CatalogueError('main must track one dataset.lock.json.')
        entries = [('100644 blob ' + blob + '\tdataset.lock.json')
                   if entry.split('\t', 1)[1] == 'dataset.lock.json' else entry for entry in entries]
        tree = self.git('mktree', '-z', input='\0'.join(entries) + '\0')
        commit = self.git('commit-tree', tree, '-p', base, input=f'Update data to {lock["tag"]}\n')
        # No force push: a concurrent publisher cannot replace this branch.
        self.git('push', 'origin', commit + ':refs/heads/' + branch)
        return commit

    def lock_pr(self, lock, base, package):
        branch = 'data/' + lock['tag']
        commit = self.lock_commit(lock, base, branch)
        prs = json.loads(self.gh('pr', 'list', '--head', branch, '--base', 'main', '--state', 'all',
                                 '--json', 'number,url,state,headRefOid,isCrossRepository'))
        prs = [pr for pr in prs if not pr['isCrossRepository']]
        if len(prs) > 1:
            raise CatalogueError('Multiple pull requests use this release branch; inspect them before continuing.')
        if not prs:
            body = package.parent / 'pull-request.md'
            body.write_text(
                'Update the deployment lock to the verified dataset attachment. '
                'The default Docker build will include this dataset.\n\n'
                f'Release: https://github.com/{self.repository}/releases/tag/{lock["tag"]}\n\n'
                f'Manifest SHA-256: `{lock["manifest_sha256"]}`\n\n'
                f'Archive SHA-256: `{lock["archive_sha256"]}`\n\n'
                'The serving release and public download were verified before opening this PR. '
                'Geography remains review_required; coverage gaps and unapproved repairs are preserved.\n')
            url = self.gh('pr', 'create', '--head', branch, '--base', 'main',
                          '--title', 'Update maps data: ' + lock['tag'], '--body-file', str(body))
        else:
            pr = prs[0]
            if pr['headRefOid'] != commit or pr['state'] == 'CLOSED':
                raise CatalogueError(f'Release PR changed or was closed: {pr["url"]}. Inspect it before continuing.')
            url = pr['url']
        say('Dataset lock PR: ' + url)
        status = json.loads(self.gh('pr', 'view', url, '--json', 'state,mergeCommit,headRefOid'))
        if status['headRefOid'] != commit:
            raise CatalogueError('Release PR head changed; refusing to merge.')
        if status['state'] != 'MERGED':
            self.wait_for_ci(commit, 'pull_request', branch)
            try:
                self.gh('pr', 'merge', url, '--squash', '--match-head-commit', commit)
            except CatalogueError as error:
                raise CatalogueError(f'Could not merge {url}. Required approvals and branch protections '
                                     f'are respected. Resolve the PR requirement, then rerun ./package.sh. {error}') from error
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            status = json.loads(self.gh('pr', 'view', url, '--json', 'state,mergeCommit,headRefOid'))
            if status['headRefOid'] != commit or status['state'] == 'CLOSED':
                raise CatalogueError('Release PR changed or closed while waiting for merge: ' + url)
            if status['state'] == 'MERGED':
                return status['mergeCommit']['oid'], url
            time.sleep(10)
        raise CatalogueError('Waiting for the merge queue: ' + url + '. Rerun ./package.sh to resume.')

    def run(self, source, digest, revision):
        base = self.clean_main()
        command(['gh', 'auth', 'status', '--hostname', 'github.com'], cwd=self.root)
        if self.fetch_main() != base:
            raise CatalogueError('Local main differs from origin/main. Run git pull --ff-only, then ./package.sh.')
        self.wait_for_ci(base, 'push', 'main')
        tag = version_tag(digest, sha256(self.root / 'NOTICE.md'), revision)
        workspace = self.root / '.local' / 'packages' / tag
        workspace.mkdir(parents=True, exist_ok=True)
        package = workspace / 'distribution'
        if not package.exists():
            say('Packaging the verified serving dataset…')
            package_dataset(source, package, manifest_sha256=digest, repository=self.repository,
                            tag=tag, notice=self.root / 'NOTICE.md')
        lock = verify_package(package, digest, self.root / 'NOTICE.md', self.repository, tag)
        if self.clean_main() != base:
            raise CatalogueError('Checkout changed while packaging. Rerun from clean main.')
        self.publish(package, base)
        current = read_lock(self.root / 'dataset.lock.json')
        if current == lock:
            commit, url = base, None
        else:
            commit, url = self.lock_pr(lock, base, package)
            self.fetch_main()
            self.git('merge-base', '--is-ancestor', commit, 'FETCH_HEAD')
            if json.loads(self.git('show', commit + ':dataset.lock.json')) != lock:
                raise CatalogueError('Merged dataset lock differs from the verified upload.')
            self.wait_for_ci(commit, 'push', 'main')
            if self.clean_main() != base:
                raise CatalogueError('Checkout changed during publication. Data and PR are preserved; '
                                     'rerun from clean, updated main to finish.')
            self.git('merge', '--ff-only', commit)
        receipt = {'repository': self.repository, 'commit': commit, 'pull_request': url,
                   'dataset_tag': tag, 'manifest_sha256': digest,
                   'archive_sha256': lock['archive_sha256']}
        write_json(workspace / 'receipt.json', receipt)
        say(f'Ready to deploy commit {commit}\nDataset: {tag}\n'
            f'Receipt: {workspace.relative_to(self.root)}/receipt.json\n'
            'The default Docker build now includes this data; no separate data upload is needed.')
        return receipt


def version_tag(manifest_digest, notice_digest, revision):
    fingerprint = hashlib.sha256((manifest_digest + '\n' + notice_digest).encode()).hexdigest()
    return f'dataset-{fingerprint[:20]}-r{revision}'


def selected_source(root):
    spec = read_json(root / 'dataset.source.json')
    if (not isinstance(spec, dict) or set(spec) != {'schema_version', 'directory', 'manifest_sha256'}
            or spec['schema_version'] != 1 or not isinstance(spec['directory'], str)
            or not isinstance(spec['manifest_sha256'], str) or not HEX.fullmatch(spec['manifest_sha256'])):
        raise CatalogueError('Invalid dataset.source.json; select a reviewed serving release and its manifest SHA-256.')
    path = PurePosixPath(spec['directory'])
    if path.is_absolute() or '..' in path.parts or path.parts[:2] != ('.local', 'releases') or len(path.parts) < 3:
        raise CatalogueError('The selected dataset must live inside this repository under .local/releases/.')
    source = root / path
    if any(part.is_symlink() for part in [source, *source.parents] if part.is_relative_to(root)):
        raise CatalogueError('The selected dataset path must not contain symlinks.')
    if not source.is_dir():
        raise CatalogueError(f'Missing local dataset: {path}. Restore or build the selected release; '
                             'pushing source code does not upload ignored data.')
    _, _, digest = checked_release(source, spec['manifest_sha256'])
    check_redistribution(read_json(source / 'report.json'))
    return source, digest


def verify_package(package, digest, notice, repository, tag):
    lock = read_lock(package / 'dataset.lock.json')
    if (lock['manifest_sha256'], lock['repository'], lock['tag']) != (digest, repository, tag):
        raise CatalogueError('Cached package differs from the selected release; it will not be overwritten.')
    with tempfile.TemporaryDirectory(dir=package.parent, prefix='verify-') as scratch:
        unpack_dataset(lock, Path(scratch) / 'unpacked', archive=package / lock['asset'])
        check_redistribution(read_json(Path(scratch) / 'unpacked/dataset/report.json'))
    with ZipFile(package / lock['asset']) as archive:
        if archive.read('NOTICE.md') != notice.read_bytes():
            raise CatalogueError('Cached attribution differs from NOTICE.md.')
    return lock


@contextmanager
def exclusive_run(root):
    local = root / '.local'
    local.mkdir(exist_ok=True)
    with (local / 'package-run.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CatalogueError('Another package.sh is running in this checkout.') from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Offline data integrity and redistribution check; no GitHub writes')
    parser.add_argument('--revision', type=int, default=1, help='Packaging revision (default 1); increase only to replace an abandoned immutable version')
    parser.add_argument('--timeout', type=int, default=1800, help='Seconds to wait for each CI/merge stage (default 1800)')
    args = parser.parse_args()
    if not 1 <= args.revision <= 9999 or args.timeout < 1:
        parser.error('revision must be 1–9999; timeout must be positive')
    try:
        if not args.check:
            Publisher(ROOT).clean_main()
        say('Checking the selected dataset and its pinned files…')
        source, digest = selected_source(ROOT)
        if args.check:
            say(f'Data integrity and redistribution checks passed. Manifest SHA-256: {digest}\n'
                'Publishing also requires clean, synchronized main, GitHub authentication and passing CI.')
            return 0
        with exclusive_run(ROOT):
            Publisher(ROOT, timeout=args.timeout).run(source, digest, args.revision)
        return 0
    except (CatalogueError, OSError, ValueError) as error:
        print(f'Packaging stopped: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Rerun ./package.sh to resume; existing releases are never overwritten.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
