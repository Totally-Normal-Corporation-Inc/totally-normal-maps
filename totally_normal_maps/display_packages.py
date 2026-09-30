"""Offline display bundles and verified, file-backed HTTP representations.

Bundle membership is a delivery policy, never administrative or assignment geography.
No source networking, geometry construction or database writes occur on HTTP reads.
"""
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import resource
import shutil
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from shapely.geometry import shape

from .catalogue import CatalogueError, ROOT, geometry_issue, new_directory, read_json, sha256, write_json
from .population import encoded
from .releases import HEX, checked_release, validate_manifest

CONTRACT = 'area-display-package.v1'
GEOMETRY_CONTRACT = 'area-display-geometry.v1'
MAX_MEMBERS = 500
MAX_DEPTH = 10
MAX_GEOMETRY_BYTES = 4 * 1024 * 1024
MAX_TRANSFER_BYTES = MAX_GEOMETRY_BYTES + 4096
MAX_VERTICES = 200_000
MAX_FEATURE_VERTICES = 50_000
MAX_DESCRIPTOR_BYTES = 256 * 1024
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_ENVELOPES_BYTES = 128 * 1024 * 1024
PLAN = ROOT / 'display-groups-2021.json'
INDEX = 'packages/index.json'
ID = r'[a-zA-Z0-9_-]{1,100}'


def require(condition, message):
    if not condition:
        raise CatalogueError('Display packages: ' + message)


class PackageError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


class TooLarge(Exception):
    def __init__(self, limit, actual):
        self.limit, self.actual = limit, actual


def bound(value, maximum, name):
    if value > maximum:
        raise TooLarge(name, value)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('inventory_complete', 'suitable_for_assignment', 'representation_revision',
                     mode='before', check_fields=False)
    @classmethod
    def exact_contract_types(cls, value, info):
        # Literal validation otherwise equates true/1 and false/0 even in strict mode.
        expected = int if info.field_name == 'representation_revision' else bool
        if type(value) is not expected:
            raise ValueError('Contract declarations require their exact JSON types.')
        return value


class Encoding(Model):
    bytes: int = Field(gt=0, le=MAX_TRANSFER_BYTES)


class Geometry(Model):
    contract: Literal['area-display-geometry.v1']
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    path: str = Field(pattern=r'^/v1/display-packages/[0-9a-f]{64}\.geojson$')
    media_type: Literal['application/geo+json']
    decoded_bytes: int = Field(gt=0, le=MAX_GEOMETRY_BYTES)
    feature_count: int = Field(gt=0, le=MAX_MEMBERS)
    vertex_count: int = Field(gt=0, le=MAX_VERTICES)
    encodings: dict[Literal['identity', 'gzip'], Encoding]


class Entry(Model):
    id: str
    parent_id: str | None
    level: Literal['region', 'municipality', 'city_area']
    municipality_id: str | None
    display_status: Literal['available', 'unavailable']
    unavailable_reason: Literal['missing_geometry'] | None
    assignment_status: str
    provider_display_status: str | None
    suitable_for_assignment: Literal[False]
    qualification: Literal['review_required']
    issues: list
    evidence: dict
    source_ids: list[str]


class Counts(Model):
    areas: int = Field(ge=1, le=MAX_MEMBERS)
    available: int = Field(ge=0, le=MAX_MEMBERS)
    unavailable: int = Field(ge=0, le=MAX_MEMBERS)


class BaseDescriptor(Model):
    bundle_id: str
    bundle_kind: Literal['agglomeration', 'municipality', 'region']
    scope_root_ids: list[str] = Field(min_length=1, max_length=MAX_MEMBERS)
    grouping: dict | None
    status: Literal['ready', 'unavailable']
    unavailable_reason: Literal['no_display_geometry'] | None
    inventory_complete: Literal[True]
    coverage: Literal['complete', 'partial', 'none']
    qualification: Literal['review_required']
    counts: Counts
    bundle_bbox: list[float] | None
    areas: list[Entry] = Field(min_length=1, max_length=MAX_MEMBERS)
    geometry: Geometry | None
    sources: list[dict]
    common_source_ids: list[str]
    attribution: list[str]
    source_mapping_complete: bool


