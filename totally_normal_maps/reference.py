"""Bounded, immutable views of existing geography and report evidence.

This is an index, not a second source of geographic truth. Report documents are
exposed as paginated tree nodes: no node response recursively embeds its children.
"""
import base64
from collections import Counter, OrderedDict, defaultdict
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
from threading import RLock
from typing import Generic, Literal, TypeVar
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from .catalogue import PROVINCES
from .layers import LAYERS, selected_editions, selection_coverage

BASE = '/v1/datasets/current'
REVISION = 1
SUMMARY_BYTES = 16 * 1024
PAGE_BYTES = 128 * 1024
ITEM_BYTES = 16 * 1024
CACHE_BYTES = 4 * 1024 * 1024
Layer = Literal['administrative', 'federal', 'provincial', 'municipal']


class ReferenceError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Selection(Model):
    layer: Layer
    area_id: str
    include_descendants: bool
    edition_mode: Literal['none', 'defaults', 'explicit', 'all']
    edition_ids: list[str] = Field(max_length=30)
    edition_count: int = Field(ge=0)


class EvidenceScope(Model):
    evidence_id: str
    node_type: Literal['object', 'array', 'string', 'scalar']


class Counts(Model):
    catalogue_entries: int = Field(ge=0)
    assignment_geometries: int = Field(ge=0)
    unavailable_assignment_geometries: int = Field(ge=0)
    hierarchy_only_entries: int = Field(ge=0)
    display_geometries: int = Field(ge=0)
    boundary_disagreements: int = Field(ge=0)
    entries_with_review_flags: int = Field(ge=0)
    by_level: dict[str, int]


class Limitation(Model):
    code: str
    message: str
    count: int | None = None
    evidence_link: Literal['coverage', 'sources', 'editions']


class Summary(Model):
    representation_revision: Literal[1]
    dataset_version: str
    qualification: Literal['review_required']
    country: dict[Literal['id', 'code', 'name'], str]
    selection: Selection
    available_layers: list[Layer] = Field(max_length=4)
    counts: Counts
    limitations: list[Limitation] = Field(max_length=12)
    links: dict[str, str]


class CoverageItem(Model):
    id: str
    topic: str
    relation: Literal['direct', 'inherited', 'descendant']
    scope_count: int
    edition_id: str | None
    basis: Literal['area_record', 'report_context', 'edition', 'authority_inventory', 'default_selection']
    evidence_url: str


class SourceItem(Model):
    id: str
    relation: Literal['direct', 'inherited', 'descendant']
    roles: list[str]
    authority: str | None
    licence: str | None
    redistribution_status: str | None
    attribution: str | None
    metadata_not_inlined: list[str]
    evidence_url: str


class EditionItem(Model):
    id: str
    layer: Layer
    authority_id: str | None
    status: str
    default: bool
    label: str | None
    expected_count: int
    evidence_url: str


class EvidenceItem(Model):
    index: int
    name: str | None = None
    name_evidence_url: str | None = None
    value: str | int | float | bool | None = None
    value_type: Literal['object', 'array', 'string', 'scalar']
    evidence_url: str | None = None
    # Long strings are lossless, ordered character fragments, not truncations.
    character_offset: int | None = None


T = TypeVar('T')


class Page(Model, Generic[T]):
    representation_revision: Literal[1]
    dataset_version: str
    qualification: Literal['review_required']
    scope: Selection | EvidenceScope
    total: int
    limit: int
    items: list[T]
    next_cursor: str | None
    next: str | None
    evidence_status: Literal['available', 'no_records_for_selection']
    links: dict[str, str]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def kind(value):
    return 'object' if isinstance(value, dict) else 'array' if isinstance(value, list) else 'string' if isinstance(value, str) else 'scalar'


def link(resource, **params):
    return BASE + '/' + resource + ('?' + urlencode(params, doseq=True) if params else '')


@dataclass(frozen=True)
class Record:
    id: str
    topic: str
    layer: str
    scopes: frozenset
    edition: str | None = None
    basis: str = 'report_context'


