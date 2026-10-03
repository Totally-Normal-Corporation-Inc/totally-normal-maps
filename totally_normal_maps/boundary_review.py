"""Offline topology review. A valid polygon alone never authorizes promotion.

Sources are local, checksum-pinned snapshots. This module does no networking.
The audit is evidence, not a mutation; apply re-runs it against a pinned release.
"""
from collections import Counter
from contextlib import closing
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import shutil

from pyogrio.raw import read
from pyproj import Transformer
import shapely
from shapely.geometry import Polygon, Point
from shapely.ops import transform

from .catalogue import (CatalogueError, ROOT, geometry_issue, new_directory, polygon_parts,
                        propose_repair, read_json, sha256, source_uri, write_json)
from .releases import MAX_FILE_BYTES

POLICY = 'boundary-topology-review.v1'
TABLES = ('csd', 'region', 'city_area', 'electoral_area', 'municipal_electoral_area')
METRIC = Transformer.from_crs(4326, 3347, always_xy=True).transform
WGS84 = Transformer.from_crs(3347, 4326, always_xy=True).transform
# Strict-tier absolute AND relative ceilings; that tier never snaps or clips.
MAX_OVERLAP_M2 = 1.0
MAX_OVERLAP_FRACTION = 1e-7
MAX_MINOR_DISTANCE_M = 5.0
MAX_MINOR_AREA_M2 = 100.0
MAX_MINOR_AREA_FRACTION = 1e-4
APPROVALS = {'approve_topology_only', 'approve_minor_correction'}
MEASUREMENT_SEGMENT_DEGREES = .00001


def require(condition, message):
    if not condition:
        raise CatalogueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def metric_wgs84_delta(geometry):
    """Measure linear WGS84 edges without inventing curved-projection slivers.

    Densification is measurement-only (about one metre), never saved geometry.
    It makes opposite sides of thin changes follow the same projected curve.
    """
    if geometry.is_empty or geometry.area == 0:
        return Polygon()
    # Point/line contacts are handled by the separate linework checks.
    surface = shapely.union_all(polygon_parts(geometry))
    dense = shapely.segmentize(surface, MEASUREMENT_SEGMENT_DEGREES)
    require(shapely.get_num_coordinates(dense) <= 3_000_000, 'Review measurement exceeds its vertex budget.')
    return transform(METRIC, dense)


def validated_review(record, geometry, report):
    """Startup guard for a batch-reviewed assignment, not a generic status bypass."""
    repair = record.get('repair') or {}
    if record.get('assignment_status') != 'validated_derived' or repair.get('status') != 'reviewed_topology_batch':
        return False
    proof = repair.get('review', {})
    batches = [report.get('boundary_review', {}), *report.get('boundary_review_history', [])]
    matching = [b for b in batches if b.get('contract') == POLICY and digest(b) == proof.get('audit_sha256')]
    require(len(matching) == 1, 'Missing or changed topology audit.')
    batch = matching[0]
    matches = [r for r in batch['inventory'] if r['id'] == record['id'] and r['decision'] in APPROVALS]
    require(len(matches) == 1, 'Reviewed assignment lacks a unique approval.')
    item = matches[0]
    checks = item['evidence']['checks'] if item['decision'] == 'approve_topology_only' else item['evidence']['minor_correction']['checks']
    require(item['assignment_sha256'] == hashlib.sha256(geometry.wkb).hexdigest()
            and item['source_geometry_sha256'] == repair.get('source_sha256')
            and item['candidate_sha256'] == repair.get('candidate_sha256')
            and item['record_sha256'] == proof.get('original_record_sha256')
            and proof.get('decision') == item['decision'] and not item['reasons']
            and checks and all(v is True for v in checks.values()),
            'Assignment differs from the approved topology evidence.')
    return True


