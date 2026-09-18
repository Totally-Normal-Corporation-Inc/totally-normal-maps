"""Offline, evidenced jurisdiction updates; original national rows stay immutable.

Source-family differences are uncertainty polygons, including uncovered old
extents. They never supply assignments or silently approve an existing repair.
"""
from collections import Counter
from contextlib import closing
from datetime import date
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3

from pyproj import Transformer
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import transform

from .catalogue import (CatalogueError, ROOT, PROVINCES, MAX_TOTAL_VERTICES, MAX_VERTICES_PER_FEATURE,
                        geometry_issue, new_directory, open_catalogue, polygon_parts,
                        propose_repair, read_json, sha256, write_json)
from .quebec_refresh import _display
from .jurisdiction_migrations import build_migrations

MAX_BYTES = 32 * 1024 * 1024


def compare_extents(old, new):
    """Compare full projected extents in both directions; containment is not identity."""
    areas = (old.area, new.area)
    if any(not math.isfinite(a) or a <= 0 for a in areas):
        raise CatalogueError('Spatial comparison requires finite positive areas.')
    common = old.intersection(new).area
    if not math.isfinite(common):
        raise CatalogueError('Spatial comparison produced a non-finite intersection.')
    ratios = (common / areas[0], common / areas[1])
    return {'old_area_m2': areas[0], 'new_area_m2': areas[1],
            'old_overlap_fraction': ratios[0], 'new_overlap_fraction': ratios[1],
            'removed_m2': old.difference(new).area, 'added_m2': new.difference(old).area,
            'minimum_overlap_fraction': .80, 'sufficient_overlap': min(ratios) >= .80}


def source_identity(props, source):
    value = props.get(source['id_field'])
    prefix = ''
    if value is None and source.get('fallback_id_field'):
        field = source['fallback_id_field']
        value = props.get(field)
        prefix = field.lower() + '-'
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise CatalogueError('Source identity is missing or unsupported.')
    return prefix + str(value)


def checked_source(path, source, *, bounds=(-141.1, 41, -52, 90)):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES or sha256(path) != source['sha256']:
        raise CatalogueError('jurisdiction source checksum or byte budget mismatch.')
    data = read_json(path, MAX_BYTES)
    crs = data.get('crs')
    if (data.get('type') != 'FeatureCollection' or data.get('exceededTransferLimit') or
            len(data.get('features', [])) != source['expected_count'] or crs != source.get('geojson_crs') or
            crs not in (None, {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
                       {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}})):
        raise CatalogueError('Incomplete jurisdiction source or unsupported coordinate declaration.')
    expected = {r['source_id']: r['properties'] for r in source['identities']}
    if len(expected) != source['expected_count']:
        raise CatalogueError('Duplicate planned jurisdiction identities.')
    result, vertices, invalid = {}, 0, set()
    for feature in data['features']:
        props = feature['properties']; uid = source_identity(props, source)
        if uid not in expected or uid in result or any(props.get(k) != v for k, v in expected[uid].items()):
            raise CatalogueError('Changed or duplicate jurisdiction source identity.')
        geom = shape(feature['geometry'])
        count = int(shapely.get_num_coordinates(geom)); vertices += count
        issue = geometry_issue(geom)
        if issue:
            if uid not in source.get('unapproved_invalid_ids', []) or not issue.startswith('invalid_geometry:'):
                raise CatalogueError('Unexpected invalid jurisdiction geometry.')
            invalid.add(uid)
        if count > MAX_VERTICES_PER_FEATURE or vertices > MAX_TOTAL_VERTICES:
            raise CatalogueError('jurisdiction source exceeds vertex budget.')
        west, south, east, north = geom.bounds
        if not (bounds[0] <= west <= east <= bounds[2] and bounds[1] <= south <= north <= bounds[3]):
            raise CatalogueError('Source coordinates outside jurisdiction.')
        result[uid] = geom
    if set(result) != set(expected) or invalid != set(source.get('unapproved_invalid_ids', [])):
        raise CatalogueError('Changed jurisdiction source identity or repair set.')
    return result


