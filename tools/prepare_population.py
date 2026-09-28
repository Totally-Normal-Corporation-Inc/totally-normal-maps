"""Prepare a national, conservative population crosswalk from pinned local inputs.

No downloads, publishing or geographic repairs. Unchanged geometry is positively
checked; a shared code or absence from a changes list is never sufficient.
Reviewed adjustments are supplied as explicit overrides, bound to this release.
"""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile

import pyogrio
from pyogrio.raw import read
from pyproj import CRS, Transformer
import shapely
from shapely.ops import transform

from totally_normal_maps.catalogue import read_json, write_json, sha256
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.population import (Source, Plan, validate, require, source_rows,
    territory_fingerprint, eligible, identity_hash)


# Only floating-point export/projection roundoff: at most ~0.012 mm in latitude.
# Not a display tolerance, area threshold or permission to apportion population.
ROUNDTRIP_DEGREES = 1e-10


def equivalent(data, uid, native, wgs84):
    full = data.geometries.get(uid)
    if full is not None:
        return bool(shapely.equals_exact(wgs84, full, ROUNDTRIP_DEGREES, normalize=True))
    # A missing assignment polygon can still have an unchanged original source
    # territory. Never compare against a proposed repair to establish equivalence.
    return data.areas[uid].get('repair', {}).get('source_sha256') == hashlib.sha256(native.wkb).hexdigest()


def prepare(data, manifest, source_dir, overrides=None):
    require(manifest.get('schema_version') == 1 and manifest.get('reference_year') == 2021, 'Unsupported population source manifest.')
    sources = {k: validate(Source, v) for k, v in manifest['sources'].items()}
    census_key = manifest['census_source']
    require(census_key in sources and sources[census_key].format == 'statcan_98100002_zip', 'Missing census source selection.')
    facts = {k: source_rows(Path(source_dir) / source.filename, source) for k, source in sources.items()}
    # Even an unchanged outline may have an official population correction.
    # Such cases require a reviewed transaction chain, not automatic attachment.
    affected = {row[direction] for key, rows in facts.items() if sources[key].format == 'statcan_interim_csv'
                for row in rows.values() if row['count'] is not None for direction in ('gain', 'loss')}
    boundary = manifest['boundary_source']
    path = Path(source_dir) / boundary['filename']
    require(path.is_file() and not path.is_symlink() and sha256(path) == boundary['sha256'], 'Census boundary checksum mismatch.')
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and boundary['member'] in names
                and all('/' not in name and '\\' not in name for name in names)
                and sum(e.file_size for e in archive.infolist()) <= 512 * 1024 * 1024, 'Unsafe census boundary archive.')
    uri = '/vsizip/' + str(path.resolve()) + '/' + boundary['member']
    info = pyogrio.read_info(uri)
    require(info['features'] == boundary['expected_count'] and CRS(info['crs']).equals(CRS(boundary['crs'])),
            'Census boundary CRS or inventory changed.')
    transformer = Transformer.from_crs(info['crs'], 'EPSG:4326', always_xy=True)
    population = eligible(data)
    matches, missing, seen = {}, {}, set()
    for offset in range(0, info['features'], 100):
        _, _, shapes, columns = read(uri, columns=['CSDUID'], skip_features=offset, max_features=100)
        for code, raw in zip(columns[0], shapes):
            require(isinstance(code, str) and len(code) == 7 and code.isdigit() and code not in seen and raw is not None,
                    'Malformed census boundary identity.')
            seen.add(code)
            uid = 'ca-csd-' + code
            if uid not in population:
                continue
            dguid = '2021A0005' + code
            require(dguid in facts[census_key], 'Population table and census boundary inventories differ.')
            if code in affected:
                continue
            native = shapely.from_wkb(raw)
            if not equivalent(data, uid, native, transform(transformer.transform, native)):
                continue
            matches[uid] = {'source': census_key, 'record_id': dguid, 'target_sha256': territory_fingerprint(data, uid),
                'basis': 'equivalent_geometry', 'geography_reference': sources[census_key].geography_reference,
                'evidence': [f'2021 source boundary SHA-256 {boundary["sha256"]}',
                             f'CSDUID {code}; full coordinates equivalent within {ROUNDTRIP_DEGREES} degrees of export roundoff.'],
                'adjustments': []}
    require(len(seen) == boundary['expected_count'] and identity_hash(seen) == boundary['identity_sha256']
            and {'2021A0005' + code for code in seen} == set(facts[census_key]), 'Incomplete census boundary/source crosswalk.')
    require(sha256(path) == boundary['sha256'], 'Census boundary input changed while preparing the crosswalk.')
    for uid in sorted(population - matches.keys()):
        code = data.areas[uid]['source_id']
        reason = 'incompatible_boundary' if '2021A0005' + code in facts[census_key] else 'unmatched_geography'
        missing[uid] = {'reason': reason, 'target_sha256': territory_fingerprint(data, uid),
                        'evidence': ['No qualified equivalence between the census geography and this served territory.']}
    if overrides:
        require(overrides['base_dataset_version'] == data.version, 'Reviewed population overrides pin a different dataset.')
        for uid, row in overrides['matches'].items():
            require(uid in population, 'Reviewed override has an unknown/noncurrent municipality.')
            require(row['target_sha256'] == territory_fingerprint(data, uid), 'Reviewed override territory changed.')
            matches[uid] = row
            missing.pop(uid, None)
    return validate(Plan, {'schema_version': 1, 'base_dataset_version': data.version, 'reference_year': 2021,
        'reviewed_on': manifest['reviewed_on'], 'sources': {k: v.model_dump() for k, v in sources.items()},
        'matches': dict(sorted(matches.items())), 'unavailable': dict(sorted(missing.items()))}).model_dump()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--sources', type=Path, default=Path('totally_normal_maps/population-2021.json'))
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--overrides', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), 'Population plan output exists; choose another review path.')
    data = Dataset(args.dataset, args.manifest_sha256)
    plan = prepare(data, read_json(args.sources), args.source_dir, read_json(args.overrides) if args.overrides else None)
    write_json(args.output, plan)
    print(f'Prepared {len(plan["matches"])} evidenced municipal matches and {len(plan["unavailable"])} explicit gaps.')


if __name__ == '__main__':
    main()