def load_rows(data):
    with closing(sqlite3.connect((data.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {table: {r['id']: {**dict(r), 'record': json.loads(r['record'])}
                        for r in db.execute(f'SELECT * FROM {table} ORDER BY id')}
                for table in TABLES if table in present}


def local_source(directories, filename, checksum):
    require(Path(filename).name == filename and filename not in {'.', '..'}, 'Unsafe source filename.')
    found = [Path(d) / filename for d in directories if (Path(d) / filename).exists()]
    for p in found:
        require(not p.is_symlink(), 'Source may not be a symlink.')
        if sha256(p) == checksum:
            return p
    require(not found, f'Local source checksum mismatch: {filename}')
    return None


def source_groups(data, rows, directories, statcan):
    """Yield (table, source key, source checksum, CRS, id -> original geometry).

    Use the original importer identity rules; never guess names or feature order.
    Missing snapshots stay explicit. Invalid snapshots fail the whole audit.
    """
    if any(r['record']['assignment_status'] == 'unreviewed_repair' for r in rows['csd'].values()):
        spec = read_json(ROOT / 'statcan-2025.json')
        require(data.report['source']['sha256'] == spec['sha256'], 'StatCan source vintage changed.')
        if statcan is not None:
            meta, _, geometries, columns = read(source_uri(Path(statcan), spec), layer=spec['layer'], columns=['CSDUID'])
            require(meta['crs'] == spec['crs'] and len(geometries) == spec['expected_count'], 'StatCan source inventory changed.')
            shapes = {str(uid): shapely.from_wkb(raw) for uid, raw in zip(columns[0], geometries)}
            require(len(shapes) == len(geometries), 'Duplicate StatCan identity.')
            require(sha256(statcan) == spec['sha256'], 'StatCan source changed during review.')
            yield 'csd', 'statcan-2025', spec['sha256'], 'EPSG:3347', shapes
    from .jurisdiction_refresh import checked_source
    plans = [ROOT / 'ontario-refresh-2026-09.json', *sorted(ROOT.glob('jurisdiction-*-2026-09.json'))]
    for plan_path in plans:
        plan = read_json(plan_path)
        for layer in plan['city_layers']:
            key = layer['source']
            members = {uid: row for uid, row in rows.get('city_area', {}).items() if row['record'].get('source') == key}
            if not any(r['record']['assignment_status'] == 'unreviewed_repair' for r in members.values()):
                continue
            spec = plan['sources'][key]
            source = local_source(directories, key + '.geojson', spec['sha256'])
            if source is None:
                continue
            originals = checked_source(source, spec)
            require(sha256(source) == spec['sha256'], 'City source changed during review.')
            shapes = {uid: transform(METRIC, originals[row['record']['source_id']]) for uid, row in members.items()}
            yield 'city_area', key, spec['sha256'], 'EPSG:3347', shapes
    from . import electoral, municipal_elections
    for table, filename, section, module in [
            ('electoral_area', 'electoral-2026-09.json', 'electoral', electoral),
            ('municipal_electoral_area', 'municipal-elections-2026-09.json', 'municipal_elections', municipal_elections)]:
        plan = read_json(ROOT / filename)
        pending = {r['record']['source'] for r in rows.get(table, {}).values()
                   if r['record']['assignment_status'] == 'unreviewed_repair'}
        for key in sorted(pending):
            spec = plan['sources'][key]
            require(data.report[section]['sources'][key]['sha256'] == spec['sha256'], 'Electoral source vintage changed.')
            path = local_source(directories, spec['filename'], spec['sha256'])
            if path is None:
                continue
            loaded = module.read_source(path, spec)
            require(sha256(path) == spec['sha256'], 'Electoral source changed during review.')
            for edition in plan['editions']:
                if key not in edition['sources']:
                    continue
                if table == 'electoral_area':
                    shapes = {f"ca-{edition['id']}-{item.code.lower()}": item.geometry for item in loaded}
                else:
                    shapes = {f"ca-{edition['id']}-{code}": full
                              for _, code, _, full, _, _ in module.district_rows(loaded, spec, edition)}
                yield table, key, spec['sha256'], 'EPSG:4326', shapes


def surface_checks(original, candidate, neighbours, *, crs):
    """Conservative topology-only rule; no fixed buffers or coordinate rounding.

    Neighbours are valid original polygons in the SAME source scheme. Unreviewed
    neighbouring candidates may measure conflicts but cannot corroborate holes.
    """
    metric = (lambda g: g) if crs == 'EPSG:3347' else lambda g: transform(METRIC, g)
    repaired = shapely.make_valid(original)
    area = metric(candidate).area
    changed_holes = (sum(len(p.interiors) for p in polygon_parts(original)) !=
                     sum(len(p.interiors) for p in polygon_parts(candidate)))
    checks = {
        'polygon_source': original.geom_type in {'Polygon', 'MultiPolygon'},
        'invalid_source': not original.is_valid,
        'valid_polygon_candidate': geometry_issue(candidate) is None,
        'boundary_unchanged': original.boundary is not None and original.boundary.equals(candidate.boundary),
        'no_discarded_coordinates': shapely.get_num_coordinates(repaired) == shapely.get_num_coordinates(candidate),
        'buffer_zero_agrees': candidate.equals(original.buffer(0)),
        'structure_agrees': candidate.equals(shapely.make_valid(original, method='structure')),
    }
    # Only a round-off bound, never a licence to remove small territories. The
    # edge and independent-hole checks are required even below this bound.
    delta = metric(candidate).area - metric(original).area
    checks['area_roundoff_only'] = abs(delta) <= max(1e-6, area * 1e-12)
    valid = {uid: g for uid, g in neighbours.items() if g is not None and not geometry_issue(g)}
    holes = [Polygon(ring) for p in polygon_parts(candidate) for ring in p.interiors]
    original_holes = [Polygon(ring) for p in polygon_parts(original) for ring in p.interiors
                      if Polygon(ring).is_valid]
    corroboration = []
    if changed_holes:
        for hole in holes:
            unchanged = next((old for old in original_holes if hole.equals(old) and hole.boundary.equals(old.boundary)), None)
            if unchanged is not None:
                corroboration.append({'basis': 'unchanged_source_hole', 'sha256': hashlib.sha256(unchanged.wkb).hexdigest()})
                continue
            # A publisher feature may contain separate islands in several
            # exclusions. Match complete components, never intersections/clips.
            matches = {uid: [p for p in polygon_parts(g) if hole.covers(p)] for uid, g in valid.items()}
            matches = {uid: parts for uid, parts in matches.items() if parts}
            union = shapely.union_all([p for parts in matches.values() for p in parts])
            if matches and hole.equals(union) and hole.boundary.equals(union.boundary):
                corroboration.append({'basis': 'same_source_complete_components', 'ids': sorted(matches),
                    'sha256': {uid: hashlib.sha256(valid[uid].wkb).hexdigest() for uid in sorted(matches)},
                    'component_sha256': {uid: sorted(hashlib.sha256(p.wkb).hexdigest() for p in parts)
                                         for uid, parts in sorted(matches.items())}})
        checks['exclusions_corroborated'] = bool(holes) and len(corroboration) == len(holes)
    else:
        checks['exclusions_corroborated'] = True
    overlaps = []
    unresolved_neighbours = []
    for uid, other in neighbours.items():
        if other is None or not candidate.intersects(other.envelope):
            continue
        if geometry_issue(other):
            other, _ = propose_repair(other)
            if other is None or geometry_issue(other):
                unresolved_neighbours.append(uid)
                continue
        intersection = candidate.intersection(other)
        overlap = (intersection.area if crs == 'EPSG:3347' else metric_wgs84_delta(intersection).area)
        if overlap > 0:
            overlaps.append({'id': uid, 'area_m2': overlap})
    total = sum(r['area_m2'] for r in overlaps)
    checks['neighbour_overlap_bounded'] = not unresolved_neighbours and total <= MAX_OVERLAP_M2 and total <= area * MAX_OVERLAP_FRACTION
    return {'checks': {k: bool(v) for k, v in checks.items()}, 'candidate_area_m2': area, 'area_change_m2': delta,
            'changed_hole_count': changed_holes, 'exclusion_evidence': corroboration,
            'neighbour_overlaps': sorted(overlaps, key=lambda r: r['id']),
            'unresolved_neighbours': sorted(unresolved_neighbours), 'overlap_area_m2': total,
            'measurement_crs': 'EPSG:3347'}


def within_corridor(geometry, boundary):
    """Whole-component displacement proof, localized to avoid enormous buffers."""
    if geometry.is_empty:
        return True
    if geometry.geom_type.startswith('Multi') or geometry.geom_type == 'GeometryCollection':
        return all(within_corridor(part, boundary) for part in geometry.geoms)
    nearby = boundary.intersection(geometry.envelope.buffer(MAX_MINOR_DISTANCE_M))
    return bool(nearby.buffer(MAX_MINOR_DISTANCE_M).covers(geometry))


def current_overlap_correction(candidate, owners, prior_affected=0):
    """Resolve tiny serving-CRS slivers after the source repair has qualified."""
    fixed = candidate.difference(shapely.union_all([owners[uid] for uid in sorted(owners)]))
    if geometry_issue(fixed):
        return fixed, {'checks': {'valid_corrected_polygon': False}, 'overlap_owner_ids': sorted(owners)}
    before, after = transform(METRIC, candidate), transform(METRIC, fixed)
    # Intersect/difference in the assignment CRS first. Projecting two shapes
    # with different segment vertices first can invent strips along long edges.
    delta = metric_wgs84_delta(candidate.symmetric_difference(fixed))
    limit = min(MAX_MINOR_AREA_M2, before.area * MAX_MINOR_AREA_FRACTION)
    residual = sum(metric_wgs84_delta(fixed.intersection(g)).area for g in owners.values())
    checks = {'valid_corrected_polygon': geometry_issue(fixed) is None,
              'correction_area_bounded': delta.area + prior_affected <= limit,
              'movement_bounded': within_corridor(transform(METRIC, fixed.boundary.difference(candidate.boundary)), before.boundary)
                                 and within_corridor(transform(METRIC, candidate.boundary.difference(fixed.boundary)), after.boundary),
              'removed_territory_near_source_boundary': within_corridor(delta, before.boundary)}
    checks['current_neighbours_compatible'] = residual <= min(MAX_OVERLAP_M2, before.area * MAX_OVERLAP_FRACTION)
    return fixed, {'checks': checks, 'area_limit_m2': limit, 'max_boundary_movement_m': MAX_MINOR_DISTANCE_M,
                   'overlap_owner_ids': sorted(owners), 'correction_area_m2': delta.area,
                   'residual_overlap_area_m2': residual,
                   'total_affected_area_m2': delta.area + prior_affected,
                   'method': 'qualified candidate; current validated neighbours retain shared slivers'}


def minor_correction(original, candidate, neighbours, crs, evidence):
    """Operator-authorized small corrections with explicit displacement/area caps.

    Preserve existing valid neighbours; give them ownership of tiny overlap
    slivers by subtracting their complete polygons from the pending candidate.
    Never adjust an already validated assignment or arbitrate two pending peers.
    """
    metric = (lambda g: g) if crs == 'EPSG:3347' else lambda g: transform(METRIC, g)
    limit = min(MAX_MINOR_AREA_M2, metric(candidate).area * MAX_MINOR_AREA_FRACTION)
    checks = {'polygon_source': original.geom_type in {'Polygon', 'MultiPolygon'},
              'invalid_source': not original.is_valid, 'valid_polygon_candidate': not geometry_issue(candidate),
              'source_area_change_bounded': abs(evidence['area_change_m2']) <= limit}
    overlaps = {r['id']: r['area_m2'] for r in evidence['neighbour_overlaps']}
    checks['overlap_correction_bounded'] = sum(overlaps.values()) <= limit and not evidence['unresolved_neighbours']
    checks['overlap_owners_valid'] = all(not geometry_issue(neighbours[uid]) for uid in overlaps)
    details = {'checks': checks, 'area_limit_m2': limit, 'max_boundary_movement_m': MAX_MINOR_DISTANCE_M,
               'overlap_owner_ids': sorted(overlaps), 'method': 'existing linework candidate; valid neighbours retain shared slivers'}
    if not all(checks.values()):
        return candidate, details
    fixed = candidate.difference(shapely.union_all([neighbours[uid] for uid in sorted(overlaps)])) if overlaps else candidate
    checks['valid_corrected_polygon'] = geometry_issue(fixed) is None
    if not checks['valid_corrected_polygon']:
        return candidate, details
    original_holes = [Polygon(r) for p in polygon_parts(original) for r in p.interiors if Polygon(r).is_valid]
    unproven = []
    for p in polygon_parts(candidate):
        for ring in p.interiors:
            hole = Polygon(ring)
            if any(hole.equals(old) for old in original_holes):
                continue
            pieces = [part for g in neighbours.values() if g is not None and not geometry_issue(g)
                      for part in polygon_parts(g) if hole.covers(part)]
            if not pieces or not hole.equals(shapely.union_all(pieces)):
                unproven.append(metric(hole))
    small_holes = shapely.union_all(unproven)
    details['unproven_exclusion_area_m2'] = small_holes.area
    if small_holes.area > limit:
        checks['unproven_exclusions_minor'] = False
        return candidate, details
    metric_original = metric(original); metric_fixed = metric(fixed)
    # Only buffer the boundary near a changed component, never a complete
    # northern municipality. Proof corridors are never output geometry.
    missing_lines = metric(original.boundary.difference(fixed.boundary))
    added_lines = metric(fixed.boundary.difference(original.boundary))
    checks['movement_bounded'] = (within_corridor(added_lines, metric_original.boundary)
                                  and within_corridor(missing_lines, metric_fixed.boundary))
    measure_change = (lambda g: g) if crs == 'EPSG:3347' else metric_wgs84_delta
    difference = measure_change(candidate.symmetric_difference(fixed))
    checks['correction_area_bounded'] = difference.area <= limit and within_corridor(difference, metric_original.boundary)
    alternatives = [original.buffer(0), shapely.make_valid(original, method='structure')]
    disagreements = [measure_change(fixed.symmetric_difference(g)) for g in alternatives]
    disagreement = shapely.union_all(disagreements)
    checks['method_disagreement_bounded'] = disagreement.area <= limit and within_corridor(disagreement, metric_original.boundary)
    checks['unproven_exclusions_minor'] = small_holes.area <= limit and within_corridor(small_holes, metric_original.boundary)
    details.update(checks={k: bool(v) for k, v in checks.items()},
                   correction_area_m2=difference.area, method_disagreement_m2=disagreement.area,
                   unproven_exclusion_area_m2=small_holes.area)
    # Shapely covers(empty) is false; an empty difference means nothing moved.
    checks = details['checks']
    if difference.is_empty: checks['correction_area_bounded'] = True
    if disagreement.is_empty: checks['method_disagreement_bounded'] = True
    if small_holes.is_empty: checks['unproven_exclusions_minor'] = True
    affected = shapely.union_all([difference, disagreement, small_holes])
    checks['total_affected_area_bounded'] = affected.area <= limit
    details['total_affected_area_m2'] = affected.area
    return fixed, details


def audit(data, *, directories=(), statcan=None, progress=None):
    rows = load_rows(data)
    inventory = []
    by_key = {}
    candidates = {}
    for table, members in rows.items():
        for uid, row in members.items():
            record = row['record']
            if not record['assignment_status'].startswith('unreviewed') and record['assignment_status'] != 'missing_geometry':
                continue
            api_id = 'ca-csd-' + uid if table == 'csd' else uid
            live = data.areas.get(api_id, {})
            item = {'table': table, 'id': uid, 'api_id': api_id, 'name': record['name'],
                    'status': record['assignment_status'], 'edition': record.get('edition'),
                    'edition_status': live.get('edition_status'), 'lifecycle_status': live.get('lifecycle_status', 'active'),
                    'record_sha256': digest(record), 'decision': 'retain_unapproved',
                    'reasons': ['derived_members_pending' if table == 'region' else
                                'source_snapshot_unavailable' if record['assignment_status'] == 'unreviewed_repair' else
                                'source_relationship_review_required' if record['assignment_status'].startswith('unreviewed') else
                                'missing_source_geometry']}
            inventory.append(item); by_key[table, uid] = item
    for table, key, source_hash, crs, shapes in source_groups(data, rows, directories, statcan):
        pending = [uid for uid in shapes if (table, uid) in by_key and by_key[table, uid]['status'] == 'unreviewed_repair']
        for uid in pending:
            if progress:
                progress(table, uid)
            item = by_key[table, uid]; row = rows[table][uid]; record = row['record']
            original = shapes[uid]
            candidate, ledger = propose_repair(original)
            require(candidate is not None and not geometry_issue(candidate), 'Unexpected failed repair candidate.')
            if table == 'electoral_area' or (table == 'municipal_electoral_area' and
                    record['repair'].get('method', '').endswith('in EPSG:4326; area measurements in EPSG:3347')):
                ledger['method'] += ' in EPSG:4326; area measurements in EPSG:3347'
                ledger['source_area_m2'] = transform(METRIC, original).area
                ledger['candidate_area_m2'] = transform(METRIC, candidate).area
                ledger['area_change_m2'] = ledger['candidate_area_m2'] - ledger['source_area_m2']
            require(ledger == record['repair'], f'Source/candidate ledger changed: {uid}')
            full = transform(WGS84, candidate) if crs == 'EPSG:3347' else candidate
            require(not geometry_issue(full), 'Projected candidate is invalid.')
            if 'repair_candidate' in row:
                require(full.wkb == row['repair_candidate'], f'Stored candidate changed: {uid}')
            # Spatial filtering is only an optimization; every same-scheme
            # neighbour intersecting the candidate envelope is considered.
            nearby = {other_id: g for other_id, g in shapes.items() if other_id != uid and g is not None
                      and candidate.envelope.intersects(g.envelope)}
            evidence = surface_checks(original, candidate, nearby, crs=crs)
            reasons = [k for k, passed in evidence['checks'].items() if not passed]
            decision = 'approve_topology_only'
            if reasons:
                corrected, minor = minor_correction(original, candidate, nearby, crs, evidence)
                evidence['minor_correction'] = minor
                if all(minor['checks'].values()):
                    full = transform(WGS84, corrected) if crs == 'EPSG:3347' else corrected
                    require(not geometry_issue(full), 'Corrected projection is invalid.')
                    decision = 'approve_minor_correction'; reasons = []
            if table == 'city_area':
                parent_id = data.areas[uid]['parent_id']; parent = data.geometries.get(parent_id)
                outside = transform(METRIC, full).difference(transform(METRIC, parent)).area if parent is not None else None
                evidence['parent_outside_m2'] = outside
                if outside is None or outside > MAX_OVERLAP_M2 or outside > evidence['candidate_area_m2'] * MAX_OVERLAP_FRACTION:
                    reasons.append('parent_extent_review_required')
            api_id = item['api_id']
            current = data.areas.get(api_id, {})
            conflicts = []
            for index in data.tree.query(full, predicate='intersects'):
                other_id = data.geometry_ids[int(index)]; other = data.areas[other_id]
                if other_id == api_id or other['level'] != current.get('level'):
                    continue
                if other.get('layer', 'administrative') != current.get('layer', 'administrative'):
                    continue
                if table == 'city_area' and (other.get('scheme') != current.get('scheme') or
                        other.get('municipality_id') != current.get('municipality_id')):
                    continue
                if table in {'electoral_area', 'municipal_electoral_area'} and other.get('edition') != current.get('edition'):
                    continue
                area = metric_wgs84_delta(full.intersection(data.geometries[other_id])).area
                if area > 0:
                    conflicts.append({'id': other_id, 'area_m2': area})
            evidence['current_assignment_overlaps'] = sorted(conflicts, key=lambda r: r['id'])
            total_overlap = sum(r['area_m2'] for r in conflicts)
            if total_overlap > MAX_OVERLAP_M2 or total_overlap > evidence['candidate_area_m2'] * MAX_OVERLAP_FRACTION:
                corrected = None
                if not reasons and total_overlap <= min(MAX_MINOR_AREA_M2, evidence['candidate_area_m2'] * MAX_MINOR_AREA_FRACTION):
                    previous = evidence.get('minor_correction')
                    corrected, correction = current_overlap_correction(full,
                        {r['id']: data.geometries[r['id']] for r in conflicts},
                        previous.get('total_affected_area_m2', 0) if previous else 0)
                    evidence['current_overlap_correction'] = correction
                    if all(correction['checks'].values()):
                        if previous: evidence['source_minor_correction'] = previous
                        evidence['minor_correction'] = correction
                        full = corrected; decision = 'approve_minor_correction'
                    else:
                        corrected = None
                if corrected is None:
                    reasons.append('current_assignment_conflict')
            if data.areas.get(api_id, {}).get('lifecycle_status') == 'superseded' or api_id not in data.areas:
                reasons.append('inactive_identity')
            if api_id in data.geometries:
                reasons.append('assignment_overridden_by_later_revision')
            if table == 'csd' and api_id in data.populations and data.populations[api_id]['metadata']['population'] is not None:
                reasons.append('population_match_requires_review')
            item.update(source=key, source_sha256=source_hash, source_geometry_sha256=ledger['source_sha256'],
                        candidate_sha256=ledger['candidate_sha256'], assignment_sha256=hashlib.sha256(full.wkb).hexdigest(),
                        evidence=evidence, decision='retain_unapproved' if reasons else decision, reasons=reasons)
            if not reasons:
                candidates[table, uid] = full
    result = {'contract': POLICY, 'dataset_version': data.version,
              'runtime': {'shapely': shapely.__version__, 'geos': shapely.geos_version_string},
              'policy': {'max_overlap_m2': MAX_OVERLAP_M2, 'max_overlap_fraction': MAX_OVERLAP_FRACTION,
                         'max_minor_distance_m': MAX_MINOR_DISTANCE_M, 'max_minor_area_m2': MAX_MINOR_AREA_M2,
                         'max_minor_area_fraction': MAX_MINOR_AREA_FRACTION,
                         'measurement_segment_degrees': MEASUREMENT_SEGMENT_DEGREES,
                         'scope': 'topology_only; source vintage, licensing and coverage qualifications remain'},
              'counts': dict(Counter(i['decision'] for i in inventory)), 'inventory': inventory}
    return result, candidates


def update_reports(report, rows, changed):
    """Update current availability counts; retain historical source measurements."""
    statuses = Counter(r['record']['assignment_status'] for r in rows['csd'].values())
    report['valid_geometry_count'] = statuses['validated_source'] + statuses['validated_derived']
    report['repair_candidate_count'] = statuses['unreviewed_repair']
    if 'regions' in report:
        report['regions']['geometry_status_counts'] = dict(Counter(r['record']['assignment_status'] for r in rows.get('region', {}).values()))
    approved_csd = {uid for table, uid in changed if table == 'csd'}
    parts = [report.get('quebec_refresh', {}), report.get('ontario_refresh', {}),
             *report.get('jurisdiction_refreshes', {}).values()]
    for part in parts:
        for review in part.get('repair_review', []):
            if review.get('csd_id') in approved_csd:
                review.setdefault('prior_topology_review', copy.deepcopy(review))
                review.update(status='reviewed_topology_batch', decision='approved_in_batch',
                              reason='See boundary_review for exact checks, source pins and decision tier.')
        for unresolved in part.get('unresolved', []):
            if not isinstance(unresolved, dict):
                continue  # Older source reports also contain narrative notes.
            ids = unresolved.get('ids')
            if isinstance(ids, list) and 'repair' in unresolved.get('scope', '').lower():
                unresolved['ids'] = [u for u in ids if u.removeprefix('ca-csd-') not in approved_csd]
                unresolved['reason'] = 'Remaining source repairs require review; resolved IDs are recorded in boundary_review.'
    for part in [report.get('ontario_refresh', {}), *report.get('jurisdiction_refreshes', {}).values(),
                 {'coverage': report.get('city_areas', {}).get('municipalities', [])}]:
        for scope in part.get('coverage', []):
            members = [r for r in rows.get('city_area', {}).values()
                       if r['record'].get('source') == scope.get('source')
                       and r['record'].get('kind') == scope.get('kind')]
            if not members or not any(('city_area', r['id']) in changed for r in members):
                continue
            scope.setdefault('prior_topology_counts', {k: scope[k] for k in
                ('assignment_boundary_count', 'unapproved_repair_count', 'assignment_sibling_overlap_m2') if k in scope})
            scope['assignment_boundary_count'] = sum(r['geometry'] is not None for r in members)
            scope['unapproved_repair_count'] = sum(r['record']['assignment_status'] == 'unreviewed_repair' for r in members)
            scope['coverage_measure_includes_unapproved_candidates'] = scope['assignment_boundary_count'] != scope['expected_count']
            covered = Polygon(); overlap = 0.0
            for row in sorted(members, key=lambda r: r['id']):
                if row['geometry'] is None:
                    continue
                shape = shapely.from_wkb(row['geometry'])
                overlap += metric_wgs84_delta(covered.intersection(shape)).area
                covered = shapely.union_all([covered, shape])
            scope['assignment_sibling_overlap_m2'] = overlap
    for table, section in [('electoral_area', 'electoral'), ('municipal_electoral_area', 'municipal_elections')]:
        if section not in report:
            continue
        for edition, validation in report[section]['validation'].items():
            members = [r for r in rows[table].values() if r['record']['edition'] == edition]
            validation['unavailable_count'] = sum(r['geometry'] is None for r in members)
        for edition, provinces in report[section].get('edition_coverage', {}).items():
            for province, item in provinces.items():
                item['unavailable_count'] = sum(r['geometry'] is None for r in rows[table].values()
                    if r['record']['edition'] == edition and r['record']['province'] == province)
        # Other coverage fields carry source/vintage declarations. Only the
        # derived missing counts change; the loader rederives current coverage.
        for scope in report[section].get('coverage', {}).values():
            scopes = [scope] if section == 'municipal_elections' else scope.values()
            for item in scopes:
                editions = item.get('default_editions', item.get('editions', [item.get('edition')]))
                item['unavailable_count'] = sum(r['geometry'] is None for r in rows[table].values()
                                               if r['record']['edition'] in editions
                                               and (section == 'municipal_elections' or r['record']['province'] in scope and scope[r['record']['province']] is item))


def assignment_checks(before, after, approved_ids):
    """Exercise components, exclusions and metre-scale boundary neighbourhoods.

    This checks implementation impact, not an independent legal survey. No query
    coordinates or private venue data are persisted in the result.
    """
    added = set(after.geometries) - set(before.geometries)
    results = []
    for uid in sorted(approved_ids):
        full = after.geometries[uid]; row = after.areas[uid]
        layer = row.get('layer', 'administrative')
        args = {'layers': [layer]}
        if layer != 'administrative':
            args['editions'] = {layer: [row['edition']]}
        probes = []
        for part in polygon_parts(full):
            probes.append(part.representative_point())
            probes.extend(Polygon(r).representative_point() for r in part.interiors)
            metric = transform(METRIC, part)
            for fraction in (0, .25, .5, .75):
                edge = metric.exterior.interpolate(fraction, normalized=True)
                probes.extend(transform(WGS84, Point(edge.x + dx, edge.y + dy))
                              for dx, dy in ((0, 0), (.1, 0), (-.1, 0), (0, .1), (0, -.1)))
        changed = 0; introduced = 0; exclusions = 0
        for point in probes:
            require(math.isfinite(point.x) and math.isfinite(point.y), 'Nonfinite assignment probe.')
            old = before.lookup(point.x, point.y, **args)
            new = after.lookup(point.x, point.y, **args)
            old_ids, new_ids = set(old['direct_match_ids']), set(new['direct_match_ids'])
            require(old_ids <= new_ids and new_ids - old_ids <= added, 'Repair changed an existing assignment.')
            require((uid in new_ids) == full.covers(point) and uid not in new['review_candidate_ids'],
                    'Repaired assignment or uncertainty index differs from the approved polygon.')
            changed += old_ids != new_ids
            introduced += uid in new_ids and uid not in old_ids
            exclusions += not full.covers(point)
        results.append({'id': uid, 'probes': len(probes), 'changed_match_sets': changed,
                        'new_direct_matches': introduced, 'outside_or_exclusion_probes': exclusions,
                        'existing_assignments_preserved': True})
    return {'areas': results, 'probe_count': sum(r['probes'] for r in results),
            'method': 'component/hole representative points and shell samples offset by 0.1 projected metres',
            'limitations': 'finite regression probes; independent territory proof is in the topology audit'}


def apply_review(data, output, expected_audit, *, directories=(), statcan=None, progress=None):
    """Recompute the evidence and atomically derive a new pre-package release."""
    from .dataset import Dataset
    from .display_packages import require_unprepared
    from .population import territory_fingerprint, digest as population_digest
    require_unprepared(data)
    require(not Path(output).resolve().is_relative_to(data.root), 'Output must be outside the immutable input release.')
    result, candidates = audit(data, directories=directories, statcan=statcan, progress=progress)
    require(result == expected_audit, 'Audit differs from the reviewed evidence; rerun review before applying.')
    require(candidates, 'No repairs satisfy the approval policy.')
    rows = load_rows(data)
    audit_hash = digest(result)
    approved = {(i['table'], i['id']): i for i in result['inventory'] if i['decision'] in APPROVALS}
    updated_population = copy.deepcopy(data.populations)
    fingerprint_data = copy.copy(data)
    fingerprint_data.areas = copy.deepcopy(data.areas)
    fingerprint_data.geometries = dict(data.geometries)
    changed_ids = {i['api_id'] for i in approved.values()}
    retained_pending = [(u, g) for u, g in zip(data.pending_ids, data.pending_shapes) if u not in changed_ids]
    fingerprint_data.pending_ids = [u for u, _ in retained_pending]
    fingerprint_data.pending_shapes = [g for _, g in retained_pending]
    for (table, uid), full in candidates.items():
        row = rows[table][uid]; record = row['record']; item = approved[table, uid]
        original_issues = record.get('issues', [])
        record.update(assignment_status='validated_derived', vertices=int(shapely.get_num_coordinates(full)))
        record['issues'] = [s for s in original_issues if not s.startswith('invalid_geometry:') and s != 'Unapproved source repair; display only']
        record.pop('uncertainty_basis', None)
        record['repair'] = {**record['repair'], 'status': 'reviewed_topology_batch', 'original_issues': original_issues,
                            'review': {'contract': POLICY, 'audit_sha256': audit_hash,
                                       'original_record_sha256': item['record_sha256'],
                                       'decision': item['decision'], 'measurement_crs': 'EPSG:3347',
                                       'candidate_area_m2': item['evidence']['candidate_area_m2'],
                                       'area_change_m2': item['evidence']['area_change_m2']}}
        if item['decision'] == 'approve_minor_correction':
            record['repair']['review']['affected_area_m2'] = item['evidence']['minor_correction']['total_affected_area_m2']
        if table == 'municipal_electoral_area' and 'area measurements' not in record['repair']['method']:
            record['repair']['original_measurement_crs'] = 'EPSG:4326; legacy *_m2 fields contain square degrees; use review measurements'
        row['geometry'] = full.wkb
        api_id = item['api_id']
        fingerprint_data.areas[api_id].update(assignment_status='validated_derived', repair=record['repair'])
        fingerprint_data.areas[api_id].pop('uncertainty_basis', None)
        fingerprint_data.geometries[api_id] = full
        if api_id in updated_population:
            pop = updated_population[api_id]
            require(pop['metadata']['population'] is None and 'source' not in pop['evidence'], 'A population match requires separate review.')
            # Preserve missing population and its reason. Topology approval does
            # not supply census evidence or infer a population value.
            pop['target_sha256'] = territory_fingerprint(fingerprint_data, api_id)
            pop['evidence']['target_sha256'] = pop['target_sha256']
    regional_changes = {}
    with closing(sqlite3.connect((data.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        membership = list(db.execute('SELECT csd_id, region_id FROM csd_region')) if 'region' in rows else []
    for uid, row in rows.get('region', {}).items():
        if row['record']['assignment_status'] != 'unreviewed_repair' or uid in data.geometries:
            continue
        members = [rows['csd'][u] for u, region in membership if region == uid]
        if not members or not any(('csd', r['id']) in candidates for r in members):
            continue
        missing = sorted(r['id'] for r in members if r['geometry'] is None)
        record = row['record']; record['unreviewed_member_ids'] = missing
        record['issues'] = [s for s in record.get('issues', []) if not s.endswith(
            'member boundaries require review; regional geometry is an unapproved candidate')]
        if not missing:
            union = shapely.union_all([shapely.from_wkb(r['geometry']) for r in members])
            candidate = shapely.from_wkb(row['repair_candidate'])
            if geometry_issue(union) or not union.equals(candidate):
                regional_changes[uid] = 'member_union_differs; separate regional review required'
                record['issues'].append('Reviewed member union differs from stored regional candidate; regional review required')
                continue
            row['geometry'] = candidate.wkb
            prior_evidence = record.get('evidence', {})
            review_evidence = {'batch_topology_audit_sha256': audit_hash}
            evidence = [*prior_evidence, review_evidence] if isinstance(prior_evidence, list) else {**prior_evidence, **review_evidence}
            record.update(assignment_status='validated_derived', evidence=evidence)
            regional_changes[uid] = 'validated_complete_member_union'
        else:
            record['issues'].append(f'{len(missing)} member boundaries require review; regional geometry is an unapproved candidate')
            regional_changes[uid] = 'remaining_unreviewed_members'
    report = copy.deepcopy(data.report)
    if 'boundary_review' in report:
        report.setdefault('boundary_review_history', []).append(report['boundary_review'])
    report['boundary_review'] = result
    report['boundary_review_effects'] = {'audit_sha256': audit_hash, 'regions': regional_changes,
        'population_missing_rebindings': sorted(u for u in changed_ids if u in updated_population)}
    update_reports(report, rows, candidates)
    if updated_population:
        report['population']['records_sha256'] = population_digest(updated_population)
    with new_directory(output) as staging:
        for name, spec in data.manifest['files'].items():
            target = staging / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(data.root / name, target)
            require(sha256(target) == spec['sha256'], 'Input changed during repair release.')
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db, db:
            for table, members in rows.items():
                for uid, row in members.items():
                    if (table, uid) in candidates or table == 'region' and uid in regional_changes:
                        db.execute(f'UPDATE {table} SET record=?, geometry=? WHERE id=?',
                                   (json.dumps(row['record'], ensure_ascii=False), row['geometry'], uid))
            for uid in changed_ids & updated_population.keys():
                db.execute('UPDATE area_population SET record=? WHERE area_id=?',
                           (json.dumps(updated_population[uid], ensure_ascii=False), uid))
        display_status = {uid: 'validated_derived' for _, uid in candidates}
        display_status.update({uid: 'validated_derived' for uid, status in regional_changes.items() if status == 'validated_complete_member_union'})
        for name in data.manifest['files']:
            if not name.startswith('display/'):
                continue
            document = read_json(staging / name, MAX_FILE_BYTES)
            changed = False
            for feature in document['features']:
                uid = feature['properties']['id']
                if uid in display_status:
                    feature['properties']['assignment_status'] = display_status[uid]; changed = True
            if changed:
                write_json(staging / name, document)
        report['catalogue_sha256'] = sha256(staging / 'catalogue.sqlite3')
        write_json(staging / 'report.json', report)
        manifest = {**data.manifest, 'label': 'canada-topology-batch-reviewed-v1', 'files': {
            name: {'bytes': (staging / name).stat().st_size, 'sha256': sha256(staging / name)} for name in data.manifest['files']}}
        write_json(staging / 'manifest.json', manifest)
        verified = Dataset(staging)
        for key, full in candidates.items():
            uid = approved[key]['api_id']
            require(verified.geometries[uid].wkb == full.wkb and uid not in verified.pending_ids,
                    'Approved assignment is absent or still uncertain.')
        for uid, full in data.geometries.items():
            require(verified.geometries[uid].wkb == full.wkb, 'An existing assignment geometry changed.')
        impact = assignment_checks(data, verified, changed_ids)
        report['boundary_review_effects']['assignment_checks'] = impact
        write_json(staging / 'report.json', report)
        manifest['files']['report.json'] = {'bytes': (staging / 'report.json').stat().st_size,
                                            'sha256': sha256(staging / 'report.json')}
        write_json(staging / 'manifest.json', manifest)
        Dataset(staging)  # Verify the final evidence envelope before atomic rename.
    return {'output': str(output), 'dataset_version': sha256(Path(output) / 'manifest.json'),
            'approved': len(candidates), 'regional_changes': regional_changes, 'audit_sha256': audit_hash}
