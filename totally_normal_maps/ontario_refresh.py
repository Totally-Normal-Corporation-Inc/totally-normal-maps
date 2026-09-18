"""Offline, evidenced Ontario updates; original national rows stay immutable.

Source-family differences are uncertainty polygons, including uncovered old
extents. They never supply assignments or silently approve an existing repair.
"""
from collections import Counter
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import re
import shutil
import sqlite3

from pyproj import Transformer
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import transform

from .catalogue import (CatalogueError, ROOT, MAX_TOTAL_VERTICES, MAX_VERTICES_PER_FEATURE,
                        geometry_issue, new_directory, open_catalogue, polygon_parts,
                        propose_repair, read_json, sha256, write_json)
from .quebec_refresh import _display

PLAN = ROOT / 'ontario-refresh-2026-09.json'
MAX_BYTES = 32 * 1024 * 1024


def source_identity(props, source):
    value = props.get(source['id_field'])
    if value is None and source.get('fallback_id_field'):
        field = source['fallback_id_field']
        return field.lower() + '-' + str(props.get(field))
    return str(value)


def checked_source(path, source):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES or sha256(path) != source['sha256']:
        raise CatalogueError('Ontario source checksum or byte budget mismatch.')
    data = read_json(path, MAX_BYTES)
    crs = data.get('crs')
    if (data.get('type') != 'FeatureCollection' or data.get('exceededTransferLimit') or
            len(data.get('features', [])) != source['expected_count'] or crs != source.get('geojson_crs') or
            crs not in (None, {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
                       {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}})):
        raise CatalogueError('Incomplete Ontario source or unsupported coordinate declaration.')
    expected = {r['source_id']: r['properties'] for r in source['identities']}
    if len(expected) != source['expected_count']:
        raise CatalogueError('Duplicate planned Ontario identities.')
    result, vertices, invalid = {}, 0, set()
    for feature in data['features']:
        props = feature['properties']; uid = source_identity(props, source)
        if uid not in expected or uid in result or any(props.get(k) != v for k, v in expected[uid].items()):
            raise CatalogueError('Changed or duplicate Ontario source identity.')
        geom = shape(feature['geometry'])
        count = int(shapely.get_num_coordinates(geom)); vertices += count
        issue = geometry_issue(geom)
        if issue:
            if uid not in source.get('unapproved_invalid_ids', []) or not issue.startswith('invalid_geometry:'):
                raise CatalogueError('Unexpected invalid Ontario geometry.')
            invalid.add(uid)
        if count > MAX_VERTICES_PER_FEATURE or vertices > MAX_TOTAL_VERTICES:
            raise CatalogueError('Ontario source exceeds vertex budget.')
        west, south, east, north = geom.bounds
        if not (-96 <= west <= east <= -74 and 41 <= south <= north <= 57):
            raise CatalogueError('Source coordinates outside Ontario.')
        result[uid] = geom
    if set(result) != set(expected) or invalid != set(source.get('unapproved_invalid_ids', [])):
        raise CatalogueError('Changed Ontario source identity or repair set.')
    return result


