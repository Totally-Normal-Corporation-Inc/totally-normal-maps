"""Bounded example consumer: authenticate on a server, validate, then atomically retain.

This example does not connect provider identities to a consumer's local catalogue.
A consumer must validate current selectable identities before activating its snapshot.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from totally_normal_maps.catalogue import CatalogueError, new_directory
from totally_normal_maps.display_packages import (
    Descriptor, CONTRACT, GEOMETRY_CONTRACT, MAX_DESCRIPTOR_BYTES, MAX_GEOMETRY_BYTES,
    MAX_TRANSFER_BYTES, MAX_FEATURE_VERTICES, MAX_VERTICES, polygon_stats, union_bbox,
)
from totally_normal_maps.population import encoded


def require(value,message):
    if not value:raise CatalogueError(message)


def validate_pair(descriptor,wire=None,encoding='identity'):
    require(len(encoded(descriptor))<=MAX_DESCRIPTOR_BYTES,'Oversized descriptor.')
    Descriptor.model_validate(descriptor)
    rows=descriptor['areas'];ids={r['id'] for r in rows};roots=set(descriptor['scope_root_ids'])
    require(len(ids)==len(rows) and roots<=ids and descriptor['requested_area_id'] in roots,'Invalid scope identities.')
    mapping={r['id']:r for r in rows}
    require(descriptor['root_id']==descriptor['requested_area_id']
            and descriptor['root_level']==mapping[descriptor['root_id']]['level']
            and descriptor['scope_root_ids']==sorted(roots),'Invalid requested focus.')
    require(all(mapping[u]['parent_id'] not in ids for u in roots),'Overlapping or cyclic scope roots.')
    require(descriptor['selection'].get('bundle_id')==descriptor['bundle_id'],'Invalid bundle selection.')
    selection=descriptor['selection'];basic={'bundle_id','reason'}
    if descriptor['bundle_kind']=='agglomeration':
        require(all(mapping[u]['level']=='municipality' for u in roots)
                and descriptor['bundle_id'] not in ids and descriptor['grouping'] is not None,'Invalid agglomeration roots.')
        require(selection=={'bundle_id':descriptor['bundle_id'],'reason':'preferred_agglomeration',
                'preferred_bundle_id':descriptor['bundle_id'],'preferred_unavailable_reason':None},'Invalid preferred selection.')
    else:
        require(roots=={descriptor['root_id']} and descriptor['bundle_id']==descriptor['root_id']
                and descriptor['bundle_kind']==descriptor['root_level'] and descriptor['grouping'] is None,'Invalid catalogue scope.')
        if selection.get('reason')=='preferred_group_unavailable':
            require(descriptor['bundle_kind']=='municipality'
                    and set(selection)==basic|{'preferred_bundle_id','preferred_unavailable_reason'}
                    and isinstance(selection['preferred_bundle_id'],str)
                    and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',selection['preferred_bundle_id'])
                    and selection['preferred_bundle_id'] not in ids
                    and selection['preferred_unavailable_reason']=='membership_unresolved','Invalid fallback selection.')
        else:
            require(set(selection)==basic and selection.get('reason')=='catalogue_scope','Invalid catalogue selection.')
    sources={s['id'] for s in descriptor['sources']}
    require(len(sources)==len(descriptor['sources']) and set(descriptor['common_source_ids'])<=sources
            and all(set(r['source_ids'])<=sources for r in rows),'Invalid source references.')
    require(all(r['unavailable_reason']==('missing_geometry' if r['display_status']=='unavailable' else None)
                for r in rows),'Invalid missing-geometry reason.')
    for uid in ids-roots:
        seen={uid};current=uid
        while current not in roots:
            current=mapping[current]['parent_id']
            require(current in ids and current not in seen,'Incomplete or cyclic hierarchy.');seen.add(current)
            require(len(seen)<=11,'Hierarchy exceeds depth limit.')
        if mapping[uid]['level']=='city_area':
            require(mapping[uid]['municipality_id'] in seen
                    and mapping[mapping[uid]['municipality_id']]['level']=='municipality','Invalid municipal ancestry.')
    available={r['id'] for r in rows if r['display_status']=='available'}
    require(descriptor['counts']=={'areas':len(ids),'available':len(available),'unavailable':len(ids)-len(available)},'Invalid counts.')
    require(descriptor['coverage']==('none' if not available else 'complete' if available==ids else 'partial'),'Invalid coverage.')
    g=descriptor['geometry']
    if g is None:
        require(not available and descriptor['status']=='unavailable' and descriptor['unavailable_reason']=='no_display_geometry' and wire is None,'Invalid unavailable package.')
        require(descriptor['bundle_bbox'] is None and descriptor['viewport_bbox'] is None
                and descriptor['viewport_basis'] is None,'Unexpected unavailable bounds.')
        return None
    require(descriptor['status']=='ready' and descriptor['unavailable_reason'] is None,'Invalid ready status.')
    require(g['path']=='/v1/display-packages/'+g['sha256']+'.geojson','Untrusted artifact path.')
    require(set(g['encodings'])=={'identity','gzip'} and g['decoded_bytes']==g['encodings']['identity']['bytes'],'Invalid encoding inventory.')
    require(encoding in g['encodings'] and wire is not None and len(wire)==g['encodings'][encoding]['bytes']<=MAX_TRANSFER_BYTES,'Transfer size mismatch.')
    if encoding=='gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(wire)) as stream:body=stream.read(MAX_GEOMETRY_BYTES+1)
    else:body=wire
    require(len(body)==g['decoded_bytes']<=MAX_GEOMETRY_BYTES and hashlib.sha256(body).hexdigest()==g['sha256'],'Decoded integrity mismatch.')
    artifact=json.loads(body)
    require(encoded(artifact)==body and set(artifact)=={'contract','purpose','type','bundle_id','bbox','features'}
        and artifact['contract']==GEOMETRY_CONTRACT and artifact['purpose']=='display_only'
        and artifact['type']=='FeatureCollection' and artifact['bundle_id']==descriptor['bundle_id'],'Invalid artifact envelope.')
    require([f['id'] for f in artifact['features']]==sorted(available),'Feature inventory mismatch.')
    vertices=0;boxes=[]
    for f in artifact['features']:
        require(set(f)=={'type','id','properties','bbox','geometry'} and f['type']=='Feature' and f['properties']=={},'Invalid feature.')
        count,bbox=polygon_stats(f['geometry']);require(count<=MAX_FEATURE_VERTICES and bbox==f['bbox'],'Invalid feature bounds/vertices.')
        vertices+=count;boxes.append(bbox)
    require(vertices==g['vertex_count']<=MAX_VERTICES and len(available)==g['feature_count']
            and artifact['bbox']==descriptor['bundle_bbox']==union_bbox(boxes),'Invalid stored statistics.')
    focus=next((f for f in artifact['features'] if f['id']==descriptor['requested_area_id']),None)
    require(descriptor['viewport_bbox']==(focus['bbox'] if focus else artifact['bbox'])
            and descriptor['viewport_basis']==('root_display' if focus else 'available_features'),'Invalid focus viewport.')
    return body


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise CatalogueError('Provider redirects are not accepted.')


def download(base,path,headers,maximum):
    opener=build_opener(NoRedirect())
    with opener.open(Request(base+path,headers=headers),timeout=30) as response:
        require(response.status==200,'Expected a complete response.')
        if response.headers.get('Content-Length'):
            require(int(response.headers['Content-Length'])<=maximum,'Oversized transfer.')
        content=response.read(maximum+1);require(len(content)<=maximum,'Oversized transfer.')
        return content,response.headers


def fetch(base,area_id,version,token):
    url=urlsplit(base)
    require(url.scheme=='https' or url.scheme=='http' and url.hostname in {'127.0.0.1','localhost','::1'},'Use HTTPS or local loopback.')
    require(url.hostname and not url.username and not url.password and not url.query and not url.fragment and url.path in {'','/'},'Use a provider origin.')
    require(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',area_id) and re.fullmatch(r'[0-9a-f]{64}',version),'Invalid identity/version.')
    headers={'Authorization':'Bearer '+token,'If-Match':'"'+version+'"','Accept-Encoding':'identity'}
    raw,h=download(base.rstrip('/'),'/v1/areas/'+area_id+'/display-package',headers,MAX_DESCRIPTOR_BYTES)
    require(h.get('Content-Encoding','identity')=='identity','Unexpected descriptor encoding.')
    d=json.loads(raw);Descriptor.model_validate(d)
    require(d['dataset_version']==version and d['requested_area_id']==area_id and h.get('X-Maps-Dataset-Version')==version,'Descriptor version/scope mismatch.')
    if d['geometry'] is None:validate_pair(d);return d,None
    path=d['geometry']['path'];require(path=='/v1/display-packages/'+d['geometry']['sha256']+'.geojson','Untrusted artifact path.')
    raw,h=download(base.rstrip('/'),path,{**headers,'Accept-Encoding':'gzip'},MAX_TRANSFER_BYTES)
    require(h.get('X-Maps-Dataset-Version')==version,'Artifact version mismatch.')
    return d,validate_pair(d,raw,h.get('Content-Encoding','identity'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',required=True);p.add_argument('--area-id',required=True);p.add_argument('--dataset-version',required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    token=os.environ.get('MAPS_CONSUMER_TOKEN');require(token,'Set MAPS_CONSUMER_TOKEN on the consuming server.')
    d,body=fetch(a.url,a.area_id,a.dataset_version,token)
    with new_directory(a.output) as staging:
        (staging/'descriptor.json').write_bytes(encoded(d))
        if body is not None:(staging/(d['geometry']['sha256']+'.geojson')).write_bytes(body)
    print(json.dumps({'status':d['status'],'bundle_id':d['bundle_id'],'dataset_version':d['dataset_version']}))


if __name__=='__main__':main()
