"""Immutable, checksummed serving releases and optional S3 downloads.

Source archives, local reports and consumer inventories are not serving artifacts.
The manifest hash is the external trust anchor; hashes alone do not establish trust.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from urllib.parse import urlsplit

from .catalogue import CatalogueError, PROVINCES, new_directory, open_catalogue, read_json, sha256, write_json

MAX_RELEASE_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_FILES = 100
HEX = re.compile(r'[0-9a-f]{64}')


def allowed_file(name):
    return (name in {'catalogue.sqlite3', 'report.json'} or
            isinstance(name, str) and re.fullmatch(r'display/[a-zA-Z0-9_-]{1,80}\.geojson', name) is not None)


def validate_manifest(manifest):
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != 1
            or manifest.get('country') != 'CA' or manifest.get('qualification') != 'review_required'
            or not isinstance(manifest.get('label'), str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', manifest['label'])):
        raise CatalogueError('Unsupported serving manifest or qualification state.')
    entries = manifest.get('files')
    if not isinstance(entries, dict) or not 3 <= len(entries) <= MAX_FILES:
        raise CatalogueError('Invalid serving manifest file list.')
    if not {'catalogue.sqlite3', 'report.json', 'display/provinces.geojson'} <= entries.keys():
        raise CatalogueError('Serving release lacks required files.')
    total = 0
    for name, item in entries.items():
        if (not allowed_file(name) or not isinstance(item, dict)
                or type(item.get('bytes')) is not int or not 0 < item['bytes'] <= MAX_FILE_BYTES
                or not isinstance(item.get('sha256'), str) or HEX.fullmatch(item['sha256']) is None):
            raise CatalogueError('Invalid serving artifact entry.')
        total += item['bytes']
    if total > MAX_RELEASE_BYTES:
        raise CatalogueError('Serving release exceeds its byte budget.')
    return manifest


def checked_release(root, expected_sha256=None):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise CatalogueError('Expected a real serving release directory.')
    root = root.resolve()
    manifest_path = root / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CatalogueError('Missing serving manifest.')
    if expected_sha256 is not None and (HEX.fullmatch(expected_sha256) is None or sha256(manifest_path) != expected_sha256):
        raise CatalogueError('Serving manifest differs from the pinned digest.')
    manifest = validate_manifest(read_json(manifest_path, MAX_MANIFEST_BYTES))
    for name, item in manifest['files'].items():
        path = root / name
        if (any(part.is_symlink() for part in [path, *path.parents] if part != root.parent)
                or not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']):
            raise CatalogueError('Serving artifact failed integrity validation.')
    return root, manifest, sha256(manifest_path)


def source_metadata(source):
    metadata = {key: source[key] for key in ('authority', 'family', 'release', 'reference_date',
                'retrieved_at', 'retrieved_on', 'url', 'dataset_url', 'licence', 'sha256', 'scope', 'attribution_statement') if key in source}
    if source.get('authority') == 'Statistics Canada':
        metadata['attribution'] = (f"Adapted from Statistics Canada, {source['family']}, {source['reference_date']}. "
                                   'This does not constitute an endorsement by Statistics Canada of this product.')
    else:
        metadata['attribution'] = f"Source: {source.get('authority', 'See source URL')}, {source.get('release', '')}. No publisher endorsement is implied."
    if source.get('attribution_statement'):
        metadata['attribution'] += ' ' + source['attribution_statement']
    if source.get('authority') == 'City of Toronto':
        metadata['attribution'] += ' Contains information licensed under the Open Government Licence – Toronto.'
    elif source.get('authority') == 'County of Grey':
        metadata['attribution'] += ' Contains information licensed under the Grey County Open Data Licence.'
    elif source.get('authority') == 'Land Information Ontario':
        metadata['attribution'] += ' Contains information licensed under the Open Government Licence – Ontario.'
    metadata['modifications'] = ('Reference geography adapted for this catalogue: coordinate transformation, '
                                'regional aggregation where applicable, and separate simplified display boundaries. '
                                'Unapproved repairs remain labelled and excluded from normal coordinate matches.')
    return metadata


def serving_report(report):
    """Explicit public metadata projection; never copy arbitrary operator reports."""
    output = {key: report[key] for key in ('schema_version', 'catalogue_sha256', 'identity_sha256',
              'feature_count', 'valid_geometry_count', 'repair_candidate_count', 'province_counts')}
    output.update(state='review_required', source=source_metadata(report['source']),
                  qualification={'geometry_validation': report['qualification']['geometry_validation'],
                                 'topology_gaps_overlaps': report['qualification']['topology_gaps_overlaps'],
                                 'production_approval': 'not_evaluated'})
    if 'province_display_source' in report:
        output['province_display_source'] = source_metadata(report['province_display_source'])
    if 'regions' in report:
        part = report['regions']
        output['regions'] = {key: part[key] for key in ('feature_count', 'province_counts', 'jurisdictions',
            'geometry_status_counts', 'membership_count', 'unassigned_member_count', 'outline_method')}
        output['regions']['sources'] = [source_metadata(s) for s in part['sources']]
    if 'city_areas' in report:
        part = report['city_areas']
        output['city_areas'] = {key: part[key] for key in ('feature_count', 'municipality_count',
            'kind_counts', 'municipalities', 'display_tolerance_metres')}
        output['city_areas']['sources'] = {key: source_metadata(s) for key, s in part['sources'].items()}
    if 'quebec_refresh' in report:
        part = report['quebec_refresh']
        output['quebec_refresh'] = {key: part[key] for key in ('reviewed_on', 'state',
            'added_municipality_count', 'superseded_municipality_count', 'active_municipality_count',
            'mergers', 'names', 'coverage', 'unresolved', 'repair_review')}
        output['quebec_refresh']['sources'] = {key: source_metadata(s) for key, s in part['sources'].items()}
    if 'ontario_refresh' in report:
        part = report['ontario_refresh']
        output['ontario_refresh'] = {key: part[key] for key in ('reviewed_on', 'state', 'adjustments',
            'updated_municipality_count', 'updated_region_count', 'added_city_area_count', 'coverage', 'names', 'repair_review', 'unresolved')}
        output['ontario_refresh']['sources'] = {key: source_metadata(s) for key, s in part['sources'].items()}
        for key in ('deferred_adjustments', 'deferred_municipality_count'):
            if key in part:
                output['ontario_refresh'][key] = part[key]
    if 'jurisdiction_refreshes' in report:
        output['jurisdiction_refreshes'] = {}
        for province, part in report['jurisdiction_refreshes'].items():
            output['jurisdiction_refreshes'][province] = {key: part[key] for key in (
                'reviewed_on', 'state', 'adjustments', 'deferred_adjustments', 'deferred_municipality_count',
                'updated_municipality_count', 'updated_region_count', 'added_city_area_count',
                'coverage', 'names', 'repair_review', 'unresolved', 'audit')}
            output['jurisdiction_refreshes'][province]['sources'] = {key: source_metadata(s) for key, s in part['sources'].items()}
            if 'migrations' in part:
                output['jurisdiction_refreshes'][province]['migrations'] = {key: part['migrations'][key] for key in (
                    'mergers', 'deferred_mergers', 'membership_updates', 'region_updates', 'city_parent_updates',
                    'added_municipality_count', 'superseded_municipality_count', 'added_region_count',
                    'retired_region_count', 'revised_region_ids', 'regional_coverage')}
    return output


def export_release(run, output, *, label='canada-review'):
    run = Path(run).resolve()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', label):
        raise CatalogueError('Release label must be 1–80 letters, digits, dots, underscores or hyphens.')
    if Path(output).resolve().is_relative_to(run):
        raise CatalogueError('Serving output must be outside the source run.')
    report = read_json(run / 'report.json')
    with open_catalogue(run) as db:
        tables = {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'csd' not in tables or tables - {'csd', 'region', 'csd_region', 'city_area', 'area_revision', 'boundary_revision', 'jurisdiction_revision'}:
            raise CatalogueError('Only reference-geography tables may enter a serving release.')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise CatalogueError('Catalogue failed database integrity checks.')
    names = ['provinces.geojson'] + [f'{p}.geojson' for p in PROVINCES]
    if 'regions' in report:
        names += [f'regions-{p}.geojson' for p in PROVINCES]
    if 'city_areas' in report:
        with open_catalogue(run) as db:
            city_provinces = {json.loads(r['record'])['province'] for r in db.execute('SELECT record FROM city_area')}
        names += ['city-areas-' + p + '.geojson' for p in sorted(city_provinces)]
    with new_directory(output) as staging:
        (staging / 'display').mkdir()
        shutil.copyfile(run / 'catalogue.sqlite3', staging / 'catalogue.sqlite3')
        if sha256(staging / 'catalogue.sqlite3') != report['catalogue_sha256']:
            raise CatalogueError('Catalogue changed while exporting.')
        write_json(staging / 'report.json', serving_report(report))
        for name in names:
            source = run / 'preview' / name
            if source.is_symlink() or source.stat().st_size > MAX_FILE_BYTES:
                raise CatalogueError('Invalid display artifact.')
            # Strip arbitrary display properties; metadata is loaded from the checked DB.
            payload = read_json(source, MAX_FILE_BYTES)
            if payload.get('type') != 'FeatureCollection' or not isinstance(payload.get('features'), list):
                raise CatalogueError('Invalid display collection.')
            features = []
            for feature in payload['features']:
                props = feature['properties']
                properties = {key: props[key] for key in ('id', 'assignment_status') if key in props}
                features.append({'type': 'Feature', 'properties': properties, 'geometry': feature['geometry']})
            write_json(staging / 'display' / name, {'type': 'FeatureCollection', 'features': features})
        files = {str(p.relative_to(staging)): {'bytes': p.stat().st_size, 'sha256': sha256(p)}
                 for p in sorted(staging.rglob('*')) if p.is_file()}
        manifest = {'schema_version': 1, 'label': label, 'country': 'CA',
                    'qualification': 'review_required', 'files': files}
        validate_manifest(manifest)
        write_json(staging / 'manifest.json', manifest)
        checked_release(staging)
    return {'output': str(output), 'manifest_sha256': sha256(Path(output) / 'manifest.json'),
            'file_count': len(files), 'bytes': sum(v['bytes'] for v in files.values()),
            'qualification': 'review_required'}


def fetch_s3(uri, destination, *, expected_sha256, client=None):
    """Download an operator-selected release. Never accepts HTTP request input.

    Uses normal AWS SDK credentials (task role in production). Requires no write
    permission. A trusted manifest digest is mandatory, even for a private bucket.
    """
    parsed = urlsplit(uri)
    if (parsed.scheme != 's3' or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', parsed.netloc)
            or parsed.query or parsed.fragment or not parsed.path.endswith('/manifest.json')
            or not isinstance(expected_sha256, str) or HEX.fullmatch(expected_sha256) is None):
        raise CatalogueError('Use an s3://bucket/prefix/manifest.json URI and a pinned SHA-256.')
    if client is None:
        import boto3
        from botocore.config import Config
        client = boto3.client('s3', config=Config(connect_timeout=10, read_timeout=30,
                                                retries={'max_attempts': 3, 'mode': 'standard'}))
    key = parsed.path.lstrip('/')
    prefix = key.rsplit('/', 1)[0]

    def download(object_key, path, limit, expected_size=None):
        result = client.get_object(Bucket=parsed.netloc, Key=object_key)
        with closing(result['Body']) as stream:
            if result['ContentLength'] > limit or (expected_size is not None and result['ContentLength'] != expected_size):
                raise CatalogueError('S3 object size differs from the release manifest.')
            size = 0
            with path.open('xb') as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise CatalogueError('S3 download exceeded its byte budget.')
                    output.write(chunk)
            if size != result['ContentLength']:
                raise CatalogueError('Incomplete S3 object.')

    with new_directory(destination) as staging:
        download(key, staging / 'manifest.json', MAX_MANIFEST_BYTES)
        if sha256(staging / 'manifest.json') != expected_sha256:
            raise CatalogueError('S3 manifest differs from the trusted digest.')
        manifest = validate_manifest(read_json(staging / 'manifest.json', MAX_MANIFEST_BYTES))
        for name, spec in manifest['files'].items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            download(f'{prefix}/{name}', path, spec['bytes'], spec['bytes'])
        checked_release(staging, expected_sha256)
    return {'output': str(destination), 'manifest_sha256': expected_sha256}
