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
MAX_PROVEN_SLIVER_AREA_M2 = 6000.0
APPROVALS = {'approve_topology_only', 'approve_minor_correction', 'approve_source_child_union'}
MEASUREMENT_SEGMENT_DEGREES = .00001
# The publisher's combined borough/district edition uses borough.district codes.
# This declaration applies only to this exact retained source, never other IDs.
BOROUGH_SOURCE = 'rep-montreal-boroughs-and-districts'
BOROUGH_SHA256 = 'b20f3dbc53857154c423eda0c3b4f766e695f7ab2f9708a647f838261c1dc01e'


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


def metric_linework(geometry, crs):
    if crs == 'EPSG:3347':
        return geometry
    dense = shapely.segmentize(geometry, MEASUREMENT_SEGMENT_DEGREES)
    require(shapely.get_num_coordinates(dense) <= 3_000_000, 'Review linework exceeds its vertex budget.')
    return transform(METRIC, dense)


def validate_inventoried_reviews(db, tables, report):
    """Every inventoried approval requires proof, regardless of record markers.

    Inspect the original stored rows before later, separately verified revisions
    are loaded. Historical batches remain binding on those original rows.
    """
    reviewed = set()
    for batch in [report.get('boundary_review', {}), *report.get('boundary_review_history', [])]:
        for item in batch.get('inventory', []):
            if item.get('decision') not in APPROVALS:
                continue
            table, uid = item.get('table'), item.get('id')
            require(table in TABLES and table in tables and isinstance(uid, str),
                    'Invalid inventoried topology approval identity.')
            require((table, uid) not in reviewed, 'Duplicate inventoried topology approval.')
            row = db.execute(f'SELECT record, geometry FROM {table} WHERE id=?', (uid,)).fetchone()
            require(row is not None and row['geometry'] is not None,
                    'Inventoried topology approval lacks its stored assignment.')
            record = json.loads(row['record'])
            require(record.get('id') == uid and validated_review(record, shapely.from_wkb(row['geometry']), report),
                    'Inventoried topology approval lacks valid audit proof.')
            reviewed.add((table, uid))
    return reviewed


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
    partition = batch.get('csd_exclusion_partition')
    if partition is not None:
        members = partition.get('member_ids', [])
        approvals = [r for r in batch['inventory'] if r['decision'] in APPROVALS]
        require(partition.get('contract') == 'csd-exclusion-partition.v1'
                and members and len(members) == len(set(members))
                and {r['id'] for r in approvals} == set(members) and len(approvals) == len(members)
                and all(r['table'] == 'csd' and r['decision'] == 'approve_topology_only'
                        and r['source_sha256'] == partition.get('source_sha256')
                        and r['candidate_sha256'] == partition.get('candidate_sha256', {}).get(r['id'])
                        and not r['reasons'] and r['evidence']['checks']
                        and all(v is True for v in r['evidence']['checks'].values()) for r in approvals),
                'Incomplete or inconsistent joint municipal exclusion approval.')
    matches = [r for r in batch['inventory'] if r['id'] == record['id'] and r['decision'] in APPROVALS]
    require(len(matches) == 1, 'Reviewed assignment lacks a unique approval.')
    item = matches[0]
    children = item['evidence'].get('source_child_partition', {}).get('child_ids')
    if children is not None or item['decision'] == 'approve_source_child_union':
        hierarchy = batch.get('municipal_hierarchy', {})
        require(hierarchy.get('contract') == 'source-borough-partition.v1'
                and hierarchy.get('source_sha256') == BOROUGH_SHA256
                and item.get('source_sha256') == BOROUGH_SHA256
                and children and len(children) == len(set(children))
                and set(children) == {u for u, change in hierarchy.get('changes', {}).items()
                                      if change['parent_id'] == record['id']},
                'Incomplete source child partition approval.')
    require(partition is not None or not any(p.get('basis') == 'same_source_partition'
            for p in item['evidence'].get('exclusion_evidence', [])),
            'Municipal partition evidence lacks its joint approval.')
    checks = (item['evidence']['checks'] if item['decision'] == 'approve_topology_only' else
              item['evidence']['child_union_checks'] if item['decision'] == 'approve_source_child_union' else
              item['evidence']['minor_correction']['checks'])
    require(item['assignment_sha256'] == hashlib.sha256(geometry.wkb).hexdigest()
            and item['source_geometry_sha256'] == repair.get('source_sha256')
            and item['candidate_sha256'] == repair.get('candidate_sha256')
            and item['record_sha256'] == proof.get('original_record_sha256')
            and proof.get('decision') == item['decision'] and not item['reasons']
            and checks and all(v is True for v in checks.values()),
            'Assignment differs from the approved topology evidence.')
    return True


