"""Generate executable synthetic consumer fixtures, with actual canonical/gzip hashes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from tests.api_fixture import make_release
from tests.test_display_packages import plan, QC, ON
from totally_normal_maps.catalogue import new_directory
from totally_normal_maps.dataset import Dataset
from totally_normal_maps.display_packages import (Provenance, base_descriptor, envelope, scope_members, TooLarge,
                                                 MAX_MEMBERS, read_plan)
from totally_normal_maps.population import encoded
from tools.read_display_package import validate_pair


def generate(output):
    with tempfile.TemporaryDirectory() as scratch, new_directory(output) as out:
        root=Path(scratch);_,release,_=make_release(root);original=Dataset(release)
        membership=read_plan(plan(root));group=membership['groups'][0]
        grouping={k:membership[k] for k in ('basis','membership_vintage','sources')}
        grouping.update(name=group['name'],source_category='A',identity_updates=[])
        for case in ('complete','partial','unavailable','version-change'):
            data=copy.deepcopy(original)
            if case in {'partial','unavailable'}:
                missing=['ca-qc-test-west'] if case=='partial' else scope_members(data,[QC,ON])
                for uid in missing:
                    data.displays.pop(uid,None);data.areas[uid]['assignment_status']='missing_geometry'
            if case=='version-change':data.areas[QC]['name']='Updated label; same shapes and membership'
            # This small fixture manifest supplies an actual reproducible dataset identity;
            # it is explicitly a consumer fixture, not a deployable serving release.
            fixture_manifest=encoded({'contract':'display-package-consumer-fixture.v1','areas':data.areas,'displays':data.displays})
            data.version=hashlib.sha256(fixture_manifest).hexdigest()
            base,body,compressed=base_descriptor(data,group['id'],'agglomeration',[QC,ON],grouping,Provenance(data))
            descriptor,_=envelope(data,QC,base,{'bundle_id':group['id'],'reason':'preferred_agglomeration'})
            parsed=json.loads(descriptor);validate_pair(parsed,compressed,'gzip') if body else validate_pair(parsed)
            directory=out/case;directory.mkdir()
            (directory/'fixture-manifest.json').write_bytes(fixture_manifest)
            (directory/'descriptor.json').write_bytes(descriptor)
            if body:
                name=parsed['geometry']['sha256']+'.geojson'
                (directory/name).write_bytes(body);(directory/(name+'.gz')).write_bytes(compressed)
        data=copy.deepcopy(original)
        for i in range(MAX_MEMBERS):
            uid='synthetic-child-'+str(i)
            data.areas[uid]={**data.areas[QC],'id':uid,'level':'city_area','parent_id':QC,'municipality_id':QC}
            data.children[QC].append(uid)
        try:scope_members(data,[QC])
        except TooLarge as exc:
            directory=out/'oversized';directory.mkdir()
            (directory/'response.json').write_bytes(encoded({'status':409,'error':'scope_too_large','code':'scope_too_large','limit':exc.limit,'actual':exc.actual}))
        else:raise AssertionError('Oversized fixture was accepted')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    generate(p.parse_args().output)


if __name__=='__main__':main()
