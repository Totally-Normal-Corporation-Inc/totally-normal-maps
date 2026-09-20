"""Public, display-only website derived from the same verified API dataset."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3

from shapely.geometry import shape
from shapely import get_num_coordinates

from .catalogue import CatalogueError, PROVINCES, ROOT, new_directory, read_json, sha256, write_json
from .releases import MAX_FILE_BYTES, MAX_MANIFEST_BYTES, MAX_RELEASE_BYTES, HEX
from .layers import layer_inventory

WEB_ASSETS = {'index.html', 'preview.js', 'preview.css', 'leaflet.js', 'leaflet.css',
              'leaflet-LICENSE.txt', 'NOTICE.md'}
IMAGE_ASSETS = {'images/' + name for name in ('layers-2x.png', 'layers.png', 'marker-icon-2x.png', 'marker-icon.png', 'marker-shadow.png')}
GEO_ASSETS = {'provinces.geojson', *(p + '.geojson' for p in PROVINCES), *('municipal-' + p + '.geojson' for p in PROVINCES),
              *('regions-' + p + '.geojson' for p in PROVINCES), *('city-areas-' + p + '.geojson' for p in PROVINCES), *('electoral-' + p + '.geojson' for p in PROVINCES)}
PUBLIC_ASSETS = WEB_ASSETS | IMAGE_ASSETS | GEO_ASSETS | {'catalogue.json'}


def website_catalogue(dataset):
    """Expose selected geographic metadata, never database contents or full shapes."""
    ids = {uid: original for (_, original), uid in dataset.source_ids.items()}
    for province in PROVINCES:
        ids['ca-' + PROVINCES[province][0].lower()] = province
    # Source keys and original vertex counts are display metadata absent from the
    # API's normalized areas. Read only those fields from the already checked DB.
    details = {}
    # The overview has its own display-only provenance and repair warnings.
    for feature in read_json(dataset.root / 'display/provinces.geojson')['features']:
        properties = feature['properties']
        details['ca-' + PROVINCES[properties['id']][0].lower()] = {
            k: properties[k] for k in ('display_reference_year', 'repair', 'issues', 'assignment_status') if k in properties}
    with closing(sqlite3.connect((dataset.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
        for table in ('csd', 'city_area'):
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone(): continue
            for uid, record in db.execute('SELECT id, record FROM ' + table):
                original = json.loads(record)
                details['ca-csd-' + uid if table == 'csd' else uid] = {
                    k: original[k] for k in ('source', 'vertices') if k in original}
    groups = {'provinces': [], 'regions': [], 'areas': [], 'city_areas': [], 'electoral_areas': []}
    for uid, area in sorted(dataset.areas.items()):
        level = area['level']
        if level == 'country': continue
        province = area['source_id'] if level == 'province' else ids[area['province_id']]
        row = {k: area[k] for k in ('name', 'source_id', 'kind', 'assignment_status', 'aliases', 'issues',
               'bbox', 'evidence', 'coverage_note', 'coverage_policy', 'boundary_basis', 'parent_overlap',
               'scheme', 'repair', 'lifecycle_status', 'valid_to', 'successor_ids', 'predecessor_ids',
               'effective_date', 'update_status', 'comparison', 'uncertainty_basis', 'layer', 'edition',
               'boundary_set', 'authority', 'electoral_event', 'edition_status', 'source', 'identity_basis', 'catalogue_code',
               'authority_id', 'authority_name', 'source_date') if k in area}
        if row.get('authority_id'): row['authority_id'] = ids[row['authority_id']]
        row.update(details.get(uid, {}))
        if level != 'province' and uid in dataset.geometries:
            row['vertices'] = int(get_num_coordinates(dataset.geometries[uid]))
        row.update(id=ids[uid], province=province, code=PROVINCES[province][0], level=level,
                   type=area.get('source_type') or area['kind'].replace('_', ' ').title())
        if level == 'province':
            row.update(count=sum(a['level'] == 'municipality' and a.get('province_id') == uid and a.get('lifecycle_status') != 'superseded'
                                 for a in dataset.areas.values()), bbox=list(shape(dataset.displays[uid]).bounds))
        elif level == 'municipality':
            parent = dataset.areas[area['parent_id']]
            row['region_id'] = parent['id'] if parent['level'] == 'region' else None
        elif level == 'region':
            row['member_count'] = area['child_count']
        elif level == 'city_area':
            city = dataset.areas[area['municipality_id']]
            row.update(parent_csd_id=ids[city['id']], parent_name=city['name'],
                       region_id=city['parent_id'] if dataset.areas[city['parent_id']]['level'] == 'region' else None)
            if dataset.areas[area['parent_id']]['level'] == 'city_area': row['parent_area_id'] = area['parent_id']
            if area['assignment_status'] == 'missing_geometry': row['geometry_status'] = 'unavailable'
        groups[{'province': 'provinces', 'region': 'regions', 'municipality': 'areas', 'city_area': 'city_areas', 'electoral_district': 'electoral_areas'}[level]].append(row)
    report = dict(dataset.report)
    if 'electoral' in report:
        report['electoral'] = {**report['electoral'], 'edition_coverage': dataset.edition_coverage,
                              'coverage': {layer['id']: layer['coverage'] for layer in layer_inventory(dataset)
                                           if layer['id'] in {'federal', 'provincial'}}}
    if 'municipal_elections' in report:
        part = report['municipal_elections']
        report['municipal_elections'] = {**part,
            'editions': [{**e, 'authority_id': ids[e['authority_id']]} for e in part['editions']],
            'coverage': {ids[uid]: {**r, 'authority_id': ids[uid]} for uid,r in part['coverage'].items()}}
    return {**groups, 'dataset_version': dataset.version, 'report': report}


def export_website(dataset, output, *, notice):
    with new_directory(output) as staging:
        for name in ('index.html', 'preview.js', 'preview.css'):
            shutil.copyfile(ROOT / 'web' / name, staging / name)
        for name in ('leaflet.js', 'leaflet.css'):
            shutil.copyfile(ROOT / 'vendor/leaflet' / name, staging / name)
        shutil.copyfile(ROOT / 'vendor/leaflet/LICENSE', staging / 'leaflet-LICENSE.txt')
        (staging / 'images').mkdir()
        for name in IMAGE_ASSETS:
            shutil.copyfile(ROOT / 'vendor/leaflet' / name, staging / name)
        shutil.copyfile(notice, staging / 'NOTICE.md')
        for name in dataset.manifest['files']:
            if name.startswith('display/'):
                shutil.copyfile(dataset.root / name, staging / Path(name).name)
        write_json(staging / 'catalogue.json', website_catalogue(dataset))
        files = {str(p.relative_to(staging)): {'sha256': sha256(p), 'bytes': p.stat().st_size}
                 for p in sorted(staging.rglob('*')) if p.is_file()}
        write_json(staging / 'site-manifest.json', {'schema_version': 1, 'dataset_manifest_sha256': dataset.version, 'files': files})
    return sha256(Path(output) / 'site-manifest.json')


def checked_website(path, *, expected_sha256, dataset_sha256):
    root = Path(path)
    manifest_path = root / 'site-manifest.json'
    if (root.is_symlink() or not root.is_dir() or manifest_path.is_symlink()
            or sha256(manifest_path) != expected_sha256):
        raise CatalogueError('Website differs from the deployment manifest.')
    manifest = read_json(manifest_path, MAX_MANIFEST_BYTES)
    files = manifest.get('files', {})
    if (manifest.get('schema_version') != 1 or manifest.get('dataset_manifest_sha256') != dataset_sha256
            or not isinstance(files, dict) or not (WEB_ASSETS | IMAGE_ASSETS | {'catalogue.json', 'provinces.geojson'}) <= files.keys()
            or files.keys() - PUBLIC_ASSETS):
        raise CatalogueError('Invalid website inventory or dataset version.')
    if any(p.is_symlink() for p in root.rglob('*')):
        raise CatalogueError('Website cannot contain symlinks.')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual != files.keys() | {'site-manifest.json'}:
        raise CatalogueError('Website contains unexpected or missing files.')
    total = 0
    for name, spec in files.items():
        file = root / name
        if (not isinstance(spec, dict) or type(spec.get('bytes')) is not int or not 0 < spec['bytes'] <= MAX_FILE_BYTES
                or not isinstance(spec.get('sha256'), str) or HEX.fullmatch(spec['sha256']) is None
                or file.stat().st_size != spec['bytes'] or sha256(file) != spec['sha256']):
            raise CatalogueError('Website file failed integrity verification.')
        total += spec['bytes']
    if total > MAX_RELEASE_BYTES:
        raise CatalogueError('Website exceeds its byte budget.')
    catalogue = read_json(root / 'catalogue.json', MAX_FILE_BYTES)
    if catalogue.get('dataset_version') != dataset_sha256:
        raise CatalogueError('Website catalogue belongs to another dataset.')
    return manifest
