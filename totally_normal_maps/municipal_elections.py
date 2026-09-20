"""Offline, editioned municipal electoral boundaries and explicit coverage gaps."""
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
from datetime import date, datetime

import pyogrio
from pyogrio.raw import read
from pyproj import CRS, Transformer
import shapely
from shapely.geometry import box, mapping
from shapely.ops import transform
from shapely.strtree import STRtree

from .catalogue import (CatalogueError, PROVINCES, ROOT, geometry_issue, identity_digest,
                        new_directory, propose_repair, read_json, sha256, write_json)
from .electoral import source_uri, electoral_source_metadata
from .layers import TOKEN, public_url, valid_date
from .releases import MAX_FILE_BYTES, checked_release, validate_manifest

PLAN = ROOT / 'municipal-elections-2026-09.json'
STATUSES = {'current', 'reference', 'historical', 'upcoming'}
COVERAGE = {'included', 'reference', 'partial', 'at_large', 'unverified', 'unavailable', 'historical_only'}


def text_value(value):
    """Publisher values as stable strings, with integral numeric fields normalized."""
    if hasattr(value, 'item'): value = value.item()
    if value is None: return ''
    if isinstance(value, (date, datetime)): return value.isoformat()
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise CatalogueError('Unsupported municipal source field type.')
    if isinstance(value, float):
        if not math.isfinite(value): return ''
        if value.is_integer(): value = int(value)
    return str(value).strip()


def municipal_scopes(data):
    return {uid for uid, r in data.areas.items() if r['level'] == 'municipality'
            and r.get('lifecycle_status') != 'superseded'}


def validate_editions(editions, data):
    if not isinstance(editions, list) or len(editions) > 5000:
        raise CatalogueError('Invalid municipal edition inventory.')
    seen, defaults = set(), set()
    for e in editions:
        if not isinstance(e, dict): raise CatalogueError('Invalid municipal edition.')
        uid, scope = e.get('id'), e.get('authority_id')
        parent = data.areas.get(scope) if isinstance(scope, str) else None
        if (not isinstance(uid, str) or not TOKEN.fullmatch(uid) or uid in seen
                or not parent or parent['level'] not in {'municipality', 'region'}
                or parent.get('lifecycle_status') == 'superseded'
                or e.get('layer') != 'municipal' or e.get('provinces') != [data.areas[parent['province_id']]['source_id']]
                or not isinstance(e.get('status'), str) or e['status'] not in STATUSES
                or type(e.get('default')) is not bool or e['default'] and e['status'] not in {'current', 'reference'}
                or not isinstance(e.get('scheme'), str) or not TOKEN.fullmatch(e['scheme'])
                or not all(isinstance(e.get(k), str) and 0 < len(e[k].strip()) <= 500 for k in
                           ('label', 'authority', 'boundary_set', 'electoral_event'))
                or not public_url(e.get('evidence_url'))
                or type(e.get('expected_count')) is not int or not 1 <= e['expected_count'] <= 2000
                or not isinstance(e.get('sources'), list) or len(e['sources']) != 1
                or not isinstance(e['sources'][0], str) or not TOKEN.fullmatch(e['sources'][0])
                or any(e.get(k) is not None and not valid_date(e[k]) for k in ('effective_date', 'valid_to', 'source_date'))):
            raise CatalogueError('Invalid municipal edition identity, scope, provenance or date.')
        if e.get('effective_date') and e.get('valid_to') and e['effective_date'] >= e['valid_to']:
            raise CatalogueError('Municipal edition validity dates are reversed.')
        seen.add(uid)
        if e['default']:
            key = (scope, e['scheme'])
            if key in defaults: raise CatalogueError('Multiple default municipal editions for one authority and scheme.')
            defaults.add(key)
    return editions


