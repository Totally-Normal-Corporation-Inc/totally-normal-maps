"""Evidence-pinned Québec updates layered over an immutable national catalogue.

Original CSD, regional and city-area rows remain available for provenance. Current
municipal successors have provincial identities; no StatCan identity is invented.
This command is offline. Source acquisition is an explicit separate operation.
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
                        geometry_issue, new_directory, open_catalogue, read_json, sha256, write_json)

PLAN = ROOT / 'quebec-refresh-2026-09.json'
MAX_BYTES = 32 * 1024 * 1024
ID = re.compile(r'ca-qc-[a-z0-9-]{1,80}')


def checked_source(path, source):
    """Pin bytes AND the entire identity set, not just a replaceable checksum."""
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES or sha256(path) != source['sha256']:
        raise CatalogueError('Québec refresh source checksum or byte budget mismatch.')
    data = read_json(path, MAX_BYTES)
    if data.get('exceededTransferLimit') or len(data.get('features', [])) != source['expected_count']:
        raise CatalogueError('Incomplete Québec refresh source.')
    if data.get('type') != 'FeatureCollection' or data.get('crs') != source.get('geojson_crs'):
        raise CatalogueError('Unexpected source format or coordinate reference declaration.')
    if source.get('geojson_crs') not in (None, {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}}):
        raise CatalogueError('Only WGS84 longitude/latitude sources are supported.')
    expected = {r['source_id']: r['properties'] for r in source['identities']}
    if len(expected) != source['expected_count']:
        raise CatalogueError('Duplicate planned source identities.')
    result, vertices = {}, 0
    for feature in data['features']:
        props = feature['properties']
        uid = str(props.get(source['id_field']))
        if uid not in expected or uid in result or any(props.get(k) != v for k, v in expected[uid].items()):
            raise CatalogueError('Changed or duplicate Québec refresh source identity.')
        geom = shape(feature['geometry'])
        count = int(shapely.get_num_coordinates(geom)); vertices += count
        if geometry_issue(geom) or count > MAX_VERTICES_PER_FEATURE or vertices > MAX_TOTAL_VERTICES:
            raise CatalogueError('Invalid Québec refresh geometry or vertex budget exceeded.')
        west, south, east, north = geom.bounds
        if not (-81 <= west <= east <= -56 and 44 <= south <= north <= 64):
            raise CatalogueError('Québec refresh coordinates are outside Québec.')
        result[uid] = geom
    if set(result) != set(expected):
        raise CatalogueError('Incomplete Québec refresh identity set.')
    return result


def validate_plan(plan, report, municipalities, areas, regions):
    if (plan.get('schema_version') != 1 or plan.get('base_source_sha256') != report['source']['sha256'] or
            plan.get('base_identity_sha256') != report['identity_sha256'] or 'quebec_refresh' in report):
        raise CatalogueError('Québec refresh plan does not match an unmodified base release.')
    if len(plan.get('areas', [])) > 1000 or len(plan.get('mergers', [])) > 100:
        raise CatalogueError('Québec refresh plan exceeds the identity budget.')
    sources = plan['sources']
    for key, source in sources.items():
        if (not re.fullmatch(r'[a-z0-9-]{1,60}', key) or not source.get('evidence') or
                not source.get('licence') or not source.get('authority')):
            raise CatalogueError('Source requires a safe key, publisher, licence and evidence.')
    ids, predecessors = set(areas), set()
    new_ids = set()
    for merger in plan['mergers']:
        uid = merger['id']
        if (uid in new_ids or not re.fullmatch(r'ca-qc-mun-[0-9]{5}', uid) or
                uid != 'ca-qc-mun-' + merger['source_id'] or not merger.get('evidence') or
                merger['region_id'] not in regions or merger['source'] not in sources or
                len(merger['predecessor_csd_ids']) < 2):
            raise CatalogueError('Invalid or unevidenced municipal successor.')
        date.fromisoformat(merger['effective_date'])
        source = sources[merger['source']]
        identity = next((r for r in source['identities'] if r['source_id'] == merger['source_id']), None)
        if identity is None or identity['properties'].get(source['name_field']) != merger['name']:
            raise CatalogueError('Successor name differs from its pinned source identity.')
        new_ids.add(uid)
        for old in merger['predecessor_csd_ids']:
            if old in predecessors or old not in municipalities or municipalities[old]['province'] != '24':
                raise CatalogueError('Missing or duplicate municipal predecessor.')
            predecessors.add(old)
    if any(row['parent_csd_id'] in predecessors for row in areas.values()):
        raise CatalogueError('Municipal succession requires an explicit plan for existing city-area parents.')
    changed = set()
    for update in plan['names']:
        uid = update['csd_id']
        if (uid in changed or uid in predecessors or uid not in municipalities or
                municipalities[uid]['province'] != '24' or not update.get('evidence') or
                municipalities[uid]['name'] != update['source_name']):
            raise CatalogueError('Invalid or changed municipal name identity.')
        changed.add(uid)
    definitions = {r['id']: r for r in plan['areas']}
    if len(definitions) != len(plan['areas']):
        raise CatalogueError('Duplicate city-area additions.')
    for row in plan['areas']:
        uid, city = row['id'], row['parent_csd_id']
        if (uid in ids or uid in new_ids or ID.fullmatch(uid) is None or city not in municipalities or
                municipalities[city]['province'] != '24' or city in predecessors or
                row['parent_name'] != municipalities[city]['name'] or not row.get('evidence') or
                row['kind'] not in {'quartier', 'sector'} or not row.get('name')):
            raise CatalogueError('Invalid or unevidenced city-area addition.')
        if row.get('geometry_status') == 'unavailable':
            if row.get('source') is not None or not row.get('coverage_note'):
                raise CatalogueError('Unavailable boundaries require an explicit coverage note.')
        elif row.get('source') not in sources:
            raise CatalogueError('Missing city-area source.')
        else:
            source = sources[row['source']]
            identity = next((r for r in source['identities'] if r['source_id'] == row['source_id']), None)
            if identity is None or identity['properties'].get(source['name_field']) != row['name']:
                raise CatalogueError('Subdivision name differs from its pinned source identity.')
        parent = row.get('parent_area_id')
        if parent:
            # Only one additional city-area depth in this release; never infer parentage.
            if parent not in areas or areas[parent]['parent_csd_id'] != city:
                raise CatalogueError('Missing, cyclic or cross-city subdivision parent.')
        allowance = row.get('parent_outside_limit', .10)
        if not .10 <= allowance <= .20 or (allowance > .10 and not row.get('parent_exception_evidence')):
            raise CatalogueError('Spatial parent exception requires explicit evidence.')
    groups = plan['coverage']
    if Counter(r['source'] for r in plan['areas'] if r.get('source')) != Counter({r['source']: r['expected_count'] for r in groups if r.get('source')}):
        raise CatalogueError('City-area coverage counts differ from the plan.')


def _display(geom, forward, inverse, tolerance):
    candidate = transform(inverse, transform(forward, geom).simplify(tolerance, preserve_topology=True))
    return geom if geometry_issue(candidate) else candidate


def build_refresh(run, destination, *, source_dir, plan_path=None):
    run, source_dir = Path(run), Path(source_dir)
    plan = read_json(plan_path or PLAN)
    report = read_json(run / 'report.json')
    if 'city_areas' not in report:
        raise CatalogueError('Québec refresh requires a completed city-area run.')
    with open_catalogue(run) as db:
        municipal_rows = {r['id']: dict(r) for r in db.execute('SELECT * FROM csd')}
        municipalities = {uid: json.loads(r['record']) for uid, r in municipal_rows.items()}
        area_rows = {r['id']: dict(r) for r in db.execute('SELECT * FROM city_area')}
        areas = {uid: json.loads(r['record']) for uid, r in area_rows.items()}
        region_rows = {r['id']: dict(r) for r in db.execute('SELECT * FROM region')}
        regions = {uid: json.loads(r['record']) for uid, r in region_rows.items()}
        membership = dict(db.execute('SELECT csd_id, region_id FROM csd_region'))
    validate_plan(plan, report, municipalities, areas, regions)
    forward = Transformer.from_crs(4326, 3347, always_xy=True).transform
    inverse = Transformer.from_crs(3347, 4326, always_xy=True).transform
    revisions, shapes, new_areas, coverage = [], {}, [], []
    with new_directory(destination) as staging:
        if any(p.is_symlink() for p in run.rglob('*')):
            raise CatalogueError('Base run may not contain symlinks.')
        shutil.copytree(run, staging, dirs_exist_ok=True)
        if sha256(staging / 'catalogue.sqlite3') != report['catalogue_sha256']:
            raise CatalogueError('Base catalogue changed during refresh.')
        archive = staging / 'quebec-refresh-sources'; archive.mkdir()
        write_json(archive / 'plan.json', plan)
        for key, source in plan['sources'].items():
            path = source_dir / f'{key}.geojson'
            # Validate before copying and then validate the copied bytes as well.
            checked_source(path, source)
            shutil.copyfile(path, archive / path.name)
            shapes[key] = checked_source(archive / path.name, source)
        public = read_json(staging / 'preview/catalogue.json')
        municipality_displays = read_json(staging / 'preview/24.geojson')
        area_displays = read_json(staging / 'preview/city-areas-24.geojson')
        region_displays = read_json(staging / 'preview/regions-24.geojson')
        new_geometry, retired = {}, set()
        for merger in plan['mergers']:
            reference = shapes[merger['source']][merger['source_id']]
            old_ids = merger['predecessor_csd_ids']
            if any(membership.get(uid) != merger['region_id'] or municipal_rows[uid]['geometry'] is None for uid in old_ids):
                raise CatalogueError('Merger crosses a region or depends on an unapproved predecessor repair.')
            old_union = shapely.union_all([shapely.from_wkb(municipal_rows[uid]['geometry']) for uid in old_ids])
            old_metric, metric = transform(forward, old_union), transform(forward, reference)
            overlap = metric.intersection(old_metric).area
            if overlap / metric.area < .90:
                raise CatalogueError('Successor boundary does not match its evidenced predecessors.')
            # A merger combines complete retained predecessor geometry. The newer
            # provincial polygon is a cross-check, never a silent replacement of
            # land/water coverage from a different boundary family or vintage.
            geom = old_union
            if geometry_issue(geom):
                raise CatalogueError('Invalid complete predecessor union.')
            row = {**merger, 'province': '24', 'code': 'QC', 'level': 'municipality',
                   'kind': 'municipality', 'parent_id': merger['region_id'],
                   'assignment_status': 'validated_derived', 'lifecycle_status': 'current',
                   'source_name': merger['name'], 'aliases': [municipalities[u]['name'] for u in old_ids if municipalities[u]['name'] != merger['name']],
                   'predecessor_ids': ['ca-csd-' + u for u in old_ids], 'issues': [],
                   'boundary_basis': 'predecessor_csd_union',
                   'coverage_note': 'Complete union of retained national predecessor boundaries; current provincial polygon is a comparison source only.',
                   'vertices': int(shapely.get_num_coordinates(geom)),
                   'bbox': list(geom.bounds), 'comparison': {'outside_predecessors_m2': metric.difference(old_metric).area,
                       'uncovered_predecessors_m2': old_metric.difference(metric).area,
                       'covered_predecessors_fraction': overlap / old_metric.area, 'status': 'evidence_for_review'}}
            if overlap / old_metric.area < .99:
                row['issues'].append('Provincial comparison omits part of the national predecessor outline; full predecessor union retained, review required')
            revisions.append(('new', row, geom)); new_geometry[row['id']] = geom
            public['areas'].append(row)
            municipality_displays['features'].append({'type': 'Feature', 'properties': {'id': row['id']},
                'geometry': mapping(_display(geom, forward, inverse, 200))})
            for uid in old_ids:
                retired.add(uid)
                patch = {'id': 'ca-csd-' + uid, 'lifecycle_status': 'superseded',
                         'valid_to': merger['effective_date'], 'successor_ids': [row['id']], 'evidence': merger['evidence']}
                revisions.append(('metadata', patch, None))
                next(r for r in public['areas'] if r['id'] == uid).update({k: v for k, v in patch.items() if k != 'id'})
        for update in plan['names']:
            uid = update['csd_id']
            patch = {'id': 'ca-csd-' + uid, 'name': update['name'], 'source_name': update['source_name'],
                     'aliases': sorted(set(update.get('aliases', []) + [update['source_name']]) - {update['name']}),
                     'evidence': update['evidence']}
            revisions.append(('metadata', patch, None))
            next(r for r in public['areas'] if r['id'] == uid).update({k: v for k, v in patch.items() if k != 'id'})
        # Rebuild only affected complete regional unions; the original region table is retained.
        for rid in sorted({r['region_id'] for r in plan['mergers']}):
            members = [u for u, r in membership.items() if r == rid and u not in retired]
            if any(municipal_rows[u]['geometry'] is None for u in members):
                raise CatalogueError('A revised region depends on unapproved or missing geometry.')
            extra = [r for r in plan['mergers'] if r['region_id'] == rid]
            geom = shapely.union_all([shapely.from_wkb(municipal_rows[u]['geometry']) for u in members] + [new_geometry[r['id']] for r in extra])
            if geometry_issue(geom):
                raise CatalogueError('Invalid revised regional union.')
            row = {**regions[rid], 'member_count': len(members) + len(extra), 'bbox': list(geom.bounds),
                   'vertices': int(shapely.get_num_coordinates(geom)), 'boundary_basis': 'current_member_union',
                   'evidence': [e for r in extra for e in r['evidence']],
                   'coverage_note': 'Union of original StatCan members and current provincial municipal successors; source-vintage differences require review.'}
            revisions.append(('region', row, geom))
            next(r for r in public['regions'] if r['id'] == rid).update(row)
            feature = next(f for f in region_displays['features'] if f['properties']['id'] == rid)
            feature['geometry'] = mapping(_display(geom, forward, inverse, 200))
        projected = {}
        for definition in plan['areas']:
            city = definition['parent_csd_id']
            parent_row = municipal_rows[city]
            parent_wkb = parent_row['geometry'] or parent_row['repair_candidate']
            if parent_wkb is None:
                raise CatalogueError('Missing municipal geometry for subdivision comparison.')
            municipal = shapely.from_wkb(parent_wkb)
            row = {**definition, 'province': '24', 'code': 'QC', 'level': 'city_area',
                   'region_id': membership[city], 'issues': []}
            if row.get('geometry_status') == 'unavailable':
                row.update(assignment_status='missing_geometry', bbox=list(municipal.bounds), vertices=0,
                           uncertainty_basis='municipality_bbox', issues=[row['coverage_note']])
                new_areas.append((row, None)); continue
            geom = shapes[row['source']][row['source_id']]
            metric = transform(forward, geom); projected[row['id']] = metric
            municipal_metric = transform(forward, municipal)
            parent = (shapely.from_wkb(area_rows[row['parent_area_id']]['geometry']) if row.get('parent_area_id') else municipal)
            parent_metric = transform(forward, parent)
            outside = metric.difference(parent_metric).area / metric.area
            municipal_outside = metric.difference(municipal_metric).area / metric.area
            if municipal_outside > .10 or outside > row.get('parent_outside_limit', .10):
                raise CatalogueError(f"Subdivision spatial parent check failed: {row['id']}.")
            row.update(assignment_status='validated_source', bbox=list(geom.bounds), vertices=int(shapely.get_num_coordinates(geom)),
                       parent_overlap={'outside_fraction': outside, 'outside_m2': metric.difference(parent_metric).area,
                           'municipality_outside_fraction': municipal_outside,
                           'parent_uses_unreviewed_repair': parent_row['geometry'] is None,
                           'status': 'evidence_for_review'})
            if outside > .01:
                row['issues'].append(f'{outside:.1%} outside its declared parent source boundary; retained without clipping, review required')
            if parent_row['geometry'] is None:
                row['issues'].append('Municipal comparison uses an unapproved repair candidate')
            new_areas.append((row, geom))
            area_displays['features'].append({'type': 'Feature', 'properties': {'id': row['id']},
                'geometry': mapping(_display(geom, forward, inverse, 20))})
        for group in plan['coverage']:
            children = [r for r, g in new_areas if r.get('source') == group.get('source') and r['parent_csd_id'] == group['parent_csd_id']]
            if len(children) != group['expected_count']:
                raise CatalogueError('Subdivision coverage identity count mismatch.')
            if group['coverage_policy'] == 'unavailable':
                coverage.append({**group, 'status': 'boundary_source_required'}); continue
            shapes_metric = [projected[r['id']] for r in children]
            union = shapely.union_all(shapes_metric)
            overlap = max(0, sum(g.area for g in shapes_metric) - union.area)
            p = municipal_rows[group['parent_csd_id']]
            parent = transform(forward, shapely.from_wkb(p['geometry'] or p['repair_candidate']))
            fraction = union.intersection(parent).area / parent.area
            if overlap > max(1, union.area * .000001) or (group['coverage_policy'] == 'citywide' and fraction < .90):
                raise CatalogueError('Overlapping siblings or unexpectedly incomplete city coverage.')
            coverage.append({**group, 'covered_parent_fraction': fraction, 'sibling_overlap_m2': overlap,
                             'uncovered_parent_m2': parent.difference(union).area, 'outside_parent_m2': union.difference(parent).area,
                             'parent_uses_unreviewed_repair': p['geometry'] is None, 'status': 'evidence_for_review'})
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE area_revision (id TEXT PRIMARY KEY, operation TEXT NOT NULL, record TEXT NOT NULL, geometry BLOB)')
            for operation, row, geom in revisions:
                db.execute('INSERT INTO area_revision VALUES (?, ?, ?, ?)', (row['id'], operation, json.dumps(row, ensure_ascii=False), geom.wkb if geom is not None else None))
            # Nullable geometry represents explicitly evidenced identities without a qualified boundary.
            db.execute('ALTER TABLE city_area RENAME TO original_city_area')
            db.execute('CREATE TABLE city_area (id TEXT PRIMARY KEY, parent_csd_id TEXT NOT NULL REFERENCES csd(id), record TEXT NOT NULL, geometry BLOB)')
            db.execute('INSERT INTO city_area SELECT * FROM original_city_area')
            db.execute('DROP TABLE original_city_area')
            db.execute('CREATE INDEX city_area_parent ON city_area(parent_csd_id)')
            for row, geom in new_areas:
                db.execute('INSERT INTO city_area VALUES (?, ?, ?, ?)', (row['id'], row['parent_csd_id'], json.dumps(row, ensure_ascii=False), geom.wkb if geom is not None else None))
        public['city_areas'].extend(r for r, _ in new_areas)
        active_count = report['feature_count'] + len(plan['mergers']) - len(retired)
        report['quebec_refresh'] = {'reviewed_on': plan['reviewed_on'], 'state': 'review_required',
            'plan_sha256': sha256(archive / 'plan.json'), 'sources': plan['sources'],
            'added_municipality_count': len(plan['mergers']), 'superseded_municipality_count': len(retired),
            'active_municipality_count': active_count, 'mergers': plan['mergers'], 'names': plan['names'],
            'coverage': coverage, 'unresolved': plan['unresolved'], 'repair_review': plan['repair_review']}
        report['catalogue_sha256'] = sha256(staging / 'catalogue.sqlite3')
        report['city_areas']['feature_count'] = len(public['city_areas'])
        report['city_areas']['municipality_count'] = len({r['parent_csd_id'] for r in public['city_areas']})
        report['city_areas']['kind_counts'] = dict(Counter(r['kind'] for r in public['city_areas']))
        report['city_areas']['sources'].update({k: s for k, s in plan['sources'].items() if k in {r.get('source') for r in plan['areas']}})
        report['city_areas']['municipalities'].extend(coverage)
        report['city_areas']['issues'].extend({'id': r['id'], 'name': r['name'], 'issues': r['issues']} for r, _ in new_areas if r['issues'])
        report['regions']['membership_count'] += len(plan['mergers']) - len(retired)
        for jurisdiction in report['regions'].get('jurisdictions', []):
            if jurisdiction['province'] == '24':
                jurisdiction['source_member_count'] = jurisdiction['member_count']
                jurisdiction['member_count'] += len(plan['mergers']) - len(retired)
        report['regions']['sources'].extend(s for k, s in plan['sources'].items() if k in {r['source'] for r in plan['mergers']})
        # Source counts remain pinned in the base report; current counts are explicitly separate.
        for p in public['provinces']:
            if p['id'] == '24': p['count'] += len(plan['mergers']) - len(retired)
        public['report'] = report
        write_json(staging / 'report.json', report)
        write_json(staging / 'preview/catalogue.json', public)
        for filename, content in [('24.geojson', municipality_displays), ('regions-24.geojson', region_displays), ('city-areas-24.geojson', area_displays)]:
            write_json(staging / 'preview' / filename, content)
        for name in ('index.html', 'preview.js', 'preview.css'):
            shutil.copyfile(ROOT / 'web' / name, staging / 'preview' / name)
    return report
