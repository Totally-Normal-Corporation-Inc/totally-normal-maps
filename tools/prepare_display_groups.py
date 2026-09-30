"""Reproduce the checked-in membership plan from two saved official HTML references.

No network access. Reference bytes must match the published plan's SHA-256 pins.
The only adopted code substitution is the evidenced SGC transaction 240018.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re

from totally_normal_maps.catalogue import CatalogueError
from totally_normal_maps.display_packages import PLAN, read_plan


def extract(raw):
    groups=[];current=None
    for level,part in re.findall(r'<li class="list-group-item indent-([23])">(.*?)(?=<li|</ul>)',raw.decode('utf-8'),re.S):
        value=html.unescape(re.sub('<[^>]+>','',part)).strip()
        code,name=value.split(' - ',1)
        if level=='2':
            if not re.fullmatch(r'\d{3}',code):raise CatalogueError('Invalid CMA/CA code.')
            current={'id':'ca-sac-2021-'+code,'name':name,'municipality_ids':[]};groups.append(current)
        else:
            if current is None or not re.fullmatch(r'\d{7}',code):raise CatalogueError('Invalid CSD membership.')
            current['municipality_ids'].append('ca-csd-'+code)
    return groups


def reproduce(cma,ca):
    reference=read_plan(PLAN);result={**reference,'groups':[]}
    definitions={g['id']:g for g in reference['groups']}
    for category,path,source,count in zip(('A','B'),(cma,ca),reference['sources'],(41,111)):
        raw=Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise CatalogueError('Reference bytes differ from reviewed membership evidence.')
        groups=extract(raw)
        if len(groups)!=count:raise CatalogueError('Incomplete reference group inventory.')
        for group in groups:
            group.update(kind='agglomeration',source_category=category)
            updates=definitions[group['id']].get('identity_updates',[])
            if updates:
                group['identity_updates']=updates
                for update in updates:
                    group['municipality_ids'].remove(update['previous_id'])
                    group['municipality_ids'].append(update['current_id'])
            group['municipality_ids'].sort();result['groups'].append(group)
    if result!=reference:raise CatalogueError('Extracted membership differs from reviewed plan.')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cma-html',required=True,type=Path);p.add_argument('--ca-html',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result=reproduce(a.cma_html,a.ca_html)
    with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')


if __name__=='__main__':main()
