"""Explicit, offline real-data circle acceptance; no downloads or dataset changes.

Uses only public sample coordinates. Optionally verifies every missing municipal
repair envelope against vertices from a checksum-pinned local source archive.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import time

from pyogrio.raw import read
from pyproj import CRS, Transformer
import shapely
from shapely.ops import transform

from totally_normal_maps.catalogue import CatalogueError, source_uri, validate_manifest
from totally_normal_maps.circle import CircleIndex, CircleInput, CircleResult, MAX_RESPONSE_BYTES
from totally_normal_maps.dataset import Dataset


SAMPLES = (
    ('gatineau_30km', 45.4, -75.8, 30000),
    ('montreal_30km', 45.5019, -73.5674, 30000),
    ('quebec_30km', 46.8139, -71.208, 30000),
    ('toronto_30km', 43.6532, -79.3832, 30000),
    ('vancouver_30km', 49.2827, -123.1207, 30000),
    ('iqaluit_100km', 63.7467, -68.517, 100000),
    ('north_pole_100km', 90, 0, 100000),
    ('us_border_30km', 44.95, -73.45, 30000),
    ('outside_30km', 0, 0, 30000),
    ('gatineau_100km', 45.4, -75.8, 100000),
)


def require(condition, message):
    if not condition:
        raise CatalogueError(message)


def audit_envelopes(index, archive, manifest_path):
    """Independent source evidence, not a comparison of a candidate to itself."""
    manifest = json.loads(Path(manifest_path).read_text())
    validate_manifest(manifest)
    uri = source_uri(archive, manifest)
    missing = {uid: row for uid, row in index.data.areas.items()
               if row['level'] == 'municipality' and row.get('layer', 'administrative') == 'administrative'
               and row.get('lifecycle_status') != 'superseded' and uid not in index.data.geometries}
    require(not index.unlocated, 'Unlocated municipal extents cannot be certified by this audit.')
    envelopes = {c.uid: c.geometry for c in index.uncertain if c.reason == 'municipal_geometry_unavailable'}
    require(set(envelopes) == set(missing), 'Missing municipalities lack one conservative envelope each.')
    require(all(re.fullmatch(r'ca-csd-\d{7}', uid) for uid in missing),
            'This source audit supports national CSD repair identities only.')
    transformer = Transformer.from_crs(manifest['crs'], 'EPSG:4326', always_xy=True)
    verified, vertices = set(), 0
    # Values are validated seven-digit public identifiers, not arbitrary SQL.
    ids = sorted(uid.removeprefix('ca-csd-') for uid in missing)
    for offset in range(0, len(ids), 50):
        where = 'CSDUID IN (' + ','.join("'" + uid + "'" for uid in ids[offset:offset + 50]) + ')'
        meta, _, geometries, columns = read(uri, layer=manifest['layer'], columns=['CSDUID'], where=where)
        require(CRS(meta['crs']).equals(CRS(manifest['crs'])), 'Source audit CRS mismatch.')
        for code, raw in zip(columns[0], geometries):
            uid = 'ca-csd-' + str(code)
            require(uid in missing and uid not in verified and raw is not None, 'Unexpected source audit identity.')
            geometry = shapely.from_wkb(raw)
            repair = missing[uid]['repair']
            require(hashlib.sha256(geometry.wkb).hexdigest() == repair['source_sha256'],
                    'Original source geometry differs from the repair ledger.')
            require(shapely.get_num_coordinates(geometry) == repair['source_vertices'], 'Source vertex count mismatch.')
            original = transform(transformer.transform, geometry)
            west, south, east, north = envelopes[uid].bounds
            x0, y0, x1, y1 = original.bounds
            require(west <= x0 <= x1 <= east and south <= y0 <= y1 <= north,
                    'Repair envelope does not contain every original source vertex.')
            vertices += int(shapely.get_num_coordinates(original))
            verified.add(uid)
    require(verified == set(missing), 'Source audit did not cover every missing municipal geometry.')
    return {'source_sha256': manifest['sha256'], 'certified_missing_municipalities': len(verified),
            'original_vertices_checked': vertices}


def check(index):
    metrics = []
    for name, latitude, longitude, radius in SAMPLES:
        point = CircleInput(latitude=latitude, longitude=longitude, radius_m=radius)
        start = time.monotonic()
        result = index.lookup(point)
        size = len(result.model_dump_json().encode())
        require(size <= MAX_RESPONSE_BYTES, 'Circle page exceeded 128 KiB.')
        require(result.dataset_version == index.data.version, 'Circle result version mismatch.')
        require(result.query.model_dump() == point.query(), 'Circle result changed the query.')
        row = {'sample': name, 'status': result.status, 'seconds': round(time.monotonic() - start, 4),
               'decoded_json_bytes': size}
        if isinstance(result, CircleResult):
            row['total'] = result.total
            ids = [r.id for r in result.items]
            while result.next_offset is not None:
                point = point.model_copy(update={'offset': result.next_offset})
                page = index.lookup(point)
                require(isinstance(page, CircleResult) and page.total == row['total'], 'Unstable circle continuation.')
                require(len(page.items) == min(point.limit, page.total - point.offset), 'Short circle page.')
                ids.extend(r.id for r in page.items)
                result = page
            require(ids == sorted(set(ids)) and len(ids) == row['total'], 'Incomplete or unordered circle result.')
            if name == 'outside_30km':
                require(row['total'] == 0, 'Outside sample unexpectedly intersects the catalogue.')
        else:
            row['affected_count'] = result.affected_count
            row['reason_codes'] = [r.code for r in result.reasons]
        metrics.append(row)
    # The budget is per request; simultaneous work must not contaminate results.
    points = [CircleInput(latitude=lat, longitude=lon, radius_m=r) for _, lat, lon, r in SAMPLES[:2]]
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(index.lookup, points))
    concurrent_seconds = time.monotonic() - start
    require([r.model_dump() for r in concurrent] == [index.lookup(p).model_dump() for p in points],
            'Concurrent circle results differ.')
    return {'samples': metrics, 'two_queries_seconds': round(concurrent_seconds, 4)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--source-archive', type=Path, help='Optional already-downloaded national ZIP; never fetched')
    parser.add_argument('--source-manifest', type=Path, default=Path('totally_normal_maps/statcan-2025.json'))
    args = parser.parse_args()
    start = time.monotonic()
    data = Dataset(args.dataset, args.manifest_sha256)
    load_seconds = time.monotonic() - start
    start = time.monotonic()
    index = CircleIndex(data)
    report = {'dataset_version': data.version, 'dataset_load_seconds': round(load_seconds, 3),
              'circle_index_seconds': round(time.monotonic() - start, 3), 'population': index.population,
              'full_geometry_components': len(index.components), 'uncertainty_components': len(index.uncertain),
              'unlocated_municipalities': len(index.unlocated)}
    if args.source_archive:
        report['source_envelope_audit'] = audit_envelopes(index, args.source_archive, args.source_manifest)
    report.update(check(index))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
