"""Offline acceptance and bounded local serving measurements. Never calls production.

Timing is evidence, not a CI gate. Cold file reads request POSIX DONTNEED for the
specific file; this is advisory and is not a global page-cache flush.
"""
import argparse
import hashlib
import http.client
import socket
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import time

from totally_normal_maps.catalogue import read_json
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.display_packages import PackageError
from totally_normal_maps.population import metadata
from tools.read_display_package import validate_pair

SAMPLES=['ca-qc-ra-07','ca-csd-2481017','ca-csd-2466023','ca-csd-2465005','ca-csd-2458227',
         'ca-csd-3520005','ca-csd-3506008','ca-csd-5915022','ca-nu-cd-6204']


def summary(values):
    values=sorted(values)
    return {'median_ms':statistics.median(values)*1000,'p95_ms':values[max(0, int(len(values)*.95+.999)-1)]*1000}


def file_times(path,n,cold):
    values=[]
    for _ in range(n):
        with path.open('rb') as f:
            if cold and hasattr(os,'posix_fadvise'):os.posix_fadvise(f.fileno(),0,0,os.POSIX_FADV_DONTNEED)
            start=time.perf_counter();f.read();values.append(time.perf_counter()-start)
    return summary(values)


def acceptance(data):
    groups=Counter();unsupported=[];gaps=0
    for uid in sorted(data.packages.roots):
        try:
            d=json.loads(data.packages.descriptor(uid)[0]);groups[d['bundle_kind']]+=1;gaps+=d['coverage']!='complete'
        except PackageError as exc:unsupported.append({'area_id':uid,'reason':exc.code})
    ranked=[]
    for uid in data.packages.roots:
        r=data.areas[uid]
        if r['level']!='municipality':continue
        p=metadata(data,r)['population']
        if p is not None and p['reference_year']==2021 and p['measure']=='usual_residents':ranked.append((p['count'],uid))
    top=[]
    for count,uid in sorted(ranked,key=lambda r:(-r[0],r[1]))[:100]:
        try:
            d=json.loads(data.packages.descriptor(uid)[0]);top.append({'area_id':uid,'population':count,'status':d['status'],'bundle_id':d['bundle_id'],'coverage':d['coverage']})
        except PackageError as exc:top.append({'area_id':uid,'population':count,'status':exc.code})
    return {'root_count':len(data.packages.roots),'selection_counts':dict(groups),'unsupported_roots':unsupported,
            'partial_or_none_roots':gaps,'qualified_population_candidates':len(ranked),'top_100_qualified':top,
            'query_coverage_fraction':None,'query_coverage_reason':'No consumer query-frequency evidence supplied.'}


def run(dataset,version,n=20,concurrency=4):
    start=time.perf_counter();data=Dataset(dataset,version);startup=time.perf_counter()-start
    if data.packages.index is None:raise ValueError('Release has no prepared packages.')
    report={'dataset_version':data.version,'startup_seconds':startup,'python':platform.python_version(),
            'platform':platform.platform(),'cpu_count':os.cpu_count(),'cpu_model':next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),'unknown'),
            'sample_count':n,'concurrency':concurrency,'cache_state':'Warm startup verification; DONTNEED reads are advisory only.',
            'acceptance':acceptance(data),'samples':[],
            'package_bytes':sum(s['bytes'] for f,s in data.manifest['files'].items() if f.startswith('packages/'))}
    # The server uses already verified geography; startup was measured separately.
    # Each scope experiment has its own normal 120/minute consumer budget.
    import uvicorn
    from totally_normal_maps.api import create_app,Settings
    tokens={uid:hashlib.sha256(('benchmark:'+uid).encode()).hexdigest() for uid in SAMPLES}
    app=create_app(Settings(Path(dataset),data.version,mode='production',tokens=tokens,allowed_hosts=('127.0.0.1',)))
    app.state.dataset=data
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,lifespan='off',access_log=False,log_level='error',limit_concurrency=64))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    deadline=time.monotonic()+10
    while not server.started:
        if time.monotonic()>deadline:raise RuntimeError('Loopback benchmark server did not start.')
        time.sleep(.01)
    for uid in SAMPLES:
        if uid not in data.areas:continue
        try:raw,_=data.packages.descriptor(uid)
        except PackageError as exc:report['samples'].append({'area_id':uid,'status':exc.code});continue
        d=json.loads(raw);g=d['geometry']
        sample={'area_id':uid,'name':data.areas[uid]['name'],'bundle_id':d['bundle_id'],'status':d['status'],
                'counts':d['counts'],'descriptor_bytes':len(raw),'geometry':g}
        if g:
            path,_=data.packages.artifact(g['sha256'],'gzip');wire=path.read_bytes();validate_pair(d,wire,'gzip')
            sample['warm_file_read']=file_times(path,n,False);sample['advisory_cold_file_read']=file_times(path,n,True)
            def request(target):
                start=time.perf_counter();connection=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
                try:
                    connection.request('GET',target,headers={'Authorization':'Bearer '+tokens[uid],
                        'If-Match':'"'+data.version+'"','Accept-Encoding':'gzip'})
                    response=connection.getresponse()
                    if response.status!=200:raise ValueError('Benchmark request failed: '+str(response.status))
                    first=response.read(1);ttfb=time.perf_counter()-start
                    content=first+response.read()
                    return ttfb,time.perf_counter()-start,len(content)
                finally:connection.close()
            cpu=time.process_time()
            descriptors=[request('/v1/areas/'+uid+'/display-package') for _ in range(n)]
            artifacts=[request(g['path']) for _ in range(n)]
            sample['descriptor_first_byte']=summary([v[0] for v in descriptors])
            sample['descriptor_complete']=summary([v[1] for v in descriptors])
            sample['artifact_first_byte']=summary([v[0] for v in artifacts])
            sample['artifact_complete']=summary([v[1] for v in artifacts])
            started=time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:values=list(pool.map(request,[g['path']]*n))
            elapsed=time.perf_counter()-started
            sample['concurrent_http']=summary([v[1] for v in values]);sample['concurrent_requests_per_second']=n/elapsed
            sample['concurrent_wire_mib_per_second']=sum(v[2] for v in values)/elapsed/1024**2
            sample['cpu_seconds']=time.process_time()-cpu
        report['samples'].append(sample)
    server.should_exit=True;thread.join(timeout=10);listener.close()
    report['peak_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    report['timing_scope']='Local loopback HTTP, new TCP connection per request, identity descriptors and precompressed gzip artifacts; no TLS or browser rendering. Each scope uses an isolated consumer identity with unchanged 120/minute quota.'
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--manifest-sha256',required=True);p.add_argument('--samples',type=int,default=10)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not 1<=a.samples<=20:p.error('Use 1–20 samples to stay within the standard request budget.')
    result=run(a.dataset,a.manifest_sha256,a.samples)
    with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'samples','acceptance'}},indent=2))


if __name__=='__main__':main()
