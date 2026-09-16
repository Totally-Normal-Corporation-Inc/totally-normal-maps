"""Small synthetic release; no government downloads or consumer data."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3

import shapely
from shapely.geometry import box

from totally_normal_maps.catalogue import build, read_json, sha256, write_json
from totally_normal_maps.releases import export_release
from .test_catalogue import fixture_source


def make_release(root):
    root = Path(root)
    source, manifest, _, _ = fixture_source(root, invalid=True)
    run = root / 'run'
    report = build(source, run, manifest_path=manifest)
    with closing(sqlite3.connect(run / 'catalogue.sqlite3')) as db, db:
        full = shapely.from_wkb(db.execute("SELECT geometry FROM csd WHERE id='2401001'").fetchone()[0])
        region = {'id': 'ca-qc-test-region', 'province': '24', 'name': 'Région de test',
                  'kind': 'administrative_region', 'type': 'Region', 'aliases': ['Test Region'],
                  'assignment_status': 'validated_derived', 'issues': [], 'bbox': list(full.bounds)}
        db.execute('CREATE TABLE region (id TEXT PRIMARY KEY, province TEXT, record TEXT, geometry BLOB, repair_candidate BLOB)')
        db.execute('CREATE TABLE csd_region (csd_id TEXT PRIMARY KEY, region_id TEXT, basis TEXT)')
        db.execute('CREATE TABLE city_area (id TEXT PRIMARY KEY, parent_csd_id TEXT, record TEXT, geometry BLOB)')
        db.execute('INSERT INTO region VALUES (?, ?, ?, ?, NULL)', (region['id'], '24', json.dumps(region), full.wkb))
        db.execute("INSERT INTO csd_region VALUES ('2401001', 'ca-qc-test-region', 'synthetic')")
        children = []
        for uid, name, geom in [
            ('ca-qc-test-west', 'West', full.intersection(box(-111, 49, -109.5, 52))),
            ('ca-qc-test-east', 'East', box(-109.5, 50.1, -108.99, 50.9)),
        ]:
            row = {'id': uid, 'province': '24', 'name': name, 'kind': 'sector', 'type': 'Sector',
                   'parent_csd_id': '2401001', 'assignment_status': 'validated_source',
                   'issues': [], 'bbox': list(geom.bounds)}
            db.execute('INSERT INTO city_area VALUES (?, ?, ?, ?)', (uid, '2401001', json.dumps(row), geom.wkb))
            children.append({'type': 'Feature', 'properties': {'id': uid}, 'geometry': shapely.geometry.mapping(geom)})
        region_feature = {'type': 'Feature', 'properties': {'id': region['id']}, 'geometry': shapely.geometry.mapping(full)}
    for province in report['province_counts']:
        write_json(run / 'preview' / f'regions-{province}.geojson', {'type': 'FeatureCollection', 'features': [region_feature] if province == '24' else []})
    write_json(run / 'preview/city-areas-24.geojson', {'type': 'FeatureCollection', 'features': children})
    report['catalogue_sha256'] = sha256(run / 'catalogue.sqlite3')
    report['regions'] = {'feature_count': 1, 'province_counts': {'24': 1}, 'jurisdictions': [],
                         'geometry_status_counts': {'validated_derived': 1}, 'membership_count': 1,
                         'unassigned_member_count': 12, 'outline_method': 'synthetic', 'sources': []}
    report['city_areas'] = {'feature_count': 2, 'municipality_count': 1, 'kind_counts': {'sector': 2},
                           'municipalities': [], 'display_tolerance_metres': 0, 'sources': {}}
    write_json(run / 'report.json', report)
    release = root / 'release'
    exported = export_release(run, release, label='synthetic-test')
    return run, release, exported['manifest_sha256']
