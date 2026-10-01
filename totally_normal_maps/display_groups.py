"""Metadata-only catalogue of reviewed groups from the verified release index."""
import hashlib
import json

from .display_packages import PackageError
from .population import encoded

CONTRACT = 'display-groups.v1'
MAX_PAGE_BYTES = 256 * 1024


def page(data, *, offset=0, limit=25):
    index = data.packages.index
    if index is None:
        raise PackageError(409, 'package_not_built')
    plan = index['plan']
    revision = hashlib.sha256(encoded(plan)).hexdigest()
    groups = sorted(plan['groups'], key=lambda group: group['id'])
    items = []
    for group in groups[offset:offset + limit]:
        members = group['municipality_ids']
        missing = [uid for uid in members if uid not in data.packages.roots
                   or data.areas[uid]['level'] != 'municipality']
        record = index['bundles'][group['id']]
        anchor = None
        bounds = None
        if not missing and record['status'] != 'unsupported':
            anchor = members[0]
            descriptor = json.loads(data.packages.responses[anchor][0])
            bounds = descriptor['bundle_bbox']
        items.append({
            'id': group['id'], 'name': group['name'], 'municipality_ids': members,
            'membership_status': 'unresolved' if missing else 'complete',
            'missing_ids': missing,
            'provenance': {**{k: plan[k] for k in ('membership_vintage', 'basis', 'sources')},
                           'source_category': group['source_category'],
                           'identity_updates': group.get('identity_updates', [])},
            'map': {'status': record['status'], 'reason': record.get('reason'),
                    'anchor_id': anchor, 'bbox': bounds},
        })
    next_offset = offset + len(items)
    body = encoded({'contract': CONTRACT, 'dataset_version': data.version, 'revision': revision,
                    'offset': offset, 'total': len(groups),
                    'next_offset': next_offset if next_offset < len(groups) else None, 'items': items})
    if len(body) > MAX_PAGE_BYTES:
        raise PackageError(413, 'group_page_too_large')
    return body, '"' + hashlib.sha256(body).hexdigest() + '"'