def validated_parent_review(record, geometry, report, records):
    """Validate a source-proven electoral child without weakening authority checks."""
    proof = record.get('parent_review')
    if not proof:
        return False
    batches = [report.get('boundary_review', {}), *report.get('boundary_review_history', [])]
    matches = [b for b in batches if digest(b) == proof.get('audit_sha256')]
    require(len(matches) == 1, 'Missing reviewed municipal hierarchy audit.')
    batch = matches[0]; hierarchy = batch.get('municipal_hierarchy', {})
    item = hierarchy.get('changes', {}).get(record['id'], {})
    parent = records.get(record.get('parent_id'), {})
    approvals = [a for a in batch['inventory'] if a['id'] == record.get('parent_id') and a['decision'] in APPROVALS]
    original = {k: v for k, v in record.items() if k != 'parent_review'}
    original['parent_id'] = item.get('previous_parent_id')
    require(hierarchy.get('contract') == 'source-borough-partition.v1'
            and hierarchy.get('source') == record.get('source') == BOROUGH_SOURCE
            and hierarchy.get('source_sha256') == BOROUGH_SHA256
            and report['municipal_elections']['sources'][BOROUGH_SOURCE]['sha256'] == BOROUGH_SHA256
            and item.get('parent_id') == record['parent_id']
            and item.get('previous_parent_id') == record['authority_id']
            and parent.get('parent_id') == record['authority_id']
            and parent.get('edition') == record['edition'] and parent.get('source') == record['source']
            and record['source_id'].startswith(parent.get('source_id', '') + '.')
            and len(approvals) == 1 and record['id'] in approvals[0]['evidence']['source_child_partition']['child_ids']
            and digest(original) == item.get('record_sha256')
            and geometry is not None and hashlib.sha256(geometry).hexdigest() == item.get('geometry_sha256'),
            'Municipal child differs from its source partition approval.')
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


def source_groups(data, rows, directories, statcan, *, csd_only=False):
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
    if csd_only:
        return
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