def build_refresh(run, destination, *, source_dir, plan_path=None):
    run, source_dir = Path(run), Path(source_dir)
    plan, report = read_json(plan_path or PLAN), read_json(run / 'report.json')
    if (plan.get('schema_version') != 1 or 'ontario_refresh' in report or
            plan.get('base_source_sha256') != report['source']['sha256'] or
            plan.get('base_identity_sha256') != report['identity_sha256'] or 'city_areas' not in report):
        raise CatalogueError('Ontario plan requires a matching unmodified base.')
    if len(plan['adjustments']) > 100 or len(plan['city_layers']) > 50:
        raise CatalogueError('Ontario plan exceeds its budget.')
    for key, source in plan['sources'].items():
        if (not re.fullmatch(r'[a-z0-9-]{1,60}', key) or not source.get('authority') or
                not source.get('licence') or not source.get('evidence')):
            raise CatalogueError('Ontario source requires safe identity, licence and evidence.')
    with open_catalogue(run) as db:
        csds = {r['id']: dict(r) for r in db.execute('SELECT * FROM csd')}
        regions = {r['id']: dict(r) for r in db.execute('SELECT * FROM region')}
        membership = dict(db.execute('SELECT csd_id, region_id FROM csd_region'))
        old_areas = {r['id'] for r in db.execute('SELECT id FROM city_area')}
    forward = Transformer.from_crs(4326, 3347, always_xy=True).transform
    inverse = Transformer.from_crs(3347, 4326, always_xy=True).transform
    def metric(g): return transform(forward, g)
    def municipal(uid, name):
        if uid not in csds:
            raise CatalogueError('Unknown Ontario municipality.')
        row = json.loads(csds[uid]['record'])
        if row['province'] != '35' or row['name'] != name:
            raise CatalogueError('Changed Ontario municipal identity.')
        return row
    revisions, updated, additions, coverage = [], {}, {}, []
    with new_directory(destination) as staging:
        if any(p.is_symlink() for p in run.rglob('*')):
            raise CatalogueError('Base run contains symlinks.')
        shutil.copytree(run, staging, dirs_exist_ok=True)
        if sha256(staging / 'catalogue.sqlite3') != report['catalogue_sha256']:
            raise CatalogueError('Base catalogue changed during refresh.')
        archive = staging / 'ontario-refresh-sources'; archive.mkdir()
        write_json(archive / 'plan.json', plan)
        sources = {}
        for key, source in plan['sources'].items():
            path = source_dir / (key + '.geojson')
            checked_source(path, source)
            shutil.copyfile(path, archive / path.name)
            sources[key] = checked_source(archive / path.name, source)
        public = read_json(staging / 'preview/catalogue.json')
        displays = {name: read_json(staging / 'preview' / name) for name in ('35.geojson', 'regions-35.geojson')}
        displays['city-areas-35.geojson'] = {'type': 'FeatureCollection', 'features': []}
        def display(name, uid, geom, status):
            features = displays[name]['features']
            feature = {'type': 'Feature', 'properties': {'id': uid, 'assignment_status': status},
                       'geometry': mapping(_display(geom, forward, inverse, 20 if name.startswith('city-') else 200))}
            existing = next((f for f in features if f['properties']['id'] == uid), None)
            if existing is None: features.append(feature)
            else: existing.update(feature)
        for adjustment in plan['adjustments']:
            date.fromisoformat(adjustment['effective_date'])
            if not adjustment.get('evidence') or len(adjustment['members']) < 2:
                raise CatalogueError('Boundary adjustment lacks participants or evidence.')
            for member in adjustment['members']:
                uid = member['csd_id']; original = municipal(uid, member['name'])
                if uid in updated or csds[uid]['geometry'] is None:
                    raise CatalogueError('Cannot duplicate an update or approve a municipal repair.')
                selected = sources[member['source']]
                ids = member['source_ids']
                if not ids or len(ids) != len(set(ids)) or any(i not in selected for i in ids):
                    raise CatalogueError('Incomplete or duplicate municipal boundary parts.')
                identities = plan['sources'][member['source']]['identities']
                complete = {i['source_id'] for i in identities if str(i['properties'].get(member['group_field'])) == member['group_value']}
                if set(ids) != complete:
                    raise CatalogueError('Municipal update omits source extent parts.')
                # All source parts, including water and islands, are retained.
                geom = shapely.union_all([selected[i] for i in ids])
                if geometry_issue(geom): raise CatalogueError('Invalid updated municipal boundary.')
                old = shapely.from_wkb(csds[uid]['geometry'])
                old_metric, new_metric = metric(old), metric(geom)
                common = old_metric.intersection(new_metric).area
                if common / min(old_metric.area, new_metric.area) < .80:
                    raise CatalogueError('Municipal update fails spatial identity comparison.')
                delta = shapely.union_all(polygon_parts(old.symmetric_difference(geom)))
                review = None if delta.is_empty else delta
                row = {'id': 'ca-csd-' + uid, 'assignment_status': 'validated_source',
                       'bbox': list(geom.bounds), 'vertices': int(shapely.get_num_coordinates(geom)),
                       'boundary_basis': 'current_official_municipal_source',
                       'effective_date': adjustment['effective_date'], 'boundary_source': member['source'],
                       'boundary_source_ids': ids, 'evidence': adjustment['evidence'],
                       'previous_boundary_reference_date': report['source']['reference_date'],
                       'uncertainty_basis': 'old_new_boundary_difference',
                       'coverage_note': 'Full current publisher boundary. Original national boundary is retained in the source table and earlier release; every old/new difference requires review, including water coverage and old extents absent from the new source.',
                       'comparison': {'old_area_m2': old_metric.area, 'new_area_m2': new_metric.area,
                                      'removed_m2': old_metric.difference(new_metric).area,
                                      'added_m2': new_metric.difference(old_metric).area},
                       'issues': ['Municipal boundary source and vintage changed; old/new differences remain review uncertainty']}
                revisions.append(('boundary', row, geom, review)); updated[uid] = geom
                next(r for r in public['areas'] if r['id'] == uid).update({k: v for k, v in row.items() if k != 'id'})
                display('35.geojson', uid, geom, row['assignment_status'])
        for rid in sorted({membership[uid] for uid in updated if uid in membership}):
            members = [uid for uid, parent in membership.items() if parent == rid]
            pending = any(csds[uid]['geometry'] is None for uid in members)
            shapes = [updated[uid] if uid in updated else shapely.from_wkb(csds[uid]['geometry'] or csds[uid]['repair_candidate']) for uid in members]
            geom = shapely.union_all(shapes)
            if geometry_issue(geom): raise CatalogueError('Invalid revised regional union.')
            original = json.loads(regions[rid]['record'])
            row = {'id': rid, 'assignment_status': 'unreviewed_repair' if pending else 'validated_derived',
                   'bbox': list(geom.bounds), 'vertices': int(shapely.get_num_coordinates(geom)),
                   'boundary_basis': 'current_member_union',
                   'evidence': [e for a in plan['adjustments'] for e in a['evidence']],
                   'coverage_note': 'Complete current member union; national and newer municipal source differences require review.',
                   'issues': original.get('issues', []) + ['Mixed national and current municipal boundary sources']}
            revisions.append(('region', row, None if pending else geom, geom if pending else None))
            next(r for r in public['regions'] if r['id'] == rid).update(row)
            display('regions-35.geojson', rid, geom, row['assignment_status'])
        for change in plan['names']:
            municipal(change['csd_id'], change['source_name'])
            if not change.get('evidence'): raise CatalogueError('Name update lacks evidence.')
            row = {'id': 'ca-csd-' + change['csd_id'], 'name': change['name'],
                   'source_name': change['source_name'], 'aliases': [change['source_name']], 'evidence': change['evidence']}
            revisions.append(('metadata', row, None, None))
            next(r for r in public['areas'] if r['id'] == change['csd_id']).update({k: v for k, v in row.items() if k != 'id'})
        for layer in plan['city_layers']:
            city = layer['parent_csd_id']; parent_record = municipal(city, layer['parent_name'])
            if city in updated or csds[city]['geometry'] is None:
                raise CatalogueError('City-area parent needs a separate qualification plan.')
            municipal_geom = shapely.from_wkb(csds[city]['geometry']); municipal_metric = metric(municipal_geom)
            source = plan['sources'][layer['source']]
            if layer['expected_count'] != source['expected_count'] or not layer.get('evidence'):
                raise CatalogueError('City-area coverage count or evidence mismatch.')
            metrics, full_count = [], 0
            for identity in source['identities']:
                sid, props = identity['source_id'], identity['properties']
                uid = layer['id_prefix'] + sid
                if uid in old_areas or uid in additions or not re.fullmatch(r'ca-on-[a-z0-9-]{1,100}', uid):
                    raise CatalogueError('Invalid or duplicate Ontario city-area identity.')
                geom = sources[layer['source']][sid]; issue = geometry_issue(geom)
                row = {'id': uid, 'source_id': sid, 'source': layer['source'], 'name': props[source['name_field']],
                       'province': '35', 'code': 'ON', 'level': 'city_area', 'kind': layer['kind'], 'type': layer['type'],
                       'scheme': layer['scheme'], 'parent_csd_id': city, 'parent_name': parent_record['name'],
                       'region_id': membership.get(city), 'evidence': layer['evidence'], 'issues': []}
                if layer.get('coverage_note'): row['coverage_note'] = layer['coverage_note']
                if issue:
                    # GEOS produces a proposal only. No assignment geometry is stored.
                    candidate, repair = propose_repair(metric(geom))
                    if geometry_issue(candidate): raise CatalogueError('No valid city-area repair candidate.')
                    comparison_geom = transform(inverse, candidate)
                    row.update(assignment_status='unreviewed_repair', repair=repair,
                               uncertainty_basis='source_bbox', issues=[issue, 'Unapproved source repair; display only'])
                else:
                    comparison_geom = geom; full_count += 1
                    row['assignment_status'] = 'validated_source'
                current_metric = metric(comparison_geom); metrics.append(current_metric)
                parent = municipal_metric
                if layer.get('parent_property'):
                    parent_id = layer['parent_ids'].get(props.get(layer['parent_property']))
                    if parent_id not in additions or additions[parent_id][0]['parent_csd_id'] != city or additions[parent_id][1] is None:
                        raise CatalogueError('Missing or cross-city declared community parent.')
                    row.update(parent_area_id=parent_id, relationship_basis='publisher_community_attribute')
                    parent = metric(additions[parent_id][1])
                outside = current_metric.difference(parent).area / current_metric.area
                if outside > .10 or current_metric.difference(municipal_metric).area / current_metric.area > .10:
                    raise CatalogueError('City-area spatial parent check failed: ' + uid)
                row.update(bbox=list(comparison_geom.bounds), vertices=int(shapely.get_num_coordinates(geom)),
                           parent_overlap={'outside_fraction': outside, 'status': 'evidence_for_review'})
                if outside > .01: row['issues'].append('Source boundary extends beyond its parent; retained without clipping')
                additions[uid] = (row, None if issue else geom)
                display('city-areas-35.geojson', uid, comparison_geom, row['assignment_status'])
            union = shapely.union_all(metrics)
            overlap = max(0, sum(g.area for g in metrics) - union.area)
            fraction = union.intersection(municipal_metric).area / municipal_metric.area
            if overlap > max(1, union.area * .000001) or fraction < .90:
                raise CatalogueError('Overlapping siblings or unexpectedly incomplete city coverage.')
            coverage.append({**layer, 'name': layer['parent_name'], 'covered_parent_fraction': fraction,
                'assignment_boundary_count': full_count, 'unapproved_repair_count': layer['expected_count'] - full_count,
                'coverage_measure_includes_unapproved_candidates': full_count != layer['expected_count'],
                'sibling_overlap_m2': overlap, 'uncovered_parent_m2': municipal_metric.difference(union).area,
                'outside_parent_m2': union.difference(municipal_metric).area, 'status': 'evidence_for_review'})
        pending_ids = {uid for uid, r in csds.items() if json.loads(r['record'])['province'] == '35' and r['geometry'] is None}
        if pending_ids != {r['csd_id'] for r in plan['repair_review']}:
            raise CatalogueError('Ontario municipal repair review is incomplete.')
        for review in plan['repair_review']:
            original = json.loads(csds[review['csd_id']]['record'])
            if review['status'] != 'unapproved' or review['repair'] != original['repair'] or review['name'] != original['name']:
                raise CatalogueError('Cannot approve or silently change a municipal repair.')
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE boundary_revision (id TEXT PRIMARY KEY, operation TEXT NOT NULL, record TEXT NOT NULL, geometry BLOB, review_geometry BLOB)')
            for operation, row, geom, review in revisions:
                db.execute('INSERT INTO boundary_revision VALUES (?, ?, ?, ?, ?)', (row['id'], operation, json.dumps(row, ensure_ascii=False),
                           geom.wkb if geom is not None else None, review.wkb if review is not None else None))
            if any(r[1] == 'geometry' and r[3] for r in db.execute('PRAGMA table_info(city_area)')):
                db.execute('ALTER TABLE city_area RENAME TO previous_city_area')
                db.execute('CREATE TABLE city_area (id TEXT PRIMARY KEY, parent_csd_id TEXT NOT NULL REFERENCES csd(id), record TEXT NOT NULL, geometry BLOB)')
                db.execute('INSERT INTO city_area SELECT * FROM previous_city_area')
                db.execute('DROP TABLE previous_city_area')
                db.execute('CREATE INDEX city_area_parent ON city_area(parent_csd_id)')
            for row, geom in additions.values():
                db.execute('INSERT INTO city_area VALUES (?, ?, ?, ?)', (row['id'], row['parent_csd_id'], json.dumps(row, ensure_ascii=False), geom.wkb if geom is not None else None))
        public['city_areas'].extend(r for r, _ in additions.values())
        report['ontario_refresh'] = {'reviewed_on': plan['reviewed_on'], 'state': 'review_required',
            'sources': plan['sources'], 'plan_sha256': sha256(archive / 'plan.json'), 'adjustments': plan['adjustments'],
            'updated_municipality_count': len(updated), 'updated_region_count': sum(op == 'region' for op, *_ in revisions),
            'added_city_area_count': len(additions), 'coverage': coverage, 'names': plan['names'],
            'repair_review': plan['repair_review'], 'unresolved': plan['unresolved']}
        report['catalogue_sha256'] = sha256(staging / 'catalogue.sqlite3')
        part = report['city_areas']
        part['feature_count'] = len(public['city_areas'])
        part['municipality_count'] = len({r['parent_csd_id'] for r in public['city_areas']})
        part['kind_counts'] = dict(Counter(r['kind'] for r in public['city_areas']))
        part['province_counts'] = dict(Counter(r['province'] for r in public['city_areas']))
        part['sources'].update({l['source']: plan['sources'][l['source']] for l in plan['city_layers']})
        part['municipalities'].extend(coverage)
        part.setdefault('issues', []).extend({'id': r['id'], 'name': r['name'], 'issues': r['issues']} for r, _ in additions.values() if r['issues'])
        public['report'] = report
        write_json(staging / 'report.json', report); write_json(staging / 'preview/catalogue.json', public)
        for name, content in displays.items(): write_json(staging / 'preview' / name, content)
        for name in ('index.html', 'preview.js', 'preview.css'):
            shutil.copyfile(ROOT / 'web' / name, staging / 'preview' / name)
    return report
