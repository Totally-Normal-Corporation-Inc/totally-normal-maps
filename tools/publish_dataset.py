"""Verify a reviewed distribution; upload only with the explicit --publish option."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

from totally_normal_maps.catalogue import CatalogueError
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.distribution import read_lock, unpack_dataset
from totally_normal_maps.licensing import redistribution_approved


def check_redistribution(report):
    unresolved = [f'{part}/{key}' for part in ('electoral', 'municipal_elections')
                  for key, source in report.get(part, {}).get('sources', {}).items()
                  if not redistribution_approved(source)]
    if unresolved:
        sample = ', '.join(unresolved[:8])
        raise CatalogueError(f'Public upload blocked: {len(unresolved)} electoral sources lack redistribution '
                             f'permission or a documented government-source publication decision ({sample}). '
                             'Review the sources in report.json and rebuild the release first.')


def publication_command(lock, archive, lock_path, notes, commit):
    if re.fullmatch(r'[0-9a-f]{40}', commit) is None:
        raise CatalogueError('Use the exact reviewed 40-character Git commit for the dataset tag.')
    return ['gh', 'release', 'create', lock['tag'], str(archive), str(lock_path),
            '--repo', lock['repository'], '--target', commit, '--title', lock['tag'],
            '--prerelease', '--latest=false', '--notes-file', str(notes)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--commit', required=True, help='Reviewed commit already present on GitHub')
    parser.add_argument('--publish', action='store_true', help='Create a NEW public dataset release; never overwrite an existing one')
    args = parser.parse_args()
    lock_path = args.package / 'dataset.lock.json'
    lock = read_lock(lock_path)
    archive = args.package / lock['asset']
    with tempfile.TemporaryDirectory(prefix='maps-publication-') as scratch:
        root = Path(scratch)
        unpack_dataset(lock, root / 'unpacked', archive=archive)
        data = Dataset(root / 'unpacked/dataset', lock['manifest_sha256'])
        notes = root / 'notes.md'
        notes.write_text(
            'Reviewed distribution for Totally Normal Maps. Geography remains **review_required**.\n\n'
            'This dataset release is not an application deployment. Preserve NOTICE.md and report.json attribution.\n'
            'Coverage gaps and unapproved repairs remain explicit.\n\n'
            f"Archive SHA-256: `{lock['archive_sha256']}`\n\n"
            f"Dataset manifest SHA-256: `{lock['manifest_sha256']}`\n\n"
            'Counts: `' + json.dumps(data.summary['counts'], sort_keys=True) + '`\n')
        command = publication_command(lock, archive, lock_path, notes, args.commit)
        if args.publish:
            check_redistribution(data.report)
            existing = subprocess.check_output(['git', 'ls-remote', '--tags',
                'https://github.com/' + lock['repository'] + '.git', 'refs/tags/' + lock['tag']], text=True)
            if existing.strip():
                raise CatalogueError('Dataset tag already exists; choose a new immutable dataset version.')
            # gh refuses an existing release. Do not add --clobber, delete or edit
            # an existing release, even if a previous upload was interrupted.
            subprocess.run(command, check=True)
        else:
            print(json.dumps({'verified': True, 'published': False, 'repository': lock['repository'],
                              'tag': lock['tag'], 'archive_bytes': lock['archive_bytes'],
                              'manifest_sha256': data.version, 'counts': data.summary['counts']}, indent=2))


if __name__ == '__main__': main()