class Descriptor(BaseDescriptor):
    selection: dict
    contract: Literal['area-display-package.v1']
    representation_revision: Literal[1]
    dataset_version: str = Field(pattern=r'^[0-9a-f]{64}$')
    requested_area_id: str
    root_id: str
    root_level: Literal['municipality', 'region']
    layer: Literal['administrative']
    viewport_bbox: list[float] | None
    viewport_basis: Literal['root_display', 'available_features'] | None


def eligible(data):
    return {u for u, r in data.areas.items() if r['level'] in {'municipality', 'region'}
            and r.get('layer') == 'administrative' and r.get('lifecycle_status') != 'superseded'}


def read_plan(path):
    return validate_plan(read_json(path, MAX_INDEX_BYTES))


def validate_plan(plan):
    require(isinstance(plan, dict) and len(encoded(plan)) <= MAX_INDEX_BYTES and set(plan) == {'schema_version', 'membership_vintage', 'basis', 'sources', 'groups'}
            and type(plan['schema_version']) is int and plan['schema_version'] == 1 and isinstance(plan['groups'], list)
            and len(plan['groups']) <= 500, 'invalid grouping plan')
    require(isinstance(plan['basis'], str) and len(plan['basis']) <= 2000
            and isinstance(plan['membership_vintage'], str) and len(plan['membership_vintage']) <= 40,
            'invalid membership provenance')
    require(isinstance(plan['sources'], list) and 1 <= len(plan['sources']) <= 20, 'missing grouping sources')
    for source in plan['sources']:
        require(isinstance(source, dict) and set(source) == {'url', 'sha256', 'authority', 'licence', 'attribution'}
                and all(isinstance(v, str) and len(v) <= 4096 for v in source.values())
                and source['url'].startswith('https://') and source['licence'].startswith('https://')
                and HEX.fullmatch(source['sha256']), 'invalid grouping evidence')
    ids, members = set(), set()
    for g in plan['groups']:
        require(isinstance(g, dict) and set(g) - {'identity_updates'} == {'id', 'name', 'kind', 'source_category', 'municipality_ids'}
                and isinstance(g['id'], str) and re.fullmatch(ID, g['id'])
                and g['id'] not in ids and g['kind'] == 'agglomeration'
                and isinstance(g['source_category'], str) and g['source_category'] in {'A', 'B'} and isinstance(g['name'], str)
                and 0 < len(g['name']) <= 300, 'invalid or duplicate group')
        ids.add(g['id']); roots = g['municipality_ids']
        require(isinstance(roots, list) and len(roots) >= 1
                and all(isinstance(u, str) and re.fullmatch(ID, u) for u in roots)
                and roots == sorted(set(roots)) and not members.intersection(roots),
                'overlapping or invalid preferred group membership')
        updates = g.get('identity_updates', [])
        require(isinstance(updates, list) and len(updates) <= MAX_MEMBERS, 'invalid identity updates')
        for update in updates:
            require(isinstance(update, dict) and set(update) == {'previous_id','current_id','evidence_url','transaction','effective_date','reason'}
                    and all(isinstance(v,str) and len(v) <= 1000 for v in update.values())
                    and update['evidence_url'].startswith('https://') and update['current_id'] in g['municipality_ids']
                    and update['previous_id'] not in g['municipality_ids'], 'invalid identity update evidence')
        members.update(roots)
    return plan


def scope_members(data, roots):
    """Metadata traversal, not polygon enumeration. Roots retain external parents."""
    require(roots == sorted(set(roots)) and all(
        (row := data.areas.get(u)) is not None
        and row.get('layer') == 'administrative'
        and row.get('level') in {'municipality', 'region'}
        and row.get('lifecycle_status') != 'superseded'
        for u in roots), 'invalid scope roots')
    visited, stack = set(), [(u, 0) for u in roots]
    while stack:
        uid, depth = stack.pop()
        require(uid not in visited, 'cycle, duplicate or overlapping scope roots')
        visited.add(uid)
        bound(len(visited), MAX_MEMBERS, 'members'); bound(depth, MAX_DEPTH, 'depth')
        row = data.areas[uid]
        require(row.get('lifecycle_status') != 'superseded' and row.get('layer') == 'administrative', 'inactive scope member')
        for child in data.children[uid]:
            r = data.areas[child]
            if r.get('layer') != 'administrative' or r.get('lifecycle_status') == 'superseded':
                continue
            require(r['parent_id'] == uid, 'conflicting parent')
            stack.append((child, depth + 1))
    return sorted(visited)


