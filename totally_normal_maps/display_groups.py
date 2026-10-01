"""Metadata-only catalogue of reviewed groups from the verified release index."""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .display_packages import PackageError
from .population import encoded

CONTRACT = 'display-groups.v1'
MAX_PAGE_BYTES = 256 * 1024


class GroupModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class GroupSource(GroupModel):
    url: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    authority: str
    licence: str
    attribution: str


class GroupIdentityUpdate(GroupModel):
    previous_id: str
    current_id: str
    evidence_url: str
    transaction: str
    effective_date: str
    reason: str


class GroupProvenance(GroupModel):
    membership_vintage: str
    basis: str
    sources: list[GroupSource]
    source_category: Literal['A', 'B']
    identity_updates: list[GroupIdentityUpdate]


class GroupMap(GroupModel):
    status: Literal['ready', 'unavailable', 'unsupported']
    reason: Literal['no_display_geometry', 'membership_unresolved', 'scope_too_large'] | None
    anchor_id: str | None
    bbox: list[float] | None = Field(min_length=4, max_length=4)


class GroupItem(GroupModel):
    id: str
    name: str
    municipality_ids: list[str]
    membership_status: Literal['complete', 'unresolved']
    missing_ids: list[str]
    provenance: GroupProvenance
    map: GroupMap


class DisplayGroupPage(GroupModel):
    contract: Literal['display-groups.v1']
    dataset_version: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
    next_offset: int | None = Field(ge=0)
    items: list[GroupItem] = Field(max_length=25)


class GroupPageError(GroupModel):
    error: Literal['package_not_built', 'group_page_too_large']
    code: Literal['package_not_built', 'group_page_too_large']


def page(data, *, offset=0, limit=25):
    index = data.packages.index
    if index is None:
        raise PackageError(409, 'package_not_built')
    plan = index['plan']
    revision = hashlib.sha256(encoded(plan)).hexdigest()
    groups = sorted(plan['groups'], key=lambda group: group['id'])
    items = []
    item_bytes = 0

    def envelope(count, values):
        next_offset = offset + count
        return {'contract': CONTRACT, 'dataset_version': data.version, 'revision': revision,
                'offset': offset, 'total': len(groups),
                'next_offset': next_offset if next_offset < len(groups) else None, 'items': values}

    for group in groups[offset:offset + limit]:
        members = group['municipality_ids']
        missing = [uid for uid in members if uid not in data.packages.roots
                   or data.areas[uid]['level'] != 'municipality']
        record = index['bundles'][group['id']]
        anchor = None
        bounds = None
        reason = record.get('reason')
        if not missing and record['status'] != 'unsupported':
            anchor = members[0]
            descriptor = json.loads(data.packages.responses[anchor][0])
            bounds = descriptor['bundle_bbox']
            reason = descriptor['unavailable_reason']
        item = {
            'id': group['id'], 'name': group['name'], 'municipality_ids': members,
            'membership_status': 'unresolved' if missing else 'complete',
            'missing_ids': missing,
            'provenance': {**{k: plan[k] for k in ('membership_vintage', 'basis', 'sources')},
                           'source_category': group['source_category'],
                           'identity_updates': group.get('identity_updates', [])},
            'map': {'status': record['status'], 'reason': reason,
                    'anchor_id': anchor, 'bbox': bounds},
        }
        # Include the precise envelope, UTF-8 byte sizes and inter-item commas.
        # A short page retains the next whole group for its continuation.
        size = len(encoded(item))
        count = len(items) + 1
        if len(encoded(envelope(count, []))) + item_bytes + size + count - 1 > MAX_PAGE_BYTES:
            if not items:
                raise PackageError(413, 'group_page_too_large')
            break
        items.append(item)
        item_bytes += size
    result = envelope(len(items), items)
    DisplayGroupPage.model_validate(result)
    body = encoded(result)
    if len(body) > MAX_PAGE_BYTES:
        raise PackageError(413, 'group_page_too_large')
    return body, '"' + hashlib.sha256(body).hexdigest() + '"'
