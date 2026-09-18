"""Explicit municipal succession and regional membership, over retained source rows.

No regions or relationships are inferred from names, containment or proximity.
Successors retain complete predecessor geometry. Publisher geometry is comparison
evidence, and a failed comparison defers the entire succession.
"""
from datetime import date
import json
import re

import shapely

from .catalogue import CatalogueError, PROVINCES, geometry_issue


def build_migrations(plan, province, csds, regions, membership, area_rows, sources,
                     public, display, metric, compare_extents, updated, considered):
    mergers = plan.get('mergers', [])
    region_updates = plan.get('region_updates', [])
    moves = plan.get('membership_updates', [])
    if not any((mergers, region_updates, moves)):
        return [], None
    if len(mergers) > 100 or len(region_updates) > 100 or len(moves) > 2000:
        raise CatalogueError('Jurisdiction migration exceeds its identity budget.')
    code = PROVINCES[province][0]
    province_id = 'ca-' + code.lower()
    current = {'ca-csd-' + uid: json.loads(r['record']) for uid, r in csds.items()
               if json.loads(r['record'])['province'] == province}
    geometry = {'ca-csd-' + uid: updated.get(uid, shapely.from_wkb(r['geometry'] or r['repair_candidate']))
                for uid, r in csds.items() if 'ca-csd-' + uid in current}
    pending = {'ca-csd-' + uid for uid, r in csds.items() if 'ca-csd-' + uid in current and r['geometry'] is None}
    parents = {uid: membership.get(uid.removeprefix('ca-csd-')) for uid in current}
    existing_regions = {uid: json.loads(r['record']) for uid, r in regions.items()
                        if json.loads(r['record'])['province'] == province}
    definitions, retired_regions, rows = {}, set(), []

    def evidenced(item):
        if not item.get('evidence'):
            raise CatalogueError('Migration requires substantive source evidence.')
        try:
            if date.fromisoformat(item['effective_date']) > date.fromisoformat(plan['reviewed_on']):
                raise CatalogueError('A future migration cannot be current geography.')
        except (KeyError, TypeError, ValueError) as error:
            raise CatalogueError('Migration requires a valid effective date.') from error

    for item in region_updates:
        evidenced(item)
        uid, operation = item.get('id'), item.get('operation')
        if (not isinstance(uid, str) or not re.fullmatch(province_id + r'-[a-z0-9-]{1,100}', uid)
                or uid in definitions or operation not in {'add', 'update', 'retire'}
                or (operation == 'add') != (uid not in existing_regions)
                or uid in area_rows):
            raise CatalogueError('Invalid or duplicate regional migration identity.')
        if (not isinstance(item.get('member_ids'), list)
                or len(item['member_ids']) != len(set(item['member_ids']))):
            raise CatalogueError('Regional migration requires an exact member identity set.')
        if operation == 'retire':
            if item['member_ids']:
                raise CatalogueError('A retired region may not retain current members.')
            retired_regions.add(uid)
        elif (not all(isinstance(item.get(k), str) and item[k].strip()
                      for k in ('name', 'kind', 'type', 'source_id', 'coverage_note'))
              or item.get('coverage_policy') not in {'whole_divisions', 'selected_members', 'complete_members'}):
            raise CatalogueError('Region requires named, evidenced coverage semantics.')
        definitions[uid] = item
    available_regions = (existing_regions.keys() | definitions.keys()) - retired_regions

    def parent_valid(parent):
        if parent is not None and parent not in available_regions:
            raise CatalogueError('Municipal parent is missing, retired or outside the jurisdiction.')

    applied, deferred, retired, affected, successors = [], [], set(), set(), {}
    considered_predecessors = set()
    city_updates, reserved = [], set()
    for merger in mergers:
        evidenced(merger)
        uid, sid = merger.get('id'), merger.get('source_id')
        old_ids = merger.get('predecessor_csd_ids', [])
        old = ['ca-csd-' + v for v in old_ids]
        if (not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9-]{1,60}', sid)
                or uid != province_id + '-mun-' + sid or uid in current or uid in reserved
                or uid in regions or uid in definitions or uid in area_rows
                or len(old) < 2 or len(old) != len(set(old)) or set(old) - current.keys()
                or considered_predecessors.intersection(old) or considered.intersection(old_ids)
                or set(old_ids).intersection(r['csd_id'] for r in plan['names'])
                or not isinstance(merger.get('type'), str) or not merger['type']):
            raise CatalogueError('Invalid, duplicated or conflicting municipal succession.')
        reserved.add(uid)
        considered_predecessors.update(old)
        if any(x in pending for x in old):
            raise CatalogueError('Succession cannot approve a predecessor repair.')
        parent = merger.get('region_id'); parent_valid(parent)
        source = plan['sources'].get(merger.get('source'), {})
        identity = next((i for i in source.get('identities', []) if i['source_id'] == sid), None)
        if identity is None or identity['properties'].get(source['name_field']) != merger.get('name'):
            raise CatalogueError('Successor differs from its qualified publisher identity.')
        union = shapely.union_all([geometry[x] for x in old])
        reference = sources[merger['source']][sid]
        if geometry_issue(union) or geometry_issue(reference):
            raise CatalogueError('Invalid complete successor or comparison boundary.')
        comparison = compare_extents(metric(union), metric(reference))
        children = {i for i, r in area_rows.items() if r['parent_csd_id'] in old_ids}
        declared = merger.get('city_area_ids', [])
        if set(declared) != children or len(declared) != len(children):
            raise CatalogueError('Succession requires every existing city-area parent migration explicitly.')
        if not comparison['sufficient_overlap']:
            deferred.append({**merger, 'comparison': comparison, 'status': 'deferred',
                             'reason': 'Insufficient overlap relative to both boundary extents'})
            continue
        applied.append(merger); retired.update(old); successors[uid] = merger
        row = {'id': uid, 'source_id': sid, 'name': merger['name'], 'type': merger['type'],
               'kind': 'municipality', 'level': 'municipality', 'province': province, 'code': code,
               'province_id': province_id, 'parent_id': parent or province_id, 'region_id': parent,
               'assignment_status': 'validated_derived', 'lifecycle_status': 'current',
               'predecessor_ids': old, 'effective_date': merger['effective_date'],
               'source_name': merger['name'], 'source': merger['source'],
               'aliases': sorted({current[x]['name'] for x in old} - {merger['name']}),
               'evidence': merger['evidence'], 'boundary_basis': 'predecessor_csd_union',
               'coverage_note': 'Complete retained predecessor union; publisher polygon is comparison evidence only.',
               'comparison': comparison, 'bbox': list(union.bounds),
               'vertices': int(shapely.get_num_coordinates(union)),
               'issues': ['Current publisher comparison differs from retained predecessor geometry'] if not union.equals(reference) else []}
        delta = union.symmetric_difference(reference)
        review = None if delta.is_empty else delta
        rows.append(('new', row, union, review))
        current[uid] = row; geometry[uid] = union; parents[uid] = parent
        public['areas'].append(row.copy())
        display(province + '.geojson', uid, union, row['assignment_status'])
        for old_uid in old:
            affected.add(parents[old_uid])
            patch = {'id': old_uid, 'lifecycle_status': 'superseded', 'valid_to': merger['effective_date'],
                     'successor_ids': [uid], 'evidence': merger['evidence']}
            rows.append(('supersede', patch, None, None))
            next(r for r in public['areas'] if r['id'] == old_uid.removeprefix('ca-csd-')).update(
                {k: v for k, v in patch.items() if k != 'id'})
        affected.add(parent)
        for child in sorted(children):
            original = json.loads(area_rows[child]['record'])
            patch = {'id': child, 'municipality_id': uid,
                     'parent_id': original.get('parent_area_id') or uid,
                     'evidence': merger['evidence']}
            rows.append(('city_parent', patch, None, None)); city_updates.append(patch)
            next(r for r in public['city_areas'] if r['id'] == child).update(
                parent_csd_id=uid, parent_name=merger['name'], region_id=parent)
    moved = set()
    for move in moves:
        evidenced(move)
        uid = move.get('municipality_id'); parent = move.get('region_id')
        if (uid not in current or uid in retired or uid in successors or uid in moved
                or parents[uid] != move.get('previous_region_id')):
            raise CatalogueError('Invalid or stale municipal regional membership migration.')
        parent_valid(parent)
        if parents[uid] == parent:
            raise CatalogueError('Regional membership migration must change the parent.')
        moved.add(uid); affected.update((parents[uid], parent)); parents[uid] = parent
        patch = {'id': uid, 'parent_id': parent or province_id, 'evidence': move['evidence'],
                 'membership_effective_date': move['effective_date']}
        rows.append(('membership', patch, None, None))
        next(r for r in public['areas'] if r['id'] == uid.removeprefix('ca-csd-')).update(region_id=parent)
    for child in public['city_areas']:
        uid = child['parent_csd_id']
        uid = uid if uid in successors else 'ca-csd-' + uid
        if uid in parents and uid not in retired:
            child['region_id'] = parents[uid]
    for definition in definitions.values():
        expected = {uid for uid, parent in parents.items() if parent == definition['id'] and uid not in retired}
        if set(definition['member_ids']) != expected:
            raise CatalogueError('Regional definition differs from explicit current municipal membership.')
    if any(parent in retired_regions for uid, parent in parents.items() if uid not in retired):
        raise CatalogueError('Retiring a region requires explicit reassignment of every current member.')
    evidence = [e for item in (*applied, *moves, *region_updates) for e in item['evidence']]
    revised = []
    for rid in sorted((affected | definitions.keys()) - {None}):
        definition = definitions.get(rid)
        if rid in retired_regions:
            patch = {'id': rid, 'lifecycle_status': 'superseded', 'valid_to': definition['effective_date'],
                     'evidence': definition['evidence']}
            rows.append(('retire_region', patch, None, None))
            next(r for r in public['regions'] if r['id'] == rid).update(patch)
            continue
        member_ids = sorted(uid for uid, parent in parents.items() if parent == rid and uid not in retired)
        if not member_ids:
            raise CatalogueError('An empty regional grouping requires explicit retirement.')
        geom = shapely.union_all([geometry[uid] for uid in member_ids])
        if geometry_issue(geom):
            raise CatalogueError('Invalid complete regional member union.')
        original = existing_regions.get(rid, {})
        is_pending = bool(pending.intersection(member_ids)) or original.get('assignment_status', '').startswith('unreviewed_')
        row = {**original, **({k: definition[k] for k in ('name', 'kind', 'type', 'source_id',
                           'coverage_policy', 'coverage_note')} if definition else {}),
               'id': rid, 'province': province, 'code': code, 'province_id': province_id,
               'level': 'region', 'parent_id': province_id, 'evidence': evidence,
               'assignment_status': 'unreviewed_repair' if is_pending else 'validated_derived',
               'member_ids': member_ids, 'member_count': len(member_ids), 'bbox': list(geom.bounds),
               'vertices': int(shapely.get_num_coordinates(geom)), 'boundary_basis': 'current_member_union',
               'issues': original.get('issues', []) + (['Current member union includes unapproved geometry'] if is_pending else [])}
        row.setdefault('aliases', [])
        rows.append(('region' if original else 'new_region', row, None if is_pending else geom, geom if is_pending else None))
        revised.append(rid)
        if original: next(r for r in public['regions'] if r['id'] == rid).update(row)
        else: public['regions'].append(row.copy())
        display('regions-' + province + '.geojson', rid, geom, row['assignment_status'])
    summary = {'mergers': applied, 'deferred_mergers': deferred,
               'membership_updates': moves, 'region_updates': region_updates, 'city_parent_updates': city_updates,
               'added_municipality_count': len(applied), 'superseded_municipality_count': len(retired),
               'added_region_count': sum(r['operation'] == 'add' for r in region_updates),
               'retired_region_count': len(retired_regions), 'revised_region_ids': revised,
               'regional_coverage': {
                   'current_region_ids': sorted(available_regions),
                   'current_municipality_count': len(current.keys() - retired),
                   'member_count': sum(parent is not None for uid, parent in parents.items() if uid not in retired),
                   'unassigned_municipality_ids': sorted(uid for uid, parent in parents.items() if uid not in retired and parent is None),
                   'outline_method': 'complete_current_member_union'}}
    for item in public['provinces']:
        if item['id'] == province:
            item['count'] = summary['regional_coverage']['current_municipality_count']
    return rows, summary