def polygon_stats(geometry):
    """Every coordinate pair, including closing coordinates, counts as a vertex."""
    require(isinstance(geometry, dict) and set(geometry) == {'type', 'coordinates'}
            and geometry['type'] in {'Polygon', 'MultiPolygon'}, 'unsupported polygon')
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    require(isinstance(polygons, (list, tuple)) and len(polygons) > 0, 'empty polygon')
    n = 0; west = south = math.inf; east = north = -math.inf
    for polygon in polygons:
        require(isinstance(polygon, (list, tuple)) and len(polygon) > 0, 'missing rings')
        for ring in polygon:
            require(isinstance(ring, (list, tuple)) and len(ring) >= 4 and ring[0] == ring[-1], 'unclosed or short ring')
            for p in ring:
                require(isinstance(p, (list, tuple)) and len(p) == 2
                        and all(type(v) in {int, float} and math.isfinite(v) for v in p)
                        and -180 <= p[0] <= 180 and -90 <= p[1] <= 90, 'invalid WGS84 coordinate')
                x, y = p; west = min(west, x); east = max(east, x); south = min(south, y); north = max(north, y)
                n += 1
    require(geometry_issue(shape(geometry)) is None, 'invalid polygon topology')
    return n, [west, south, east, north]


def union_bbox(boxes):
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def geometry_body(data, bundle_id, members):
    features, vertices = [], 0
    for uid in members:
        g = data.displays.get(uid)
        if g is None:
            require(data.areas[uid]['assignment_status'] == 'missing_geometry', 'missing display without explicit catalogue evidence')
            continue
        count, bbox = polygon_stats(g)
        bound(count, MAX_FEATURE_VERTICES, 'feature_vertices'); vertices += count
        bound(vertices, MAX_VERTICES, 'vertices')
        features.append({'type': 'Feature', 'id': uid, 'bbox': bbox, 'properties': {}, 'geometry': g})
    if not features:
        return None, None, None, 0
    bbox = union_bbox([f['bbox'] for f in features])
    body = encoded({'contract': GEOMETRY_CONTRACT, 'purpose': 'display_only', 'type': 'FeatureCollection',
                    'bundle_id': bundle_id, 'bbox': bbox, 'features': features})
    bound(len(body), MAX_GEOMETRY_BYTES, 'decoded_bytes')
    # GzipFile fixes the timestamp, filename and OS header across supported Python runtimes.
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', filename='', mtime=0, compresslevel=9) as f:
        f.write(body)
    compressed = buf.getvalue(); bound(len(compressed), MAX_TRANSFER_BYTES, 'transfer_bytes')
    return body, compressed, bbox, vertices


class Provenance:
    def __init__(self, data):
        from .reference import ReferenceIndex
        self.index = ReferenceIndex(data)
        self.data = data
        self.unscoped = {u for u, uses in self.index.usages.items()
                         if any(role == 'unscoped_report_source' for _, _, _, role in uses)}

        self.common = self.unscoped | {s for s, uses in self.index.usages.items()
            if any(a == 'ca' and layer == 'administrative' and role not in {'province_display','population'}
                   for a, layer, edition, role in uses)}

        self.by_anchor = defaultdict(set)
        for source_id, uses in self.index.usages.items():
            if source_id in self.common:
                continue
            for area_id, layer, edition, role in uses:
                if layer == 'administrative' and role not in {'province_display', 'population'}:
                    self.by_anchor[area_id].add(source_id)
        self.area_sources = {}

    def for_area(self, uid):
        if uid not in self.area_sources:
            ancestors = self.index.ancestors[uid] | {uid}
            self.area_sources[uid] = sorted({source for a in ancestors for source in self.by_anchor[a]})
        return self.area_sources[uid]

    def sources(self, ids):
        # Keep all required notices; do not silently shorten licences to meet a budget.
        keys = ('authority', 'licence', 'attribution', 'attribution_statement', 'attribution_display',
                'modifications', 'redistribution_status', 'publication_disclaimer', 'url', 'dataset_url')
        return [{'id': u, **{k: self.index.sources[u][k] for k in keys if k in self.index.sources[u]},
                 'scope_basis': 'unscoped_context' if u in self.unscoped else 'catalogue_or_inherited',
                 'evidence_url': self.index.evidence_url(u)} for u in sorted(ids)]


