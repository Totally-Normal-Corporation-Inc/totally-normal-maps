"""Independent geography families and explicitly selected boundary editions."""
import json
import math
import re
from collections import Counter
from datetime import date
from urllib.parse import urlsplit

import shapely
from shapely.geometry import box

from .catalogue import CatalogueError, PROVINCES, geometry_issue

LAYERS = {
    'administrative': 'Regions and cities',
    'federal': 'Federal electoral districts',
    'provincial': 'Provincial / territorial electoral districts',
    'municipal': 'Municipal elections',
}
ELECTORAL = {'federal', 'provincial'}
TOKEN = re.compile(r'[a-z0-9][a-z0-9_-]{0,79}')


def public_url(value):
    if not isinstance(value, str): return False
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


def valid_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_editions(editions):
    if not isinstance(editions, list) or not editions or len(editions) > 100:
        raise CatalogueError('Expected a bounded electoral edition inventory.')
    seen, defaults = set(), set()
    for edition in editions:
        if not isinstance(edition, dict): raise CatalogueError('Invalid electoral edition metadata.')
        uid = edition.get('id', '')
        provinces = edition.get('provinces', [])
        if (not isinstance(uid, str) or not TOKEN.fullmatch(uid) or uid in seen
                or not isinstance(edition.get('layer'), str) or edition['layer'] not in ELECTORAL
                or not isinstance(provinces, list) or not provinces
                or any(not isinstance(p, str) or p not in PROVINCES for p in provinces)
                or len(set(provinces)) != len(provinces)
                or not isinstance(edition.get('status'), str) or edition['status'] not in {'current', 'upcoming', 'historical'}
                or type(edition.get('default')) is not bool
                or edition.get('default') and edition.get('status') != 'current'
                or not all(isinstance(edition.get(k), str) and 0 < len(edition[k].strip()) <= 500 for k in
                           ('label', 'authority', 'boundary_set', 'electoral_event'))
                or not public_url(edition.get('evidence_url'))
                or any(edition.get(k) is not None and not valid_date(edition[k]) for k in ('effective_date', 'valid_to'))
                or type(edition.get('expected_count')) is not int or not 1 <= edition['expected_count'] <= 10000
                or not isinstance(edition.get('sources'), list) or not edition['sources']
                or any(not isinstance(s, str) or not TOKEN.fullmatch(s) for s in edition['sources'])
                or len(set(edition['sources'])) != len(edition['sources'])):
            raise CatalogueError('Invalid electoral edition metadata.')
        if (edition.get('effective_date') and edition.get('valid_to')
                and edition['effective_date'] >= edition['valid_to']):
            raise CatalogueError('Electoral validity dates are reversed or empty.')
        predecessors, evidence = edition.get('predecessors', {}), edition.get('relationship_evidence', [])
        if (not isinstance(predecessors, dict) or not isinstance(evidence, list)
                or any(not isinstance(code, str) or not isinstance(ids, list)
                       or any(not isinstance(uid, str) or not 1 <= len(uid) <= 100 for uid in ids)
                       for code, ids in predecessors.items())
                or predecessors and (not evidence or any(not public_url(e if isinstance(e, str) else e.get('url') if isinstance(e, dict) else None)
                                                        for e in evidence))):
            raise CatalogueError('Invalid electoral predecessor identities or evidence.')
        seen.add(uid)
        if edition['default']:
            keys = {(edition['layer'], p) for p in provinces}
            if defaults & keys:
                raise CatalogueError('Two default editions for the same layer and province.')
            defaults |= keys
    return editions


def derive_edition_coverage(editions, rows, declared=None):
    """Inventory coverage belongs to an edition, never to another edition's default."""
    counts, unavailable = Counter(), Counter()
    for row in rows:
        key = (row['edition'], row['province'])
        counts[key] += 1
        unavailable[key] += row['assignment_status'] != 'validated_source'
    declared = declared or {}
    if not isinstance(declared, dict) or declared.keys() - editions.keys():
        raise CatalogueError('Coverage references an unknown electoral edition.')
    output = {}
    for uid, edition in editions.items():
        specs = declared.get(uid, {})
        if not isinstance(specs, dict) or specs.keys() - set(edition['provinces']):
            raise CatalogueError('Invalid electoral coverage provinces.')
        output[uid] = {}
        for province in edition['provinces']:
            spec = specs.get(province, {})
            count = counts[(uid, province)]
            if (not isinstance(spec, dict) or not isinstance(spec.get('status', 'included'), str)
                    or spec.get('status', 'included') not in {'included', 'partial', 'unavailable'}
                    or not isinstance(spec.get('note', ''), str)
                    or type(spec.get('expected_count', count)) is not int
                    or spec.get('expected_count', count) != count or not count):
                raise CatalogueError('Electoral coverage differs from the boundary inventory.')
            output[uid][province] = {'edition': uid, 'expected_count': count,
                'status': spec.get('status', 'included'), 'unavailable_count': unavailable[(uid, province)],
                'note': spec.get('note', 'Complete edition inventory; independent gap validation remains unavailable.')}
    return output


