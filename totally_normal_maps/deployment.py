"""One local deployment artifact: code identity, API dataset and public website."""
import hashlib
from pathlib import Path
import shutil

from .catalogue import CatalogueError, ROOT, new_directory, read_json, sha256, write_json
from .distribution import read_lock, unpack_dataset
from .releases import HEX, MAX_MANIFEST_BYTES
from .website import checked_website, export_website


def code_digest():
    # These are the installed package's public inputs, independent of installation
    # path, bytecode caches, source checkout timestamps and generated data.
    digest = hashlib.sha256()
    for path in sorted(ROOT.rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc': continue
        if path.is_symlink(): raise CatalogueError('Code identity cannot contain symlinks.')
        if path.is_file():
            name = str(path.relative_to(ROOT)).encode()
            digest.update(name + b'\0' + sha256(path).encode() + b'\n')
    return digest.hexdigest()


def read_deployment(root):
    root = Path(root)
    if root.is_symlink() or (root / 'deployment.json').is_symlink():
        raise CatalogueError('Deployment must be a real, immutable directory.')
    record = read_json(root / 'deployment.json', MAX_MANIFEST_BYTES)
    fields = {'schema_version', 'qualification', 'dataset_manifest_sha256', 'website_manifest_sha256', 'code_sha256', 'lock_sha256', 'notice_sha256'}
    if (set(record) != fields or record.get('schema_version') != 1 or record.get('qualification') != 'review_required'
            or any(not isinstance(record[k], str) or HEX.fullmatch(record[k]) is None for k in fields - {'schema_version', 'qualification'})):
        raise CatalogueError('Invalid combined deployment record.')
    return record


def verify_deployment(root, *, verify_code=True):
    from .dataset import Dataset
    root = Path(root)
    record = read_deployment(root)
    if (set(p.name for p in root.iterdir()) != {'deployment.json', 'dataset.lock.json', 'dataset', 'site', 'NOTICE.md'}
            or any(p.is_symlink() for p in root.rglob('*'))
            or sha256(root / 'dataset.lock.json') != record['lock_sha256']
            or sha256(root / 'NOTICE.md') != record['notice_sha256']
            or verify_code and code_digest() != record['code_sha256']):
        raise CatalogueError('Deployment files or running code differ from the sealed release.')
    lock = read_lock(root / 'dataset.lock.json')
    if lock['manifest_sha256'] != record['dataset_manifest_sha256']:
        raise CatalogueError('Deployment dataset differs from its committed lock.')
    dataset = Dataset(root / 'dataset', record['dataset_manifest_sha256'])
    actual = {str(p.relative_to(root / 'dataset')) for p in (root / 'dataset').rglob('*') if p.is_file()}
    if actual != dataset.manifest['files'].keys() | {'manifest.json'}:
        raise CatalogueError('Unexpected files in the bundled dataset.')
    site = checked_website(root / 'site', expected_sha256=record['website_manifest_sha256'], dataset_sha256=dataset.version)
    if site['files']['NOTICE.md']['sha256'] != record['notice_sha256']:
        raise CatalogueError('Website attribution differs from the reviewed distribution.')
    return dataset, {**record, 'deployment_version': sha256(root / 'deployment.json')}, site


def assemble_deployment(lock_path, output, *, archive=None, opener=None):
    """Network only when an exact local archive was not supplied; no source rebuild."""
    from .dataset import Dataset
    lock = read_lock(lock_path)
    with new_directory(output) as staging:
        incoming = staging / 'incoming'
        unpack_dataset(lock, incoming, archive=archive, opener=opener)
        (incoming / 'dataset').rename(staging / 'dataset')
        (incoming / 'NOTICE.md').rename(staging / 'NOTICE.md')
        shutil.rmtree(incoming)
        write_json(staging / 'dataset.lock.json', lock)
        dataset = Dataset(staging / 'dataset', lock['manifest_sha256'])
        website_digest = export_website(dataset, staging / 'site', notice=staging / 'NOTICE.md')
        record = {'schema_version': 1, 'qualification': 'review_required',
                  'dataset_manifest_sha256': dataset.version, 'website_manifest_sha256': website_digest,
                  'code_sha256': code_digest(), 'lock_sha256': sha256(staging / 'dataset.lock.json'),
                  'notice_sha256': sha256(staging / 'NOTICE.md')}
        write_json(staging / 'deployment.json', record)
        # Build artifacts are public reference data and readable by the unprivileged
        # serving user. Never grant write access to other users.
        for path in staging.rglob('*'): path.chmod(0o755 if path.is_dir() else 0o644)
        staging.chmod(0o755)
        checked_website(staging / 'site', expected_sha256=website_digest, dataset_sha256=dataset.version)
    return {**record, 'output': str(output), 'deployment_version': sha256(Path(output) / 'deployment.json')}