def coverage_inventory(data, editions, rows, declarations=None):
    declarations = declarations or {}
    scopes = municipal_scopes(data) | {e['authority_id'] for e in editions}
    if not isinstance(declarations, dict) or declarations.keys() - scopes:
        raise CatalogueError('Municipal coverage references an unknown authority.')
    counts, missing = Counter(), Counter()
    for r in rows:
        counts[r['edition']] += 1
        missing[r['edition']] += r['assignment_status'] != 'validated_source'
    output = {}
    for scope in sorted(scopes):
        spec = declarations.get(scope, {})
        if (not isinstance(spec, dict) or not isinstance(spec.get('status', 'unverified'), str)
                or spec.get('status', 'unverified') not in COVERAGE):
            raise CatalogueError('Invalid municipal coverage status.')
        available = [e for e in editions if e['authority_id'] == scope]
        chosen = [e for e in available if e['default']]
        if spec.get('status') == 'at_large':
            if chosen or not public_url(spec.get('evidence_url')) or not valid_date(spec.get('reviewed_on')):
                raise CatalogueError('At-large representation needs dated evidence and cannot have default wards.')
            status = 'at_large'
        elif chosen:
            status = 'reference' if any(e['status'] == 'reference' for e in chosen) else 'included'
            if spec.get('status') == 'partial': status = 'partial'
        else:
            status = 'historical_only' if available else spec.get('status', 'unverified')
            if status in {'included', 'partial', 'reference'}:
                raise CatalogueError('Municipal coverage claims boundaries without a default edition.')
        row = data.areas[scope]
        output[scope] = {'authority_id': scope, 'name': row['name'], 'level': row['level'],
            'province': data.areas[row['province_id']]['source_id'], 'status': status,
            'editions': [e['id'] for e in available], 'default_editions': [e['id'] for e in chosen],
            'district_count': sum(counts[e['id']] for e in chosen),
            'unavailable_count': sum(missing[e['id']] for e in chosen),
            'evidence_url': spec.get('evidence_url') or (chosen[0]['evidence_url'] if chosen else None),
            'reviewed_on': spec.get('reviewed_on'),
            'note': spec.get('note') or ('All councillors are elected across the municipality; no ward boundaries.' if status == 'at_large' else
                'Available reference edition; applicability to the current election has not been verified.' if status == 'reference' else
                'Municipal electoral coverage has not yet been verified.' if status == 'unverified' else
                'Source district inventory retained; independent legal gap validation is unavailable.')}
    return output


def load_municipal(data, db, present):
    data.municipal_coverage = {}
    part = data.report.get('municipal_elections')
    if not part:
        if present: raise CatalogueError('Municipal boundaries require their provenance report.')
        return
    if not present: raise CatalogueError('Municipal report lacks its boundary table.')
    editions = validate_editions(part['editions'], data)
    by_id = {e['id']: e for e in editions}
    if by_id.keys() & data.editions.keys(): raise CatalogueError('Duplicate electoral edition namespace.')
    counts, records = Counter(), []
    for raw in db.execute('SELECT * FROM municipal_electoral_area ORDER BY id'):
        row = json.loads(raw['record'])
        e = by_id.get(row.get('edition'))
        if (not e or row.get('id') != raw['id'] or row.get('parent_id') != e['authority_id']
                or row.get('authority_id') != e['authority_id'] or row.get('province') not in e['provinces']
                or row.get('province_id') != data.areas[e['authority_id']]['province_id']
                or row.get('layer') != 'municipal' or row.get('level') != 'electoral_district'
                or row.get('source') not in e['sources'] or row['source'] not in part['sources']
                or row.get('edition_status') != e['status'] or row.get('scheme') != e['scheme']
                or row.get('boundary_set') != e['boundary_set']
                or not isinstance(row.get('name'), str) or not row['name']
                or not isinstance(row.get('source_id'), str) or not row['source_id']):
            raise CatalogueError('Invalid municipal district identity or authority.')
        data.add(row); records.append(row); counts[e['id']] += 1
        data.source_ids[('electoral_district', row['id'])] = row['id']
        if raw['geometry'] is not None:
            geometry = shapely.from_wkb(raw['geometry'])
            if geometry_issue(geometry) or row['assignment_status'] != 'validated_source' or row.get('source_geometry_issue') or row.get('repair'):
                raise CatalogueError('Invalid municipal assignment geometry.')
            data.geometries[row['id']] = geometry; data.required_displays.add(row['id'])
        else:
            if row['assignment_status'] not in {'unreviewed_repair', 'missing_geometry'}:
                raise CatalogueError('Missing municipal assignment geometry.')
            if raw['repair_candidate'] is not None:
                geometry = shapely.from_wkb(raw['repair_candidate'])
                if geometry_issue(geometry): raise CatalogueError('Invalid municipal display candidate.')
                data.required_displays.add(row['id'])
            elif row.get('bbox'):
                bounds = row['bbox']
                if (not isinstance(bounds, list) or len(bounds) != 4
                        or any(type(x) not in (int,float) or not math.isfinite(x) for x in bounds)
                        or not -180 <= bounds[0] <= bounds[2] <= 180 or not -90 <= bounds[1] <= bounds[3] <= 90):
                    raise CatalogueError('Invalid municipal uncertainty bounds.')
                geometry = box(*bounds)
            else:
                data.unknown_ids.append(row['id']); continue
            data.pending_ids.append(row['id']); data.pending_shapes.append(geometry)
    if dict(counts) != {e['id']:e['expected_count'] for e in editions} or dict(counts) != part['edition_counts']:
        raise CatalogueError('Municipal district inventory differs from the release report.')
    data.municipal_coverage = coverage_inventory(data, editions, records, part['coverage'])
    if data.municipal_coverage != part['coverage']:
        raise CatalogueError('Municipal coverage differs from its actual inventory.')
    data.editions.update(by_id)
    for scope, spec in data.municipal_coverage.items(): data.areas[scope]['municipal_elections'] = spec


