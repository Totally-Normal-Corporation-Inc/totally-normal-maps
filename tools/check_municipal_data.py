"""Explicit local acceptance for municipal wards; no network or geometry repair."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import shapely
from totally_normal_maps.catalogue import sha256,write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.municipal_elections import municipal_scopes

def check(root,base,output):
    data=Dataset(root);part=data.report['municipal_elections']
    assert municipal_scopes(data)<=data.municipal_coverage.keys()
    assert len(municipal_scopes(data))==5050
    # Compare exact stored rows, including geometry blobs, in every original table.
    with sqlite3.connect(Path(base).resolve().as_uri()+'/catalogue.sqlite3?mode=ro',uri=True) as old, sqlite3.connect((Path(root).resolve()/'catalogue.sqlite3').as_uri()+'?mode=ro',uri=True) as new:
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            assert table.replace('_','').isalnum()
            assert old.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()==new.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall(),table
    checked=0;pending=0;statuses=Counter();provinces={}
    for uid,row in data.areas.items():
        if row.get('layer')!='municipal':continue
        assert row['authority_id']==row['parent_id'] and row['source'] in part['sources']
        assert row['edition'] in data.editions and row['source_id']
        if uid in data.geometries:
            geom=data.geometries[uid];point=geom.representative_point()
            r=data.lookup(point.x,point.y,layers=['municipal'],editions={'municipal':[row['edition']]})
            assert uid in r['direct_match_ids'],uid
            assert r['layers']['municipal']['municipal_coverage']
            assert data.boundary(uid,'full')['properties']['suitable_for_assignment']
            statuses[r['status']]+=1;checked+=1
            if data.editions[row['edition']]['default'] and data.editions[row['edition']]['status']=='reference':
                assert data.lookup(point.x,point.y,layers=['municipal'])['status']=='review_required',uid
        else:
            assert row['assignment_status'] in ('unreviewed_repair','missing_geometry')
            assert not row['geometry_available'];pending+=1
            if uid in data.pending_ids:
                point=data.pending_shapes[data.pending_ids.index(uid)].representative_point()
                r=data.lookup(point.x,point.y,layers=['municipal'],editions={'municipal':[row['edition']]})
                assert uid not in r['direct_match_ids'] and uid in r['review_candidate_ids'],uid
        assert all(k not in row for k in ('CONS','EMAIL','CONSEILLER','COURRIEL','ALDERMAN'))
    for p in sorted({r['province'] for r in data.municipal_coverage.values()}):
        scopes=[r for r in data.municipal_coverage.values() if r['province']==p]
        editions=[e for e in part['editions'] if p in e['provinces']]
        provinces[p]={'coverage':dict(Counter(r['status'] for r in scopes)), 'editions':len(editions),
            'all_districts':sum(e['expected_count'] for e in editions),
            'default_districts':sum(e['expected_count'] for e in editions if e['default'])}
    result={'passed':True,'dataset_manifest_sha256':data.version,'base_manifest_sha256':sha256(Path(base)/'manifest.json'),
        'preserved_tables':tables,'full_geometry_points_checked':checked,'unapproved_boundaries':pending,'point_statuses':dict(statuses),
        'municipal_scopes':5050,'total_authority_scopes':len(data.municipal_coverage),'editions':len(part['editions']),
        'districts':checked+pending,'provinces':provinces}
    write_json(output,result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',type=Path,required=True);parser.add_argument('--base',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();check(args.dataset,args.base,args.report)
