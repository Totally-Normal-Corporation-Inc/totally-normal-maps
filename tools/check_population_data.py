"""Explicit offline acceptance against a prepared population release and sources."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from totally_normal_maps.catalogue import read_json, sha256
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.population import (Plan, Source, Metadata, validate, source_rows, prepare_records,
    require, metadata_page, encoded, coverage)


def check_reviewed_adjustment(data, source_dir, national_boundaries):
    """Reproduce the two-area review; this is not a national matching tolerance."""
    import pyogrio
    from pyogrio.raw import read
    from pyproj import CRS, Transformer
    import shapely
    from shapely.ops import transform
    import totally_normal_maps

    package = Path(totally_normal_maps.__file__).parent
    manifest = read_json(package / 'population-2021.json')
    census = manifest['boundary_source']
    national = read_json(package / 'statcan-2025.json')
    codes = {'2481017', '2482025'}
    geometries = []
    for path, spec in ((Path(source_dir) / census['filename'], census), (Path(national_boundaries), national)):
        require(not path.is_symlink() and sha256(path) == spec['sha256'], 'Reviewed boundary input checksum changed.')
        uri = '/vsizip/' + str(path.resolve()) + '/' + spec['member']
        require(CRS(pyogrio.read_info(uri)['crs']).equals(CRS('EPSG:3347')), 'Reviewed boundary CRS changed.')
        _, _, shapes, columns = read(uri, columns=['CSDUID'], where="CSDUID IN ('2481017','2482025')")
        require(len(shapes) == 2 and set(columns[0]) == codes, 'Reviewed boundary identities changed.')
        geometries.append({code: shapely.from_wkb(raw) for code, raw in zip(columns[0], shapes)})
    old, new = geometries
    old_union, new_union = shapely.union_all(list(old.values())), shapely.union_all(list(new.values()))
    require(old_union.buffer(.001).covers(new_union) and new_union.buffer(.001).covers(old_union),
            'Reviewed outer territories differ beyond 1 mm numerical roundoff.')
    require(old['2481017'].buffer(.002).covers(new['2481017']) and new['2482025'].buffer(.002).covers(old['2482025']),
            'Reviewed directional transfer differs beyond 2 mm numerical roundoff.')
    transformer = Transformer.from_crs(3347, 4326, always_xy=True)
    changes = {key: source_rows(Path(source_dir) / spec['filename'], validate(Source, spec))
               for key, spec in manifest['sources'].items() if spec['format'] == 'statcan_interim_csv'}
    for code in sorted(codes):
        uid = 'ca-csd-' + code
        require(shapely.equals_exact(data.geometries[uid], transform(transformer.transform, new[code]), 0, normalize=True),
                'Served territory differs from the reviewed 2025 source.')
        transactions = [(key, rid, row) for key, rows in changes.items() for rid, row in rows.items()
                        if code in (row['gain'], row['loss'])]
        require(len(transactions) == 1, 'Reviewed pair has additional or missing official transactions.')
        key, rid, row = transactions[0]
        direction = 'loss' if code == '2481017' else 'gain'
        require(key == 'interim2023' and row['file_number'] == '240028' and row['count'] == 0
                and row[direction] == code and row['effective_date'] == '16/04/2022', 'Reviewed official transfer changed.')
        require(data.populations[uid]['evidence']['adjustments'] == [{'source': key, 'record_id': rid, 'direction': direction}],
                'Stored adjustment differs from the reviewed transaction.')
    return {'official_transaction': '240028', 'population_affected': 0,
            'outer_boundary_roundoff_m': .001, 'directional_roundoff_m': .002,
            'combined_symmetric_difference_m2': old_union.symmetric_difference(new_union).area}


def check(data, plan_path, source_dir):
    plan = validate(Plan, read_json(plan_path, 32 * 1024 * 1024))
    facts = {key: source_rows(Path(source_dir) / s.filename, s) for key, s in plan.sources.items()}
    require(prepare_records(data, plan, facts) == data.populations, 'Stored population differs from verified source/crosswalk calculation.')
    offset, maximum, ids = 0, 0, []
    while offset is not None:
        page = metadata_page(data, data.page(offset=offset, limit=100))
        maximum = max(maximum, len(encoded(page)))
        require(maximum < 2 * 1024 * 1024, 'Catalogue page exceeds the consumer decoded-size bound.')
        for row in page['items']:
            validate(Metadata, {k: row[k] for k in ('population', 'population_unavailable_reason')})
            ids.append(row['id'])
        offset = page['next_offset']
    require(len(ids) == len(set(ids)) == page['total'], 'Catalogue pagination lost or duplicated identities.')
    names = defaultdict(list)
    for uid, record in data.populations.items():
        if record['metadata']['population'] is not None:
            names[data.areas[uid]['name']].append(uid)
    duplicates = next((v for _, v in sorted(names.items()) if len(v) > 1), [])
    samples = ['ca-csd-2481017', 'ca-csd-2484050', 'ca-csd-6204019', *duplicates[:2]]
    # Include a positive matched municipality outside Québec selected by code,
    # not a manually assigned city priority or a name-based join.
    samples += next(([uid] for uid, r in sorted(data.populations.items()) if data.areas[uid]['province_id'] != 'ca-qc'
                     and r['metadata']['population'] is not None and r['metadata']['population']['count'] > 0), [])
    examples = [{k: data.areas[uid][k] for k in ('id', 'name', 'province_id')} | data.populations[uid]['metadata']
                for uid in samples if uid in data.populations]
    return {'dataset_version': data.version, 'coverage': coverage(data, data.populations),
            'catalogue_items': len(ids), 'maximum_100_item_page_bytes': maximum, 'examples': examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--national-boundaries', type=Path, help='Optional pinned 2025 national ZIP: reproduce the Gatineau/Chelsea review')
    args = parser.parse_args()
    data = Dataset(args.dataset, args.manifest_sha256)
    report = check(data, args.plan, args.source_dir)
    if args.national_boundaries:
        report['reviewed_adjustment'] = check_reviewed_adjustment(data, args.source_dir, args.national_boundaries)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