class Window:
    """Materialize at most the requested page, including for very large arrays."""
    def __init__(self, length, get):
        self.length, self.get = length, get

    def __len__(self):
        return self.length

    def __getitem__(self, selection):
        return [self.get(i) for i in range(*selection.indices(self.length))]


class ReferenceIndex:
    def __init__(self, data):
        self.data = data
        self.nodes, self.node_keys, self.coverage = {}, {}, []
        self.sources, self.usages, self.source_paths = {}, defaultdict(set), {}
        self.ancestors = {uid: frozenset(a['id'] for a in data.ancestors(uid)) for uid in data.areas}
        self.provinces = {p: 'ca-' + abbr.lower() for p, (abbr, _) in PROVINCES.items()}
        self.cache, self.cache_size, self.lock = OrderedDict(), 0, RLock()
        self.default_coverage = {layer: selection_coverage(data.editions, data.edition_coverage,
            selected_editions(data, layer)) for layer in ('federal', 'provincial')}
        self._register_sources()
        self._register_coverage()
        self._register_area_sources()
        for uid in self.sources:
            if not self.usages[uid]:
                self.usages[uid].add(('ca', 'administrative', None, 'unscoped_report_source'))
        self.unscoped_sources = sum(any(role == 'unscoped_report_source' for _, _, _, role in uses) for uses in self.usages.values())
        self.edition_nodes = {uid: self.node(('editions', uid), e) for uid, e in data.editions.items()}
        self.coverage.sort(key=lambda r: (r.topic, r.id))
        self._statistics = {}
        for layer in LAYERS:
            self._statistics[(layer, None)] = self._counts(layer, selected_editions(data, layer))
        # The common four small summaries are serialized once, independently of
        # the legacy multi-megabyte report and its source/election inventories.
        for layer in LAYERS:
            self.summary(layer)

    def node(self, path, value):
        uid = hashlib.sha256(encoded(path)).hexdigest()[:32]
        if uid in self.nodes:
            return uid
        self.nodes[uid] = value
        keys = tuple(sorted(value)) if isinstance(value, dict) else ()
        self.node_keys[uid] = keys
        if isinstance(value, (dict, list)):
            for key in keys if isinstance(value, dict) else range(len(value)):
                child = value[key]
                if isinstance(key, str) and len(key) > 256:
                    self.node((uid, key, 'name'), key)
                if isinstance(child, (dict, list)) or isinstance(child, str) and len(child) > 512:
                    self.node((uid, key), child)
        return uid

    def evidence_url(self, uid):
        return link('evidence/' + uid)

    def _scopes(self, value, inherited):
        if not isinstance(value, dict):
            return inherited
        candidates = set()
        for field in ('area_id', 'authority_id', 'municipality_id', 'id', 'csd_id', 'parent_csd_id'):
            item = value.get(field)
            if isinstance(item, str):
                uid = item if item in self.data.areas else 'ca-csd-' + item
                if uid in self.data.areas:
                    candidates.add(uid)
        for field in ('ids', 'area_ids', 'csd_ids', 'predecessor_ids', 'successor_ids'):
            for item in value.get(field, []) if isinstance(value.get(field), list) else []:
                if isinstance(item, str):
                    uid = item if item in self.data.areas else 'ca-csd-' + item
                    if uid in self.data.areas:
                        candidates.add(uid)
        if candidates:
            return frozenset(candidates)
        province = value.get('province')
        if isinstance(province, str) and province in self.provinces:
            return frozenset({self.provinces[province]})
        return inherited

    def _register_sources(self):
        def add(path, source):
            digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            uid = self.node(('sources', digest), source)
            self.sources[uid] = source
            self.source_paths[tuple(path)] = uid
            return uid
        report = self.data.report
        base = add(('source',), report['source'])
        self.usages[base].add(('ca', 'administrative', None, 'baseline'))
        if 'province_display_source' in report:
            uid = add(('province_display_source',), report['province_display_source'])
            self.usages[uid].add(('ca', 'administrative', None, 'province_display'))
        for name, part in report.items():
            groups = [(('jurisdiction_refreshes', p), v) for p, v in part.items()] if name == 'jurisdiction_refreshes' else [((name,), part)]
            for prefix, group in groups:
                if not isinstance(group, dict):
                    continue
                sources = group.get('sources', {})
                for key, source in sources.items() if isinstance(sources, dict) else enumerate(sources):
                    add((*prefix, 'sources', key), source)
        for e in self.data.editions.values():
            prefix = 'municipal_elections' if e['layer'] == 'municipal' else 'electoral'
            scopes = [e['authority_id']] if e['layer'] == 'municipal' else [self.provinces[p] for p in e['provinces']]
            for key in e['sources']:
                uid = self.source_paths[(prefix, 'sources', key)]
                for scope in scopes:
                    self.usages[uid].add((scope, e['layer'], e['id'], 'electoral_boundary'))

    def _source_reference(self, prefix, key, scopes, role='reported_source'):
        paths = [(*prefix, 'sources', key), ('city_areas', 'sources', key)]
        uid = next((self.source_paths[p] for p in paths if p in self.source_paths), None)
        if uid:
            for scope in scopes:
                self.usages[uid].add((scope, 'administrative', None, role))

    def _register_coverage(self):
        def walk(value, path, scopes, prefix, root=False):
            own = self._scopes(value, scopes)
            if root or own != scopes:
                uid = self.node(path, value)
                self.coverage.append(Record(uid, '/'.join(map(str, prefix)), 'administrative', own))
            if isinstance(value, dict):
                for field in ('source', 'boundary_source', 'proposed_boundary_source'):
                    if isinstance(value.get(field), str):
                        self._source_reference(prefix, value[field], own, field)
                for key, child in value.items():
                    if key in {'sources', 'source'}:
                        continue
                    child_scope = frozenset({self.provinces[key]}) if key in self.provinces else own
                    walk(child, (*path, key), child_scope, prefix, root=child_scope != own)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    walk(child, (*path, i), own, prefix)
        report = self.data.report
        for name, value in report.items():
            if name in {'source', 'province_display_source', 'electoral', 'municipal_elections'} or not isinstance(value, (dict, list)):
                continue
            if name == 'jurisdiction_refreshes':
                for p, part in value.items():
                    walk(part, (name, p), frozenset({self.provinces[p]}), (name, p), True)
            else:
                scope = {'quebec_refresh': 'ca-qc', 'ontario_refresh': 'ca-on'}.get(name, 'ca')
                walk(value, (name,), frozenset({scope}), (name,), True)
        for uid, row in self.data.areas.items():
            if row['level'] in {'country', 'province'}:
                continue
            evidence = {k: row[k] for k in ('id', 'assignment_status', 'lifecycle_status', 'issues', 'repair',
                'coverage_note', 'coverage_policy', 'evidence', 'comparison', 'parent_overlap', 'boundary_basis',
                'uncertainty_basis', 'parent_exception_evidence') if k in row}
            key = self.node(('areas', uid), evidence)
            self.coverage.append(Record(key, 'area_quality', row.get('layer', 'administrative'),
                                        frozenset({uid}), row.get('edition'), 'area_record'))
        for uid, spec in self.data.municipal_coverage.items():
            key = self.node(('municipal_elections', 'coverage', uid), spec)
            self.coverage.append(Record(key, 'municipal_authority_inventory', 'municipal', frozenset({uid}),
                                        basis='authority_inventory'))
        for uid, e in self.data.editions.items():
            part = report['municipal_elections' if e['layer'] == 'municipal' else 'electoral']
            for section in ('validation', 'edition_coverage'):
                inventory = self.data.edition_coverage if section == 'edition_coverage' else part.get(section, {})
                if uid in inventory:
                    key = self.node((e['layer'], section, uid), inventory[uid])
                    scopes = [e['authority_id']] if e['layer'] == 'municipal' else [self.provinces[p] for p in e['provinces']]
                    self.coverage.append(Record(key, section, e['layer'], frozenset(scopes), uid, 'edition'))
        for layer, provinces in self.default_coverage.items():
            for province, spec in provinces.items():
                key = self.node((layer, 'default_selection', province), spec)
                self.coverage.append(Record(key, 'layer_default_coverage', layer,
                    frozenset({self.provinces[province]}), basis='default_selection'))

    def _register_area_sources(self):
        # Source keys on administrative rows are deliberately absent from the
        # legacy public Area projection. Read only provenance, never raw fields.
        uri = (self.data.root / 'catalogue.sqlite3').as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('city_area', 'area_revision', 'boundary_revision', 'jurisdiction_revision'):
                if table not in tables:
                    continue
                for raw, in db.execute('SELECT record FROM ' + table):
                    row = json.loads(raw)
                    uid = row.get('id')
                    if uid not in self.data.areas:
                        continue
                    p = self.data.areas[uid]['province_id']
                    code = self.data.areas[p]['source_id']
                    prefix = ('quebec_refresh',) if code == '24' else ('ontario_refresh',) if code == '35' else ('jurisdiction_refreshes', code)
                    for field in ('source', 'boundary_source', 'proposed_boundary_source'):
                        if isinstance(row.get(field), str):
                            self._source_reference(prefix, row[field], {uid}, field)

    def selection(self, layer, editions=None, area_id='ca', descendants=True, *, all_editions=False):
        if area_id not in self.data.areas:
            raise ReferenceError(404, 'Unknown geographic area.')
        area = self.data.areas[area_id]
        own_layer = area.get('layer', 'administrative')
        if (layer == 'administrative' and own_layer not in {'administrative', 'shared'} or
                layer in {'federal', 'provincial'} and area['level'] not in {'country', 'province'} and own_layer != layer or
                layer == 'municipal' and area['level'] not in {'country', 'province', 'municipality', 'region'} and own_layer != layer):
            raise ReferenceError(422, 'Area scope is not supported for this layer; no spatial overlap is inferred.')
        chosen = selected_editions(self.data, layer, editions)
        if all_editions:
            chosen = {uid for uid, e in self.data.editions.items() if e['layer'] == layer}
        relevant = {uid for uid in chosen if self._edition_applies(uid, area_id, descendants)}
        if editions is not None and relevant != chosen:
            raise ReferenceError(422, 'An explicit edition is outside the requested area scope.')
        spec = {'layer': layer, 'area_id': area_id, 'include_descendants': descendants,
                'edition_mode': 'none' if layer == 'administrative' else 'all' if all_editions else 'explicit' if editions is not None else 'defaults',
                'edition_ids': sorted(editions) if editions is not None else [], 'edition_count': len(relevant)}
        return spec, relevant

    def relation(self, scopes, area_id, descendants):
        if area_id in scopes:
            return 'direct'
        if scopes & self.ancestors[area_id]:
            return 'inherited'
        if descendants and any(area_id in self.ancestors.get(uid, ()) for uid in scopes):
            return 'descendant'
        return None

    def _edition_applies(self, uid, area_id, descendants):
        e = self.data.editions[uid]
        area = self.data.areas[area_id]
        if area['level'] == 'electoral_district':
            return area.get('edition') == uid
        scopes = {e['authority_id']} if e['layer'] == 'municipal' else {self.provinces[p] for p in e['provinces']}
        return bool(self.relation(scopes, area_id, descendants))

    def _counts(self, layer, chosen):
        rows = [r for r in self.data.areas.values() if r.get('lifecycle_status') != 'superseded' and
                (r.get('layer', 'administrative') in {'administrative', 'shared'} if layer == 'administrative'
                 else r.get('layer') == layer and r.get('edition') in chosen)]
        ids = {r['id'] for r in rows}
        full = ids & self.data.geometries.keys()
        hierarchy = {r['id'] for r in rows if r['assignment_status'] == 'hierarchy_only'}
        pending = set(self.data.pending_ids)
        return {'catalogue_entries': len(rows), 'assignment_geometries': len(full),
                'unavailable_assignment_geometries': len(ids - full - hierarchy),
                'hierarchy_only_entries': len(hierarchy), 'display_geometries': len(ids & self.data.displays.keys()),
                'boundary_disagreements': len(full & pending),
                'entries_with_review_flags': sum(bool(r['issues']) or r['id'] in pending or r['id'] in self.data.unknown_ids for r in rows),
                'by_level': dict(sorted(Counter(r['level'] for r in rows).items()))}

    def _serialize(self, payload, model, budget):
        body = encoded(model.model_validate(payload).model_dump())
        if len(body) > budget:
            raise ReferenceError(503, 'Reference representation exceeds its published byte budget.')
        return body, '"' + hashlib.sha256(body).hexdigest() + '"'

    def _cached(self, key, factory):
        with self.lock:
            if key in self.cache:
                result = self.cache.pop(key); self.cache[key] = result
                return result
        result = factory()
        with self.lock:
            if key not in self.cache:
                self.cache[key] = result; self.cache_size += len(result[0])
                while self.cache_size > CACHE_BYTES or len(self.cache) > 128:
                    _, old = self.cache.popitem(last=False); self.cache_size -= len(old[0])
        return result

    def summary(self, layer='administrative', editions=None):
        scope, chosen = self.selection(layer, editions)
        key = ('summary', encoded(scope))
        def build():
            counts = self._statistics.get((layer, None)) if editions is None else None
            counts = counts if counts is not None else self._counts(layer, chosen)
            params = {'layer': layer, 'area_id': 'ca', 'include_descendants': 'true', 'edition': sorted(editions or [])}
            coverage = link('coverage', **params)
            limitations = [{'code': 'geography_review_required', 'message': 'This reference dataset is not a qualified legal boundary service.', 'count': None, 'evidence_link': 'coverage'},
                {'code': 'coverage_evidence_requires_review', 'message': 'Inventory and geometry counts do not establish complete geographic coverage. Detailed limitations are in the scoped evidence.', 'count': None, 'evidence_link': 'coverage'}]
            for name, field, message in (
                ('assignment_geometry_unavailable', 'unavailable_assignment_geometries', 'Missing and unapproved boundaries cannot be used for assignment.'),
                ('boundary_disagreement', 'boundary_disagreements', 'Usable boundaries retain source or extent disagreements.'),
                ('area_review_flags', 'entries_with_review_flags', 'Area-specific issues and uncertainty remain in the evidence.')):
                if counts[field]:
                    limitations.append({'code': name, 'message': message, 'count': counts[field], 'evidence_link': 'coverage'})
            reference_count = sum(self.data.editions[uid]['status'] == 'reference' for uid in chosen)
            if reference_count:
                limitations.append({'code': 'reference_editions', 'message': 'Dated reference editions do not assert applicability to the current election.', 'count': reference_count, 'evidence_link': 'editions'})
            if layer == 'municipal' and editions is None:
                gaps = sum(r['status'] in {'unverified', 'unavailable', 'historical_only', 'partial'} for r in self.data.municipal_coverage.values())
                if gaps:
                    limitations.append({'code': 'municipal_coverage_gaps', 'message': 'Authorities have incomplete, unavailable or unverified electoral coverage; absent wards do not imply at-large representation.', 'count': gaps, 'evidence_link': 'coverage'})
            if layer in self.default_coverage and editions is None:
                gaps = sum(r['status'] in {'partial', 'unavailable'} for r in self.default_coverage[layer].values())
                if gaps:
                    limitations.append({'code': 'electoral_coverage_gaps', 'message': 'Provinces or territories have partial or unavailable coverage in the default edition selection.', 'count': gaps, 'evidence_link': 'coverage'})
            if layer == 'administrative' and self.unscoped_sources:
                limitations.append({'code': 'source_scope_incomplete', 'message': 'Some legacy source records have no explicit local applicability mapping. They remain available in the national source inventory.', 'count': self.unscoped_sources, 'evidence_link': 'sources'})
            payload = {'representation_revision': REVISION, 'dataset_version': self.data.version,
                       'qualification': 'review_required', 'country': {'id': 'ca', 'code': 'CA', 'name': 'Canada'},
                       'selection': scope, 'available_layers': ['administrative', *sorted({e['layer'] for e in self.data.editions.values()})],
                       'counts': counts, 'limitations': limitations,
                       'links': {'coverage': coverage, 'sources': link('sources', **params),
                                 'editions': link('editions', layer=layer), 'full_report': BASE}}
            return self._serialize(payload, Summary, SUMMARY_BYTES)
        return self._cached(key, build)

    def _cursor(self, scope_key, offset):
        return base64.urlsafe_b64encode(encoded([REVISION, self.data.version, scope_key, offset])).decode().rstrip('=')

    def _offset(self, cursor, scope_key, total):
        if cursor is None:
            return 0
        try:
            if len(cursor) > 512 or not re.fullmatch(r'[A-Za-z0-9_-]+', cursor):
                raise ValueError
            value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            if not isinstance(value, list) or len(value) != 4:
                raise ValueError
            revision, version, scope, offset = value
            if version != self.data.version:
                raise ReferenceError(412, 'Continuation belongs to a different dataset version.')
            if revision != REVISION or scope != scope_key or type(offset) is not int or not 0 <= offset <= total:
                raise ValueError
            return offset
        except (ValueError, TypeError, UnicodeError):
            raise ReferenceError(422, 'Invalid continuation or changed page scope.') from None

    def _page(self, resource, scope, rows, model, limit, cursor, params, *, links=None):
        fingerprint = hashlib.sha256(encoded([resource, scope, limit])).hexdigest()[:32]
        offset = self._offset(cursor, fingerprint, len(rows))
        items, size = [], 0
        # Reserve the bounded envelope and continuation links; enforce the exact
        # serialized byte count again below, never silently drop an item.
        for row in rows[offset:offset + limit]:
            row = model.model_validate(row).model_dump()
            length = len(encoded(row))
            if length > ITEM_BYTES:
                raise ReferenceError(503, 'Evidence item requires further normalization.')
            if size + length > PAGE_BYTES - 12000:
                break
            items.append(row); size += length + 1
        end = offset + len(items)
        next_cursor = self._cursor(fingerprint, end) if end < len(rows) else None
        payload = {'representation_revision': REVISION, 'dataset_version': self.data.version,
                   'qualification': 'review_required', 'scope': scope, 'total': len(rows), 'limit': limit,
                   'items': items, 'next_cursor': next_cursor,
                   'next': link(resource, **params, limit=limit, cursor=next_cursor) if next_cursor else None,
                   'evidence_status': 'available' if rows else 'no_records_for_selection',
                   'links': links or {'full_report': BASE}}
        return self._serialize(payload, Page[model], PAGE_BYTES)

    def records(self, resource, *, layer='administrative', area_id='ca', descendants=False,
                editions=None, limit=50, cursor=None):
        scope, chosen = self.selection(layer, editions, area_id, descendants, all_editions=resource == 'editions')
        params = {'layer': layer, 'area_id': area_id, 'include_descendants': str(descendants).lower(), 'edition': sorted(editions or [])}
        key = (resource, encoded(scope), limit, cursor)
        def build():
            rows = []
            if resource == 'coverage':
                for r in self.coverage:
                    relation = self.relation(r.scopes, area_id, descendants)
                    if r.layer != layer or not relation or r.edition is not None and r.edition not in chosen:
                        continue
                    if editions is not None and r.basis == 'default_selection':
                        continue
                    if editions is not None and r.basis == 'authority_inventory' and not any(self.data.editions[e]['authority_id'] in r.scopes for e in chosen):
                        continue
                    rows.append({'id': r.id, 'topic': r.topic, 'relation': relation, 'scope_count': len(r.scopes),
                                 'edition_id': r.edition, 'basis': r.basis, 'evidence_url': self.evidence_url(r.id)})
                model = CoverageItem
            elif resource == 'sources':
                for uid, source in sorted(self.sources.items()):
                    applicable = [(self.relation({area}, area_id, descendants), role) for area, family, edition, role in self.usages[uid]
                                  if family == layer and (edition is None or edition in chosen)
                                  and not (area_id != 'ca' and role == 'unscoped_report_source')
                                  and not (self.data.areas[area_id]['level'] not in {'country', 'province'} and role == 'province_display')]
                    applicable = [(r, role) for r, role in applicable if r]
                    if not applicable:
                        continue
                    rank = {'direct': 0, 'inherited': 1, 'descendant': 2}
                    row = {'id': uid, 'relation': min((r for r, _ in applicable), key=rank.get),
                           'roles': sorted({role for _, role in applicable}), 'evidence_url': self.evidence_url(uid), 'metadata_not_inlined': []}
                    for field in ('authority', 'licence', 'redistribution_status', 'attribution'):
                        value = source.get(field)
                        maximum = {'authority': 512, 'redistribution_status': 128}.get(field, 4096)
                        row[field] = value if isinstance(value, str) and len(encoded(value)) <= maximum else None
                        if value is not None and row[field] is None:
                            row['metadata_not_inlined'].append(field)
                    rows.append(row)
                model = SourceItem
            elif resource == 'editions':
                for uid in sorted(chosen):
                    e = self.data.editions[uid]
                    rows.append({'id': uid, 'layer': layer, 'authority_id': e.get('authority_id'), 'status': e['status'],
                                 'default': e['default'], 'label': e['label'] if len(encoded(e['label'])) <= 4096 else None,
                                 'expected_count': e['expected_count'], 'evidence_url': self.evidence_url(self.edition_nodes[uid])})
                model = EditionItem
            else:
                raise ReferenceError(404, 'Unknown reference resource.')
            links = {'full_report': BASE}
            if resource == 'sources' and layer == 'administrative' and self.unscoped_sources:
                links['unscoped_provenance_in_national_inventory'] = link('sources', layer=layer, area_id='ca', include_descendants='false')
            return self._page(resource, scope, rows, model, limit, cursor, params, links=links)
        return self._cached(key, build)

    def evidence(self, uid, limit=50, cursor=None):
        if uid not in self.nodes:
            raise ReferenceError(404, 'Unknown evidence record.')
        value = self.nodes[uid]
        scope = {'evidence_id': uid, 'node_type': kind(value)}
        def build():
            if isinstance(value, str):
                rows = Window(max(1, (len(value) + 511) // 512), lambda i: {
                    'index': i, 'character_offset': i * 512, 'value': value[i * 512:(i + 1) * 512], 'value_type': 'string'})
            elif isinstance(value, (list, dict)):
                def member(i):
                    key = self.node_keys[uid][i] if isinstance(value, dict) else i
                    child = value[key]
                    row = {'index': i, 'value_type': kind(child)}
                    if isinstance(value, dict):
                        if len(key) <= 256:
                            row['name'] = key
                        else:
                            row['name_evidence_url'] = self.evidence_url(hashlib.sha256(encoded((uid, key, 'name'))).hexdigest()[:32])
                    if isinstance(child, (dict, list)) or isinstance(child, str) and len(child) > 512:
                        row['evidence_url'] = self.evidence_url(hashlib.sha256(encoded((uid, key))).hexdigest()[:32])
                    else:
                        row['value'] = child
                    return row
                rows = Window(len(value), member)
            else:
                rows = [{'index': 0, 'value': value, 'value_type': 'scalar'}]
            return self._page('evidence/' + uid, scope, rows, EvidenceItem, limit, cursor, {})
        return self._cached(('evidence', uid, limit, cursor), build)

    def compact_boundary(self, payload):
        """Keep geometry/uncertainty exact; replace repeated global provenance by links."""
        result = dict(payload)
        result.pop('sources', None)
        row = self.data.areas[payload['id']]
        layer = row.get('layer', 'administrative')
        if layer == 'shared':
            layer = 'administrative'
        params = {'layer': layer, 'area_id': row['id'], 'edition': [row['edition']] if row.get('edition') else []}
        result['representation_revision'] = REVISION
        result['source_evidence'] = {'sources_url': link('sources', **params), 'coverage_url': link('coverage', **params),
                                     'full_report_url': BASE, 'attribution_required': True,
                                     'local_source_mapping_complete': not (layer == 'administrative' and self.unscoped_sources)}
        return result