def inventory_entry(data, uid, source_ids):
    r = data.areas[uid]; available = uid in data.displays
    return {'id': uid, 'parent_id': r['parent_id'], 'level': r['level'],
            'municipality_id': r.get('municipality_id', uid if r['level'] == 'municipality' else None),
            'display_status': 'available' if available else 'unavailable',
            'unavailable_reason': None if available else 'missing_geometry',
            'assignment_status': r['assignment_status'], 'provider_display_status': r.get('display_status'),
            'qualification': 'review_required', 'suitable_for_assignment': False,
            'issues': r.get('issues', []), 'evidence': {
                'url': '/v1/datasets/current/evidence/' + hashlib.sha256(encoded(['areas', uid])).hexdigest()[:32],
                **{k: r[k] for k in ('scheme','coverage_policy','boundary_basis','uncertainty_basis') if k in r}},
            'source_ids': source_ids}


def base_descriptor(data, bundle_id, kind, roots, grouping, provenance):
    members = scope_members(data, roots)
    body, compressed, bbox, vertices = geometry_body(data, bundle_id, members)
    entries = [inventory_entry(data, uid, provenance.for_area(uid)) for uid in members]
    sources = provenance.sources(provenance.common | {s for row in entries for s in row['source_ids']})
    attribution = sorted({str(s[k]) for s in sources for k in ('attribution', 'attribution_statement', 'attribution_display', 'modifications', 'publication_disclaimer') if s.get(k)})
    if grouping:
        attribution = sorted(set(attribution) | {s['attribution'] for s in grouping['sources']})
    available = sum(e['display_status'] == 'available' for e in entries)
    geometry = None
    if body:
        digest = hashlib.sha256(body).hexdigest()
        geometry = {'contract': GEOMETRY_CONTRACT, 'sha256': digest,
            'path': '/v1/display-packages/' + digest + '.geojson', 'media_type': 'application/geo+json',
            'decoded_bytes': len(body), 'feature_count': available, 'vertex_count': vertices,
            'encodings': {'identity': {'bytes': len(body)}, 'gzip': {'bytes': len(compressed)}}}
    base = {'bundle_id': bundle_id, 'bundle_kind': kind, 'scope_root_ids': roots, 'grouping': grouping,
        'status': 'ready' if body else 'unavailable', 'unavailable_reason': None if body else 'no_display_geometry',
        'inventory_complete': True, 'coverage': 'none' if not available else 'complete' if available == len(entries) else 'partial',
        'qualification': 'review_required', 'counts': {'areas': len(entries), 'available': available, 'unavailable': len(entries)-available},
        'common_source_ids': sorted(provenance.common), 'bundle_bbox': bbox, 'areas': entries, 'geometry': geometry, 'sources': sources, 'attribution': attribution,
        'source_mapping_complete': not provenance.unscoped}
    return base, body, compressed


def envelope(data, root, base, selection, version=None):
    bbox = polygon_stats(data.displays[root])[1] if root in data.displays else base['bundle_bbox']
    result = {'contract': CONTRACT, 'representation_revision': 1, 'dataset_version': version or data.version,
        'requested_area_id': root, 'root_id': root, 'root_level': data.areas[root]['level'], 'layer': 'administrative',
        'viewport_bbox': bbox, 'viewport_basis': 'root_display' if root in data.displays else 'available_features' if bbox else None,
        'selection': selection, **base}
    Descriptor.model_validate(result)
    body = encoded(result); bound(len(body), MAX_DESCRIPTOR_BYTES, 'descriptor_bytes')
    return body, '"' + hashlib.sha256(body).hexdigest() + '"'