def load_migrations(dataset, db, has_table):
    """Validate the exact evidence-scoped migration set before building API indexes."""
    reports = {p: r['migrations'] for p, r in dataset.report.get('jurisdiction_refreshes', {}).items()
               if 'migrations' in r}
    rows = db.execute('SELECT * FROM jurisdiction_revision ORDER BY id').fetchall() if has_table else []
    if any(r['province'] not in reports for r in rows):
        raise CatalogueError('Jurisdiction revisions require a scoped migration report.')

    def clear_pending(uid):
        if uid in dataset.pending_ids:
            index = dataset.pending_ids.index(uid)
            dataset.pending_ids.pop(index); dataset.pending_shapes.pop(index)
        if uid in dataset.unknown_ids: dataset.unknown_ids.remove(uid)

    def checked_geometry(blob):
        if blob is None:
            raise CatalogueError('Migration lacks required full or review geometry.')
        geom = shapely.from_wkb(blob)
        if geometry_issue(geom):
            raise CatalogueError('Invalid migration geometry.')
        return geom

    for province, report in reports.items():
        if province not in PROVINCES or province in {'24', '35'}:
            raise CatalogueError('Invalid generic migration jurisdiction.')
        province_id = 'ca-' + PROVINCES[province][0].lower()
        scoped = {r['id']: r for r in rows if r['province'] == province}
        expected, mergers, old_to_new = {}, {}, {}

        def expect(uid, operation):
            if uid in expected:
                raise CatalogueError('Conflicting migration identities in the report.')
            expected[uid] = operation

        for merger in report['mergers']:
            uid = merger['id']; expect(uid, 'new'); mergers[uid] = merger
            for old in merger['predecessor_csd_ids']:
                old = 'ca-csd-' + old
                expect(old, 'supersede'); old_to_new[old] = uid
        for move in report['membership_updates']: expect(move['municipality_id'], 'membership')
        for patch in report['city_parent_updates']: expect(patch['id'], 'city_parent')
        added_regions = {r['id'] for r in report['region_updates'] if r['operation'] == 'add'}
        retired_regions = {r['id'] for r in report['region_updates'] if r['operation'] == 'retire'}
        for rid in report['revised_region_ids']: expect(rid, 'new_region' if rid in added_regions else 'region')
        for rid in retired_regions: expect(rid, 'retire_region')
        if ({uid: r['operation'] for uid, r in scoped.items()} != expected
                or report['added_municipality_count'] != len(mergers)
                or report['superseded_municipality_count'] != len(old_to_new)
                or report['added_region_count'] != len(added_regions)
                or report['retired_region_count'] != len(retired_regions)
                or not added_regions <= set(report['revised_region_ids'])):
            raise CatalogueError('Jurisdiction migration identities or counts differ from report.')
        records = {uid: json.loads(r['record']) for uid, r in scoped.items()}
        for uid, row in records.items():
            operation = expected[uid]
            if row.get('id') != uid or not row.get('evidence'):
                raise CatalogueError('Inconsistent or unevidenced jurisdiction revision.')
            if operation in {'new', 'new_region'}:
                level = 'municipality' if operation == 'new' else 'region'
                if (uid in dataset.areas or not uid.startswith(province_id + '-')
                        or row.get('province') != province or row.get('province_id') != province_id
                        or row.get('level') != level):
                    raise CatalogueError('Invalid new jurisdiction identity.')
                item = {k: row[k] for k in ('id', 'source_id', 'name', 'level', 'kind', 'parent_id',
                         'assignment_status', 'bbox', 'evidence', 'boundary_basis', 'coverage_note')}
                for key in ('aliases', 'issues', 'source_name', 'lifecycle_status', 'predecessor_ids',
                            'effective_date', 'comparison', 'coverage_policy', 'member_count'):
                    if key in row: item[key] = row[key]
                item.update(province_id=province_id, source_type=row['type'])
                dataset.add(item)
                dataset.source_ids[(level, uid)] = uid
            else:
                area = dataset.areas.get(uid, {})
                level = 'region' if operation in {'region', 'retire_region'} else 'city_area' if operation == 'city_parent' else 'municipality'
                if (area.get('province_id') != province_id or area.get('level') != level
                        or area.get('lifecycle_status') == 'superseded'):
                    raise CatalogueError('Migration targets an absent, historical or cross-jurisdiction identity.')
        for uid, merger in mergers.items():
            row, source = records[uid], scoped[uid]
            old = ['ca-csd-' + x for x in merger['predecessor_csd_ids']]
            if (len(old) < 2 or row.get('predecessor_ids') != old
                    or row.get('lifecycle_status') != 'current'
                    or row.get('assignment_status') != 'validated_derived'
                    or row.get('boundary_basis') != 'predecessor_csd_union'
                    or row.get('effective_date') != merger['effective_date']
                    or row.get('parent_id') != (merger.get('region_id') or province_id)
                    or uid != province_id + '-mun-' + merger['source_id']
                    or any(x not in dataset.geometries or x in dataset.pending_ids or x in dataset.unknown_ids for x in old)):
                raise CatalogueError('Invalid successor relationship or predecessor qualification.')
            geom = checked_geometry(source['geometry'])
            if not geom.equals(shapely.union_all([dataset.geometries[x] for x in old])):
                raise CatalogueError('Successor must retain complete predecessor assignment geometry.')
            dataset.geometries[uid] = geom; dataset.required_displays.add(uid)
            if source['review_geometry'] is not None:
                dataset.pending_ids.append(uid); dataset.pending_shapes.append(checked_geometry(source['review_geometry']))
        moves = {r['municipality_id']: r for r in report['membership_updates']}
        city_updates = {r['id']: r for r in report['city_parent_updates']}
        for uid, operation in expected.items():
            row, source = records[uid], scoped[uid]
            if operation in {'new', 'region', 'new_region'}: continue
            if source['geometry'] is not None or source['review_geometry'] is not None:
                raise CatalogueError('Metadata migration may not replace assignment geometry.')
            area = dataset.areas[uid]
            if operation == 'supersede':
                successor = old_to_new[uid]
                if (set(row) - {'id', 'lifecycle_status', 'valid_to', 'successor_ids', 'evidence'}
                        or row.get('lifecycle_status') != 'superseded' or row.get('successor_ids') != [successor]
                        or row.get('valid_to') != mergers[successor]['effective_date']):
                    raise CatalogueError('Invalid predecessor lifecycle metadata.')
                area.update(row)
            elif operation == 'membership':
                move = moves[uid]
                if (set(row) - {'id', 'parent_id', 'evidence', 'membership_effective_date'}
                        or area['parent_id'] != (move.get('previous_region_id') or province_id)
                        or row.get('parent_id') != (move.get('region_id') or province_id)
                        or row.get('membership_effective_date') != move['effective_date']):
                    raise CatalogueError('Invalid municipal regional membership metadata.')
                area.update(row)
            elif operation == 'city_parent':
                successor = old_to_new.get(area['municipality_id'])
                if (row != city_updates[uid] or successor is None or row.get('municipality_id') != successor
                        or uid not in mergers[successor].get('city_area_ids', [])
                        or row.get('parent_id') != (successor if area['parent_id'] == area['municipality_id'] else area['parent_id'])
                        or set(row) - {'id', 'municipality_id', 'parent_id', 'evidence'}):
                    raise CatalogueError('Invalid city-area successor ancestry.')
                area.update(row)
            elif operation == 'retire_region':
                definition = next(r for r in report['region_updates'] if r['id'] == uid)
                if (set(row) - {'id', 'lifecycle_status', 'valid_to', 'evidence'}
                        or row.get('lifecycle_status') != 'superseded' or row.get('valid_to') != definition['effective_date']):
                    raise CatalogueError('Invalid regional retirement metadata.')
                area.update(row); clear_pending(uid)
        for rid in report['revised_region_ids']:
            row, source = records[rid], scoped[rid]
            members = sorted(uid for uid, a in dataset.areas.items() if a.get('parent_id') == rid
                             and a['level'] == 'municipality' and a.get('lifecycle_status') != 'superseded')
            if not members or members != row.get('member_ids') or len(members) != row.get('member_count'):
                raise CatalogueError('Regional geometry must include exactly its current municipal members.')
            area = dataset.areas[rid]
            was_pending = rid in dataset.pending_ids or rid in dataset.unknown_ids
            pending = was_pending or any(uid not in dataset.geometries for uid in members)
            if ((source['geometry'] is None) != pending
                    or row.get('assignment_status') != ('unreviewed_repair' if pending else 'validated_derived')):
                raise CatalogueError('Regional migration cannot approve an unresolved repair.')
            shapes = [dataset.geometries[uid] if uid in dataset.geometries else
                      dataset.pending_shapes[dataset.pending_ids.index(uid)] for uid in members]
            geom = checked_geometry(source['review_geometry'] if pending else source['geometry'])
            if not geom.equals(shapely.union_all(shapes)):
                raise CatalogueError('Regional migration must retain the complete current member union.')
            clear_pending(rid)
            if pending:
                dataset.geometries.pop(rid, None)
                dataset.pending_ids.append(rid); dataset.pending_shapes.append(geom)
            else:
                if source['review_geometry'] is not None:
                    raise CatalogueError('Unexpected regional migration comparison geometry.')
                dataset.geometries[rid] = geom
            area.update({k: row[k] for k in ('name', 'kind', 'assignment_status', 'bbox', 'member_count',
                                            'boundary_basis', 'evidence', 'issues')})
            for key in ('coverage_policy', 'coverage_note', 'aliases'):
                if key in row: area[key] = row[key]
            dataset.required_displays.add(rid)
        active = {uid: a for uid, a in dataset.areas.items() if a.get('province_id') == province_id
                  and a.get('lifecycle_status') != 'superseded'}
        municipalities = {uid: a for uid, a in active.items() if a['level'] == 'municipality'}
        regional_coverage = {'current_region_ids': sorted(uid for uid, a in active.items() if a['level'] == 'region'),
                            'current_municipality_count': len(municipalities),
                            'member_count': sum(a['parent_id'] != province_id for a in municipalities.values()),
                            'unassigned_municipality_ids': sorted(uid for uid, a in municipalities.items() if a['parent_id'] == province_id),
                            'outline_method': 'complete_current_member_union'}
        if report.get('regional_coverage') != regional_coverage:
            raise CatalogueError('Current regional coverage differs from evidenced migrations.')