def selection_coverage(editions, inventory, chosen, *, explicit=False):
    coverage = {}
    for province in PROVINCES:
        specs = [inventory[uid][province] for uid in sorted(chosen) if province in editions[uid]['provinces']]
        ids = [spec['edition'] for spec in specs]
        coverage[province] = {
            'status': ('included' if all(s['status'] == 'included' for s in specs) else 'partial') if specs else
                      'not_selected' if explicit else 'unavailable',
            'edition': ids[0] if len(ids) == 1 else None, 'editions': ids,
            'expected_count': sum(s['expected_count'] for s in specs),
            'unavailable_count': sum(s['unavailable_count'] for s in specs),
            'note': ' '.join(dict.fromkeys(s['note'] for s in specs)) if specs else
                    'No edition selected for this jurisdiction.' if explicit else 'No default edition available for this jurisdiction.'}
    return coverage


def load_electoral(data, db, present):
    part = data.report.get('electoral')
    data.editions = {}
    data.edition_coverage = {}
    if not part:
        if present: raise CatalogueError('Electoral boundaries require an edition report.')
        return
    if not present: raise CatalogueError('Electoral report lacks its boundary table.')
    data.editions = {e['id']: e for e in validate_editions(part['editions'])}
    counts, rows = Counter(), []
    for source in db.execute('SELECT * FROM electoral_area ORDER BY id'):
        row = json.loads(source['record'])
        edition = data.editions.get(row.get('edition'))
        province = row.get('province')
        if (not edition or row.get('id') != source['id'] or province not in edition['provinces']
                or row.get('layer') != edition['layer'] or row.get('level') != 'electoral_district'
                or row.get('source') not in part['sources'] or row['source'] not in edition['sources']
                or row.get('boundary_set') != edition['boundary_set']
                or row.get('edition_status') != edition['status']
                or row.get('parent_id') != 'ca-' + PROVINCES[province][0].lower()
                or row.get('province_id') != row['parent_id']
                or not isinstance(row.get('source_id'), str) or not row['source_id']
                or not isinstance(row.get('name'), str) or not row['name']):
            raise CatalogueError('Invalid electoral boundary identity or parent.')
        data.add(row)
        rows.append(row)
        data.source_ids[('electoral_district', row['id'])] = row['id']
        counts[edition['id']] += 1
        if source['geometry'] is not None:
            geometry = shapely.from_wkb(source['geometry'])
            if (geometry_issue(geometry) or row['assignment_status'] != 'validated_source'
                    or row.get('source_geometry_issue') or row.get('repair')):
                raise CatalogueError('Invalid electoral assignment geometry.')
            data.geometries[row['id']] = geometry
            data.required_displays.add(row['id'])
        else:
            if row['assignment_status'] not in {'unreviewed_repair', 'missing_geometry'}:
                raise CatalogueError('Electoral assignment geometry is missing.')
            candidate = source['repair_candidate']
            if candidate is not None:
                geometry = shapely.from_wkb(candidate)
                if geometry_issue(geometry): raise CatalogueError('Invalid electoral display candidate.')
                data.required_displays.add(row['id'])
            elif row.get('bbox'):
                bbox = row['bbox']
                if (not isinstance(bbox, list) or len(bbox) != 4
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox)
                        or not -180 <= bbox[0] <= bbox[2] <= 180 or not -90 <= bbox[1] <= bbox[3] <= 90):
                    raise CatalogueError('Invalid electoral uncertainty bounds.')
                geometry = box(*row['bbox'])
            else:
                data.unknown_ids.append(row['id']); continue
            data.pending_ids.append(row['id']); data.pending_shapes.append(geometry)
    if dict(counts) != part['edition_counts']:
        raise CatalogueError('Electoral counts differ from the release report.')
    if dict(counts) != {uid: e['expected_count'] for uid, e in data.editions.items()}:
        raise CatalogueError('Electoral counts differ from the edition inventory.')
    # Older immutable releases have only default coverage. Retain its notes only
    # where it names that edition; derive historical inventories from their rows.
    declared = part.get('edition_coverage')
    if declared is None:
        declared = {}
        for layer, provinces in part.get('coverage', {}).items():
            for province, spec in provinces.items():
                uid = spec.get('edition')
                if uid in data.editions:
                    declared.setdefault(uid, {})[province] = spec
    data.edition_coverage = derive_edition_coverage(data.editions, rows, declared)


def selected_editions(data, layer, editions=None):
    if layer not in LAYERS:
        raise CatalogueError('Unknown geography layer.')
    if editions is not None:
        if (not isinstance(editions, (list, tuple, set)) or not editions or len(editions) > 30
                or any(not isinstance(e, str) or not TOKEN.fullmatch(e) for e in editions)
                or len(set(editions)) != len(editions)):
            raise CatalogueError('Expected unique, bounded electoral edition IDs.')
        if layer == 'administrative': raise CatalogueError('Administrative geography has no electoral edition.')
        if any(e not in data.editions or data.editions[e]['layer'] != layer for e in editions):
            raise CatalogueError('Unknown edition or edition belongs to another layer.')
        return set(editions)
    return {e['id'] for e in data.editions.values() if e['layer'] == layer and e['default']}


def in_layer(row, layer, editions):
    if row['level'] in {'country', 'province'}: return True
    if layer == 'municipal' and row['level'] in {'municipality', 'region'}: return True
    return row.get('layer', 'administrative') == layer and (layer == 'administrative' or row['edition'] in editions)


def layer_inventory(data):
    from .municipal_elections import layer_coverage
    return [{'id': key, 'name': name, 'editions': [e for e in data.editions.values() if e['layer'] == key],
             'coverage': selection_coverage(data.editions, data.edition_coverage, selected_editions(data, key))
                         if key in ELECTORAL else layer_coverage(data) if key == 'municipal' else {}}
            for key, name in LAYERS.items()]