def package_files(manifest):
    return {n: s for n, s in manifest['files'].items() if n.startswith('packages/')}


def require_unprepared(data):
    require(not package_files(data.manifest),
            'transform the pre-package release, then rerun prepare-display-packages; prepared packages are final release artifacts')


def scope_plan(data, plan):
    roots = eligible(data)
    require(all(g['id'] not in data.areas for g in plan['groups']), 'group identity conflicts with catalogue')
    selections = {u: {'bundle_id': u, 'reason': 'catalogue_scope'} for u in sorted(roots)}
    specs = [(u, data.areas[u]['level'], [u], None) for u in sorted(roots)]
    unresolved = {}
    for g in plan['groups']:
        missing = [u for u in g['municipality_ids'] if u not in roots or data.areas[u]['level'] != 'municipality']
        grouping = {k: plan[k] for k in ('membership_vintage', 'basis', 'sources')}
        grouping.update(name=g['name'], source_category=g['source_category'], identity_updates=g.get('identity_updates', []))
        if missing:
            unresolved[g['id']] = {'status': 'unsupported', 'reason': 'membership_unresolved', 'missing_ids': missing}
        else:
            specs.append((g['id'], 'agglomeration', g['municipality_ids'], grouping))
        for u in g['municipality_ids']:
            if u in roots:
                selections[u] = {'bundle_id': u if missing else g['id'],
                    'reason': 'preferred_group_unavailable' if missing else 'preferred_agglomeration',
                    'preferred_bundle_id': g['id'], 'preferred_unavailable_reason': 'membership_unresolved' if missing else None}
    return roots, selections, specs, unresolved


