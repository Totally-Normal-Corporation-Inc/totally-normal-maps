"""Apply the narrowly evidenced La Romaine ring repair to a new serving release.

This is not a general repair approval switch. Both the parent release and exact
original/candidate/enclave geometries are pinned; all other reviews are retained.
"""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from pyogrio.raw import read
from pyproj import Transformer
import shapely
from shapely.geometry import Polygon, mapping
from shapely.ops import transform

from .catalogue import (CatalogueError, ROOT, geometry_issue, new_directory,
                        propose_repair, read_json, sha256, source_uri, write_json)
from .dataset import Dataset
from .releases import MAX_FILE_BYTES, checked_release

PLAN = ROOT / 'topology-review-2026-09.json'


def validate_ring_repair(original, enclave, review):
    """Require exact same-source corroboration, not merely similar area totals."""
    candidate, metrics = propose_repair(original)
    if (original.geom_type != 'Polygon' or original.is_valid or len(original.interiors) != 1
            or candidate is None or geometry_issue(candidate) or candidate.geom_type != 'Polygon'
            or len(candidate.interiors) != 2 or geometry_issue(enclave)
            or metrics['source_sha256'] != review['source_sha256']
            or metrics['candidate_sha256'] != review['candidate_sha256']
            or hashlib.sha256(enclave.wkb).hexdigest() != review['enclave']['sha256']):
        raise CatalogueError('Ring repair differs from the reviewed source/candidate/enclave.')
    holes = shapely.union_all([Polygon(ring) for ring in candidate.interiors])
    if (metrics['area_change_m2'] != 0 or metrics['nonpolygon_vertices'] != 0
            or not original.exterior.equals(candidate.exterior)
            or not candidate.equals(original.buffer(0))
            or not holes.equals(enclave) or not holes.boundary.equals(enclave.boundary)
            or not Polygon(original.interiors[0]).boundary.equals(enclave.boundary)):
        raise CatalogueError('Repair changes territory or lacks exact enclave corroboration.')
    return candidate, metrics


def reviewed_source(source, review):
    manifest = read_json(ROOT / 'statcan-2025.json')
    result = read(source_uri(source, manifest), layer=manifest['layer'],
                  columns=['CSDUID', 'CSDNAME'],
                  where="CSDUID IN ('2498015', '2498804')")
    names = dict(zip(result[3][0], result[3][1]))
    raw = {uid: shapely.from_wkb(wkb) for uid, wkb in zip(result[3][0], result[2])}
    if (names != {review['csd_id']: review['name'], review['enclave_id']: review['enclave_name']}
            or result[0]['crs'] != manifest['crs']):
        raise CatalogueError('Unexpected source identity or projection.')
    candidate, metrics = validate_ring_repair(raw[review['csd_id']], raw[review['enclave_id']], review)
    inverse = Transformer.from_crs(manifest['crs'], 4326, always_xy=True)
    return transform(inverse.transform, candidate), metrics, manifest


