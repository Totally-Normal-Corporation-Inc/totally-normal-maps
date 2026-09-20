"""Pinned, offline electoral imports into a new immutable serving release."""
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Integral
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from zipfile import ZipFile

import pyogrio
from pyogrio.raw import read
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
import shapely
from shapely.geometry import mapping
from shapely.ops import transform
from shapely.strtree import STRtree

from .catalogue import (CatalogueError, PROVINCES, ROOT, geometry_issue, identity_digest,
                        new_directory, propose_repair, read_json, sha256, write_json)
from .layers import (validate_editions, derive_edition_coverage, selection_coverage,
                     public_url, valid_date, TOKEN)
from .releases import checked_release, MAX_FILE_BYTES, source_metadata, validate_manifest

PLAN = ROOT / 'electoral-2026-09.json'


@dataclass(frozen=True)
class SourceArea:
    code: str
    source_id: str
    name: str
    province: str
    aliases: list[str]
    geometry: shapely.Geometry | None
    source_issue: str | None


def electoral_source_metadata(source):
    return {**source_metadata(source), 'source_spec_sha256': hashlib.sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()}


def validate_source(source):
    if not isinstance(source, dict): raise CatalogueError('Invalid electoral source specification.')
    strings = ('filename', 'sha256', 'identity_sha256', 'id_field', 'name_field', 'crs', 'authority')
    if any(not isinstance(source.get(key), str) or not source[key].strip() for key in strings):
        raise CatalogueError('Incomplete electoral source specification.')
    if (Path(source['filename']).name != source['filename'] or source['filename'] in {'.', '..'}
            or any(not re.fullmatch(r'[0-9a-f]{64}', source[key]) for key in ('sha256', 'identity_sha256'))
            or type(source.get('expected_count')) is not int or not 1 <= source['expected_count'] <= 10000
            or type(source.get('province_from_code', False)) is not bool):
        raise CatalogueError('Invalid electoral source identity, filename or count.')
    counts, excluded = source.get('province_counts'), source.get('exclude_ids', [])
    if (not isinstance(counts, dict) or not counts or counts.keys() - PROVINCES.keys()
            or any(type(n) is not int or n <= 0 for n in counts.values())
            or not isinstance(excluded, list) or any(not isinstance(v, str) or not v for v in excluded)
            or len(set(excluded)) != len(excluded)
            or sum(counts.values()) + len(excluded) != source['expected_count']
            or excluded and not source.get('exclusion_evidence')
            or not source.get('province_from_code') and (not isinstance(source.get('province'), str)
                                                        or set(counts) != {source['province']})):
        raise CatalogueError('Invalid electoral source province or exclusion inventory.')
    aliases, identities = source.get('alias_fields', []), source.get('identity_map', {})
    if (not isinstance(aliases, list) or any(not isinstance(v, str) or not v for v in aliases)
            or len(set(aliases)) != len(aliases) or not isinstance(identities, dict)
            or any(not isinstance(k, str) or not k or not isinstance(v, str)
                   or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', v) for k, v in identities.items())
            or not isinstance(source.get('id_prefix', ''), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{0,20}', source.get('id_prefix', ''))
            or 'id_width' in source and (type(source['id_width']) is not int or not 1 <= source['id_width'] <= 30)
            or any(key in source and not isinstance(source[key], str) for key in ('member', 'archive_member', 'layer_name'))):
        raise CatalogueError('Invalid electoral source fields or identity mapping.')
    if (not public_url(source.get('licence')) or not isinstance(source.get('redistribution_status'), str)
            or source['redistribution_status'] not in {'permitted', 'unconfirmed'}):
        raise CatalogueError('Electoral source requires explicit reuse evidence.')
    try:
        CRS(source['crs'])
    except CRSError:
        raise CatalogueError('Invalid electoral source coordinate reference system.') from None


def source_uri(path, source):
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES
            or sha256(path) != source['sha256']):
        raise CatalogueError('Electoral source differs from its pinned checksum.')
    member = source.get('archive_member') or source.get('member')
    if not member: return str(path.resolve())
    components = PurePosixPath(member)
    if components.is_absolute() or '..' in components.parts or '\\' in member:
        raise CatalogueError('Unsafe electoral archive member.')
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (sum(e.file_size for e in entries) > MAX_FILE_BYTES or any(e.flag_bits & 1 for e in entries)
                or len({e.filename for e in entries}) != len(entries) or member not in archive.namelist()):
            raise CatalogueError('Invalid or oversized electoral archive.')
        if source.get('archive_member'):
            import io
            content = archive.read(member)
            with ZipFile(io.BytesIO(content)) as inner:
                if sum(e.file_size for e in inner.infolist()) > MAX_FILE_BYTES:
                    raise CatalogueError('Nested electoral archive exceeds its byte budget.')
                if len([n for n in inner.namelist() if n.endswith('.shp')]) != 1:
                    raise CatalogueError('Expected a single nested electoral shapefile.')
            return content
    return f'/vsizip/{path.resolve()}/{member}'


def read_source(path, source):
    validate_source(source)
    uri = source_uri(path, source)
    info = pyogrio.read_info(uri, layer=source.get('layer_name'))
    if (info['features'] != source['expected_count'] or not info['crs']
            or not CRS(info['crs']).equals(CRS(source['crs']))):
        raise CatalogueError('Electoral source count or CRS changed.')
    meta, _, geometries, columns = read(uri, layer=source.get('layer_name'))
    fields = list(meta['fields'])
    required = [source['id_field'], source['name_field'], *source.get('alias_fields', [])]
    if not set(required) <= set(fields): raise CatalogueError('Electoral source attributes changed.')
    to_wgs = Transformer.from_crs(source['crs'], 4326, always_xy=True)
    if source.get('coordinate_operation'):
        from pyproj.transformer import TransformerGroup
        operation = source['coordinate_operation']
        choices = [t for t in TransformerGroup(source['crs'], 4326, always_xy=True).transformers
                   if any(op.to_json_dict().get('id') == {'authority': 'EPSG', 'code': operation['epsg']}
                          for op in t.operations)]
        if len(choices) != 1 or choices[0].accuracy != operation['accuracy_metres'] or not operation.get('evidence'):
            raise CatalogueError('Pinned electoral coordinate operation is unavailable or changed.')
        to_wgs = choices[0]
    output, identities, raw_ids = [], [], []
    for i, raw in enumerate(geometries):
        props = {str(k): c[i] for k, c in zip(fields, columns)}
        identifier = props[source['id_field']]
        if isinstance(identifier, bool) or not isinstance(identifier, (str, Integral)):
            raise CatalogueError('Missing or invalid publisher electoral identity.')
        raw_id = str(identifier).strip()
        if not raw_id: raise CatalogueError('Missing publisher electoral identity.')
        if raw_id in source.get('exclude_ids', []):
            if not source.get('exclusion_evidence'): raise CatalogueError('Excluded source features require evidence.')
            continue
        raw_ids.append(raw_id)
        if 'identity_map' in source and raw_id not in source['identity_map']:
            raise CatalogueError('Publisher identity is absent from the pinned identity mapping.')
        code = source.get('identity_map', {}).get(raw_id, raw_id)
        if source.get('id_width'): code = code.zfill(source['id_width'])
        code = source.get('id_prefix', '') + code
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', code):
            raise CatalogueError('Invalid official electoral identity.')
        name = props[source['name_field']]
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise CatalogueError('Invalid electoral district name.')
        name = name.strip()
        province = code[:2] if source.get('province_from_code') else source['province']
        if province not in PROVINCES: raise CatalogueError('Invalid electoral province membership.')
        geometry = shapely.from_wkb(raw) if raw is not None else None
        source_issue = geometry_issue(geometry)
        if geometry is not None and geometry.is_empty: geometry = None
        if geometry is not None:
            if shapely.get_num_coordinates(geometry) > 3_000_000:
                raise CatalogueError('Electoral feature exceeds its vertex budget.')
            geometry = transform(to_wgs.transform, geometry)
            if not all(math.isfinite(v) for v in shapely.get_coordinates(geometry).ravel()):
                raise CatalogueError('Nonfinite electoral coordinates.')
            w, s, e, n = geometry.bounds
            if not (-142.5 <= w <= e <= -50 and 40 <= s <= n <= 90):
                raise CatalogueError('Electoral source lies outside the Canadian extent.')
        identities.append(code)
        aliases = []
        for key in source.get('alias_fields', []):
            value = props[key]
            if value is None: continue
            if not isinstance(value, str) or len(value) > 200:
                raise CatalogueError('Invalid electoral district alias.')
            if value.strip() and value.strip() != name: aliases.append(value.strip())
        output.append(SourceArea(code, raw_id, name, province, aliases, geometry, source_issue))
    if len(set(identities)) != len(identities) or identity_digest(identities) != source['identity_sha256']:
        raise CatalogueError('Electoral identity inventory differs from the pinned source.')
    if 'identity_map' in source and set(raw_ids) != set(source['identity_map']):
        raise CatalogueError('Pinned identity mapping contains absent publisher identities.')
    if dict(Counter(row.province for row in output)) != source['province_counts']:
        raise CatalogueError('Electoral provincial membership counts changed.')
    return output


def build_electoral(dataset, source_dir, output, *, plan_path=None, tolerance=100):
    """Retain previous editions, rejecting replacement of an existing edition."""
    from .dataset import Dataset
    base = Dataset(dataset)
    if Path(output).resolve().is_relative_to(base.root):
        raise CatalogueError('Electoral output must be outside the immutable source release.')
    plan = read_json(plan_path or PLAN)
    if (not isinstance(plan, dict) or type(plan.get('schema_version')) is not int or plan['schema_version'] != 1
            or not isinstance(plan.get('sources'), dict) or len(plan['sources']) > 100):
        raise CatalogueError('Invalid electoral import plan.')
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 500:
        raise CatalogueError('Electoral display tolerance must be 0–500 metres.')
    if not valid_date(plan.get('reviewed_on')): raise CatalogueError('Invalid electoral review date.')
    if not isinstance(plan.get('editions', []), list): raise CatalogueError('Invalid electoral edition inventory.')
    editions = validate_editions(plan['editions']) if plan.get('editions') else []
    updates = plan.get('edition_updates', [])
    if (not isinstance(updates, list) or len(updates) > 100 or not (editions or updates)):
        raise CatalogueError('Expected new electoral editions or evidenced metadata updates.')
    old = base.report.get('electoral', {})
    for key, source in plan['sources'].items():
        validate_source(source)
        if key in old.get('sources', {}):
            previous_source = old['sources'][key]
            candidate = electoral_source_metadata(source)
            if 'source_spec_sha256' not in previous_source:
                raise CatalogueError('Earlier release lacks a complete source specification pin; use a new source key.')
            if previous_source != candidate:
                raise CatalogueError('A changed source requires a new source key; preserve earlier edition provenance.')
    if set(base.editions) & {e['id'] for e in editions}:
        raise CatalogueError('An electoral edition already exists; do not overwrite immutable boundaries.')
    revised, seen = {}, set()
    for update in updates:
        fields = {'id', 'status', 'default', 'label', 'electoral_event', 'effective_date', 'valid_to', 'evidence_url'}
        if (not isinstance(update, dict) or update.keys() - fields or not public_url(update.get('evidence_url'))
                or not isinstance(update.get('id'), str) or update['id'] not in base.editions or update['id'] in seen):
            raise CatalogueError('Edition updates require a unique existing ID and public evidence.')
        uid = update['id']; seen.add(uid)
        revised[uid] = {**base.editions[uid], **update}
    # A new default supersedes the prior default selection, preserving its records.
    replacements = [*editions, *revised.values()]
    replace_defaults = {(e['layer'], p) for e in replacements if e['default'] for p in e['provinces']}
    previous = []
    for e in old.get('editions', []):
        if e['id'] in revised:
            previous.append(revised[e['id']]); continue
        overlaps = ({(e['layer'], p) for p in e['provinces']} & replace_defaults) if e['default'] else set()
        if overlaps and len(overlaps) != len(e['provinces']):
            raise CatalogueError('Cannot partially replace a national default edition.')
        previous.append({**e, **({'default': False} if overlaps else {})})
    all_editions = validate_editions(previous + editions)
    projected = Transformer.from_crs(4326, 3347, always_xy=True)
    inverse = Transformer.from_crs(3347, 4326, always_xy=True)
    records, features, topology = [], defaultdict(list), {}
    loaded = {}
    for key, source in plan['sources'].items():
        filename = source.get('filename', '')
        if not TOKEN.fullmatch(key) or Path(filename).name != filename or not filename:
            raise CatalogueError('Invalid electoral source filename.')
        if (not public_url(source.get('licence')) or source.get('redistribution_status') not in {'permitted', 'unconfirmed'}):
            raise CatalogueError('Electoral source requires explicit reuse evidence.')
        loaded[key] = read_source(Path(source_dir) / filename, source)
    for edition in editions:
        rows, shapes = [], []
        for key in edition['sources']:
            if key not in loaded: raise CatalogueError('Edition references an unknown source.')
            source = plan['sources'][key]
            for item in loaded[key]:
                code, name, province, aliases, full = item.code, item.name, item.province, item.aliases, item.geometry
                if province not in edition['provinces']: raise CatalogueError('Edition province mismatch.')
                uid = f"ca-{edition['id']}-{code.lower()}"
                if len(uid) > 100: raise CatalogueError('Electoral ID exceeds the API limit.')
                parent = 'ca-' + PROVINCES[province][0].lower()
                row = {'id': uid, 'source_id': item.source_id, 'catalogue_code': code,
                       'identity_basis': source.get('identity_basis', 'publisher_code'), 'name': name, 'aliases': aliases,
                       'province': province, 'province_id': parent, 'parent_id': parent,
                       'level': 'electoral_district', 'kind': edition['layer'] + '_electoral_district',
                       'layer': edition['layer'], 'edition': edition['id'], 'boundary_set': edition['boundary_set'],
                       'authority': edition['authority'], 'electoral_event': edition['electoral_event'],
                       'edition_status': edition['status'], 'effective_date': edition.get('effective_date'),
                       'valid_to': edition.get('valid_to'),
                       'source': key, 'issues': [], 'assignment_status': 'validated_source',
                       'predecessor_ids': edition.get('predecessors', {}).get(code, []),
                       'relationship_evidence': edition.get('relationship_evidence', []),
                       'coordinate_operation': source.get('coordinate_operation'),
                       'source_geometry_issue': item.source_issue,
                       'bbox': list(full.bounds) if full is not None else None}
                if row['predecessor_ids'] and (not row['relationship_evidence'] or
                        len(set(row['predecessor_ids'])) != len(row['predecessor_ids']) or
                        any(p not in base.areas or base.areas[p]['level'] != 'electoral_district'
                            or base.areas[p]['layer'] != row['layer'] or base.areas[p]['province'] != province
                            for p in row['predecessor_ids'])):
                    raise CatalogueError('Electoral predecessors require existing identities and evidence.')
                problem = item.source_issue or geometry_issue(full)
                candidate = None
                if problem:
                    row['issues'].append(problem)
                    row['assignment_status'] = 'missing_geometry'
                    if full is not None and problem.startswith('invalid_geometry:'):
                        # Keep the candidate in the assignment CRS. Transforming a
                        # repaired ring back from a projection can recreate a
                        # self-intersection through floating-point rounding.
                        candidate, metrics = propose_repair(full)
                        if 'method' in metrics: metrics['method'] += ' in EPSG:4326; area measurements in EPSG:3347'
                        metrics['source_area_m2'] = transform(projected.transform, full).area
                        metrics['candidate_area_m2'] = transform(projected.transform, candidate).area if candidate is not None else None
                        metrics['area_change_m2'] = (metrics['candidate_area_m2'] - metrics['source_area_m2']
                                                     if candidate is not None else None)
                        row['repair'] = metrics
                        if candidate is not None:
                            if geometry_issue(candidate): candidate = None
                        if candidate is not None: row['assignment_status'] = 'unreviewed_repair'
                    full = None
                display_base = full if full is not None else candidate
                features.setdefault(province, [])
                if display_base is not None:
                    display = transform(inverse.transform, transform(projected.transform, display_base).simplify(tolerance, preserve_topology=True))
                    if geometry_issue(display): display = display_base
                    features[province].append({'type': 'Feature', 'properties': {'id': uid,
                        'assignment_status': row['assignment_status']}, 'geometry': mapping(display)})
                rows.append(row)
                if full is not None: shapes.append((uid, full))
                records.append((uid, json.dumps(row, ensure_ascii=False), full.wkb if full is not None else None,
                                candidate.wkb if candidate is not None else None))
        if len({r['id'] for r in rows}) != len(rows) or len(rows) != edition['expected_count']:
            raise CatalogueError('Duplicate electoral identity or incomplete edition.')
        tree = STRtree([g for _, g in shapes])
        overlaps = []
        for i, (uid, geom) in enumerate(shapes):
            for j in tree.query(geom, predicate='intersects'):
                if int(j) <= i: continue
                other, other_geom = shapes[int(j)]
                intersection = geom.intersection(other_geom)
                if intersection.area > 0:
                    area_m2 = transform(projected.transform, intersection).area
                    if area_m2 > 1:
                        overlaps.append({'ids': [uid, other], 'area_m2': round(area_m2, 3)})
        topology[edition['id']] = {'overlaps': overlaps, 'overlap_threshold_m2': 1,
            'unavailable_count': sum(r['assignment_status'] != 'validated_source' for r in rows),
            'gap_validation': 'No independent authoritative jurisdiction envelope supplied; no clipping or gap filling performed.',
            'representative_points_checked': 0, 'representative_points_passed': False}
    with new_directory(output) as staging:
        for name in base.manifest['files']:
            path = staging / name; path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base.root / name, path)
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS electoral_area (id TEXT PRIMARY KEY, record TEXT NOT NULL, geometry BLOB, repair_candidate BLOB)')
            db.executemany('INSERT INTO electoral_area VALUES (?, ?, ?, ?)', records)
            # Update edition metadata only. Source identity and geometry blobs stay
            # byte-for-byte identical when an upcoming edition becomes current.
            for uid, serialized in db.execute('SELECT id, record FROM electoral_area').fetchall():
                row = json.loads(serialized)
                if row['edition'] not in revised: continue
                edition = revised[row['edition']]
                row.update(edition_status=edition['status'], electoral_event=edition['electoral_event'],
                           effective_date=edition.get('effective_date'), valid_to=edition.get('valid_to'))
                db.execute('UPDATE electoral_area SET record=? WHERE id=?', (json.dumps(row, ensure_ascii=False), uid))
            all_rows = [json.loads(r[0]) for r in db.execute('SELECT record FROM electoral_area')]
        for province, additions in features.items():
            path = staging / 'display' / f'electoral-{province}.geojson'
            retained = read_json(path, MAX_FILE_BYTES)['features'] if path.exists() else []
            write_json(path, {'type': 'FeatureCollection', 'features': retained + additions})
        report = dict(base.report)
        report['catalogue_sha256'] = sha256(staging / 'catalogue.sqlite3')
        declared = {uid: {p: dict(spec) for p, spec in provinces.items()} for uid, provinces in base.edition_coverage.items()}
        by_edition = {e['id']: e for e in all_editions}
        supplied = plan.get('coverage', {})
        if not isinstance(supplied, dict) or supplied.keys() - {'federal', 'provincial'}:
            raise CatalogueError('Invalid electoral layer coverage.')
        for layer, provinces in supplied.items():
            if not isinstance(provinces, dict) or provinces.keys() - PROVINCES.keys():
                raise CatalogueError('Invalid electoral coverage jurisdiction.')
            for province, spec in provinces.items():
                if not isinstance(spec, dict): raise CatalogueError('Invalid electoral coverage entry.')
                uid = spec.get('edition') or next((e['id'] for e in all_editions
                      if e['layer'] == layer and e['default'] and province in e['provinces']), None)
                if (not isinstance(uid, str) or uid not in by_edition or by_edition[uid]['layer'] != layer
                        or province not in by_edition[uid]['provinces']):
                    raise CatalogueError('Coverage refers to an unavailable or incompatible edition.')
                declared.setdefault(uid, {})[province] = spec
        inventory = derive_edition_coverage({e['id']: e for e in all_editions}, all_rows, declared)
        report['electoral'] = {'reviewed_on': plan['reviewed_on'], 'editions': all_editions,
            'import_plan_sha256': [*old.get('import_plan_sha256', []), sha256(Path(plan_path or PLAN))],
            'edition_counts': {**old.get('edition_counts', {}), **{e['id']: e['expected_count'] for e in editions}},
            'sources': {**old.get('sources', {}), **{k: {**electoral_source_metadata(s),
                       'redistribution_status': s['redistribution_status']} for k, s in plan['sources'].items()}},
            'edition_updates': [*old.get('edition_updates', []), *updates],
            'edition_coverage': inventory,
            'coverage': {layer: selection_coverage({e['id']: e for e in all_editions}, inventory,
                         {e['id'] for e in all_editions if e['layer'] == layer and e['default']})
                         for layer in ('federal', 'provincial')},
            'validation': {**old.get('validation', {}), **topology},
            'display_tolerance_metres': tolerance}
        write_json(staging / 'report.json', report)
        manifest = {**base.manifest, 'label': plan['release_label'], 'files': {
            str(p.relative_to(staging)): {'bytes': p.stat().st_size, 'sha256': sha256(p)}
            for p in sorted(staging.rglob('*')) if p.is_file()}}
        validate_manifest(manifest); write_json(staging / 'manifest.json', manifest)
        checked_release(staging)
        verified = Dataset(staging)
        for uid, _, _, _ in records:
            if uid not in verified.geometries: continue
            row = verified.areas[uid]
            point = verified.geometries[uid].representative_point()
            result = verified.lookup(point.x, point.y, layers=[row['layer']], editions={row['layer']:[row['edition']]})
            if uid not in result['direct_match_ids']:
                raise CatalogueError('Electoral representative point failed an assignment lookup.')
            topology[row['edition']]['representative_points_checked'] += 1
        for part in topology.values(): part['representative_points_passed'] = True
        write_json(staging / 'report.json', report)
        manifest['files']['report.json'] = {'bytes': (staging / 'report.json').stat().st_size,
                                          'sha256': sha256(staging / 'report.json')}
        write_json(staging / 'manifest.json', manifest)
        checked_release(staging)
    return {'output': str(output), 'manifest_sha256': sha256(Path(output) / 'manifest.json'),
            'added_districts': len(records), 'editions': [e['id'] for e in editions], 'validation': topology}