def surface_checks(original, candidate, neighbours, *, crs, partition_members=None):
    """Conservative topology-only rule; no fixed buffers or coordinate rounding.

    Neighbours are from the SAME source scheme. Pending neighbours corroborate
    holes only in the explicit all-or-nothing municipal partition review; its
    caller must verify every member before accepting any individual result.
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
    # Compare the same linear WGS84 edges in the metric CRS. Differently
    # segmented long edges otherwise acquire different projected chords.
    delta = (metric_linework(candidate, crs).area - metric_linework(original, crs).area
             if crs == 'EPSG:4326' else candidate.area - original.area)
    checks['area_roundoff_only'] = abs(delta) <= max(1e-6, area * 1e-12)
    valid = {uid: g for uid, g in neighbours.items() if g is not None and not geometry_issue(g)}
    if partition_members is not None:
        valid.update({uid: g for uid, g in partition_members.items() if uid in neighbours})
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
            islands = shapely.union_all([p for p in polygon_parts(candidate) if hole.covers(p)]) if partition_members is not None else Polygon()
            combined = shapely.union_all([union, islands])
            if (matches and hole.equals(combined) and hole.boundary.equals(combined.boundary)
                    and union.intersection(islands).area == 0):
                proof = {'basis': 'same_source_complete_components', 'ids': sorted(matches),
                    'sha256': {uid: hashlib.sha256(valid[uid].wkb).hexdigest() for uid in sorted(matches)},
                    'component_sha256': {uid: sorted(hashlib.sha256(p.wkb).hexdigest() for p in parts)
                                         for uid, parts in sorted(matches.items())}}
                if partition_members is not None:
                    proof.update(basis='same_source_partition',
                        reviewed_member_ids=sorted(set(matches) & partition_members.keys()),
                        retained_island_area_m2=islands.area,
                        retained_islands_sha256=hashlib.sha256(islands.wkb).hexdigest(),
                        excluded_surface_sha256=hashlib.sha256(hole.difference(islands).wkb).hexdigest())
                corroboration.append(proof)
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


def retraced_segments(original):
    """Exact out-and-back source edges; never infer this from small area."""
    counts = Counter()
    for part in polygon_parts(original):
        for ring in [part.exterior, *part.interiors]:
            coordinates = list(ring.coords)
            for a, b in zip(coordinates, coordinates[1:]):
                if a != b:
                    counts[a, b] += 1
    return shapely.union_all([shapely.LineString([a, b]) for (a, b), count in counts.items()
                              if count == counts[b, a]])


def source_face_proof(original, candidate):
    """Independently classify noded source faces by the even/odd fill rule.

    No neighbour is needed to invent ownership of an exclusion. Each bounded
    face is classified against the original coordinate rings, and the complete
    selected surface must exactly equal both independent repair methods.
    """
    if original.geom_type not in {'Polygon', 'MultiPolygon'}:
        return {'verified': False}
    if not candidate.equals(original.buffer(0)) or not candidate.equals(shapely.make_valid(original, method='structure')):
        return {'verified': False}
    from shapely.ops import polygonize
    import numpy as np
    rings = [list(r.coords) for p in polygon_parts(original) for r in [p.exterior, *p.interiors]]
    edges = np.asarray([(a, b) for ring in rings for a, b in zip(ring, ring[1:])])
    ax, ay, bx, by = edges[:, 0, 0], edges[:, 0, 1], edges[:, 1, 0], edges[:, 1, 1]
    faces = list(polygonize(shapely.node(original.boundary)))
    require(len(faces) <= 50000, 'Source face proof exceeds its face budget.')
    selected = []
    excluded = []
    for face in faces:
        point = face.representative_point(); x, y = point.x, point.y
        crosses = (ay > y) != (by > y)
        intersections = ax[crosses] + (y - ay[crosses]) * (bx[crosses] - ax[crosses]) / (by[crosses] - ay[crosses])
        parity = int(np.count_nonzero(x < intersections)) % 2
        (selected if parity else excluded).append(face)
    surface = shapely.union_all(selected)
    return {'verified': bool(surface.equals(candidate)), 'rule': 'original_ring_even_odd',
            'selected_faces': len(selected), 'excluded_faces': len(excluded),
            'surface_sha256': hashlib.sha256(surface.wkb).hexdigest()}


def relationship_evidence(data, rows, directories, inventory):
    """Measure each unresolved city relationship without inventing parentage."""
    from .jurisdiction_refresh import checked_source
    pending = {i['id']: i for i in inventory if i['table'] == 'city_area'
               and i['status'] in {'unreviewed_parent', 'unreviewed_overlap'}}
    for path in sorted(ROOT.glob('jurisdiction-*-2026-09.json')):
        plan = read_json(path)
        for layer in plan['city_layers']:
            key = layer['source']
            members = {u: r['record'] for u, r in rows.get('city_area', {}).items() if r['record'].get('source') == key}
            if not pending.keys() & members.keys():
                continue
            spec = plan['sources'][key]
            source = local_source(directories, key + '.geojson', spec['sha256'])
            if source is None:
                continue
            shapes = checked_source(source, spec)
            for uid in sorted(pending.keys() & members.keys()):
                item = pending[uid]; record = members[uid]; geometry = shapes[record['source_id']]
                require(not geometry_issue(geometry), 'Relationship source unexpectedly requires a topology repair.')
                parent = data.geometries.get(data.areas[uid]['parent_id'])
                require(parent is not None, 'Relationship review requires the verified parent geometry.')
                outside = geometry.difference(parent)
                others = []
                for index in data.tree.query(outside, predicate='intersects'):
                    other_id = data.geometry_ids[int(index)]
                    if data.areas[other_id]['level'] != 'municipality':
                        continue
                    area = metric_wgs84_delta(outside.intersection(data.geometries[other_id])).area
                    if area > 1:
                        others.append({'id': other_id, 'area_m2': area})
                peers = []
                for other_id, other in sorted(members.items()):
                    if other_id == uid:
                        continue
                    other_geometry = shapes[other['source_id']]
                    if geometry_issue(other_geometry) or not geometry.intersects(other_geometry.envelope):
                        continue
                    area = metric_wgs84_delta(geometry.intersection(other_geometry)).area
                    if area > 1:
                        peers.append({'id': other_id, 'area_m2': area,
                                      'contains_peer': bool(geometry.covers(other_geometry)),
                                      'contained_by_peer': bool(other_geometry.covers(geometry))})
                item['relationship_evidence'] = {'source': key, 'source_sha256': spec['sha256'],
                    'geometry_sha256': hashlib.sha256(geometry.wkb).hexdigest(),
                    'area_m2': metric_wgs84_delta(geometry).area,
                    'parent_outside_m2': metric_wgs84_delta(outside).area,
                    'other_municipalities': sorted(others, key=lambda i: i['id']), 'peer_overlaps': peers,
                    'measurement_crs': 'EPSG:3347'}
                item['reasons'] = (['parent_extent_crosses_other_municipalities' if others else
                                   'parent_extent_unmatched_requires_source_reconciliation'] if item['status'] == 'unreviewed_parent'
                                  else ['contained_peer_requires_semantic_hierarchy' if any(p['contains_peer'] or p['contained_by_peer'] for p in peers)
                                        else 'peer_overlap_requires_ownership_evidence'])


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
    # Larger accumulated strips are admissible only with an independent exact
    # source-surface proof. Width, relative area and valid-owner checks remain.
    ceiling = MAX_PROVEN_SLIVER_AREA_M2 if evidence.get('source_faces', {}).get('verified') else MAX_MINOR_AREA_M2
    limit = min(ceiling, metric(candidate).area * MAX_MINOR_AREA_FRACTION)
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
            if (not evidence.get('source_faces', {}).get('verified')
                    and (not pieces or not hole.equals(shapely.union_all(pieces)))):
                unproven.append(metric(hole))
    small_holes = shapely.union_all(unproven)
    details['unproven_exclusion_area_m2'] = small_holes.area
    if small_holes.area > limit:
        checks['unproven_exclusions_minor'] = False
        return candidate, details
    # Only buffer the boundary near a changed component, never a complete
    # northern municipality. Proof corridors are never output geometry.
    missing = original.boundary.difference(fixed.boundary)
    retraces = retraced_segments(original)
    # Removing exactly balanced out-and-back edges changes no filled surface.
    # The complete surface still undergoes method-disagreement, exclusion and
    # affected-area checks below. Positive-area edits keep all old caps.
    if not retraces.is_empty:
        details['retraced_linework_sha256'] = hashlib.sha256(retraces.wkb).hexdigest()
        missing = missing.difference(retraces)
    original_boundary = metric_linework(original.boundary, crs)
    fixed_boundary = metric_linework(fixed.boundary, crs)
    missing_lines = metric_linework(missing, crs)
    added_lines = metric_linework(fixed.boundary.difference(original.boundary), crs)
    checks['movement_bounded'] = (within_corridor(added_lines, original_boundary)
                                  and within_corridor(missing_lines, fixed_boundary))
    measure_change = (lambda g: g) if crs == 'EPSG:3347' else metric_wgs84_delta
    difference = measure_change(candidate.symmetric_difference(fixed))
    # An isolated small source sliver may disappear completely when
    # its already validated owner retains it. Its old perimeter is not a moved
    # perimeter. Exempt only linework exactly inside that removed surface in
    # the source CRS; projecting differently segmented edges first invents gaps.
    removed = candidate.difference(fixed)
    removed_area = sum(measure_change(p).area for p in polygon_parts(removed))
    if overlaps and removed_area <= MAX_MINOR_AREA_M2 and within_corridor(difference, original_boundary):
        remaining_lines = metric_linework(missing.difference(removed), crs)
        if within_corridor(added_lines, original_boundary) and within_corridor(remaining_lines, fixed_boundary):
            checks['movement_bounded'] = True
            details['owned_sliver_m2'] = removed_area
    checks['correction_area_bounded'] = difference.area <= limit and within_corridor(difference, original_boundary)
    alternatives = [original.buffer(0), shapely.make_valid(original, method='structure')]
    disagreements = [measure_change(fixed.symmetric_difference(g)) for g in alternatives]
    disagreement = shapely.union_all(disagreements)
    checks['method_disagreement_bounded'] = disagreement.area <= limit and within_corridor(disagreement, original_boundary)
    checks['unproven_exclusions_minor'] = small_holes.area <= limit and within_corridor(small_holes, original_boundary)
    details.update(checks={k: bool(v) for k, v in checks.items()},
                   correction_area_m2=difference.area, method_disagreement_m2=disagreement.area,
                   unproven_exclusion_area_m2=small_holes.area)
    # Shapely covers(empty) is false; an empty difference means nothing moved.
    checks = details['checks']
    if difference.is_empty: checks['correction_area_bounded'] = True
    if disagreement.is_empty: checks['method_disagreement_bounded'] = True
    if small_holes.is_empty: checks['unproven_exclusions_minor'] = True
    affected = shapely.union_all([difference, disagreement, small_holes])
    # Near-coincident overlay edges can give a symmetric difference slightly
    # less area than the independently measured removed components. Retain the
    # conservative component sum plus any affected surface outside that removal.
    conservative_area = max(affected.area, removed_area + affected.difference(measure_change(removed)).area)
    checks['total_affected_area_bounded'] = conservative_area <= limit
    details['total_affected_area_m2'] = conservative_area
    return fixed, details


def audit(data, *, directories=(), statcan=None, progress=None, csd_exclusions_only=False):
    rows = load_rows(data)
    inventory = []
    by_key = {}
    candidates = {}
    hierarchy_changes = {}
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
            if csd_exclusions_only and table not in {'csd', 'region'}:
                item['reasons'] = ['outside_review_scope']
    partition = None
    for table, key, source_hash, crs, shapes in source_groups(data, rows, directories, statcan,
                                                           csd_only=csd_exclusions_only):
        if csd_exclusions_only and table != 'csd':
            continue
        pending = [uid for uid in shapes if (table, uid) in by_key and by_key[table, uid]['status'] == 'unreviewed_repair']
        partition_members = None
        if csd_exclusions_only:
            require(crs == 'EPSG:3347' and pending, 'Expected pending native StatCan municipal repairs.')
            partition_members = {}
            for uid, original in shapes.items():
                if original is None or original.is_valid:
                    continue
                row = rows['csd'].get(uid)
                if row is None or (uid not in pending and row['geometry'] is None):
                    continue
                native, ledger = propose_repair(original)
                require(native is not None and not geometry_issue(native), 'Invalid partition member candidate.')
                if uid not in pending:
                    # Previously approved native candidates are evidence only
                    # when they exactly reproduce the loaded assignment bytes.
                    if transform(WGS84, native).wkb != row['geometry']:
                        continue
                    require(ledger['source_sha256'] == row['record'].get('repair', {}).get('source_sha256'),
                            'Reviewed partition owner has different source evidence.')
                partition_members[uid] = native
            partition = {'contract': 'csd-exclusion-partition.v1', 'source_sha256': source_hash,
                         'member_ids': sorted(pending),
                         'previously_reviewed_ids': sorted(partition_members.keys() - set(pending)),
                         'candidate_sha256': {u: hashlib.sha256(partition_members[u].wkb).hexdigest() for u in sorted(pending)}}
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
            children = {}
            child_union_repair = False
            if table == 'municipal_electoral_area' and key == BOROUGH_SOURCE:
                require(source_hash == BOROUGH_SHA256, 'Borough source declaration requires a new review.')
                code = record['source_id']
                if '.' not in code:
                    children = {v: rows[table][v] for v in shapes if v != uid
                                and rows[table][v]['record']['source_id'].startswith(code + '.')}
                    union = shapely.union_all([shapes[v] for v in children])
                    if (not children or any(r['geometry'] is None or r['geometry'] != shapes[v].wkb
                                            for v, r in children.items()) or geometry_issue(union)
                            or not union.equals(original.buffer(0))
                            or not union.equals(shapely.union_all(polygon_parts(shapely.make_valid(original, method='structure'))))):
                        children = {}
                    elif not candidate.equals(union):
                        candidate = union; full = union; child_union_repair = True
                    nearby = {v: g for v, g in nearby.items() if v not in children}
            review_original = original
            assembly = None
            if (table == 'municipal_electoral_area' and original.geom_type == 'GeometryCollection'
                    and record.get('source_parts') == len(original.geoms)
                    and all(g.geom_type in {'Polygon', 'MultiPolygon'} for g in original.geoms)):
                review_original = shapely.MultiPolygon(polygon_parts(original))
                assembly = {'method': 'polygon-only publisher multipart assembly; no coordinate changes',
                            'parts': len(original.geoms),
                            'geometry_sha256': hashlib.sha256(review_original.wkb).hexdigest()}
            evidence = surface_checks(review_original, candidate, nearby, crs=crs, partition_members=partition_members)
            if assembly:
                evidence['source_assembly'] = assembly
            if children:
                evidence['source_child_partition'] = {'child_ids': sorted(children),
                    'method': 'declared borough.district source codes; exact union of unchanged validated child polygons'}
            if not csd_exclusions_only and table != 'csd':
                proof = source_face_proof(review_original, candidate)
                evidence['source_faces'] = proof
                if proof['verified']:
                    evidence['checks']['exclusions_corroborated'] = True
            reasons = [k for k, passed in evidence['checks'].items() if not passed]
            decision = 'approve_topology_only'
            if child_union_repair:
                checks = {k: evidence['checks'][k] for k in
                          ('valid_polygon_candidate', 'buffer_zero_agrees', 'structure_agrees', 'neighbour_overlap_bounded')}
                checks['exact_validated_child_union'] = full.equals(shapely.union_all([shapes[v] for v in children]))
                evidence['child_union_checks'] = checks
                reasons = [k for k, passed in checks.items() if not passed]
                decision = 'approve_source_child_union'
            elif reasons and not csd_exclusions_only:
                corrected, minor = minor_correction(review_original, candidate, nearby, crs, evidence)
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
                if other_id in children:
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
                if not csd_exclusions_only and not reasons and total_overlap <= min(MAX_MINOR_AREA_M2, evidence['candidate_area_m2'] * MAX_MINOR_AREA_FRACTION):
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
                for child_id, child in children.items():
                    require(child_id not in hierarchy_changes, 'Conflicting reviewed parents.')
                    hierarchy_changes[child_id] = {'parent_id': uid, 'previous_parent_id': child['record']['parent_id'],
                        'record_sha256': digest(child['record']), 'geometry_sha256': hashlib.sha256(child['geometry']).hexdigest()}
    if csd_exclusions_only:
        # Mutual corroboration is a joint proof, not individual tentative
        # approvals: every member must independently pass all other checks.
        require(partition is not None and set(candidates) == {('csd', u) for u in partition['member_ids']},
                'Municipal exclusion partition is incomplete; no joint approvals can be applied.')
        # Native partition proofs must also remain compatible after projection
        # into the serving CRS. Pending peers are absent from data.tree above.
        for (_, uid), full in candidates.items():
            overlap = sum(metric_wgs84_delta(full.intersection(other)).area
                          for (_, other_id), other in candidates.items()
                          if other_id != uid and full.envelope.intersects(other.envelope))
            area = by_key['csd', uid]['evidence']['candidate_area_m2']
            require(overlap <= min(MAX_OVERLAP_M2, area * MAX_OVERLAP_FRACTION),
                    'Joint municipal assignments overlap after projection.')
    if not csd_exclusions_only:
        relationship_evidence(data, rows, directories, inventory)
    result = {'contract': POLICY, 'dataset_version': data.version,
              'runtime': {'shapely': shapely.__version__, 'geos': shapely.geos_version_string},
              'policy': {'max_overlap_m2': MAX_OVERLAP_M2, 'max_overlap_fraction': MAX_OVERLAP_FRACTION,
                         'max_minor_distance_m': MAX_MINOR_DISTANCE_M, 'max_minor_area_m2': MAX_MINOR_AREA_M2,
                         'max_minor_area_fraction': MAX_MINOR_AREA_FRACTION,
                         'max_proven_sliver_area_m2': MAX_PROVEN_SLIVER_AREA_M2,
                         'measurement_segment_degrees': MEASUREMENT_SEGMENT_DEGREES,
                         'scope': 'topology_only; source vintage, licensing and coverage qualifications remain'},
              'counts': dict(Counter(i['decision'] for i in inventory)), 'inventory': inventory}
    if partition is not None:
        result['csd_exclusion_partition'] = partition
    if hierarchy_changes:
        result['municipal_hierarchy'] = {'contract': 'source-borough-partition.v1',
            'source': BOROUGH_SOURCE, 'source_sha256': BOROUGH_SHA256, 'changes': hierarchy_changes}
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


def apply_review(data, output, expected_audit, *, directories=(), statcan=None, progress=None, csd_exclusions_only=False):
    """Recompute the evidence and atomically derive a new pre-package release."""
    from .dataset import Dataset
    from .display_packages import require_unprepared
    from .population import territory_fingerprint, digest as population_digest
    require_unprepared(data)
    require(not Path(output).resolve().is_relative_to(data.root), 'Output must be outside the immutable input release.')
    result, candidates = audit(data, directories=directories, statcan=statcan, progress=progress,
                               csd_exclusions_only=csd_exclusions_only)
    require(result == expected_audit, 'Audit differs from the reviewed evidence; rerun review before applying.')
    require(candidates, 'No repairs satisfy the approval policy.')
    rows = load_rows(data)
    audit_hash = digest(result)
    approved = {(i['table'], i['id']): i for i in result['inventory'] if i['decision'] in APPROVALS}
    hierarchy_changes = result.get('municipal_hierarchy', {}).get('changes', {})
    for child_id, item in hierarchy_changes.items():
        child = rows['municipal_electoral_area'][child_id]['record']
        child.update(parent_id=item['parent_id'], parent_review={'audit_sha256': audit_hash})
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
                    if ((table, uid) in candidates or table == 'region' and uid in regional_changes
                            or table == 'municipal_electoral_area' and uid in hierarchy_changes):
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
                    item = approved.get(('municipal_electoral_area', uid), {})
                    if item.get('decision') == 'approve_source_child_union':
                        full = candidates['municipal_electoral_area', uid]
                        tolerance = report['municipal_elections']['display_tolerance_metres']
                        display = transform(WGS84, transform(METRIC, full).simplify(tolerance, preserve_topology=True))
                        if geometry_issue(display):
                            display = full
                        feature['geometry'] = shapely.geometry.mapping(display)
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
