"""Offline boundary-vintage, complete-source and unapproved-repair acceptance."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import shapely
from shapely.geometry import box, mapping, Polygon

from totally_normal_maps.catalogue import CatalogueError, open_catalogue, read_json, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.ontario_refresh import build_refresh, compare_extents
from totally_normal_maps.releases import export_release
from .api_fixture import make_release


class OntarioRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.base, _, _ = make_release(self.root)
        self.evidence = [{'publisher':'Synthetic','url':'https://example.invalid/source','claim':'Test evidence'}]
        self.region = 'ca-on-test-region'; self.city = '3501004'
        shapes = {f'350100{i+1}':box(-80+i,44,-79+i,45) for i in range(3)}
        shapes[self.city] = box(-81,44,-80,45)
        with closing(sqlite3.connect(self.base/'catalogue.sqlite3')) as db, db:
            original = json.loads(db.execute("SELECT record FROM csd WHERE id='3501001'").fetchone()[0])
            db.execute("DELETE FROM csd WHERE id='3501001'")
            for uid, geom in shapes.items():
                row = {**original,'id':uid,'name':'Town '+uid[-1],'bbox':list(geom.bounds),
                       'assignment_status':'unreviewed_repair' if uid=='3501003' else 'validated_source'}
                if uid=='3501003': row['repair']={'status':'unreviewed','source_holes':1,'candidate_holes':2}
                db.execute('INSERT INTO csd VALUES (?, ?, ?, ?, ?, ?)',(uid,'35','{}',json.dumps(row),
                    None if uid=='3501003' else geom.wkb,geom.wkb if uid=='3501003' else None))
                if uid != self.city: db.execute('INSERT INTO csd_region VALUES (?, ?, ?)',(uid,self.region,'synthetic'))
            union=shapely.union_all([shapes[f'350100{i}'] for i in range(1,4)])
            region={'id':self.region,'name':'Region','province':'35','kind':'county','assignment_status':'unreviewed_repair','issues':[],'bbox':list(union.bounds)}
            db.execute('INSERT INTO region VALUES (?, ?, ?, NULL, ?)',(self.region,'35',json.dumps(region),union.wkb))
        report=read_json(self.base/'report.json');report.update(feature_count=16,valid_geometry_count=14,repair_candidate_count=2,catalogue_sha256=sha256(self.base/'catalogue.sqlite3'))
        report['province_counts']['35']=4;report['regions']['feature_count']=2;report['regions']['province_counts']['35']=1
        write_json(self.base/'report.json',report)
        public=read_json(self.base/'preview/catalogue.json')
        with open_catalogue(self.base) as db:
            for key,table in [('areas','csd'),('regions','region'),('city_areas','city_area')]:public[key]=[json.loads(r['record']) for r in db.execute('SELECT * FROM '+table)]
        public['report']=report;write_json(self.base/'preview/catalogue.json',public)
        self.display('35.geojson',shapes);self.display('regions-35.geojson',{self.region:union})
        self.payloads={
            'municipal':self.collection([('1','Town 1',box(-80,44,-78.85,45),'a'),('2','Town 1',box(-80.1,44,-80.05,44.05),'a'),('3','Town 2',box(-78.85,44,-78,44.95),'b')]),
            'former':self.collection([('1','Former town',shapes[self.city],'c')]),
            'neighbourhoods':self.collection([('1','West',box(-81,44,-80.5,45),'c'),('2','East',box(-80.5,44,-80,45),'c')])}
        self.plan={'schema_version':1,'reviewed_on':'2026-09-18','base_source_sha256':report['source']['sha256'],
            'base_identity_sha256':report['identity_sha256'],'sources':{},'adjustments':[{'id':'transfer','effective_date':'2026-01-01','evidence':self.evidence,'members':[
                {'csd_id':'3501001','name':'Town 1','source':'municipal','source_ids':['1','2'],'group_field':'GROUP','group_value':'a'},
                {'csd_id':'3501002','name':'Town 2','source':'municipal','source_ids':['3'],'group_field':'GROUP','group_value':'b'}]}],
            'city_layers':[],'names':[],'repair_review':[{'csd_id':'3501003','name':'Town 3','status':'unapproved','repair':{'status':'unreviewed','source_holes':1,'candidate_holes':2}}],'unresolved':['Synthetic review']}
        for key,payload in self.payloads.items():
            self.plan['sources'][key]={'authority':'Synthetic','family':key,'release':'test','url':'https://example.invalid/source','licence':'https://example.invalid/licence',
                'evidence':self.evidence,'id_field':'ID','name_field':'NAME','geojson_crs':None,'expected_count':len(payload['features']),
                'identities':[{'source_id':f['properties']['ID'],'properties':f['properties'].copy()} for f in payload['features']]}
        for key,scheme in [('former','former_municipality'),('neighbourhoods','neighbourhood')]:
            self.plan['city_layers'].append({'source':key,'parent_csd_id':self.city,'parent_name':'Town 4','kind':scheme,'type':scheme,
                'scheme':scheme,'id_prefix':'ca-on-test-'+key+'-','coverage_policy':'citywide','expected_count':len(self.payloads[key]['features']),'evidence':self.evidence})
        self.save()

    def collection(self, rows):
        return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{'ID':uid,'NAME':name,'GROUP':group},'geometry':mapping(geom)} for uid,name,geom,group in rows]}

    def display(self,name,rows):
        write_json(self.base/'preview'/name,{'type':'FeatureCollection','features':[{'type':'Feature','properties':{'id':uid},'geometry':mapping(geom)} for uid,geom in rows.items()]})

    def save(self):
        for key,payload in self.payloads.items():
            write_json(self.root/(key+'.geojson'),payload);self.plan['sources'][key]['sha256']=sha256(self.root/(key+'.geojson'))
        write_json(self.root/'plan.json',self.plan)

    def build(self):
        return build_refresh(self.base,self.root/'updated',source_dir=self.root,plan_path=self.root/'plan.json')

    def dataset(self):
        self.build();export_release(self.root/'updated',self.root/'new-release');return Dataset(self.root/'new-release')

    def test_preserved_rows_complete_parts_and_removed_extent_uncertainty(self):
        ds=self.dataset()
        with open_catalogue(self.base) as old, open_catalogue(self.root/'updated') as new:
            for table in ('csd','region','csd_region','city_area'):
                col='csd_id' if table=='csd_region' else 'id'
                for r in old.execute('SELECT * FROM '+table):self.assertEqual(tuple(r),tuple(new.execute(f'SELECT * FROM {table} WHERE {col}=?',(r[0],)).fetchone()))
        self.assertTrue(ds.geometries['ca-csd-3501001'].covers(box(-80.1,44,-80.05,44.05)))
        changed=ds.lookup(-78.9,44.5)
        self.assertIn('ca-csd-3501001',changed['direct_match_ids']);self.assertNotIn('ca-csd-3501002',changed['direct_match_ids'])
        missing=ds.lookup(-78.5,44.98)
        self.assertEqual(missing['status'],'review_required');self.assertIn('ca-csd-3501002',missing['review_candidate_ids'])
        self.assertNotIn('ca-csd-3501002',missing['direct_match_ids'])
        self.assertNotIn(self.region,ds.geometries);self.assertNotIn('ca-csd-3501003',ds.geometries)
        with self.assertRaisesRegex(CatalogueError,'already exists'):self.build()
        with self.assertRaisesRegex(CatalogueError,'unmodified base'):
            build_refresh(self.root/'updated',self.root/'again',source_dir=self.root,plan_path=self.root/'plan.json')

    def test_independent_schemes_nested_communities_and_shared_edges(self):
        layer=self.plan['city_layers'][1];layer.update(parent_property='GROUP',parent_ids={'c':'ca-on-test-former-1'});self.save()
        ds=self.dataset();point=ds.lookup(-80.8,44.5)
        self.assertFalse(point['ambiguous']);self.assertEqual(ds.page(parent_id='ca-on-test-former-1')['total'],2)
        self.assertTrue(ds.lookup(-80.5,44.5)['ambiguous'])
        self.assertIn('ca-on-test-former-1',{r['id'] for r in ds.ancestors('ca-on-test-neighbourhoods-1')})

    def test_parallel_schemes_do_not_create_false_ambiguity(self):
        ds=self.dataset();point=ds.lookup(-80.8,44.5)
        self.assertFalse(point['ambiguous'])
        self.assertTrue({'ca-on-test-former-1','ca-on-test-neighbourhoods-1'} <= set(point['direct_match_ids']))
        self.assertTrue(ds.lookup(-80.5,44.5)['ambiguous'])

    def test_invalid_city_source_never_becomes_assignment(self):
        geom=Polygon([(-81,44),(-80.5,44),(-80.5,45),(-80.7,45),(-80.7,44.8),(-80.7,45),(-81,45),(-81,44)])
        self.payloads['neighbourhoods']['features'][0]['geometry']=mapping(geom)
        self.plan['sources']['neighbourhoods']['unapproved_invalid_ids']=['1'];self.save()
        ds=self.dataset();uid='ca-on-test-neighbourhoods-1'
        self.assertNotIn(uid,ds.geometries);self.assertIn(uid,ds.lookup(-80.8,44.5)['review_candidate_ids'])
        self.assertFalse(ds.boundary(uid)['properties']['suitable_for_assignment'])
        with self.assertRaises(CatalogueError):ds.boundary(uid,'full')

    def test_changed_checksum_identity_omitted_parts_and_repair_approval_fail_atomically(self):
        original=copy.deepcopy(self.plan)
        for change in ('checksum','identity','parts','approval','parent'):
            with self.subTest(change=change):
                self.plan=copy.deepcopy(original)
                if change=='checksum':self.plan['sources']['municipal']['sha256']='0'*64
                elif change=='identity':self.plan['sources']['municipal']['identities'][0]['properties']['NAME']='Wrong'
                elif change=='parts':self.plan['adjustments'][0]['members'][0]['source_ids']=['1']
                elif change=='approval':self.plan['repair_review'][0]['status']='approved'
                else:self.plan['city_layers'][1].update(parent_property='GROUP',parent_ids={'c':'ca-on-missing'})
                write_json(self.root/'plan.json',self.plan)
                with self.assertRaises(CatalogueError):self.build()
                self.assertFalse((self.root/'updated').exists())

    def test_overlap_compares_both_extents_and_exact_threshold(self):
        old = box(0, 0, 100, 100)
        for new in (box(0, 0, 10, 10), box(0, 0, 1000, 1000), box(30, 0, 130, 100)):
            with self.subTest(bounds=new.bounds):
                self.assertFalse(compare_extents(old, new)['sufficient_overlap'])
        self.assertTrue(compare_extents(old, box(20, 0, 120, 100))['sufficient_overlap'])
        self.assertFalse(compare_extents(old, box(20.01, 0, 120.01, 100))['sufficient_overlap'])
        with self.assertRaises(CatalogueError):
            compare_extents(old, Polygon())

    def test_failed_member_defers_complete_group_and_preserves_uncertainty(self):
        self.payloads['municipal']['features'][2]['geometry'] = mapping(box(-78.8, 44, -78.7, 44.1))
        self.save()
        before = sha256(self.base/'catalogue.sqlite3')
        ds = self.dataset()
        report = ds.summary['coverage']['ontario_refresh']
        self.assertEqual(report['updated_municipality_count'], 0)
        self.assertEqual(report['updated_region_count'], 0)
        self.assertEqual(report['deferred_municipality_count'], 2)
        for uid in ('3501001', '3501002'):
            with open_catalogue(self.base) as db:
                old = shapely.from_wkb(db.execute('SELECT geometry FROM csd WHERE id=?', (uid,)).fetchone()[0])
            self.assertTrue(ds.geometries['ca-csd-'+uid].equals_exact(old, 0))
            self.assertEqual(ds.areas['ca-csd-'+uid]['update_status'], 'deferred')
            self.assertNotIn('boundary_source', ds.areas['ca-csd-'+uid])
            self.assertNotIn('effective_date', ds.areas['ca-csd-'+uid])
            self.assertEqual(ds.areas['ca-csd-'+uid]['proposed_boundary_source'], 'municipal')
        # A deferred source expansion outside the retained original still flags uncertainty.
        self.assertIn('ca-csd-3501001', ds.lookup(-78.9,44.5)['review_candidate_ids'])
        self.assertNotIn('ca-csd-3501001', ds.lookup(-78.9,44.5)['direct_match_ids'])
        self.assertEqual(sha256(self.base/'catalogue.sqlite3'), before)
