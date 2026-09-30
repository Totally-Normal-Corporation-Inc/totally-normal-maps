"""Synthetic package contract tests: no source downloads or production requests."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from shapely.geometry import box, mapping, Polygon, MultiPolygon

from tests.api_fixture import make_release
from totally_normal_maps.api import Settings, create_app
from totally_normal_maps.catalogue import CatalogueError, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps import display_packages as packages
from totally_normal_maps.population import encoded
from totally_normal_maps.releases import checked_release, validate_manifest

QC = 'ca-csd-2401001'
ON = 'ca-csd-3501001'
REGION = 'ca-qc-test-region'


def plan(root, members=None):
    value = {'schema_version': 1, 'membership_vintage': 'synthetic', 'basis': 'Synthetic cross-province membership.',
             'sources': [{'authority':'Synthetic','url':'https://example.test/groups','sha256':hashlib.sha256(b'fixture').hexdigest(),
                          'licence':'https://example.test/licence','attribution':'Synthetic attribution.'}],
             'groups': [{'id':'test-agglomeration','name':'Same name','kind':'agglomeration','source_category':'A',
                         'municipality_ids': sorted(members or [QC,ON])}]}
    path = root/'groups.json'; write_json(path,value); return path


def reseal(root):
    manifest = json.loads((root/'manifest.json').read_text())
    for name in manifest['files']:
        p=root/name; manifest['files'][name]={'bytes':p.stat().st_size,'sha256':sha256(p)}
    write_json(root/'manifest.json',manifest)
    return sha256(root/'manifest.json')


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        _,cls.base,cls.version=make_release(cls.root)
        cls.plan=plan(cls.root)
        cls.release=cls.root/'prepared'
        cls.report=packages.prepare(cls.base,cls.release,expected_sha256=cls.version,plan_path=cls.plan)
        cls.data=Dataset(cls.release)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_shared_cross_province_bytes_and_independent_focus(self):
        a=json.loads(self.data.packages.descriptor(QC)[0]);b=json.loads(self.data.packages.descriptor(ON)[0])
        self.assertEqual(a['bundle_id'],b['bundle_id']);self.assertEqual(a['geometry'],b['geometry'])
        self.assertNotEqual(a['viewport_bbox'],b['viewport_bbox'])
        self.assertEqual(a['root_id'],QC);self.assertEqual(b['root_id'],ON)
        self.assertEqual(a['scope_root_ids'],[QC,ON]);self.assertEqual(a['counts']['areas'],4)
        self.assertNotIn('test-agglomeration',self.data.areas)
        self.assertEqual(next(r for r in a['areas'] if r['id']==ON)['parent_id'],'ca-on')
        self.assertEqual(next(r for r in a['areas'] if r['id']==QC)['parent_id'],REGION)
        for row in a['areas']:self.assertFalse(row['suitable_for_assignment'])
        path,_=self.data.packages.artifact(a['geometry']['sha256'],'identity')
        artifact=json.loads(path.read_bytes())
        self.assertEqual({f['id'] for f in artifact['features']},{r['id'] for r in a['areas'] if r['display_status']=='available'})
        self.assertNotIn('dataset_version',artifact);self.assertNotIn('root_id',artifact)
        self.assertTrue(all(f['properties']=={} for f in artifact['features']))

    def test_all_provinces_and_single_root_fallback(self):
        self.assertEqual(len(packages.eligible(self.data)),14)
        for uid in packages.eligible(self.data):
            body,_=self.data.packages.descriptor(uid)
            descriptor=json.loads(body)
            self.assertTrue(descriptor['inventory_complete'])
            self.assertEqual(descriptor['counts']['areas'],len(descriptor['areas']))
        self.assertEqual(json.loads(self.data.packages.descriptor('ca-csd-6201001')[0])['counts']['areas'],1)

    def test_missing_outlines_and_assignment_warnings(self):
        data=copy.deepcopy(self.data)
        child='ca-qc-test-west';data.displays.pop(child);data.areas[child]['assignment_status']='missing_geometry'
        prov=packages.Provenance(data)
        base,body,_=packages.base_descriptor(data,'fixture','municipality',[QC],None,prov)
        self.assertEqual(base['coverage'],'partial');self.assertEqual(base['counts'],{'areas':3,'available':2,'unavailable':1})
        self.assertEqual(base['status'],'ready')
        for uid in packages.scope_members(data,[QC]):
            data.displays.pop(uid,None);data.areas[uid]['assignment_status']='missing_geometry'
        base,body,_=packages.base_descriptor(data,'fixture','municipality',[QC],None,prov)
        self.assertEqual(base['status'],'unavailable');self.assertIsNone(body);self.assertIsNone(base['geometry'])
        data.areas[QC]['assignment_status']='validated_source'
        with self.assertRaisesRegex(CatalogueError,'without explicit'):packages.geometry_body(data,'fixture',[QC])
        flagged=[r for r in self.data.areas.values() if r['assignment_status']=='unreviewed_repair']
        self.assertTrue(flagged)
        r=flagged[0];base,_,_=packages.base_descriptor(self.data,r['id'],'municipality',[r['id']],None,packages.Provenance(self.data))
        self.assertEqual(base['areas'][0]['assignment_status'],'unreviewed_repair')
        self.assertTrue(base['areas'][0]['issues'])

    def test_nested_hierarchy_cycles_conflicts_and_retirement(self):
        data=copy.deepcopy(self.data);east='ca-qc-test-east';west='ca-qc-test-west'
        data.children[QC].remove(east);data.children[west].append(east);data.areas[east]['parent_id']=west
        self.assertEqual(len(packages.scope_members(data,[REGION])),4)
        prov=packages.Provenance(data);base,_,_=packages.base_descriptor(data,'nested','region',[REGION],None,prov)
        self.assertEqual(next(r for r in base['areas'] if r['id']==east)['parent_id'],west)
        data.areas[east]['lifecycle_status']='superseded'
        self.assertNotIn(east,packages.scope_members(data,[REGION]))
        data.areas[east].pop('lifecycle_status');data.areas[east]['parent_id']=QC
        with self.assertRaisesRegex(CatalogueError,'conflicting parent'):packages.scope_members(data,[QC])
        data.areas[east]['parent_id']=west;data.children[east].append(QC);data.areas[QC]['parent_id']=east
        with self.assertRaisesRegex(CatalogueError,'cycle'):packages.scope_members(data,[QC])
        with self.assertRaises(CatalogueError):packages.scope_members(self.data,[REGION,QC])

    def test_canonical_bytes_ignore_population_labels_unrelated_shapes(self):
        members=packages.scope_members(self.data,[QC]);original=packages.geometry_body(self.data,QC,members)
        changed=copy.deepcopy(self.data)
        changed.areas[QC]['name']='Translated label';changed.areas[QC]['population']={'count':999}
        changed.displays[ON]=mapping(box(-10,10,-9,11))
        self.assertEqual(original,packages.geometry_body(changed,QC,members))
        changed.displays[members[-1]]=mapping(box(-20,10,-19,11))
        self.assertNotEqual(original[0],packages.geometry_body(changed,QC,members)[0])
        changed.displays.pop(members[-1]);changed.areas[members[-1]]['assignment_status']='missing_geometry'
        self.assertNotEqual(original[0],packages.geometry_body(changed,QC,members)[0])
        changed=copy.deepcopy(self.data);changed.areas[QC]['parent_id']='ca-qc'
        self.assertEqual(original,packages.geometry_body(changed,QC,members))
        self.assertEqual(gzip.decompress(original[1]),original[0])
        self.assertEqual(original[1][4:8],b'\0'*4)

    def test_holes_multipolygons_and_malformed_coordinates(self):
        geom=mapping(MultiPolygon([Polygon([(0,0),(5,0),(5,5),(0,5),(0,0)],holes=[[(1,1),(1,2),(2,2),(2,1),(1,1)]]),box(8,0,9,1)]))
        count,bbox=packages.polygon_stats(geom);self.assertEqual(count,15);self.assertEqual(bbox,[0,0,9,5])
        for invalid in [dict(type='Point',coordinates=[0,0]),dict(type='Polygon',coordinates=[]),
                        dict(type='Polygon',coordinates=[[[0,0],[1,0],[1,1],[0,1]]]),
                        dict(type='Polygon',coordinates=[[[181,0],[181,1],[182,1],[181,0]]]),
                        dict(type='Polygon',coordinates=[[[0,0,0],[1,0,0],[1,1,0],[0,0,0]]]),
                        dict(type='Polygon',coordinates=[[[0,0],[float('nan'),0],[1,1],[0,0]]])]:
            with self.subTest(invalid=invalid),self.assertRaises(CatalogueError):packages.polygon_stats(invalid)

    def test_exact_limits_then_one_over(self):
        for maximum,name in [(packages.MAX_MEMBERS,'members'),(packages.MAX_DEPTH,'depth'),
                (packages.MAX_GEOMETRY_BYTES,'decoded'),(packages.MAX_TRANSFER_BYTES,'transfer'),
                (packages.MAX_VERTICES,'vertices'),(packages.MAX_FEATURE_VERTICES,'feature'),(packages.MAX_DESCRIPTOR_BYTES,'descriptor')]:
            packages.bound(maximum,maximum,name)
            with self.assertRaises(packages.TooLarge):packages.bound(maximum+1,maximum,name)
        members=packages.scope_members(self.data,[QC]);body,compressed,_,vertices=packages.geometry_body(self.data,QC,members)
        for constant,limit in [('MAX_GEOMETRY_BYTES',len(body)),('MAX_TRANSFER_BYTES',len(compressed)),('MAX_VERTICES',vertices)]:
            with patch.object(packages,constant,limit):packages.geometry_body(self.data,QC,members)
            with patch.object(packages,constant,limit-1),self.assertRaises(packages.TooLarge):packages.geometry_body(self.data,QC,members)
        with patch.object(packages,'MAX_MEMBERS',len(members)):packages.scope_members(self.data,[QC])
        with patch.object(packages,'MAX_MEMBERS',len(members)-1),self.assertRaises(packages.TooLarge):packages.scope_members(self.data,[QC])
        with patch.object(packages,'MAX_DEPTH',0),self.assertRaises(packages.TooLarge):packages.scope_members(self.data,[QC])
        feature_vertices=max(packages.polygon_stats(self.data.displays[u])[0] for u in members)
        with patch.object(packages,'MAX_FEATURE_VERTICES',feature_vertices):packages.geometry_body(self.data,QC,members)
        with patch.object(packages,'MAX_FEATURE_VERTICES',feature_vertices-1),self.assertRaises(packages.TooLarge):packages.geometry_body(self.data,QC,members)

    def test_immutable_rebuild_and_failed_publication(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'repeat';r=packages.prepare(self.base,out,expected_sha256=self.version,plan_path=self.plan)
            self.assertEqual(r['dataset_version'],self.report['dataset_version'])
            with self.assertRaises(CatalogueError):packages.prepare(self.base,out,expected_sha256=self.version,plan_path=self.plan)
            with patch.object(packages,'geometry_body',side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):packages.prepare(self.base,Path(t)/'failure',expected_sha256=self.version,plan_path=self.plan)
            self.assertFalse((Path(t)/'failure').exists());checked_release(out)
        with self.assertRaisesRegex(CatalogueError,'final release'):packages.require_unprepared(self.data)
        with self.assertRaisesRegex(CatalogueError,'outside'):packages.prepare(self.base,self.base/'nested',expected_sha256=self.version,plan_path=self.plan)

    def test_oversized_is_explicit_and_unresolved_group_is_disclosed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            with patch.object(packages,'MAX_MEMBERS',3):
                r=packages.prepare(self.base,root/'large',expected_sha256=self.version,plan_path=self.plan)
            self.assertEqual(r['unsupported']['test-agglomeration']['reason'],'scope_too_large')
            with patch.object(packages,'MAX_MEMBERS',3):data=Dataset(root/'large')
            with self.assertRaises(packages.PackageError) as exc:data.packages.descriptor(QC)
            self.assertEqual(exc.exception.code,'scope_too_large')
            p=plan(root,[QC,'ca-csd-9999999'])
            packages.prepare(self.base,root/'unresolved',expected_sha256=self.version,plan_path=p)
            data=Dataset(root/'unresolved');result=json.loads(data.packages.descriptor(QC)[0])
            self.assertEqual(result['selection']['reason'],'preferred_group_unavailable')
            self.assertEqual(result['bundle_id'],QC)

    def test_corrupt_missing_gzip_and_stale_base_rejected(self):
        descriptor=json.loads(self.data.packages.descriptor(QC)[0]);digest=descriptor['geometry']['sha256']
        for mode in ['missing','corrupt','gzip','stale']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                root=Path(t)/'release';shutil.copytree(self.release,root)
                file=root/('packages/objects/'+digest+'.geojson')
                if mode=='missing':file.unlink()
                elif mode=='corrupt':file.write_bytes(file.read_bytes()+b' ')
                elif mode=='gzip':
                    (root/(str(file.relative_to(root))+'.gz')).write_bytes(gzip.compress(b'x'*(packages.MAX_GEOMETRY_BYTES+1)))
                    reseal(root)
                else:
                    report=json.loads((root/'report.json').read_text());report['state']='changed';write_json(root/'report.json',report);reseal(root)
                with self.assertRaises((CatalogueError,ValueError)):Dataset(root)

    def test_plan_rejects_overlapping_or_unknown_fields(self):
        p=json.loads(self.plan.read_text());p['groups'].append({**p['groups'][0],'id':'another'})
        with self.assertRaises(CatalogueError):packages.validate_plan(p)
        p=json.loads(self.plan.read_text());p['groups'][0]['url']='file:///etc/passwd'
        with self.assertRaises(CatalogueError):packages.validate_plan(p)

    def test_consumer_fixtures_and_real_version_change(self):
        from tools.make_display_package_fixtures import generate
        from tools.read_display_package import validate_pair
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'fixtures';generate(root)
            ds={}
            for case in ('complete','partial','unavailable','version-change'):
                folder=root/case;d=json.loads((folder/'descriptor.json').read_text());ds[case]=d
                self.assertEqual(sha256(folder/'fixture-manifest.json'),d['dataset_version'])
                if d['geometry']:
                    wire=(folder/(d['geometry']['sha256']+'.geojson.gz')).read_bytes()
                    validate_pair(d,wire,'gzip')
                    with self.assertRaises(CatalogueError):validate_pair(d,wire+b'extra','gzip')
                    bad=copy.deepcopy(d);bad['geometry']['path']='https://untrusted.test/a'
                    with self.assertRaises((CatalogueError,ValueError)):validate_pair(bad,wire,'gzip')
                    bad=copy.deepcopy(d);bad['geometry']['sha256']='f'*64
                    with self.assertRaises(CatalogueError):validate_pair(bad,wire,'gzip')
                    bad=copy.deepcopy(d);bad['viewport_bbox']=[0.,0.,1.,1.]
                    with self.assertRaises(CatalogueError):validate_pair(bad,wire,'gzip')
                else:
                    validate_pair(d)
                    bad=copy.deepcopy(d);bad['common_source_ids'].append('unlisted-source')
                    with self.assertRaises(CatalogueError):validate_pair(bad)
            self.assertEqual(ds['complete']['geometry'],ds['version-change']['geometry'])
            self.assertNotEqual(ds['complete']['dataset_version'],ds['version-change']['dataset_version'])
            self.assertEqual(json.loads((root/'oversized/response.json').read_text())['actual'],501)

    def test_assignment_and_circle_results_are_unchanged(self):
        from totally_normal_maps.circle import CircleIndex,CircleInput
        before=Dataset(self.base)
        a=before.lookup(-109.75,50.5);b=self.data.lookup(-109.75,50.5)
        a.pop('dataset_version');b.pop('dataset_version');self.assertEqual(a,b)
        request=CircleInput(longitude=-109.75,latitude=50.5,radius_m=1000)
        a=CircleIndex(before).lookup(request).model_dump();b=CircleIndex(self.data).lookup(request).model_dump()
        a.pop('dataset_version');b.pop('dataset_version');self.assertEqual(a,b)

    def test_schema_two_distribution_roundtrip_and_public_site_exclusion(self):
        from totally_normal_maps.distribution import package_dataset,unpack_dataset
        from totally_normal_maps.deployment import assemble_deployment,verify_deployment
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);notice=root/'NOTICE.md';notice.write_text('Synthetic reference attribution.\n')
            package_dataset(self.release,root/'distribution',manifest_sha256=self.data.version,
                            repository='example/maps',tag='dataset-synthetic-packages',notice=notice)
            lock=root/'distribution/dataset.lock.json';record=json.loads(lock.read_text())
            archive=root/'distribution'/record['asset']
            unpack_dataset(record,root/'unpacked',archive=archive)
            self.assertEqual(Dataset(root/'unpacked/dataset').version,self.data.version)
            assemble_deployment(lock,root/'bundle',archive=archive)
            loaded,deployment,site=verify_deployment(root/'bundle')
            self.assertEqual(loaded.version,self.data.version)
            self.assertFalse(any('packages/' in n for n in site['files']))
            self.assertTrue(loaded.packages.responses)

    def test_false_source_attribution_and_selection_are_rejected(self):
        for mode in ('sources','selection'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                root=Path(t)/'copy';shutil.copytree(self.release,root)
                index=json.loads((root/packages.INDEX).read_text())
                if mode=='selection':index['selections'][QC]['bundle_id']=ON
                else:
                    record=index['bundles']['test-agglomeration'];old=record['descriptor']
                    base=json.loads((root/old).read_text());base['attribution']=[]
                    raw=encoded(base);new='packages/descriptors/'+hashlib.sha256(raw).hexdigest()+'.json'
                    (root/new).write_bytes(raw);(root/old).unlink();record['descriptor']=new
                    manifest=json.loads((root/'manifest.json').read_text());manifest['files'].pop(old)
                    manifest['files'][new]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                    write_json(root/'manifest.json',manifest)
                (root/packages.INDEX).write_bytes(encoded(index));reseal(root)
                with self.assertRaises(CatalogueError):Dataset(root)

    def test_descriptor_limit_and_normal_depth_boundary(self):
        base,_,_=packages.base_descriptor(self.data,QC,'municipality',[QC],None,packages.Provenance(self.data))
        size=len(packages.envelope(self.data,QC,base,{'bundle_id':QC,'reason':'catalogue_scope'})[0])
        with patch.object(packages,'MAX_DESCRIPTOR_BYTES',size):packages.envelope(self.data,QC,base,{'bundle_id':QC,'reason':'catalogue_scope'})
        with patch.object(packages,'MAX_DESCRIPTOR_BYTES',size-1),self.assertRaises(packages.TooLarge):packages.envelope(self.data,QC,base,{'bundle_id':QC,'reason':'catalogue_scope'})
        data=copy.deepcopy(self.data);parent=QC
        for i in range(10):
            uid='nested-'+str(i);data.areas[uid]={**data.areas[QC],'id':uid,'parent_id':parent,'level':'city_area','municipality_id':QC}
            data.children[parent].append(uid);parent=uid
        packages.scope_members(data,[QC])
        uid='nested-11';data.areas[uid]={**data.areas[parent],'id':uid,'parent_id':parent};data.children[parent].append(uid)
        with self.assertRaises(packages.TooLarge):packages.scope_members(data,[QC])


class PackageHTTPTests(unittest.TestCase):
    setUpClass = classmethod(PackageTests.setUpClass.__func__)
    tearDownClass = classmethod(PackageTests.tearDownClass.__func__)
    def client(self,release=None,quota=1000):
        path=release or self.release
        settings=Settings(path,sha256(path/'manifest.json'),mode='production',tokens={'test':'a'*40},allowed_hosts=('testserver',),requests_per_minute=quota)
        client=TestClient(create_app(settings));client.__enter__();self.addCleanup(client.__exit__,None,None,None)
        client.headers['Authorization']='Bearer '+'a'*40
        return client

    def test_http_auth_preconditions_head_encodings_and_query_bounds(self):
        client=self.client();url='/v1/areas/'+QC+'/display-package'
        response=client.get(url);self.assertEqual(response.status_code,200,response.text)
        descriptor=response.json();path=descriptor['geometry']['path']
        for target in [url,path]:
            first=client.get(target,headers={'Accept-Encoding':'identity'})
            self.assertEqual(first.status_code,200)
            head=client.head(target,headers={'Accept-Encoding':'identity'})
            for h in ['etag','content-length','content-type','cache-control','vary']:
                self.assertEqual(first.headers[h],head.headers[h])
            self.assertEqual(head.content,b'');self.assertIn('no-store',first.headers['cache-control'])
            self.assertEqual(client.get(target,headers={'If-None-Match':first.headers['etag'],'Accept-Encoding':'identity'}).status_code,304)
            self.assertEqual(client.get(target,headers={'If-None-Match':'*','If-Match':'"'+'0'*64+'"'}).status_code,412)
            self.assertEqual(client.get(target,headers={'Authorization':'Bearer '+'b'*40,'If-None-Match':'*'}).status_code,401)
            self.assertEqual(client.get(target+'?arbitrary=yes').status_code,422)
        identity=client.get(path,headers={'Accept-Encoding':'identity'});compressed=client.get(path,headers={'Accept-Encoding':'gzip'})
        self.assertEqual(identity.content,compressed.content);self.assertNotEqual(identity.headers['etag'],compressed.headers['etag'])
        self.assertEqual(compressed.headers['content-encoding'],'gzip')
        self.assertEqual(hashlib.sha256(identity.content).hexdigest(),descriptor['geometry']['sha256'])
        self.assertEqual(client.get(path,headers={'Accept-Encoding':'identity;q=0,gzip;q=0'}).status_code,406)
        self.assertEqual(client.get(url+'?layer=federal').status_code,422)
        self.assertEqual(client.get(url+'?layer=administrative&layer=administrative').status_code,422)
        self.assertEqual(client.get('/v1/areas/ca/display-package').status_code,422)
        self.assertEqual(client.get('/v1/areas/unknown/display-package').status_code,404)
        self.assertEqual(client.get('/v1/display-packages/'+'0'*64+'.geojson').status_code,404)
        self.assertEqual(client.get('/v1/display-packages/https:%2F%2Fevil.test.geojson').status_code,404)
        self.assertEqual(client.get(path,headers={'Range':'bytes=0-10'}).status_code,422)

    def test_reads_do_not_build_scan_recompress_or_write(self):
        client=self.client();url='/v1/areas/'+QC+'/display-package';path=client.get(url).json()['geometry']['path']
        with patch.object(packages,'polygon_stats',side_effect=AssertionError('geometry scan')),\
             patch.object(packages,'prepare',side_effect=AssertionError('build')),\
             patch.object(packages,'encoded',side_effect=AssertionError('serialize')),\
             patch('gzip.compress',side_effect=AssertionError('compress')),\
             patch('sqlite3.connect',side_effect=AssertionError('sql')),\
             patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            self.assertEqual(client.get(url).status_code,200);self.assertEqual(client.get(path).status_code,200)

    def test_legacy_release_and_rate_limit(self):
        c=self.client(self.base);self.assertEqual(c.get('/v1/areas/'+QC+'/display-package').json()['code'],'package_not_built')
        self.assertEqual(c.get('/v1/areas/'+QC+'/boundary').status_code,200)
        c=self.client(quota=1);c.get('/v1/areas/'+QC+'/display-package')
        r=c.get('/v1/areas/'+QC+'/display-package');self.assertEqual(r.status_code,429);self.assertIn('retry-after',r.headers)

    def test_changed_dataset_requires_new_pin_even_for_same_geometry(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);shutil.copytree(self.base,root/'base')
            manifest=json.loads((root/'base/manifest.json').read_text());manifest['label']='different-version'
            write_json(root/'base/manifest.json',manifest)
            packages.prepare(root/'base',root/'prepared',expected_sha256=sha256(root/'base/manifest.json'),plan_path=self.plan)
            current=self.client(root/'prepared');old=self.client()
            url='/v1/areas/'+QC+'/display-package'
            before=old.get(url);after=current.get(url)
            self.assertNotEqual(before.headers['etag'],after.headers['etag'])
            self.assertEqual(before.json()['geometry'],after.json()['geometry'])
            path=after.json()['geometry']['path']
            response=current.get(path,headers={'If-Match':'"'+before.json()['dataset_version']+'"','If-None-Match':'*'})
            self.assertEqual(response.status_code,412)
            self.assertEqual(current.get(path,headers={'If-Match':'"'+after.json()['dataset_version']+'"','If-None-Match':'*'}).status_code,304)

    def test_openapi_and_runtime_file_failure(self):
        c=self.client();spec=c.get('/openapi.json').json()
        for path in ['/v1/areas/{area_id}/display-package','/v1/display-packages/{geometry_sha256}.geojson']:
            for method in ['get','head']:
                self.assertEqual(spec['paths'][path][method]['security'],[{'BearerAuth':[]}])
                self.assertIn('If-Match',[p['name'] for p in spec['paths'][path][method]['parameters']])
        path=c.get('/v1/areas/'+QC+'/display-package').json()['geometry']['path']
        with patch.object(packages.Path,'stat',side_effect=OSError('missing')):
            with self.assertLogs('totally_normal_maps.api',level='ERROR') as logs:r=c.get(path)
        self.assertEqual(r.status_code,503);self.assertEqual(len(logs.records),1)
