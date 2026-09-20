"""Offline municipal imports, coverage semantics and independent political layers."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import box, Polygon, mapping
from fastapi.testclient import TestClient
from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import CatalogueError, identity_digest, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.municipal_elections import build_municipal
from totally_normal_maps.website import export_website, checked_website
from tests.test_electoral import electoral_fixture

class MunicipalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        _,cls.base,_,_=electoral_fixture(cls.root)
        cls.source=cls.root/'wards.geojson'
        write_json(cls.source,{'type':'FeatureCollection','features':[
            {'type':'Feature','properties':{'code':i,'name':name},'geometry':mapping(g)}
            for i,name,g in [('1','West',box(-111,49,-110,51)),('2','East',box(-110,49,-109,51))]]})
        cls.plan={'schema_version':1,'reviewed_on':'2026-09-19','release_label':'municipal-test',
            'sources':{'wards':{'filename':cls.source.name,'sha256':sha256(cls.source),'expected_count':2,
                'crs':'EPSG:4326','authority':'Synthetic council','licence':'https://example.test/licence','redistribution_status':'permitted'}},
            'editions':[{'id':'mun-test','authority_id':'ca-csd-2401001','layer':'municipal','provinces':['24'],
                'status':'current','default':True,'scheme':'council-wards','label':'Test wards','authority':'Synthetic council',
                'boundary_set':'test-wards','electoral_event':'Test election','evidence_url':'https://example.test/election',
                'expected_count':2,'sources':['wards'],'id_fields':['code'],'name_field':'name',
                'identity_sha256':identity_digest(['1','2'])}],
            'coverage':{'ca-csd-3501001':{'status':'at_large','reviewed_on':'2026-09-19','evidence_url':'https://example.test/at-large'}}}
        cls.path=cls.root/'municipal-plan.json';write_json(cls.path,cls.plan)
        cls.release=cls.root/'municipal';build_municipal(cls.base,cls.root,cls.release,plan_path=cls.path)
        cls.data=Dataset(cls.release)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_independent_matches_and_unchanged_administration(self):
        before=Dataset(self.base).lookup(-110.5,50)
        after=self.data.lookup(-110.5,50)
        for key in ('status','direct_match_ids','ambiguous'):self.assertEqual(before[key],after[key])
        r=self.data.lookup(-110.5,50,layers=['administrative','federal','provincial','municipal'])
        self.assertEqual(r['layers']['municipal']['direct_match_ids'],['ca-mun-test-1'])
        self.assertEqual(r['layers']['municipal']['municipal_coverage'][0]['status'],'included')
        self.assertTrue(self.data.lookup(-110,50,layers=['municipal'])['ambiguous'])
        self.assertNotIn('ca-mun-test-1',before['direct_match_ids'])

    def test_coverage_and_browse(self):
        self.assertEqual(self.data.municipal_coverage['ca-csd-3501001']['status'],'at_large')
        self.assertEqual(self.data.municipal_coverage['ca-csd-1001001']['status'],'unverified')
        self.assertEqual(self.data.page(layer='municipal',parent_id='ca-csd-2401001')['total'],2)
        self.assertEqual(self.data.page(layer='municipal',level='electoral_district',within_id='ca-qc')['total'],2)
        self.assertEqual(self.data.ancestors('ca-mun-test-1')[-1]['id'],'ca-csd-2401001')
        self.assertEqual(self.data.areas['ca-csd-2401001']['child_count'],2)
        self.assertEqual(self.data.areas['ca-csd-2401001']['child_counts_by_layer']['municipal'],2)

    def test_reference_is_not_confident_current_assignment(self):
        plan=copy.deepcopy(self.plan);e=plan['editions'][0];e.update(id='mun-reference',status='reference')
        path=self.root/'reference-plan.json';write_json(path,plan)
        release=self.root/'reference';build_municipal(self.release,self.root,release,plan_path=path)
        data=Dataset(release)
        self.assertEqual(data.lookup(-110.5,50,layers=['municipal'])['status'],'review_required')
        r=data.lookup(-110.5,50,layers=['municipal'],editions={'municipal':['mun-test']})
        self.assertEqual(r['direct_match_ids'],['ca-mun-test-1'])
        self.assertEqual(r['layers']['municipal']['municipal_coverage'][0]['status'],'included')
        self.assertEqual(r['layers']['municipal']['municipal_coverage'][0]['selection_statuses'],['current'])
        self.assertFalse(data.editions['mun-test']['default'])

    def test_tampered_source_and_at_large_evidence_rejected(self):
        for name,change in [('hash',lambda p:p['sources']['wards'].update(sha256='0'*64)),
                            ('atlarge',lambda p:p['coverage']['ca-csd-3501001'].pop('evidence_url')),
                            ('identity',lambda p:p['editions'][0].update(identity_sha256='0'*64))]:
            plan=copy.deepcopy(self.plan);change(plan);path=self.root/(name+'.json');write_json(path,plan)
            with self.assertRaises(CatalogueError):build_municipal(self.base,self.root,self.root/name,plan_path=path)

    def test_api_and_site(self):
        with TestClient(create_app(Settings(self.release,sha256(self.release/'manifest.json'),tokens={'test':'s'*40},allowed_hosts=('testserver',)))) as client:
            client.headers['Authorization']='Bearer '+'s'*40
            r=client.get('/v1/municipal-coverage?province=35&status=at_large');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['total'],1)
            self.assertEqual(client.get('/v1/municipal-coverage?province=99').status_code,422)
            self.assertEqual(client.get('/v1/municipal-coverage?status=anything').status_code,422)
            r=client.get('/v1/lookup?longitude=-110.5&latitude=50&layer=municipal');self.assertEqual(r.status_code,200)
            self.assertTrue(r.json()['layers']['municipal']['municipal_coverage'])
        output=self.root/'website';digest=export_website(self.data,output,notice=Path('NOTICE.md'))
        checked_website(output,expected_sha256=digest,dataset_sha256=self.data.version)
        catalogue=json.loads((output/'catalogue.json').read_text())
        self.assertIn('2401001',catalogue['report']['municipal_elections']['coverage'])
        self.assertEqual(next(r for r in catalogue['electoral_areas'] if r['layer']=='municipal')['authority_id'],'2401001')

    def test_invalid_source_is_display_only_and_unknown_is_not_at_large(self):
        plan=copy.deepcopy(self.plan);source=self.root/'invalid-wards.geojson'
        write_json(source,{'type':'FeatureCollection','features':[
            {'type':'Feature','properties':{'code':'1','name':'Invalid'},'geometry':mapping(Polygon([(-111,49),(-109,51),(-111,51),(-109,49),(-111,49)]))}]})
        plan['sources']['wards'].update(filename=source.name,sha256=sha256(source),expected_count=1)
        plan['editions'][0].update(expected_count=1,identity_sha256=identity_digest(['1']))
        path=self.root/'invalid-plan.json';write_json(path,plan);release=self.root/'invalid-release'
        build_municipal(self.base,self.root,release,plan_path=path);data=Dataset(release)
        self.assertNotIn('ca-mun-test-1',data.geometries)
        self.assertEqual(data.areas['ca-mun-test-1']['assignment_status'],'unreviewed_repair')
        self.assertEqual(data.lookup(-110.5,50.8,layers=['municipal'])['status'],'review_required')
        with self.assertRaises(CatalogueError):data.boundary('ca-mun-test-1','full')
        self.assertEqual(data.lookup(0,0,layers=['municipal'])['status'],'review_required')

    def test_represent_full_shape_identity_join_and_pins(self):
        from totally_normal_maps.source_acquisition import represent_snapshot
        import hashlib
        raw=json.dumps({'objects':[{'name':'One','external_id':'a'},{'name':'Two','external_id':'b'}],'meta':{'next':None}}).encode()
        shapes=json.dumps({'objects':[{'name':'Two','shape':mapping(box(-111,49,-110,50))},{'name':'One','shape':mapping(box(-110,49,-109,50))}]}).encode()
        spec={'expected_count':2,'acquisition':{'kind':'represent','slug':'synthetic-wards',
              'inventory_sha256':hashlib.sha256(raw).hexdigest(),'shape_sha256':hashlib.sha256(shapes).hexdigest()}}
        def request(url):return shapes if url.endswith('/shape') else raw
        result=json.loads(represent_snapshot(spec,request=request,pause=lambda _:None))
        self.assertEqual([r['properties']['code'] for r in result['features']],['b','a'])
        altered=copy.deepcopy(spec);altered['acquisition']['shape_sha256']='0'*64
        with self.assertRaises(CatalogueError):represent_snapshot(altered,request=request,pause=lambda _:None)
        bad=json.dumps({'objects':[{'name':'One','shape':None},{'name':'One','shape':None}]}).encode()
        altered=copy.deepcopy(spec);altered['acquisition']['shape_sha256']=hashlib.sha256(bad).hexdigest()
        with self.assertRaises(CatalogueError):represent_snapshot(altered,request=lambda u:bad if u.endswith('/shape') else raw,pause=lambda _:None)
