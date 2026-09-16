"""Explicit API acceptance for the checked Canada release; no network or writes."""
import argparse
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient

from totally_normal_maps.api import Settings, create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    settings = Settings(args.dataset, requests_per_minute=10000)
    with TestClient(create_app(settings), base_url='http://localhost', client=('127.0.0.1', 1234)) as client:
        meta = client.get('/v1/datasets/current').json()
        assert meta['counts'] == {'country': 1, 'province': 13, 'municipality': 5054, 'region': 121, 'city_area': 46}
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
        assert children('ca-ab')['total'] == 419
        assert children('ca-on')['total'] == 57
        areas = client.app.state.dataset.areas
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
        print(json.dumps({'status': 'passed', 'counts': meta['counts'], 'city_area_lookups': len(city_ids),
                          'dataset_version': meta['dataset_version'], 'elapsed_seconds': round(time.perf_counter() - started, 3)}))


if __name__ == '__main__':
    main()