def prepare(dataset, output, *, expected_sha256, plan_path=PLAN):
    from .dataset import Dataset
    start = time.perf_counter(); data = Dataset(dataset, expected_sha256); plan = read_plan(plan_path)
    require(not Path(output).resolve().is_relative_to(data.root), 'output must be outside the immutable input release')
    provenance = Provenance(data)
    roots, selections, specs, unresolved = scope_plan(data, plan)
    statistics = []; bundles = dict(unresolved)
    with new_directory(output) as staging:
        for name, spec in data.manifest['files'].items():
            if name.startswith('packages/'):
                continue
            target = staging / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(data.root / name, target)
            require(sha256(target) == spec['sha256'], 'input release changed during preparation')
        (staging / 'packages/objects').mkdir(parents=True)
        (staging / 'packages/descriptors').mkdir()
        for bid, kind, scope_roots, grouping in specs:
            began = time.perf_counter()
            try:
                base, body, compressed = base_descriptor(data, bid, kind, scope_roots, grouping, provenance)
                # Every possible request envelope must fit, not just the bundle record.
                max_descriptor = max(len(envelope(data, r, base,
                    selections[r] if selections[r]['bundle_id'] == bid else {'bundle_id': bid, 'reason': 'catalogue_scope'},
                    '0'*64)[0]) for r in scope_roots)
                raw = encoded(base); name = 'packages/descriptors/' + hashlib.sha256(raw).hexdigest() + '.json'
                (staging / name).write_bytes(raw)
                if body:
                    digest = base['geometry']['sha256']
                    for ext, content in [('.geojson', body), ('.geojson.gz', compressed)]:
                        target = staging / ('packages/objects/' + digest + ext)
                        if target.exists(): require(target.read_bytes() == content, 'artifact identity collision')
                        else: target.write_bytes(content)
                bundles[bid] = {'status': base['status'], 'descriptor': name}
                statistics.append({'bundle_id': bid, **base['counts'], 'vertices': base['geometry']['vertex_count'] if body else 0,
                    'decoded_bytes': len(body) if body else 0, 'gzip_bytes': len(compressed) if body else 0,
                    'descriptor_bytes': max_descriptor, 'build_seconds': time.perf_counter()-began})
            except TooLarge as exc:
                bundles[bid] = {'status': 'unsupported', 'reason': 'scope_too_large', 'limit': exc.limit, 'actual': exc.actual}
        # An explicitly preferred oversized bundle is not silently replaced by a smaller scope.
        base_files = {n: s for n, s in data.manifest['files'].items() if not n.startswith('packages/')}
        index = {'schema_version': 1, 'contract': CONTRACT, 'base_files': base_files,
                 'plan': plan, 'selections': selections, 'bundles': bundles}
        index_bytes = encoded(index); require(len(index_bytes) <= MAX_INDEX_BYTES, 'support inventory too large')
        (staging / INDEX).write_bytes(index_bytes)
        files = {str(p.relative_to(staging)): {'bytes': p.stat().st_size, 'sha256': sha256(p)}
                 for p in sorted(staging.rglob('*')) if p.is_file()}
        manifest = {**data.manifest, 'schema_version': 2, 'files': files}
        validate_manifest(manifest); write_json(staging / 'manifest.json', manifest)
        # Reuse the verified geography to validate packages without a second national geometry load.
        import copy
        checked = copy.copy(data)
        checked.root, checked.manifest, checked.version = checked_release(staging)
        PackageIndex(checked)
    return {'dataset_version': sha256(Path(output)/'manifest.json'), 'output': str(output),
            'bundle_counts': dict(Counter(r['status'] for r in bundles.values())),
            'unsupported': {k:v for k,v in bundles.items() if v['status']=='unsupported'},
            'roots': len(roots), 'package_bytes': sum(s['bytes'] for n,s in files.items() if n.startswith('packages/')),
            'elapsed_seconds': time.perf_counter()-start,
            'peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            'bundles': statistics}


def file_signature(path):
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


class PackageIndex:
    """Validate on load; retain small envelopes and file records, not geometry copies."""
    def __init__(self, data):
        self.data = data; self.roots = eligible(data); self.responses = {}; self.artifacts = {}; self.index = None
        if INDEX not in data.manifest['files']:
            require(not package_files(data.manifest), 'package files without support index')
            return
        index = read_json(data.root / INDEX, MAX_INDEX_BYTES); self.index = index
        require(set(index) == {'schema_version', 'contract', 'base_files', 'plan', 'selections', 'bundles'}
                and type(index['schema_version']) is int and index['schema_version'] == 1
                and index['contract'] == CONTRACT, 'invalid support index')
        require(index['base_files'] == {n:s for n,s in data.manifest['files'].items() if not n.startswith('packages/')},
                'stale package input binding')
        require(set(index['selections']) == eligible(data), 'incomplete package support inventory')
        plan = validate_plan(index['plan'])
        roots, selections, specs, unresolved = scope_plan(data, plan)
        expected_specs = {bid: (kind, sr, grouping) for bid,kind,sr,grouping in specs}
        require(index['selections'] == selections and set(index['bundles']) == set(expected_specs) | set(unresolved),
                'selection or bundle inventory differs from grouping plan')
        provenance = Provenance(data)
        accounted = {INDEX}; bases = {}; total = 0
        for bid, record in index['bundles'].items():
            require(re.fullmatch(ID, bid) is not None, 'invalid bundle identity')
            if record['status'] == 'unsupported':
                if bid in unresolved:
                    require(record == unresolved[bid], 'incorrect unresolved membership')
                else:
                    require(set(record) == {'status','reason','limit','actual'} and record['reason'] == 'scope_too_large'
                            and record['limit'] in {'members','depth','feature_vertices','vertices','decoded_bytes','transfer_bytes','descriptor_bytes'}
                            and type(record['actual']) is int and record['actual'] > {
                                'members': MAX_MEMBERS, 'depth': MAX_DEPTH, 'feature_vertices': MAX_FEATURE_VERTICES,
                                'vertices': MAX_VERTICES, 'decoded_bytes': MAX_GEOMETRY_BYTES,
                                'transfer_bytes': MAX_TRANSFER_BYTES, 'descriptor_bytes': MAX_DESCRIPTOR_BYTES
                            }.get(record.get('limit'), 0), 'invalid oversized evidence')
                continue
            name = record['descriptor']; require(name in data.manifest['files'] and re.fullmatch(r'packages/descriptors/[0-9a-f]{64}\.json', name), 'unlisted descriptor')
            raw = (data.root / name).read_bytes()
            require(len(raw) <= MAX_DESCRIPTOR_BYTES and hashlib.sha256(raw).hexdigest() == Path(name).stem, 'descriptor integrity')
            base = json.loads(raw)
            require(isinstance(base, dict) and set(base) == set(BaseDescriptor.model_fields), 'invalid base descriptor fields')
            BaseDescriptor.model_validate(base)
            require(encoded(base) == raw and base['bundle_id'] == bid, 'noncanonical descriptor')
            require(bid in expected_specs, 'unresolved membership was published')
            kind, scope_roots, grouping = expected_specs[bid]
            require(base['bundle_kind'] == kind and base['scope_root_ids'] == scope_roots and base['grouping'] == grouping,
                    'descriptor scope differs from grouping definition')
            members = scope_members(data, scope_roots)
            require([r['id'] for r in base['areas']] == members, 'descriptor membership differs from catalogue')
            for entry in base['areas']:
                require(entry == inventory_entry(data, entry['id'], provenance.for_area(entry['id'])), 'stale area qualifications or hierarchy')
            sources = provenance.sources(provenance.common | {sid for e in base['areas'] for sid in e['source_ids']})
            credits = {str(v[k]) for v in sources for k in ('attribution','attribution_statement','attribution_display','modifications','publication_disclaimer') if v.get(k)}
            if grouping: credits.update(v['attribution'] for v in grouping['sources'])
            require(base['common_source_ids'] == sorted(provenance.common) and base['sources'] == sources and base['attribution'] == sorted(credits)
                    and base['source_mapping_complete'] == (not provenance.unscoped), 'incomplete source attribution')
            available = {u for u in members if u in data.displays}; g = base['geometry']
            require(base['unavailable_reason'] == (None if available else 'no_display_geometry'), 'incorrect unavailable reason')
            require(all(data.areas[u]['assignment_status'] == 'missing_geometry' for u in set(members)-available),
                    'unexplained missing display')
            require(base['counts'] == {'areas':len(members),'available':len(available),'unavailable':len(members)-len(available)}, 'invalid package counts')
            require(base['coverage'] == ('none' if not available else 'complete' if len(available)==len(members) else 'partial'), 'invalid coverage')
            require(base['status'] == record['status'] == ('ready' if available else 'unavailable'), 'invalid package status')
            if g is None:
                require(not available and base['bundle_bbox'] is None, 'missing artifact for available geometry')
            else:
                Geometry.model_validate(g)
                digest = g['sha256']; require(g['path'] == '/v1/display-packages/'+digest+'.geojson', 'invalid artifact URL')
                require(set(g['encodings']) == {'identity', 'gzip'}, 'missing encoding')
                identity = 'packages/objects/'+digest+'.geojson'; zipped = identity+'.gz'
                for file in (identity, zipped): require(file in data.manifest['files'], 'unlisted artifact')
                require(data.manifest['files'][identity]['bytes'] == g['decoded_bytes'] == g['encodings']['identity']['bytes']
                        and g['decoded_bytes'] <= MAX_GEOMETRY_BYTES
                        and data.manifest['files'][zipped]['bytes'] == g['encodings']['gzip']['bytes'] <= MAX_TRANSFER_BYTES,
                        'artifact size mismatch')
                content = (data.root/identity).read_bytes()
                require(hashlib.sha256(content).hexdigest() == digest, 'decoded checksum mismatch')
                with gzip.open(data.root/zipped, 'rb') as stream:
                    decoded = stream.read(MAX_GEOMETRY_BYTES+1)
                require(decoded == content, 'gzip expansion or content mismatch')
                artifact = json.loads(content)
                require(set(artifact) == {'contract','purpose','type','bundle_id','bbox','features'} and artifact['contract'] == GEOMETRY_CONTRACT
                    and artifact['purpose']=='display_only' and artifact['type']=='FeatureCollection' and artifact['bundle_id']==bid
                    and encoded(artifact)==content, 'invalid geometry envelope')
                require([f['id'] for f in artifact['features']] == sorted(available), 'invalid geometry membership')
                vertices = 0; boxes = []
                for f in artifact['features']:
                    require(set(f)=={'type','id','bbox','properties','geometry'} and f['type']=='Feature' and f['properties']=={}, 'invalid feature metadata')
                    count, bbox = polygon_stats(f['geometry']); bound(count, MAX_FEATURE_VERTICES, 'feature_vertices')
                    require(f['bbox']==bbox and encoded(f['geometry'])==encoded(data.displays[f['id']]), 'artifact is not published display geometry')
                    vertices += count; boxes.append(bbox)
                require(vertices == g['vertex_count'] <= MAX_VERTICES and len(available)==g['feature_count']
                        and artifact['bbox']==base['bundle_bbox']==union_bbox(boxes), 'invalid stored geometry statistics')
                self.artifacts[digest] = {encoding: (data.root/file, data.manifest['files'][file])
                                         for encoding,file in [('identity',identity),('gzip',zipped)]}
                self.artifacts[digest] = {key: (p, {**v, 'stat': file_signature(p)})
                    for key,(p,v) in self.artifacts[digest].items()}
                accounted.update((identity,zipped))
            for uid in scope_roots: envelope(data, uid, base, {'bundle_id': bid, 'reason': 'catalogue_scope'})
            bases[bid]=base; accounted.add(name)
        for uid, selection in index['selections'].items():
            record = index['bundles'].get(selection['bundle_id']); require(record is not None, 'selection references missing bundle')
            if record['status'] == 'unsupported': continue
            base = bases[selection['bundle_id']]
            require(uid in base['scope_root_ids'], 'requested municipality outside bundle')
            body, etag = envelope(data, uid, base, selection); total += len(body)
            require(total <= MAX_ENVELOPES_BYTES, 'aggregate descriptor cache exceeds budget')
            self.responses[uid]=(body, etag)
        require(accounted == set(package_files(data.manifest)), 'unreferenced package files')

    def descriptor(self, uid):
        row = self.data.areas.get(uid)
        if row is None or row.get('lifecycle_status') == 'superseded': raise PackageError(404,'unknown_area')
        if uid not in self.roots: raise PackageError(422,'unsupported_root')
        if self.index is None: raise PackageError(409,'package_not_built')
        if uid not in self.responses:
            record = self.index['bundles'][self.index['selections'][uid]['bundle_id']]
            raise PackageError(409,record['reason'])
        return self.responses[uid]

    def artifact(self, digest, encoding):
        if not isinstance(digest,str) or HEX.fullmatch(digest) is None or digest not in self.artifacts:
            raise PackageError(404,'unknown_artifact')
        path, spec = self.artifacts[digest][encoding]
        try:
            require(not path.is_symlink() and path.is_file() and file_signature(path)==spec['stat'], 'artifact unavailable')
        except (OSError, CatalogueError) as exc:
            raise PackageError(503,'artifact_unavailable') from exc
        return path, spec


def negotiate_encoding(header):
    if not header: return 'identity'
    weights = {}
    for part in header.split(','):
        pieces = part.strip().split(';'); name = pieces[0].strip().lower()
        try:
            q = 1.0
            if len(pieces)>2 or len(pieces)==2 and not pieces[1].strip().startswith('q='): raise ValueError
            if len(pieces)==2: q=float(pieces[1].strip()[2:])
            if not math.isfinite(q) or not 0<=q<=1 or name in weights: raise ValueError
            weights[name]=q
        except ValueError: raise PackageError(422,'invalid_accept_encoding') from None
    gz=weights.get('gzip',weights.get('*',0)); identity=weights.get('identity',0 if weights.get('*')==0 else 1)
    if gz>0 and gz>=identity:return 'gzip'
    if identity>0:return 'identity'
    raise PackageError(406,'encoding_not_acceptable')