def layer_coverage(data, chosen=None, *, explicit=False):
    selected = set(chosen if chosen is not None else (uid for uid,e in data.editions.items() if e['layer']=='municipal' and e['default']))
    if not hasattr(data, '_municipal_province_summary'):
        groups = defaultdict(list)
        for row in data.municipal_coverage.values(): groups[row['province']].append(row)
        data._municipal_province_summary = {p: (len(rows),dict(Counter(r['status'] for r in rows))) for p,rows in groups.items()}
    by_province = defaultdict(list)
    for uid in sorted(selected):
        edition = data.editions[uid]
        for p in edition['provinces']: by_province[p].append(edition)
    result = {}
    for province in PROVINCES:
        count, counts = data._municipal_province_summary.get(province,(0,{}))
        eds = by_province[province]
        result[province] = {'status':('not_selected' if explicit and not eds else 'partial' if count else 'unavailable'), 'editions':[e['id'] for e in eds],
            'expected_count':sum(e['expected_count'] for e in eds),
            'authority_count':count, 'coverage_counts':counts,
            'note':'Coverage is tracked per municipality/local authority; a province total does not imply complete coverage.'}
    return result


def lookup_coverage(data, point, chosen, direct, *, explicit=False):
    scopes = {data.editions[uid]['authority_id'] for uid in chosen}
    authority_ids = {data.areas[uid]['authority_id'] for uid in direct}
    for index in data.tree.query(point, predicate='covered_by'):
        uid = data.geometry_ids[int(index)]
        # A regional browsing envelope also contains incorporated towns. It is
        # not proof that the regional council represents those towns' residents.
        if (uid in data.municipal_coverage and data.areas[uid]['level'] == 'municipality'
                and (not explicit or uid in scopes)):
            if not direct or uid in authority_ids: authority_ids.add(uid)
    coverage = []
    for uid in sorted(authority_ids):
        record = data.municipal_coverage[uid]
        if explicit:
            selected = [data.editions[e] for e in sorted(chosen) if data.editions[e]['authority_id'] == uid]
            record = {**record, 'editions': [e['id'] for e in selected],
                'district_count': sum(e['expected_count'] for e in selected),
                'unavailable_count': sum(data.report['municipal_elections']['validation'][e['id']]['unavailable_count'] for e in selected),
                'status': 'partial' if record['status'] == 'partial' else
                          'reference' if any(e['status'] == 'reference' for e in selected) else 'included',
                'evidence_url': selected[0]['evidence_url'] if selected else None,
                'selection_statuses': sorted({e['status'] for e in selected}),
                'note': 'Explicit edition selection; consult each selected edition’s dates and evidence.'}
        coverage.append(record)
    uncertain = any(r['status'] in {'unverified','unavailable','partial','historical_only'} for r in coverage)
    if not explicit and any(r['status']=='reference' for r in coverage): uncertain = True
    # An unlocated or unverified authority must not become a confident negative.
    if not coverage and not explicit: uncertain = True
    return coverage, uncertain