def repair_release(dataset, source, output):
    review = read_json(PLAN)
    root, manifest, parent_digest = checked_release(dataset, review['manifest_sha256'])
    if Path(output).resolve().is_relative_to(root):
        raise CatalogueError('Corrected output must be outside the immutable source release.')
    candidate, metrics, source_manifest = reviewed_source(source, review)
    report = read_json(root / 'report.json')
    if report['source']['sha256'] != source_manifest['sha256']:
        raise CatalogueError('Release and review use different source vintages.')
    # Verify the complete input, including hierarchy/revisions, before deriving it.
    Dataset(root, parent_digest)
    evidence = {**review, 'source': report['source'], 'checks': {
        'exterior_unchanged': True, 'area_change_m2': metrics['area_change_m2'],
        'make_valid_equals_buffer_zero': True, 'holes_equal_same_source_enclave': True,
        'exclusion_boundary_unchanged': True}}
    with new_directory(output) as staging:
        for name in manifest['files']:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM csd WHERE id=?', (review['csd_id'],)).fetchone()
            record = json.loads(row['record'])
            if (row['geometry'] is not None or row['repair_candidate'] != candidate.wkb
                    or record['assignment_status'] != 'unreviewed_repair'
                    or record['repair'] != metrics):
                raise CatalogueError('Stored repair is not the reviewed candidate.')
            record.update(assignment_status='validated_derived', issues=[],
                          vertices=int(shapely.get_num_coordinates(candidate)),
                          geojson_chars=len(json.dumps(mapping(candidate), separators=(',', ':'))),
                          boundary_basis='reviewed_statcan_topology',
                          coverage_note='Includes the complete StatCan digital water extent. Québec source-boundary differences remain unresolved.')
            record['repair'] = {**metrics, 'status': 'reviewed_topology',
                                'original_issues': json.loads(row['record'])['issues'], 'evidence': evidence}
            db.execute('UPDATE csd SET record=?, geometry=? WHERE id=?',
                       (json.dumps(record, ensure_ascii=False), candidate.wkb, review['csd_id']))
            # No display coordinates change: they already used this exact candidate.
            parent = db.execute('SELECT * FROM region WHERE id=?', (review['region_id'],)).fetchone()
            regional = json.loads(parent['record'])
            members = db.execute('SELECT csd.* FROM csd JOIN csd_region ON csd.id=csd_region.csd_id WHERE region_id=?',
                                 (review['region_id'],)).fetchall()
            if (not members or any(r['geometry'] is None for r in members) or parent['geometry'] is not None
                    or regional.get('unreviewed_member_ids') != [review['csd_id']]):
                raise CatalogueError('Regional membership or qualification changed.')
            union = shapely.union_all([shapely.from_wkb(r['geometry']) for r in members])
            regional_shape = shapely.from_wkb(parent['repair_candidate'])
            if geometry_issue(union) or not union.equals(regional_shape):
                raise CatalogueError('Region differs from the complete reviewed member union.')
            regional.update(assignment_status='validated_derived', issues=[], unreviewed_member_ids=[],
                            evidence={'topology_review': evidence})
            db.execute('UPDATE region SET record=?, geometry=? WHERE id=?',
                       (json.dumps(regional, ensure_ascii=False), parent['repair_candidate'], review['region_id']))
            db.commit()
            statuses = [json.loads(r[0])['assignment_status'] for r in db.execute('SELECT record FROM csd')]
            report['valid_geometry_count'] = sum(s in {'validated_source', 'validated_derived'} for s in statuses)
            report['repair_candidate_count'] = statuses.count('unreviewed_repair')
            report['regions']['geometry_status_counts'] = dict(Counter(
                json.loads(r[0])['assignment_status'] for r in db.execute('SELECT record FROM region')))
        report['catalogue_sha256'] = sha256(staging / 'catalogue.sqlite3')
        report['topology_reviews'] = [evidence]
        qc = report['quebec_refresh']
        for item in qc['repair_review']:
            if item['csd_id'] == review['csd_id']:
                item['prior_decision'] = {'decision': item['decision'], 'reason': item['reason']}
                item.update(decision=review['decision'], reason=review['reason'], topology_review=evidence)
        for item in qc['unresolved']:
            if item.get('scope') == 'Québec municipal repairs':
                item['ids'].remove('ca-csd-' + review['csd_id'])
                item['reason'] = 'Remaining repair candidates have not been promoted.'
        qc['unresolved'].append({'scope': review['name'] + ' source reconciliation',
                                'status': 'review_required', 'ids': ['ca-csd-' + review['csd_id']],
                                'reason': review['scope']})
        write_json(staging / 'report.json', report)
        for name, uid in [('display/24.geojson', review['csd_id']),
                          ('display/regions-24.geojson', review['region_id'])]:
            display = read_json(staging / name, MAX_FILE_BYTES)
            matches = [f for f in display['features'] if f['properties']['id'] == uid]
            if len(matches) != 1:
                raise CatalogueError('Expected exactly one reviewed display feature.')
            matches[0]['properties']['assignment_status'] = 'validated_derived'
            write_json(staging / name, display)
        files = {name: {'bytes': (staging / name).stat().st_size, 'sha256': sha256(staging / name)}
                 for name in manifest['files']}
        write_json(staging / 'manifest.json', {**manifest, 'label': 'canada-topology-reviewed-2026-09-19', 'files': files})
        derived = Dataset(staging)
        if 'ca-csd-' + review['csd_id'] not in derived.geometries or review['region_id'] not in derived.geometries:
            raise CatalogueError('Reviewed geometry did not become available.')
    return {'output': str(output), 'manifest_sha256': sha256(Path(output) / 'manifest.json'),
            'reviewed_municipality': review['csd_id'], 'reviewed_region': review['region_id'],
            'remaining_csd_repairs': report['repair_candidate_count']}
