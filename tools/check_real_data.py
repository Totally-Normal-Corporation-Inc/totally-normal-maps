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
        refresh = meta['coverage'].get('quebec_refresh')
        ontario = meta['coverage'].get('ontario_refresh')
        jurisdictions = meta['coverage'].get('jurisdiction_refreshes', {})
        topology = meta['coverage'].get('topology_reviews', [])
        reviewed_ids = {'ca-csd-' + r['csd_id'] for r in topology}
        administrative_counts = {k:v for k,v in meta['counts'].items() if k != 'electoral_district'}
        assert administrative_counts == {'country': 1, 'province': 13, 'municipality': 5050 if refresh else 5054,
                                  'region': 144, 'city_area': (137 if refresh else 46) + (520 if ontario else 0) +
                                  sum(r['added_city_area_count'] for r in jurisdictions.values())}
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
        assert children('ca-csd-2465005')['total'] == (14 if refresh else 0)
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
        city_lookups = 0
        for uid in city_ids:
            if not areas[uid]['geometry_available']:
                assert areas[uid]['assignment_status'] in {'missing_geometry', 'unreviewed_repair', 'unreviewed_parent', 'unreviewed_overlap'}
                assert client.get(f'/v1/areas/{uid}/boundary?resolution=full').status_code == 409
                continue
            polygon = client.app.state.dataset.geometries[uid]
            point = polygon.representative_point()
            response = client.post('/v1/lookup', json={'longitude': point.x, 'latitude': point.y})
            response.raise_for_status()
            assert uid in response.json()['direct_match_ids'], uid
            assert response.json()['qualification'] == 'review_required'
            city_lookups += 1
        municipal_lookups = 0
        jurisdiction_lookups = 0
        dataset = client.app.state.dataset
        for province, refresh_report in jurisdictions.items():
            from totally_normal_maps.catalogue import PROVINCES
            province_id = 'ca-' + PROVINCES[province][0].lower()
            audited = {r['csd_id'] for r in refresh_report['audit']['municipalities']}
            expected = {r['source_id'] for r in areas.values() if r.get('province_id') == province_id and r['level'] == 'municipality'}
            assert audited == expected, province
            for uid, row in areas.items():
                if row.get('province_id') != province_id or row['level'] not in {'municipality', 'region'}: continue
                if uid not in dataset.geometries:
                    assert uid in dataset.pending_ids
                    continue
                point = dataset.geometries[uid].representative_point()
                assert uid in dataset.lookup(point.x, point.y)['direct_match_ids'], uid
                jurisdiction_lookups += 1
        ontario_lookups = 0
        if ontario:
            dataset = client.app.state.dataset
            assert children('ca-csd-3520005')['total'] == 164
            assert children('ca-csd-3506008')['total'] == 116
            assert children('ca-csd-3525005')['total'] == 6
            assert sum(children(f'ca-on-3525005-community-{i}')['total'] for i in range(1,7)) == 234
            assert 'ca-csd-3557014' in {r['id'] for r in client.get('/v1/areas',params={'q':'Tarbutt and Tarbutt Additional'}).json()['items']}
            for uid, row in areas.items():
                if row.get('province_id') != 'ca-on' or row['level'] not in {'municipality', 'region'}: continue
                if not row['geometry_available']:
                    assert uid in dataset.pending_ids
                    continue
                point = dataset.geometries[uid].representative_point()
                assert uid in dataset.lookup(point.x,point.y)['direct_match_ids'], uid
                ontario_lookups += 1
            for adjustment in ontario['adjustments']:
                for member in adjustment['members']:
                    uid = 'ca-csd-' + member['csd_id']
                    assert areas[uid]['effective_date'] == adjustment['effective_date']
                    assert areas[uid]['boundary_source_ids'] == member['source_ids']
            for adjustment in ontario.get('deferred_adjustments', []):
                for member in adjustment['members']:
                    uid = 'ca-csd-' + member['csd_id']
                    assert areas[uid]['update_status'] == 'deferred'
                    assert areas[uid]['boundary_basis'] == 'retained_previous_boundary'
            for uid in ('ca-on-3506008-ons-3050','ca-on-3506008-ons-3051'):
                assert uid not in dataset.geometries
                assert not dataset.boundary(uid)['properties']['suitable_for_assignment']
        if refresh:
            dataset = client.app.state.dataset
            assert meta['historical_counts'] == {'municipality': 6}
            assert children('ca-csd-2437067')['total'] == 29
            assert children('ca-csd-2464008')['total'] == 3
            assert sum(children(f'ca-qc-arr-req{n:02d}')['total'] for n in range(1,7)) == 35
            assert sum(children(f'ca-qc-arr-rea{n:02d}')['total'] for n in range(1,4)) == 10
            for uid, row in areas.items():
                if row['level'] != 'municipality' or row['province_id'] != 'ca-qc': continue
                if row.get('lifecycle_status') == 'superseded':
                    assert uid not in dataset.geometry_ids
                    assert not dataset.boundary(uid, 'full')['properties']['suitable_for_assignment']
                    continue
                if not row['geometry_available']:
                    assert uid in {'ca-csd-2423027','ca-csd-2472032','ca-csd-2485090','ca-csd-2498015'} - reviewed_ids
                    continue
                point = dataset.geometries[uid].representative_point()
                result = client.post('/v1/lookup', json={'longitude':point.x, 'latitude':point.y}).json()
                assert uid in result['direct_match_ids'], uid
                municipal_lookups += 1
            assert municipal_lookups == 1270 + len(reviewed_ids)
            for merger in refresh['mergers']:
                successor = dataset.geometries[merger['id']]
                import shapely
                original = shapely.union_all([dataset.geometries['ca-csd-'+uid] for uid in merger['predecessor_csd_ids']])
                assert successor.equals(original)
                for old in merger['predecessor_csd_ids']:
                    row = client.get('/v1/areas/ca-csd-'+old).json()['area']
                    assert row['successor_ids'] == [merger['id']]
                    assert client.get('/v1/areas', params={'q':'ca-csd-'+old}).json()['total'] == 0
                    assert client.get('/v1/areas', params={'q':'ca-csd-'+old,'include_historical':True}).json()['total'] == 1
            terrebonne = dataset.geometries['ca-csd-2464008'].representative_point()
            result = dataset.lookup(terrebonne.x,terrebonne.y)
            assert set(children('ca-csd-2464008')['items'][i]['id'] for i in range(3)) <= set(result['review_candidate_ids'])
        hull = client.post('/v1/lookup', json={'longitude': -75.72, 'latitude': 45.43}).json()
        names = [r['name'] for r in hull['matches']]
        assert {'Canada', 'Quebec', 'Outaouais', 'Gatineau', 'Hull'} <= set(names), names
        assert client.get('/v1/areas/ca-csd-2423027/boundary?resolution=full').status_code == 409
        assert client.get('/v1/areas/ca/children/boundaries').json()['type'] == 'FeatureCollection'
        coverage = meta['coverage']['city_areas']
        assert next(r for r in coverage if r['parent_csd_id'] == '2409048')['coverage_policy'] == 'partial'
        unchanged = {}
        for review in topology:
            uid, region = 'ca-csd-' + review['csd_id'], review['region_id']
            assert areas[uid]['assignment_status'] == 'validated_derived'
            assert areas[uid]['repair']['status'] == 'reviewed_topology'
            assert areas[uid]['repair']['area_change_m2'] == 0
            assert region in dataset.geometries
            enclave = dataset.geometries['ca-csd-' + review['enclave_id']]
            # Check each reserve component, not just one representative point.
            components = list(enclave.geoms) if hasattr(enclave, 'geoms') else [enclave]
            for component in components:
                point = component.representative_point()
                result = dataset.lookup(point.x, point.y)
                assert uid not in result['direct_match_ids']
                assert 'ca-csd-' + review['enclave_id'] in result['direct_match_ids']
            assert client.get(f'/v1/areas/{uid}/boundary?resolution=full').status_code == 200
        if args.baseline:
            # This also verifies the baseline manifest; never trust unchecked files.
            from totally_normal_maps.dataset import Dataset
            baseline = Dataset(args.baseline)
            with sqlite3.connect((baseline.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True) as old, \
                    sqlite3.connect((client.app.state.dataset.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True) as new:
                for table in ('csd', 'city_area', 'region', 'csd_region'):
                    rows = old.execute(f'SELECT * FROM {table}').fetchall()
                    column = 'csd_id' if table == 'csd_region' else 'id'
                    exempt = {r['csd_id' if table == 'csd' else 'region_id'] for r in topology} if table in {'csd', 'region'} else set()
                    preserved = 0
                    for row in rows:
                        updated = new.execute(f'SELECT * FROM {table} WHERE {column}=?', (row[0],)).fetchone()
                        if row[0] in exempt and baseline.version in {r['manifest_sha256'] for r in topology}:
                            # Only record and full geometry may change; the prior
                            # candidate must become the exact assignment boundary.
                            columns = [r[1] for r in old.execute(f'PRAGMA table_info({table})')]
                            old_row, new_row = dict(zip(columns, row)), dict(zip(columns, updated))
                            assert old_row['geometry'] is None
                            assert new_row['geometry'] == old_row['repair_candidate']
                            assert {k:v for k,v in old_row.items() if k not in {'record','geometry'}} == {k:v for k,v in new_row.items() if k not in {'record','geometry'}}
                        else:
                            assert updated == row, (table, row[0])
                            preserved += 1
                    unchanged[table] = preserved
        print(json.dumps({'status': 'passed', 'counts': meta['counts'], 'city_area_lookups': city_lookups,
                          'quebec_municipal_lookups': municipal_lookups,
                          'ontario_municipal_region_lookups': ontario_lookups,
                          'other_jurisdiction_municipal_region_lookups': jurisdiction_lookups,
                          'new_region_member_lookups': regional_lookups, 'unchanged_baseline_rows': unchanged,
                          'dataset_version': meta['dataset_version'], 'elapsed_seconds': round(time.perf_counter() - started, 3)}))


if __name__ == '__main__':
    main()
