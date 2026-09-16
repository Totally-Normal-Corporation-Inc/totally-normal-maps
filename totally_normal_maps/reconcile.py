"""Suggest municipal identities from a generic local inventory; never modify it."""
import unicodedata
import json
from pathlib import Path

from .catalogue import CatalogueError, PROVINCES, open_catalogue, read_json


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c)).strip()


def reconcile(run, snapshot):
    """Inventory: [{id, kind, parent_id, code?, names: [str]}].

    Municipal name matches are suggestions requiring explicit consumer review.
    Hierarchical layers with the same name never collapse into one identity.
    """
    payload = read_json(snapshot, max_bytes=64 * 1024 * 1024)
    if not isinstance(payload, list) or not 1 <= len(payload) <= 20_000:
        raise CatalogueError('Expected 1–20,000 generic area records.')
    areas = {}
    for row in payload:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not 1 <= len(row['id']) <= 200 or row['id'] in areas
                or not isinstance(row.get('kind'), str)
                or not isinstance(row.get('names'), list)
                or not row['names'] or len(row['names']) > 100
                or any(not isinstance(n, str) or not 1 <= len(n) <= 200 for n in row['names'])
                or (row.get('parent_id') is not None and not isinstance(row['parent_id'], str))):
            raise CatalogueError('Invalid or duplicate area inventory identity.')
        areas[row['id']] = row
    with open_catalogue(run) as db:
        national = [json.loads(r['record']) for r in db.execute('SELECT record FROM csd ORDER BY id')]
    by_name = {}
    for row in national:
        by_name.setdefault(normalized(row['name']), []).append(row)
    codes = {value[0]: key for key, value in PROVINCES.items()}
    results = []
    for uid, area in areas.items():
        visited, current, province, issues = set(), uid, None, []
        while current is not None:
            if current in visited or current not in areas:
                issues.append('incomplete_or_cyclic_hierarchy')
                break
            visited.add(current)
            ancestor = areas[current]
            if ancestor['kind'] in {'province', 'territory', 'province-territory'}:
                code = str(ancestor.get('code', '')).upper()
                province = codes.get(code) or (code if code in PROVINCES else None)
                if province is None:
                    issues.append('unresolved_province_identity')
                break
            current = ancestor.get('parent_id')
        candidates = {r['id']: r for name in area['names'] for r in by_name.get(normalized(name), [])}
        if province:
            candidates = {key: r for key, r in candidates.items() if r['province'] == province}
        if area['kind'] not in {'city', 'municipality', 'municipal-equivalent'}:
            status = 'preserve_existing_layer'
            if candidates:
                issues.append('name_collision_is_not_municipal_identity')
        elif not province or issues:
            status = 'needs_hierarchy_review'
        else:
            status = 'candidate_requires_identity_review' if len(candidates) == 1 else 'ambiguous' if candidates else 'no_candidate'
        results.append({'area_id': uid, 'names': area['names'], 'kind': area['kind'],
                        'province': province, 'status': status, 'issues': issues,
                        'candidate_csd_ids': sorted(candidates)})
    return {'schema_version': 1, 'state': 'review_only', 'existing_areas': len(areas),
            'results': results, 'notes': ['No consumer records or relationships were changed.']}