def build_refresh(run, destination, *, source_dir, plan_path, province, legacy_ontario=False):
    run, source_dir = Path(run), Path(source_dir)
    plan, report = read_json(plan_path), read_json(run / 'report.json')
    if province not in PROVINCES:
        raise CatalogueError('Unknown jurisdiction.')
    code = PROVINCES[province][0]
    prior = report.get('jurisdiction_refreshes', {})
    if not legacy_ontario and (plan.get('province') != province or
            plan.get('parent_catalogue_sha256') != report['catalogue_sha256'] or
            plan.get('parent_report_sha256') != sha256(run / 'report.json')):
        raise CatalogueError('Jurisdiction plan requires the pinned parent catalogue and report.')
    if not legacy_ontario and (province in {'24', '35'} or not plan.get('audit')):
        raise CatalogueError('Use the legacy refresh for Québec/Ontario; other jurisdictions require an audit.')
    if legacy_ontario and any(plan.get(key) for key in ('mergers', 'region_updates', 'membership_updates')):
        raise CatalogueError('Legacy Ontario plans do not support municipal or regional migrations.')
    if (plan.get('schema_version') != 1 or (legacy_ontario and 'ontario_refresh' in report or not legacy_ontario and province in prior) or
            plan.get('base_source_sha256') != report['source']['sha256'] or
            plan.get('base_identity_sha256') != report['identity_sha256'] or 'city_areas' not in report):
        raise CatalogueError('jurisdiction plan requires a matching unmodified base.')
    if len(plan['adjustments']) > 100 or len(plan['city_layers']) > 1000:
        raise CatalogueError('jurisdiction plan exceeds its budget.')
    for key, source in plan['sources'].items():
        if (not re.fullmatch(r'[a-z0-9-]{1,60}', key) or not source.get('authority') or
                not source.get('licence') or not source.get('evidence')):
            raise CatalogueError('jurisdiction source requires safe identity, licence and evidence.')
        if not legacy_ontario:
            bounds = source.get('bounds')
            if (not isinstance(bounds, list) or len(bounds) != 4 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds) or
                    not (-141.1 <= bounds[0] < bounds[2] <= -52 and 41 <= bounds[1] < bounds[3] <= 90)):
                raise CatalogueError('Source requires finite qualified Canadian coordinate bounds.')
    with open_catalogue(run) as db:
        csds = {r['id']: dict(r) for r in db.execute('SELECT * FROM csd')}
        regions = {r['id']: dict(r) for r in db.execute('SELECT * FROM region')}
        membership = dict(db.execute('SELECT csd_id, region_id FROM csd_region'))
        area_rows = {r['id']: dict(r) for r in db.execute('SELECT * FROM city_area')}
        old_areas = set(area_rows)
        previous_revisions = {r['id'] for r in db.execute('SELECT id FROM boundary_revision')} if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='boundary_revision'").fetchone() else set()
    if not legacy_ontario:
        audit = plan['audit']
        expected = {uid for uid, row in csds.items() if json.loads(row['record'])['province'] == province}
        audited = [r['csd_id'] for r in audit['municipalities']]
        if set(audited) != expected or len(audited) != len(expected):
            raise CatalogueError('Jurisdiction audit must account for every baseline municipal identity exactly once.')
        statuses = {'qualified_complete', 'qualified_partial', 'missing_boundary', 'source_blocked',
                    'no_qualifying_source_found', 'pending_municipal_site_review'}
        for item in audit['municipalities']:
            original = json.loads(csds[item['csd_id']]['record'])
            if item.get('name') != original['name'] or item.get('status') not in statuses or not item.get('evidence'):
                raise CatalogueError('Audit identity, status or evidence missing.')
        if audit.get('source_audit_complete') and any(r['status'] == 'pending_municipal_site_review' for r in audit['municipalities']):
            raise CatalogueError('An incomplete municipal audit cannot be reported as complete.')
    forward = Transformer.from_crs(4326, 3347, always_xy=True).transform
    inverse = Transformer.from_crs(3347, 4326, always_xy=True).transform
    def metric(g): return transform(forward, g)
    def municipal(uid, name):
        if uid not in csds:
            raise CatalogueError('Unknown jurisdiction municipality.')
        row = json.loads(csds[uid]['record'])
        if row['province'] != province or row['name'] != name:
            raise CatalogueError('Changed jurisdiction municipal identity.')
        return row
    revisions, updated, additions, coverage = [], {}, {}, []
    deferred, applied, considered = [], [], set()
    with new_directory(destination) as staging:
        if run.is_symlink() or any(p.is_symlink() for p in run.rglob('*')):
            raise CatalogueError('Base run contains symlinks.')
        shutil.copytree(run, staging, dirs_exist_ok=True)
        if sha256(staging / 'catalogue.sqlite3') != report['catalogue_sha256']:
            raise CatalogueError('Base catalogue changed during refresh.')
        if not legacy_ontario and sha256(staging / 'report.json') != plan['parent_report_sha256']:
            raise CatalogueError('Parent report changed during refresh.')
        archive = staging / ('ontario-refresh-sources' if legacy_ontario else 'jurisdiction-refresh-' + province + '-sources'); archive.mkdir()
        write_json(archive / 'plan.json', plan)
        sources = {}
        for key, source in plan['sources'].items():
            path = source_dir / (key + '.geojson')
            checked_source(path, source, bounds=(-96, 41, -74, 57) if legacy_ontario else source['bounds'])
            shutil.copyfile(path, archive / path.name)
            sources[key] = checked_source(archive / path.name, source, bounds=(-96, 41, -74, 57) if legacy_ontario else source['bounds'])
        public = read_json(staging / 'preview/catalogue.json')
        displays = {name: read_json(staging / 'preview' / name) for name in (province + '.geojson', 'regions-' + province + '.geojson')}
        city_display = 'city-areas-' + province + '.geojson'
        displays[city_display] = (read_json(staging / 'preview' / city_display) if (staging / 'preview' / city_display).exists()
                                  else {'type': 'FeatureCollection', 'features': []})
        def display(name, uid, geom, status):
            features = displays[name]['features']
            feature = {'type': 'Feature', 'properties': {'id': uid, 'assignment_status': status},
                       'geometry': mapping(_display(geom, forward, inverse, 20 if name.startswith('city-') else 200))}
            existing = next((f for f in features if f['properties']['id'] == uid), None)
            if existing is None: features.append(feature)
            else: existing.update(feature)
        for adjustment in plan['adjustments']:
            if date.fromisoformat(adjustment['effective_date']) > date.fromisoformat(plan['reviewed_on']):
                raise CatalogueError('A future municipal adjustment cannot be applied as current geography.')
            if not adjustment.get('evidence') or len(adjustment['members']) < 2:
                raise CatalogueError('Boundary adjustment lacks participants or evidence.')
            group = []
            for member in adjustment['members']:
                uid = member['csd_id']; original = municipal(uid, member['name'])
                if uid in considered or 'ca-csd-' + uid in previous_revisions or csds[uid]['geometry'] is None:
                    raise CatalogueError('Cannot duplicate an update or approve a municipal repair.')
                considered.add(uid)
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
                comparison = compare_extents(old_metric, new_metric)
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
                       'comparison': comparison,
                       'issues': ['Municipal boundary source and vintage changed; old/new differences remain review uncertainty']}
                group.append((uid, row, old, geom, review))
            failed = [uid for uid, row, *_ in group if not row['comparison']['sufficient_overlap']]
            if failed:
                deferred.append({**adjustment, 'status': 'deferred', 'failed_csd_ids': failed,
                                 'reason': 'Insufficient overlap relative to both boundary extents',
                                 'comparisons': {uid: row['comparison'] for uid, row, *_ in group}})
            else:
                applied.append(adjustment)
            for uid, row, old, geom, review in group:
                if failed:
                    geom = old
                    row.update(update_status='deferred', boundary_basis='retained_previous_boundary',
                               proposed_boundary_source=row.pop('boundary_source'),
                               proposed_boundary_source_ids=row.pop('boundary_source_ids'),
                               proposed_effective_date=row.pop('effective_date'),
                               bbox=list(old.bounds), vertices=int(shapely.get_num_coordinates(old)),
                               coverage_note='Previous boundary retained. The complete proposed adjustment group is deferred; old/new differences remain review uncertainty.',
                               issues=['Proposed municipal adjustment deferred pending source-extent qualification'])
                    revisions.append(('deferred_boundary', row, geom, review))
                else:
                    revisions.append(('boundary', row, geom, review)); updated[uid] = geom
                next(r for r in public['areas'] if r['id'] == uid).update({k: v for k, v in row.items() if k != 'id'})
                display(province + '.geojson', uid, geom, row['assignment_status'])
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
                   'evidence': [e for a in applied for e in a['evidence']],
                   'coverage_note': 'Complete current member union; national and newer municipal source differences require review.',
                   'issues': original.get('issues', []) + ['Mixed national and current municipal boundary sources']}
            revisions.append(('region', row, None if pending else geom, geom if pending else None))
            next(r for r in public['regions'] if r['id'] == rid).update(row)
            display('regions-' + province + '.geojson', rid, geom, row['assignment_status'])
        renamed = set()
        for change in plan['names']:
            municipal(change['csd_id'], change['source_name'])
            if change['csd_id'] in renamed or not change.get('evidence') or not isinstance(change.get('name'), str) or not change['name'].strip():
                raise CatalogueError('Name update lacks a name or evidence.')
            renamed.add(change['csd_id'])
            row = {'id': 'ca-csd-' + change['csd_id'], 'name': change['name'],
                   'source_name': change['source_name'], 'aliases': [change['source_name']], 'evidence': change['evidence']}
            boundary = next((r for op, r, *_ in revisions if r['id'] == row['id']), None)
            if boundary is not None:
                evidence = boundary['evidence'] + row['evidence']
                boundary.update(row); boundary['evidence'] = evidence
            else:
                revisions.append(('metadata', row, None, None))
            next(r for r in public['areas'] if r['id'] == change['csd_id']).update({k: v for k, v in row.items() if k != 'id'})
        migration_rows, migrations = build_migrations(plan, province, csds, regions, membership,
            area_rows, sources, public, display, metric, compare_extents, updated, considered)
        successors = {r['id']: (r, geom) for op, r, geom, _ in migration_rows if op == 'new'}
        superseded = {r['id'] for op, r, *_ in migration_rows if op == 'supersede'}
        for op, row, *_ in migration_rows:
            if op == 'membership':
                parent = row['parent_id']
                if parent == 'ca-' + code.lower(): membership.pop(row['id'].removeprefix('ca-csd-'), None)
                else: membership[row['id'].removeprefix('ca-csd-')] = parent
        for layer in plan['city_layers']:
            city = layer['parent_csd_id']; successor_id = layer.get('parent_municipality_id')
            if successor_id:
                if successor_id not in successors or 'ca-csd-' + city not in successors[successor_id][0]['predecessor_ids']:
                    raise CatalogueError('City-area successor parent requires an applied, evidenced municipal succession.')
                parent_record, municipal_geom = successors[successor_id]
                if parent_record['name'] != layer['parent_name']:
                    raise CatalogueError('Changed successor city-area parent name.')
            else:
                parent_record = municipal(city, layer['parent_name'])
                if 'ca-csd-' + city in superseded:
                    raise CatalogueError('City-area layer must explicitly select the current municipal successor.')
                municipal_geom = shapely.from_wkb(csds[city]['geometry'])
            if city in updated or csds[city]['geometry'] is None:
                raise CatalogueError('City-area parent needs a separate qualification plan.')
            municipal_metric = metric(municipal_geom)
            source = plan['sources'][layer['source']]
            excluded = layer.get('excluded_source_ids', {})
            if (not isinstance(excluded, dict) or not set(excluded) <= sources[layer['source']].keys() or
                    any(not reason for reason in excluded.values())):
                raise CatalogueError('Excluded city source identities require explicit reasons.')
            if layer['expected_count'] != source['expected_count'] - len(excluded) or not layer.get('evidence'):
                raise CatalogueError('City-area coverage count or evidence mismatch.')
            metrics, assignment_metrics, full_count, repair_count, parent_pending = [], [], 0, 0, set()
            overlap_pending = set(layer.get('unapproved_overlap_ids', []))
            if overlap_pending and (not layer.get('topology_evidence') or not overlap_pending <= sources[layer['source']].keys() - excluded.keys()):
                raise CatalogueError('Overlap review requires known source identities and topology evidence.')
            for identity in source['identities']:
                sid, props = identity['source_id'], identity['properties']
                if sid in excluded: continue
                uid = layer['id_prefix'] + layer.get('id_map', {}).get(sid, sid)
                if uid in old_areas or uid in additions or not re.fullmatch(r'ca-' + code.lower() + r'-[a-z0-9-]{1,100}', uid):
                    raise CatalogueError('Invalid or duplicate jurisdiction city-area identity.')
                geom = sources[layer['source']][sid]; issue = geometry_issue(geom)
                row = {'id': uid, 'source_id': sid, 'source': layer['source'], 'name': props[source['name_field']],
                       'province': province, 'code': code, 'level': 'city_area', 'kind': layer['kind'], 'type': layer['type'],
                       'scheme': layer['scheme'], 'parent_csd_id': city, 'parent_name': parent_record['name'],
                       'region_id': membership.get(city), 'evidence': layer['evidence'], 'issues': []}
                if successor_id:
                    row.update(municipality_id=successor_id, region_id=parent_record.get('region_id'))
                if layer.get('coverage_note'): row['coverage_note'] = layer['coverage_note']
                if issue:
                    # GEOS produces a proposal only. No assignment geometry is stored.
                    candidate, repair = propose_repair(metric(geom))
                    if geometry_issue(candidate): raise CatalogueError('No valid city-area repair candidate.')
                    comparison_geom = transform(inverse, candidate)
                    row.update(assignment_status='unreviewed_repair', repair=repair,
                               uncertainty_basis='source_bbox', issues=[issue, 'Unapproved source repair; display only'])
                    repair_count += 1
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
                    if sid not in layer.get('unapproved_parent_ids', []):
                        raise CatalogueError('City-area spatial parent check failed: ' + uid)
                    parent_pending.add(sid)
                    if not issue:
                        full_count -= 1
                        row.update(assignment_status='unreviewed_parent', uncertainty_basis='source_bbox',
                                   issues=['Publisher city-area extent differs substantially from the municipal source; parent qualification pending'])
                row.update(bbox=list(comparison_geom.bounds), vertices=int(shapely.get_num_coordinates(geom)),
                           parent_overlap={'outside_fraction': outside, 'status': 'evidence_for_review'})
                if outside > .01: row['issues'].append('Source boundary extends beyond its parent; retained without clipping')
                if sid in overlap_pending:
                    if not issue and sid not in parent_pending:
                        full_count -= 1
                        row.update(assignment_status='unreviewed_overlap', uncertainty_basis='source_bbox')
                    row['issues'].append('Unapproved overlap with another publisher area; no nesting inferred')
                full = None if issue or sid in parent_pending or sid in overlap_pending else geom
                if full is not None: assignment_metrics.append(current_metric)
                additions[uid] = (row, full)
                display(city_display, uid, comparison_geom, row['assignment_status'])
            union = shapely.union_all(metrics)
            overlap = max(0, sum(g.area for g in metrics) - union.area)
            assignment_union = shapely.union_all(assignment_metrics)
            assignment_overlap = max(0, sum(g.area for g in assignment_metrics) - assignment_union.area)
            fraction = union.intersection(municipal_metric).area / municipal_metric.area
            minimum = .90 if layer.get('coverage_policy') == 'citywide' else layer.get('minimum_parent_fraction')
            if minimum is None or not 0 < minimum <= 1 or (layer.get('coverage_policy') != 'citywide' and not layer.get('coverage_note')):
                raise CatalogueError('Partial city coverage requires an evidenced minimum and coverage note.')
            overlap_limit = layer.get('max_sibling_overlap_fraction', .000001)
            if (not 0 <= overlap_limit <= .001 or
                    overlap_limit > .000001 and not layer.get('topology_evidence')):
                raise CatalogueError('Retained overlap requires bounded, explicit topology evidence.')
            if parent_pending != set(layer.get('unapproved_parent_ids', [])):
                raise CatalogueError('City-area parent review set differs from the qualified plan.')
            if assignment_overlap > max(1, assignment_union.area * overlap_limit) or fraction < minimum:
                raise CatalogueError('Overlapping siblings or unexpectedly incomplete city coverage.')
            coverage.append({**layer, 'name': layer['parent_name'], 'covered_parent_fraction': fraction,
                'assignment_boundary_count': full_count, 'unapproved_repair_count': repair_count,
                'unapproved_parent_count': len(parent_pending),
                'unapproved_overlap_count': len(overlap_pending), 'assignment_sibling_overlap_m2': assignment_overlap,
                'coverage_measure_includes_unapproved_candidates': full_count != layer['expected_count'],
                'sibling_overlap_m2': overlap, 'uncovered_parent_m2': municipal_metric.difference(union).area,
                'outside_parent_m2': union.difference(municipal_metric).area, 'status': 'evidence_for_review'})
            if successor_id:
                coverage[-1].update(parent_csd_id=successor_id, baseline_parent_csd_id=city)
        pending_ids = {uid for uid, r in csds.items() if json.loads(r['record'])['province'] == province and r['geometry'] is None}
        if pending_ids != {r['csd_id'] for r in plan['repair_review']}:
            raise CatalogueError('jurisdiction municipal repair review is incomplete.')
        for review in plan['repair_review']:
            original = json.loads(csds[review['csd_id']]['record'])
            if review['status'] != 'unapproved' or review['repair'] != original['repair'] or review['name'] != original['name']:
                raise CatalogueError('Cannot approve or silently change a municipal repair.')
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE IF NOT EXISTS boundary_revision (id TEXT PRIMARY KEY, operation TEXT NOT NULL, record TEXT NOT NULL, geometry BLOB, review_geometry BLOB)')
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
            if migration_rows:
                db.execute('CREATE TABLE IF NOT EXISTS jurisdiction_revision (id TEXT PRIMARY KEY, province TEXT NOT NULL, operation TEXT NOT NULL, record TEXT NOT NULL, geometry BLOB, review_geometry BLOB)')
                for operation, row, geom, review in migration_rows:
                    db.execute('INSERT INTO jurisdiction_revision VALUES (?, ?, ?, ?, ?, ?)',
                        (row['id'], province, operation, json.dumps(row, ensure_ascii=False),
                         geom.wkb if geom is not None else None, review.wkb if review is not None else None))
        public['city_areas'].extend({**r, 'parent_csd_id': r.get('municipality_id', r['parent_csd_id'])} for r, _ in additions.values())
        refresh_report = {'reviewed_on': plan['reviewed_on'], 'state': 'review_required',
            'sources': plan['sources'], 'plan_sha256': sha256(archive / 'plan.json'), 'adjustments': applied,
            'deferred_adjustments': deferred, 'deferred_municipality_count': sum(len(a['members']) for a in deferred),
            'updated_municipality_count': len(updated), 'updated_region_count': sum(op == 'region' for op, *_ in revisions),
            'added_city_area_count': len(additions), 'coverage': coverage, 'names': plan['names'],
            'repair_review': plan['repair_review'], 'unresolved': plan['unresolved']}
        if legacy_ontario:
            report['ontario_refresh'] = refresh_report
        else:
            refresh_report['audit'] = plan['audit']
            if migrations is not None: refresh_report['migrations'] = migrations
            report.setdefault('jurisdiction_refreshes', {})[province] = refresh_report
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
