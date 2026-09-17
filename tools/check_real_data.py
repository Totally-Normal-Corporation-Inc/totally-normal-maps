"""Explicit API acceptance for the checked Canada release; no network or writes."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient

from totally_normal_maps.api import Settings, create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, help='Optional earlier serving release to verify unchanged existing rows')
    args = parser.parse_args()
    started = time.perf_counter()
    settings = Settings(args.dataset, requests_per_minute=10000)
    with TestClient(create_app(settings), base_url='http://localhost', client=('127.0.0.1', 1234)) as client:
        meta = client.get('/v1/datasets/current').json()
        assert meta['counts'] == {'country': 1, 'province': 13, 'municipality': 5054, 'region': 144, 'city_area': 46}
        def children(uid):
            response = client.get(f'/v1/areas/{uid}/children')
            response.raise_for_status()
            return response.json()
        assert children('ca')['total'] == 13
        assert children('ca-qc')['total'] == 17
        assert children('ca-qc-ra-07')['total'] == 75
        assert children('ca-csd-2481017')['total'] == 5
        assert children('ca-csd-2466023')['total'] == 19
        assert children('ca-csd-2409048')['total'] == 1
        assert children('ca-csd-2465005')['total'] == 0  # Laval has no imported city areas.
        assert children('ca-ab')['total'] == 394  # 2 groups + 392 direct municipalities.
        assert children('ca-mb')['total'] == 8
        assert children('ca-nt')['total'] == 13
        assert children('ca-nl')['total'] == 235
        assert children('ca-yt')['total'] == 25
        assert children('ca-sk')['total'] == 995
        assert children('ca-on')['total'] == 57
        areas = client.app.state.dataset.areas
        expected_parents = {'6105020': 'ca-nt-gr-north-slave', '6104014': 'ca-nt-gr-south-slave',
            '6104017': 'ca-nt-gr-south-slave', '6101017': 'ca-nt-gr-beaufort-delta',
            '6102007': 'ca-nt-gr-sahtu', '6104038': 'ca-nt-gr-dehcho',
            '6001048': 'ca-yt-gr-southern-lakes', '6001029': 'ca-yt-gr-klondike',
            '6001018': 'ca-yt-gr-kluane', '4819012': 'ca-ab-gr-peace-country',
            '4808011': 'ca-ab-gr-central-alberta', '1006009': 'ca-nl-gr-central',
            '1005018': 'ca-nl-gr-western', '1007023': 'ca-nl-gr-eastern',
            '1010025': 'ca-nl-gr-labrador', '6001045': 'ca-yt', '6001008': 'ca-yt', '6104097': 'ca-nt'}
        for uid, parent in expected_parents.items():
            response = client.get(f'/v1/areas/ca-csd-{uid}')
            response.raise_for_status()
            assert response.json()['area']['parent_id'] == parent, uid
        regional_lookups = 0
        for uid, area in areas.items():
            if area['level'] != 'region' or '-gr-' not in uid:
                continue
            response = client.get(f'/v1/areas/{uid}/boundary')
            response.raise_for_status()
            assert response.json()['properties']['coverage_policy'] in {'whole_divisions', 'selected_members'}
            assert area['evidence'] and area['coverage_note'] and area['boundary_basis'] == 'member_csd_union'
            detail = client.get(f'/v1/areas/{uid}').json()['area']
            for key in ('evidence', 'coverage_note', 'coverage_policy', 'boundary_basis'):
                assert detail[key] == response.json()['properties'][key], (uid, key)
            for child in client.app.state.dataset.children[uid]:
                polygon = client.app.state.dataset.geometries.get(child)
                if polygon is None:
                    continue
                point = polygon.representative_point()
                result = client.post('/v1/lookup', json={'longitude': point.x, 'latitude': point.y})
                result.raise_for_status()
                assert uid in {r['id'] for r in result.json()['matches']}, child
                match = next(r for r in result.json()['matches'] if r['id'] == uid)
                assert match['coverage_policy'] == area['coverage_policy']
                if not area['geometry_available']:
                    assert uid not in result.json()['direct_match_ids'], uid
                regional_lookups += 1
        for alias, uid in [('sahtu', 'ca-nt-gr-sahtu'), ('Peace Region', 'ca-ab-gr-peace-country'),
                           ('Parklands', 'ca-mb-gr-parkland')]:
            assert uid in {r['id'] for r in client.get('/v1/areas', params={'q': alias}).json()['items']}
        city_ids = [uid for uid, r in areas.items() if r['level'] == 'city_area']
        for uid in city_ids:
            polygon = client.app.state.dataset.geometries[uid]
            point = polygon.representative_point()
            response = client.post('/v1/lookup', json={'longitude': point.x, 'latitude': point.y})
            response.raise_for_status()
            assert uid in response.json()['direct_match_ids'], uid
            assert response.json()['qualification'] == 'review_required'
        hull = client.post('/v1/lookup', json={'longitude': -75.72, 'latitude': 45.43}).json()
        names = [r['name'] for r in hull['matches']]
        assert {'Canada', 'Quebec', 'Outaouais', 'Gatineau', 'Hull'} <= set(names), names
        assert client.get('/v1/areas/ca-csd-2423027/boundary?resolution=full').status_code == 409
        assert client.get('/v1/areas/ca/children/boundaries').json()['type'] == 'FeatureCollection'
        coverage = meta['coverage']['city_areas']
        assert next(r for r in coverage if r['parent_csd_id'] == '2409048')['coverage_policy'] == 'partial'
        unchanged = {}
        if args.baseline:
            # This also verifies the baseline manifest; never trust unchecked files.
            from totally_normal_maps.dataset import Dataset
            baseline = Dataset(args.baseline)
            with sqlite3.connect((baseline.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True) as old, \
                    sqlite3.connect((client.app.state.dataset.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True) as new:
                for table in ('csd', 'city_area', 'region', 'csd_region'):
                    rows = old.execute(f'SELECT * FROM {table}').fetchall()
                    column = 'csd_id' if table == 'csd_region' else 'id'
                    for row in rows:
                        assert new.execute(f'SELECT * FROM {table} WHERE {column}=?', (row[0],)).fetchone() == row, (table, row[0])
                    unchanged[table] = len(rows)
        print(json.dumps({'status': 'passed', 'counts': meta['counts'], 'city_area_lookups': len(city_ids),
                          'new_region_member_lookups': regional_lookups, 'unchanged_baseline_rows': unchanged,
                          'dataset_version': meta['dataset_version'], 'elapsed_seconds': round(time.perf_counter() - started, 3)}))


if __name__ == '__main__':
    main()
