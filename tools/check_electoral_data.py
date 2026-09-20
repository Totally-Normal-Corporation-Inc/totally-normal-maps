"""Explicit real-source acceptance; no downloads, writes or cloud operations."""
import argparse
from collections import Counter
import json
import sqlite3
from pathlib import Path

from totally_normal_maps.dataset import Dataset
from totally_normal_maps.catalogue import sha256


def check(root, baseline=None, previous=None):
    data = Dataset(root)
    assert data.editions
    counts, checked, pending = Counter(), 0, []
    for uid, area in data.areas.items():
        if area.get('layer') not in {'federal', 'provincial'}: continue
        counts[area['edition']] += 1
        assert [a['level'] for a in data.ancestors(uid)] == ['country', 'province'], uid
        assert area['parent_id'] == area['province_id']
        if uid not in data.geometries:
            assert uid in data.pending_ids or uid in data.unknown_ids
            if uid in data.pending_ids:
                point = data.pending_shapes[data.pending_ids.index(uid)].representative_point()
                result = data.lookup(point.x, point.y, layers=[area['layer']], editions={area['layer']:[area['edition']]})
                assert uid in result['review_candidate_ids'], uid
                assert uid not in result['direct_match_ids'], uid
                assert result['status'] == 'review_required', uid
            pending.append(uid); continue
        point = data.geometries[uid].representative_point()
        result = data.lookup(point.x, point.y, layers=[area['layer']], editions={area['layer']:[area['edition']]})
        assert uid in result['direct_match_ids'], uid
        assert not any(data.areas[a]['layer'] == 'administrative' for a in result['direct_match_ids'])
        assert all(data.areas[a]['edition'] == area['edition'] for a in result['direct_match_ids'])
        assert uid not in data.lookup(point.x, point.y)['direct_match_ids']
        checked += 1
    assert dict(counts) == data.report['electoral']['edition_counts']
    for layer in ('federal', 'provincial'):
        coverage = data.report['electoral']['coverage'][layer]
        assert len(coverage) == 13
        for province, item in coverage.items():
            parent = next(a['id'] for a in data.areas.values() if a['level']=='province' and a['source_id']==province)
            page = data.page(parent_id=parent, layer=layer, limit=500)
            assert page['total'] == item['expected_count'], (layer, province)
            assert all(a['edition'] == item['edition'] for a in page['items'])
    if baseline:
        old = Dataset(baseline)
        with sqlite3.connect((old.root/'catalogue.sqlite3').as_uri()+'?mode=ro', uri=True) as left, \
             sqlite3.connect((data.root/'catalogue.sqlite3').as_uri()+'?mode=ro', uri=True) as right:
            for (table,) in left.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if table == 'electoral_area': continue
                assert list(left.execute(f'SELECT * FROM "{table}" ORDER BY 1')) == list(right.execute(f'SELECT * FROM "{table}" ORDER BY 1')), table
    if previous:
        # A code/provenance review must not silently edit published geometry.
        previous = Path(previous).resolve()
        with sqlite3.connect((previous/'catalogue.sqlite3').as_uri()+'?mode=ro', uri=True) as left, \
             sqlite3.connect((data.root/'catalogue.sqlite3').as_uri()+'?mode=ro', uri=True) as right:
            query = 'SELECT id, geometry, repair_candidate FROM electoral_area ORDER BY id'
            assert list(left.execute(query)) == list(right.execute(query)), 'Electoral geometry changed'
            for uid, serialized in left.execute('SELECT id, record FROM electoral_area'):
                old_row = json.loads(serialized)
                for key in ('source_id', 'catalogue_code', 'edition', 'boundary_set', 'assignment_status', 'parent_id'):
                    assert old_row[key] == data.areas[uid][key], (uid, key)
        for path in (previous/'display').glob('*.geojson'):
            assert sha256(path) == sha256(data.root/'display'/path.name), path.name
    return {'passed': True, 'districts': sum(counts.values()), 'editions': dict(counts),
            'assignment_lookup_checks': checked, 'unapproved_geometry_ids': pending,
            'baseline_preserved': bool(baseline), 'previous_geometry_preserved': bool(previous), 'dataset_version': data.version}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--previous', type=Path, help='Compare identities, geometry blobs and display bytes against an earlier electoral build.')
    args = parser.parse_args()
    print(json.dumps(check(args.dataset, args.baseline, args.previous), ensure_ascii=False))