def read_source(path, source):
    if (not isinstance(source, dict) or not isinstance(source.get('filename'), str)
            or Path(source['filename']).name != source['filename'] or source['filename'] in {'.','..'}
            or not isinstance(source.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}',source['sha256'])
            or type(source.get('expected_count')) is not int or not 1 <= source['expected_count'] <= 50000
            or not public_url(source.get('licence')) or source.get('redistribution_status') not in {'permitted','unconfirmed'}):
        raise CatalogueError('Invalid municipal source specification.')
    uri = source_uri(path, source)
    info = pyogrio.read_info(uri, layer=source.get('layer_name'))
    if not info['crs'] or not CRS(info['crs']).equals(CRS(source['crs'])) or info['features'] != source['expected_count']:
        raise CatalogueError('Municipal source CRS or feature count changed.')
    meta, _, geometries, columns = read(uri, layer=source.get('layer_name'), encoding=source.get('encoding'))
    output = []
    for i, raw in enumerate(geometries):
        properties = {str(k):text_value(c[i]) for k,c in zip(meta['fields'],columns)}
        geometry = shapely.from_wkb(raw) if raw is not None else None
        output.append((properties, geometry))
    return output


def district_rows(source_rows, source, edition):
    where = edition.get('where', {})
    fields = edition.get('id_fields', [])
    if (not isinstance(where,dict) or any(not isinstance(k,str) or not isinstance(v,list) or not v
            or any(not isinstance(x,str) for x in v) for k,v in where.items())
            or not isinstance(fields,list) or not fields or any(not isinstance(f,str) for f in fields)):
        raise CatalogueError('Invalid municipal source selection or identity fields.')
    groups = defaultdict(list)
    required = {*where,*fields,*([edition['name_field']] if edition.get('name_field') else [])}
    for properties, geometry in source_rows:
        if not required <= properties.keys(): raise CatalogueError('Municipal publisher fields changed.')
        if not all(properties[k] in values for k,values in where.items()): continue
        raw_id = '|'.join(properties[f] for f in fields)
        if any(not properties[f] for f in fields): raise CatalogueError('Empty municipal publisher identity.')
        groups[raw_id].append((properties,geometry))
    if len(groups) != edition['expected_count'] or identity_digest(groups) != edition['identity_sha256']:
        raise CatalogueError('Municipal district identities differ from the pinned inventory.')
    projection = Transformer.from_crs(source['crs'],4326,always_xy=True)
    codes = set()
    for raw_id, items in sorted(groups.items()):
        if len(items)>1 and not edition.get('merge_parts'):
            raise CatalogueError('Duplicate district source identity without an explicit part-union rule.')
        props = items[0][0]
        name = props.get(edition.get('name_field'), '') or (edition.get('name_prefix','District')+' '+raw_id)
        if any((p.get(edition.get('name_field'), '') or name) != name for p,_ in items):
            raise CatalogueError('District parts disagree on their name.')
        code = edition.get('identity_map',{}).get(raw_id, re.sub(r'[^a-z0-9_-]+','-',raw_id.lower()).strip('-'))
        if not code or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,49}',code) or code in codes:
            raise CatalogueError('Ambiguous municipal catalogue identity; provide an explicit identity mapping.')
        codes.add(code)
        issues = [geometry_issue(g) for _,g in items if geometry_issue(g)]
        native = [g for _,g in items if g is not None and not g.is_empty]
        if not native: full = None
        elif len(native)==1: full = native[0]
        elif issues: full = shapely.GeometryCollection(native)
        else: full = shapely.union_all(native)
        issue = issues[0] if issues else geometry_issue(full)
        if full is not None:
            if shapely.get_num_coordinates(full)>3_000_000: raise CatalogueError('Municipal geometry exceeds vertex budget.')
            full = transform(projection.transform,full)
            w,s,e,n = full.bounds
            if not (-142.5<=w<=e<=-50 and 40<=s<=n<=90):
                raise CatalogueError(f"Municipal geometry lies outside Canada: {edition['id']} / {raw_id}.")
            issue = issue or geometry_issue(full)
        yield raw_id,code,name,full,issue,len(items)


