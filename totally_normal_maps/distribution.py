"""Pinned public dataset archives. Acquisition is an explicit build-time operation."""
import hashlib
import json
from pathlib import Path
import re
import stat
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .catalogue import CatalogueError, new_directory, read_json, sha256, write_json
from .releases import HEX, MAX_FILES, MAX_MANIFEST_BYTES, MAX_RELEASE_BYTES, checked_release, validate_manifest

MAX_ARCHIVE_BYTES = MAX_RELEASE_BYTES + 1024 * 1024
MAX_NOTICE_BYTES = 128 * 1024
LOCK_FIELDS = {'schema_version', 'repository', 'tag', 'asset', 'archive_bytes', 'archive_sha256', 'manifest_sha256'}
DOCUMENTS = {'NOTICE.md', 'README.txt'}


def validate_lock(lock):
    if (not isinstance(lock, dict) or set(lock) != LOCK_FIELDS or type(lock.get('schema_version')) is not int or lock['schema_version'] != 1
            or not isinstance(lock.get('repository'), str)
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', lock['repository']) is None
            or not isinstance(lock.get('tag'), str) or re.fullmatch(r'dataset-[A-Za-z0-9][A-Za-z0-9._-]{0,79}', lock['tag']) is None
            or not isinstance(lock.get('asset'), str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.zip', lock['asset']) is None
            or '..' in lock['tag'] or '..' in lock['asset']
            or type(lock.get('archive_bytes')) is not int or not 0 < lock['archive_bytes'] <= MAX_ARCHIVE_BYTES
            or any(not isinstance(lock.get(k), str) or HEX.fullmatch(lock[k]) is None for k in ('archive_sha256', 'manifest_sha256'))):
        raise CatalogueError('Invalid pinned dataset lock.')
    return lock


def read_lock(path):
    path = Path(path)
    if path.is_symlink():
        raise CatalogueError('Dataset lock may not be a symlink.')
    return validate_lock(read_json(path, MAX_MANIFEST_BYTES))


def asset_url(lock):
    validate_lock(lock)
    return f"https://github.com/{lock['repository']}/releases/download/{lock['tag']}/{lock['asset']}"


def _zip_file(package, name, data):
    item = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    item.create_system = 3
    item.external_attr = (stat.S_IFREG | 0o644) << 16
    item.compress_type = ZIP_DEFLATED
    package.writestr(item, data, compresslevel=6)


def package_dataset(dataset, output, *, manifest_sha256, repository, tag, notice):
    """Deterministic, reviewed serving files only; never include a working directory."""
    from .dataset import Dataset
    data = Dataset(dataset, manifest_sha256)
    notice = Path(notice)
    if notice.is_symlink() or notice.stat().st_size > MAX_NOTICE_BYTES:
        raise CatalogueError('Expected a bounded attribution notice.')
    notice_bytes = notice.read_bytes()
    if not notice_bytes.decode('utf-8').strip():
        raise CatalogueError('The distribution must preserve attribution.')
    lock = {'schema_version': 1, 'repository': repository, 'tag': tag,
            'asset': data.manifest['label'] + '.zip', 'archive_bytes': 1,
            'archive_sha256': '0' * 64, 'manifest_sha256': data.version}
    validate_lock(lock)
    with new_directory(output) as staging:
        archive = staging / lock['asset']
        with ZipFile(archive, 'x') as package:
            for name in ['manifest.json', *sorted(data.manifest['files'])]:
                source = data.root / name
                expected = data.version if name == 'manifest.json' else data.manifest['files'][name]['sha256']
                content = source.read_bytes()
                if source.is_symlink() or hashlib.sha256(content).hexdigest() != expected:
                    raise CatalogueError('Serving release changed while packaging.')
                _zip_file(package, 'dataset/' + name, content)
            _zip_file(package, 'NOTICE.md', notice_bytes)
            _zip_file(package, 'README.txt', (
                'Totally Normal Maps — reviewed distribution\n\n'
                'Use the dataset/ directory with maps verify-release and maps api.\n'
                'Qualification remains review_required. Coverage gaps and unapproved repairs are retained.\n'
                'Preserve NOTICE.md and the source attribution/licences in dataset/report.json.\n'
                f'Dataset manifest SHA-256: {data.version}\n').encode())
        lock.update(archive_bytes=archive.stat().st_size, archive_sha256=sha256(archive))
        validate_lock(lock)
        write_json(staging / 'dataset.lock.json', lock)
        (staging / (lock['asset'] + '.sha256')).write_text(lock['archive_sha256'] + '  ' + lock['asset'] + '\n')
    return {'output': str(output), 'asset': lock['asset'], 'archive_bytes': lock['archive_bytes'],
            'archive_sha256': lock['archive_sha256'], 'manifest_sha256': data.version, 'qualification': 'review_required'}


class _HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise CatalogueError('Dataset download redirects must preserve public HTTPS.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_archive(lock, destination, *, opener=None):
    """Only the public GitHub asset named in the committed lock; no credentials."""
    validate_lock(lock)
    opener = opener or build_opener(_HTTPSRedirects()).open
    received, started = 0, time.monotonic()
    try:
        with opener(asset_url(lock), timeout=30) as response, Path(destination).open('xb') as target:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > lock['archive_bytes'] or time.monotonic() - started > 300:
                    raise CatalogueError('Dataset download exceeded its pinned size or time budget.')
                target.write(chunk)
    except (URLError, TimeoutError, OSError) as error:
        raise CatalogueError('Unable to download the pinned dataset attachment; publish or restore that exact release first.') from error
    _checked_archive(destination, lock)


def _checked_archive(path, lock):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != lock['archive_bytes'] or sha256(path) != lock['archive_sha256']:
        raise CatalogueError('Dataset archive differs from the committed checksum or size.')


def _extract_archive(archive, lock, staging):
    """Reject arbitrary members, links, traversal, duplicates and expansion bombs."""
    with ZipFile(archive) as package:
        entries = package.infolist()
        names = [i.filename for i in entries]
        if (len(entries) > MAX_FILES + 3 or len(names) != len(set(names))
                or sum(i.file_size for i in entries) > MAX_RELEASE_BYTES + MAX_MANIFEST_BYTES + 2 * MAX_NOTICE_BYTES
                or any(i.orig_filename != i.filename or i.is_dir() or '\\' in i.filename
                       or i.filename.startswith('/') or '..' in i.filename.split('/')
                       or i.flag_bits & 1 or i.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                       or stat.S_IFMT(i.external_attr >> 16) not in {0, stat.S_IFREG} for i in entries)
                or 'dataset/manifest.json' not in names):
            raise CatalogueError('Invalid dataset archive layout or byte budget.')
        if package.getinfo('dataset/manifest.json').file_size > MAX_MANIFEST_BYTES:
            raise CatalogueError('Oversized dataset manifest.')
        content = package.read('dataset/manifest.json')
        if hashlib.sha256(content).hexdigest() != lock['manifest_sha256']:
            raise CatalogueError('Dataset manifest differs from the committed digest.')
        manifest = validate_manifest(json.loads(content))
        expected = {'dataset/manifest.json', *('dataset/' + name for name in manifest['files']), *DOCUMENTS}
        if set(names) != expected:
            raise CatalogueError('Archive must contain exactly the serving release and attribution documents.')
        (staging / 'dataset').mkdir()
        (staging / 'dataset/manifest.json').write_bytes(content)
        for name, spec in manifest['files'].items():
            member = 'dataset/' + name
            if package.getinfo(member).file_size != spec['bytes']:
                raise CatalogueError('Dataset member size differs from the manifest.')
            target = staging / member
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, received = hashlib.sha256(), 0
            with package.open(member) as source, target.open('xb') as output:
                while chunk := source.read(1024 * 1024):
                    received += len(chunk)
                    if received > spec['bytes']:
                        raise CatalogueError('Dataset member exceeded its byte budget.')
                    output.write(chunk); digest.update(chunk)
            if received != spec['bytes'] or digest.hexdigest() != spec['sha256']:
                raise CatalogueError('Dataset member differs from its pinned checksum.')
        for name in sorted(DOCUMENTS):
            if package.getinfo(name).file_size > MAX_NOTICE_BYTES:
                raise CatalogueError('Oversized distribution document.')
            content = package.read(name)
            if not content.decode('utf-8').strip():
                raise CatalogueError('Missing distribution attribution or usage document.')
            (staging / name).write_bytes(content)
    checked_release(staging / 'dataset', lock['manifest_sha256'])


def unpack_dataset(lock, output, *, archive=None, opener=None):
    validate_lock(lock)
    with new_directory(output) as staging, tempfile.TemporaryDirectory(prefix='maps-download-') as scratch:
        if archive is None:
            archive = Path(scratch) / 'dataset.zip'
            download_archive(lock, archive, opener=opener)
        _checked_archive(archive, lock)
        try:
            _extract_archive(archive, lock, staging)
        except (BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError, EOFError) as error:
            raise CatalogueError('Malformed dataset archive.') from error
    return {'output': str(output), 'manifest_sha256': lock['manifest_sha256']}
