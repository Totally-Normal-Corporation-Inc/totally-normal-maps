"""Reject build contents outside the exact reviewed public file set."""
import argparse
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile

if __package__:
    from .check_publication import PATTERNS
    from .publication_files import MAX_PUBLIC_BYTES, publication_files
else:
    from check_publication import PATTERNS
    from publication_files import MAX_PUBLIC_BYTES, publication_files

ROOT = Path(__file__).resolve().parents[1]
METADATA = {'PKG-INFO', 'METADATA', 'WHEEL', 'RECORD', 'entry_points.txt',
            'top_level.txt', 'dependency_links.txt', 'requires.txt', 'SOURCES.txt'}


def archive_files(path):
    if path.name.endswith('.whl'):
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                if entry.file_size > MAX_PUBLIC_BYTES or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('oversized artifact or archive symlink')
                yield entry.filename, archive.read(entry)
    elif path.name.endswith('.tar.gz'):
        with tarfile.open(path) as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                if not entry.isfile() or entry.size > MAX_PUBLIC_BYTES:
                    raise ValueError('oversized artifact or nonregular archive member')
                yield entry.name, archive.extractfile(entry).read()
    else:
        raise ValueError('expected a wheel or source .tar.gz')


def check_archive(path, public_files):
    count, seen = 0, set()
    for name, data in archive_files(path):
        parts = PurePosixPath(name).parts
        if not parts or name.startswith('/') or '\\' in name or '..' in parts or name in seen:
            raise ValueError('unsafe or duplicate archive path')
        seen.add(name)
        if path.name.endswith('.tar.gz'):
            if len(parts) < 2 or not re.fullmatch(r'totally_normal_maps-[0-9][A-Za-z0-9._-]*', parts[0]):
                raise ValueError('unexpected source archive root')
            parts = parts[1:]
        relative = '/'.join(parts)
        public_name = relative
        if len(parts) == 3 and parts[0].endswith('.dist-info') and parts[1] == 'licenses':
            public_name = parts[2]
        if public_name in public_files:
            if data != public_files[public_name]:
                raise ValueError(f'{relative}: bytes differ from reviewed public file')
        else:
            generated = (relative in {'PKG-INFO', 'setup.cfg'} or
                         len(parts) == 2 and (parts[0].endswith('.egg-info') or parts[0].endswith('.dist-info'))
                         and parts[1] in METADATA)
            if not generated:
                raise ValueError(f'{relative}: not in reviewed public file set')
            text = data.decode('utf-8')
            if any(pattern.search(text) for pattern in PATTERNS.values()):
                raise ValueError(f'{relative}: sensitive metadata pattern')
        count += 1
    if not count:
        raise ValueError('empty build archive')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Compare against the exact proposed Git commit')
    parser.add_argument('archives', nargs='+', type=Path)
    args = parser.parse_args()
    entries = list(publication_files(ROOT, staged=args.staged))
    if any(entry.problem for entry in entries):
        print('Cannot verify artifacts against an invalid publication surface.', file=sys.stderr)
        return 1
    public_files = {entry.name: entry.data for entry in entries}
    try:
        for path in args.archives:
            print(f'{path.name}: {check_archive(path, public_files)} artifact files checked against reviewed public bytes.')
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f'Artifact check failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
