"""Offline lifecycle, nested hierarchy and source integrity tests with synthetic shapes."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import shapely
from shapely.geometry import box, mapping

from totally_normal_maps.catalogue import CatalogueError, open_catalogue, read_json, sha256, write_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.quebec_refresh import build_refresh
from totally_normal_maps.releases import export_release
from .api_fixture import make_release


class QuebecRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, _, _ = make_release(self.root)
        self.city = box(-76, 45, -75, 46)
        self.old = [box(-74, 45, -73.5, 46), box(-73.5, 45, -73, 46)]
        self.successor = shapely.union_all(self.old)
        self.region = 'ca-qc-test-region'
        self.west = 'ca-qc-test-west'
        self.evidence = [{'publisher': 'Synthetic test', 'url': 'https://example.invalid/evidence', 'claim': 'Synthetic identities and explicit parentage.'}]
        with closing(sqlite3.connect(self.base / 'catalogue.sqlite3')) as db, db:
            record = json.loads(db.execute("SELECT record FROM csd WHERE id='2401001'").fetchone()[0])
            record.update(bbox=list(self.city.bounds))
            db.execute("UPDATE csd SET record=?,geometry=? WHERE id='2401001'", (json.dumps(record), self.city.wkb))
            for uid, name, geom in zip(['2401002', '2401003'], ['Old A', 'Old B'], self.old):
                row = {**record, 'id': uid, 'name': name, 'bbox': list(geom.bounds)}
                db.execute('INSERT INTO csd VALUES (?, ?, ?, ?, ?, NULL)', (uid, '24', '{}', json.dumps(row), geom.wkb))
                db.execute('INSERT INTO csd_region VALUES (?, ?, ?)', (uid, self.region, 'synthetic'))
            full = shapely.union_all([self.city, *self.old])
            region_record = json.loads(db.execute('SELECT record FROM region').fetchone()[0])
            region_record.update(bbox=list(full.bounds), member_count=3)
            db.execute('UPDATE region SET record=?,geometry=?', (json.dumps(region_record), full.wkb))
            areas = []
            for uid, geom in [(self.west, box(-76,45,-75.5,46)), ('ca-qc-test-east', box(-75.5,45,-75,46))]:
                area = json.loads(db.execute('SELECT record FROM city_area WHERE id=?',(uid,)).fetchone()[0])
                area.update(parent_name='Gatineau', region_id=self.region, bbox=list(geom.bounds), level='city_area')
                db.execute('UPDATE city_area SET record=?,geometry=? WHERE id=?', (json.dumps(area),geom.wkb,uid));areas.append(area)
        report = read_json(self.base / 'report.json')
        report.update(feature_count=15, valid_geometry_count=14, catalogue_sha256=sha256(self.base / 'catalogue.sqlite3'))
        report['province_counts']['24'] = 3
        report['regions']['membership_count'] = 3
        report['city_areas']['issues'] = []
        write_json(self.base / 'report.json', report)
        public = read_json(self.base / 'preview/catalogue.json')
        public.update(report=report, city_areas=areas, regions=[region_record])
        with open_catalogue(self.base) as db:
            public['areas'] = [{**json.loads(r['record']), 'region_id': self.region if r['province']=='24' else None} for r in db.execute('SELECT * FROM csd')]
        next(r for r in public['provinces'] if r['id']=='24')['count'] = 3
        write_json(self.base / 'preview/catalogue.json', public)
        self.display('24.geojson', [(r['id'], self.city if r['id']=='2401001' else self.old[int(r['id'][-1])-2]) for r in public['areas'] if r['province']=='24'])
        self.display('regions-24.geojson', [(self.region, full)])
        self.display('city-areas-24.geojson', [(self.west, box(-76,45,-75.5,46)), ('ca-qc-test-east', box(-75.5,45,-75,46))])
        self.plan = {'schema_version':1, 'reviewed_on':'2026-09-18', 'base_source_sha256':report['source']['sha256'],
            'base_identity_sha256':report['identity_sha256'], 'sources':{},
            'mergers':[{'id':'ca-qc-mun-01004','source_id':'01004','source':'merger','name':'New City','type':'V',
                'region_id':self.region,'predecessor_csd_ids':['2401002','2401003'],'effective_date':'2026-01-01','evidence':self.evidence}],
            'names':[{'csd_id':'2401001','source_name':'Gatineau','name':'New Gatineau','evidence':self.evidence}],
            'areas':[], 'coverage':[], 'unresolved':['Synthetic unavailable sector'], 'repair_review':[]}
        self.payloads = {
            'merger': {'type':'FeatureCollection','features':[self.feature('01004','New City',self.successor)]},
            'quartiers': {'type':'FeatureCollection','features':[self.feature('1','Quarter A',box(-76,45,-75.75,46)),self.feature('2','Quarter B',box(-75.75,45,-75.5,46))]}}
        for key,payload in self.payloads.items():
            self.plan['sources'][key] = {'authority':'Synthetic test','family':key,'release':'test','url':'https://example.invalid/source','licence':'https://creativecommons.org/licenses/by/4.0/',
                'evidence':self.evidence,'expected_count':len(payload['features']),'id_field':'ID','name_field':'NOM','geojson_crs':None,
                'identities':[{'source_id':f['properties']['ID'],'properties':f['properties'].copy()} for f in payload['features']]}
        for uid,name in [('1','Quarter A'),('2','Quarter B')]:
            self.plan['areas'].append({'id':'ca-qc-quarter-'+uid,'name':name,'type':'Quartier','kind':'quartier',
                'parent_csd_id':'2401001','parent_name':'Gatineau','parent_area_id':self.west,'source':'quartiers','source_id':uid,'evidence':self.evidence})
        self.plan['areas'].append({'id':'ca-qc-unavailable','name':'Missing sector','type':'Secteur','kind':'sector','parent_csd_id':'2401001',
            'parent_name':'Gatineau','source':None,'geometry_status':'unavailable','coverage_note':'No qualified boundary.','evidence':self.evidence})
        self.plan['coverage'] = [{'parent_csd_id':'2401001','name':'Gatineau','source':'quartiers','expected_count':2,'coverage_policy':'partial'},
            {'parent_csd_id':'2401001','name':'Gatineau','source':None,'expected_count':1,'coverage_policy':'unavailable'}]
        self.save()

    def feature(self, uid, name, geom):
        return {'type':'Feature','properties':{'ID':uid,'NOM':name},'geometry':mapping(geom)}

    def display(self, name, rows):
        write_json(self.base/'preview'/name, {'type':'FeatureCollection','features':[{'type':'Feature','properties':{'id':uid},'geometry':mapping(g)} for uid,g in rows]})

    def save(self):
        for key,payload in self.payloads.items():
            write_json(self.root/(key+'.geojson'),payload)
            self.plan['sources'][key]['sha256'] = sha256(self.root/(key+'.geojson'))
        write_json(self.root/'plan.json', self.plan)

    def build(self, name='refreshed'):
        return build_refresh(self.base,self.root/name,source_dir=self.root,plan_path=self.root/'plan.json')

    def dataset(self):
        self.build(); export_release(self.root/'refreshed',self.root/'current-release')
        return Dataset(self.root/'current-release')

    def test_preserves_source_rows_and_complete_assignment_union(self):
        # A smaller provincial reference cannot silently remove predecessor land.
        self.payloads['merger']['features'][0]['geometry'] = mapping(self.old[0]);self.save()
        self.build()
        with open_catalogue(self.base) as old, open_catalogue(self.root/'refreshed') as new:
            for table in ('csd','region','csd_region'):
                self.assertEqual([tuple(r) for r in old.execute(f'SELECT * FROM {table}')],[tuple(r) for r in new.execute(f'SELECT * FROM {table}')])
            for row in old.execute('SELECT * FROM city_area'):
                self.assertEqual(tuple(row),tuple(new.execute('SELECT * FROM city_area WHERE id=?',(row['id'],)).fetchone()))
            geom = shapely.from_wkb(new.execute("SELECT geometry FROM area_revision WHERE id='ca-qc-mun-01004'").fetchone()[0])
            self.assertTrue(geom.equals(self.successor))
        with self.assertRaisesRegex(CatalogueError,'already exists'): self.build()
        with self.assertRaisesRegex(CatalogueError,'unmodified base'):
            build_refresh(self.root/'refreshed',self.root/'repeat',source_dir=self.root,plan_path=self.root/'plan.json')

    def test_current_history_search_and_nested_lookup(self):
        ds = self.dataset()
        self.assertEqual(ds.summary['counts']['municipality'],14)
        self.assertEqual(ds.summary['historical_counts'],{'municipality':2})
        self.assertEqual(ds.page(level='municipality',include_historical=True)['total'],16)
        self.assertEqual(ds.page(query='Old A')['items'][0]['id'],'ca-qc-mun-01004')
        self.assertEqual(ds.page(query='Gatineau')['items'][0]['name'],'New Gatineau')
        self.assertEqual(ds.page(parent_id=self.region)['total'],2)
        self.assertEqual(ds.page(parent_id=self.region,include_historical=True)['total'],4)
        self.assertFalse(ds.boundary('ca-csd-2401002','full')['properties']['suitable_for_assignment'])
        point = ds.lookup(-73.25,45.5)
        self.assertIn('ca-qc-mun-01004',point['direct_match_ids'])
        self.assertNotIn('ca-csd-2401003',point['direct_match_ids'])
        point = ds.lookup(-75.9,45.5)
        self.assertIn(self.west,point['direct_match_ids']);self.assertIn('ca-qc-quarter-1',point['direct_match_ids'])
        self.assertFalse(point['ambiguous'])
        self.assertEqual(ds.page(parent_id=self.west)['total'],2)
        self.assertTrue(ds.lookup(-75.75,45.5)['ambiguous'])  # sibling edge remains ambiguous

    def test_missing_boundary_is_local_uncertainty_and_never_assignment(self):
        ds=self.dataset()
        self.assertFalse(ds.areas['ca-qc-unavailable']['geometry_available'])
        with self.assertRaises(CatalogueError): ds.boundary('ca-qc-unavailable','full')
        point=ds.lookup(-75.9,45.5)
        self.assertNotIn('ca-qc-unavailable',point['direct_match_ids'])
        self.assertIn('ca-qc-unavailable',point['review_candidate_ids'])
        self.assertNotIn('ca-qc-unavailable',ds.lookup(-73.25,45.5)['review_candidate_ids'])

    def test_checksum_and_re_pinned_identity_changes_fail_atomically(self):
        (self.root/'quartiers.geojson').write_text((self.root/'quartiers.geojson').read_text()+' ')
        with self.assertRaisesRegex(CatalogueError,'checksum'):self.build()
        self.assertFalse((self.root/'refreshed').exists())
        self.payloads['quartiers']['features'][0]['properties']['NOM']='Changed';self.save()
        with self.assertRaisesRegex(CatalogueError,'source identity'):self.build()
        self.assertFalse((self.root/'refreshed').exists())

    def test_inconsistent_predecessor_and_nested_city_links_rejected(self):
        for change in ('predecessor','city-parent','counts'):
            with self.subTest(change=change):
                self.build(change)
                path = self.root/change
                with closing(sqlite3.connect(path/'catalogue.sqlite3')) as db, db:
                    if change=='predecessor':
                        row=json.loads(db.execute("SELECT record FROM area_revision WHERE operation='new'").fetchone()[0])
                        row['predecessor_ids'].append('ca-csd-2401001')
                        db.execute("UPDATE area_revision SET record=? WHERE operation='new'",(json.dumps(row),))
                    elif change=='city-parent':
                        db.execute("UPDATE city_area SET parent_csd_id='2401002' WHERE id='ca-qc-quarter-1'")
                report=read_json(path/'report.json')
                if change=='counts':report['quebec_refresh']['added_municipality_count']=2
                report['catalogue_sha256']=sha256(path/'catalogue.sqlite3');write_json(path/'report.json',report)
                export_release(path,self.root/(change+'-release'))
                with self.assertRaisesRegex(CatalogueError,'predecessor|ancestry|revision counts'):
                    Dataset(self.root/(change+'-release'))

    def test_unqualified_parent_exception_and_misparenting_rejected(self):
        original=copy.deepcopy(self.plan)
        for change in ('exception','parent','duplicate','namespace','retire-parent'):
            with self.subTest(change=change):
                self.plan=copy.deepcopy(original)
                if change=='exception':self.plan['areas'][0]['parent_outside_limit']=.17
                elif change=='parent':self.plan['areas'][0]['parent_area_id']='ca-qc-missing'
                elif change=='duplicate':self.plan['areas'].append(copy.deepcopy(self.plan['areas'][0]))
                elif change=='namespace':self.plan['mergers'][0]['id']='ca-csd-2401004'
                else:self.plan['mergers'][0]['predecessor_csd_ids']=['2401001','2401003']
                self.save()
                with self.assertRaises(CatalogueError):self.build()
                self.assertFalse((self.root/'refreshed').exists())

    def test_gross_sibling_overlap_wrong_parent_and_incomplete_source_rejected(self):
        original=copy.deepcopy(self.payloads)
        for change in ('overlap','parent','missing','invalid','crs'):
            with self.subTest(change=change):
                self.payloads=copy.deepcopy(original)
                if change=='overlap':self.payloads['quartiers']['features'][1]['geometry']=self.payloads['quartiers']['features'][0]['geometry']
                elif change=='parent':self.payloads['quartiers']['features'][0]['geometry']=mapping(box(-70,45,-69,46))
                elif change=='missing':self.payloads['quartiers']['features'].pop()
                elif change=='invalid':self.payloads['quartiers']['features'][0]['geometry']={'type':'Polygon','coordinates':[[[-76,45],[-75,46],[-75,45],[-76,46],[-76,45]]]}
                else:self.payloads['quartiers']['crs']={'properties':{'name':'EPSG:3857'}}
                self.save()
                with self.assertRaises(CatalogueError):self.build()
                self.assertFalse((self.root/'refreshed').exists())