def build_municipal(dataset, source_dir, output, *, plan_path=None, tolerance=40):
    from .dataset import Dataset
    base = Dataset(dataset)
    if Path(output).resolve().is_relative_to(base.root): raise CatalogueError('Municipal output must be outside its input release.')
    plan_path = Path(plan_path or PLAN); plan = read_json(plan_path,MAX_FILE_BYTES)
    plan_hash = sha256(plan_path)
    if (plan.get('schema_version')!=1 or not valid_date(plan.get('reviewed_on'))
            or not isinstance(plan.get('sources'),dict) or len(plan['sources'])>2000
            or not isinstance(plan.get('release_label'),str) or not plan['release_label']):
        raise CatalogueError('Invalid municipal import plan.')
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or not 0<=tolerance<=200:
        raise CatalogueError('Municipal display tolerance must be 0–200 metres.')
    editions = validate_editions(plan['editions'],base)
    old = base.report.get('municipal_elections',{})
    if set(base.editions)&{e['id'] for e in editions}: raise CatalogueError('Municipal edition already exists.')
    replacing = {(e['authority_id'],e['scheme']) for e in editions if e['default']}
    previous = [{**e,**({'default':False} if (e['authority_id'],e['scheme']) in replacing else {})}
                for e in old.get('editions',[])]
    all_editions = validate_editions(previous+editions,base)
    sources, loaded = dict(old.get('sources',{})), {}
    for key,s in plan['sources'].items():
        if not isinstance(key,str) or not TOKEN.fullmatch(key): raise CatalogueError('Invalid municipal source key.')
        metadata = electoral_source_metadata(s)
        if key in sources and sources[key]!=metadata: raise CatalogueError('Changed municipal source requires a new source key.')
        loaded[key] = read_source(Path(source_dir)/s['filename'],s); sources[key]=metadata
    projected = Transformer.from_crs(4326,3347,always_xy=True)
    inverse = Transformer.from_crs(3347,4326,always_xy=True)
    records, features, checks = [],defaultdict(list),{}
    for edition in editions:
        key = edition['sources'][0]
        if key not in loaded: raise CatalogueError('Municipal edition source is unavailable.')
        scope = base.areas[edition['authority_id']]; shapes=[]; unavailable=0
        for raw_id,code,name,full,issue,parts in district_rows(loaded[key],plan['sources'][key],edition):
            uid = f"ca-{edition['id']}-{code}"
            if len(uid)>100 or len(name)>200: raise CatalogueError('Municipal identity or name exceeds API bounds.')
            row = {'id':uid,'source_id':raw_id,'catalogue_code':code,'name':name,'aliases':[],
                'level':'electoral_district','kind':edition.get('kind','municipal_electoral_district'),
                'layer':'municipal','parent_id':scope['id'],'authority_id':scope['id'],'authority_name':scope['name'],
                'province_id':scope['province_id'],'province':edition['provinces'][0],
                'edition':edition['id'],'edition_status':edition['status'],'scheme':edition['scheme'],
                'boundary_set':edition['boundary_set'],'authority':edition['authority'],
                'electoral_event':edition['electoral_event'],'effective_date':edition.get('effective_date'),
                'valid_to':edition.get('valid_to'),'source_date':edition.get('source_date'),
                'source':key,'source_geometry_issue':issue,'source_parts':parts,
                'identity_basis':edition.get('identity_basis','publisher_code'),
                'bbox':list(full.bounds) if full is not None else None,'issues':[], 'assignment_status':'validated_source'}
            candidate=None
            if issue:
                row['issues'].append(issue);row['assignment_status']='missing_geometry';unavailable+=1
                if full is not None and issue.startswith('invalid_geometry:'):
                    candidate,metrics=propose_repair(full);row['repair']=metrics
                    if candidate is not None and not geometry_issue(candidate):row['assignment_status']='unreviewed_repair'
                    else:candidate=None
                full=None
            display_base=full if full is not None else candidate
            features.setdefault(row['province'],[])
            if display_base is not None:
                display=transform(inverse.transform,transform(projected.transform,display_base).simplify(tolerance,preserve_topology=True))
                if geometry_issue(display):display=display_base
                features[row['province']].append({'type':'Feature','properties':{'id':uid,'assignment_status':row['assignment_status']},'geometry':mapping(display)})
            if full is not None:shapes.append((uid,full))
            records.append((uid,json.dumps(row,ensure_ascii=False),full.wkb if full is not None else None,candidate.wkb if candidate is not None else None))
        tree=STRtree([g for _,g in shapes]);overlaps=[]
        for i,(uid,g) in enumerate(shapes):
            for j in tree.query(g,predicate='intersects'):
                if int(j)<=i:continue
                area=transform(projected.transform,g.intersection(shapes[int(j)][1])).area
                if area>1:overlaps.append({'ids':[uid,shapes[int(j)][0]],'area_m2':round(area,3)})
        checks[edition['id']]={'overlaps':overlaps,'unavailable_count':unavailable,
            'representative_points_checked':0,'representative_points_passed':False,
            'gap_validation':'No independent legal authority envelope supplied; source polygons are not clipped or gap-filled.'}
    with new_directory(output) as staging:
        if sha256(plan_path) != plan_hash: raise CatalogueError('Municipal import plan changed during the build.')
        for name in base.manifest['files']:
            path=staging/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(base.root/name,path)
        with closing(sqlite3.connect(staging/'catalogue.sqlite3')) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS municipal_electoral_area (id TEXT PRIMARY KEY, record TEXT NOT NULL, geometry BLOB, repair_candidate BLOB)')
            db.executemany('INSERT INTO municipal_electoral_area VALUES (?,?,?,?)',records)
            rows=[json.loads(r[0]) for r in db.execute('SELECT record FROM municipal_electoral_area')]
        for province,items in features.items():
            path=staging/'display'/f'municipal-{province}.geojson'
            retained=read_json(path,MAX_FILE_BYTES)['features'] if path.exists() else []
            write_json(path,{'type':'FeatureCollection','features':retained+items})
        declarations={**old.get('coverage',{}),**plan.get('coverage',{})}
        # Counts and selected editions are regenerated when defaults change.
        declarations={uid:{k:v for k,v in spec.items() if k in {'status','note','evidence_url','reviewed_on'}} for uid,spec in declarations.items()}
        coverage=coverage_inventory(base,all_editions,rows,declarations)
        report={**base.report,'catalogue_sha256':sha256(staging/'catalogue.sqlite3')}
        report['municipal_elections']={'schema_version':1,'reviewed_on':plan['reviewed_on'],
            'editions':all_editions,'sources':sources,'coverage':coverage,
            'edition_counts':dict(Counter(r['edition'] for r in rows)),
            'import_plan_sha256':[*old.get('import_plan_sha256',[]),plan_hash],
            'validation':{**old.get('validation',{}),**checks},'display_tolerance_metres':tolerance,
            'source_inventory':plan.get('source_inventory',old.get('source_inventory',{}))}
        write_json(staging/'report.json',report)
        manifest={**base.manifest,'label':plan['release_label'],'files':{str(p.relative_to(staging)):{'bytes':p.stat().st_size,'sha256':sha256(p)} for p in sorted(staging.rglob('*')) if p.is_file()}}
        validate_manifest(manifest);write_json(staging/'manifest.json',manifest)
        verified=Dataset(staging)
        for uid,_,_,_ in records:
            if uid not in verified.geometries:continue
            row=verified.areas[uid];point=verified.geometries[uid].representative_point()
            result=verified.lookup(point.x,point.y,layers=['municipal'],editions={'municipal':[row['edition']]})
            if uid not in result['direct_match_ids']:raise CatalogueError('Municipal representative point failed lookup.')
            checks[row['edition']]['representative_points_checked']+=1
        for check in checks.values():check['representative_points_passed']=True
        write_json(staging/'report.json',report)
        manifest['files']['report.json']={'bytes':(staging/'report.json').stat().st_size,'sha256':sha256(staging/'report.json')}
        write_json(staging/'manifest.json',manifest);checked_release(staging)
    return {'output':str(output),'manifest_sha256':sha256(Path(output)/'manifest.json'),
            'added_districts':len(records),'added_editions':len(editions),'coverage':dict(Counter(r['status'] for r in coverage.values()))}
