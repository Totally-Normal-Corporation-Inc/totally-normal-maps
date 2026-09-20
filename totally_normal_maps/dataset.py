"""Read-only geographical queries over one verified immutable release."""
from collections import Counter, defaultdict
from contextlib import closing
import json
import math
import sqlite3
import unicodedata

import shapely
from shapely.geometry import Point, box, mapping, shape
from shapely.strtree import STRtree

from .catalogue import CatalogueError, PROVINCES, geometry_issue, read_json
from .releases import MAX_FILE_BYTES, checked_release, source_metadata
from .jurisdiction_migrations import load_migrations
from .layers import LAYERS, load_electoral, selected_editions, selection_coverage, in_layer, layer_inventory
from .municipal_elections import load_municipal, lookup_coverage, layer_coverage


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c))


class Dataset:
    """Construct once per process. No SQL connections or mutation during requests."""

    def __init__(self, root, expected_sha256=None):
        self.root, self.manifest, self.version = checked_release(root, expected_sha256)
        self.report = read_json(self.root / 'report.json')
        if self.report['catalogue_sha256'] != self.manifest['files']['catalogue.sqlite3']['sha256']:
            raise CatalogueError('Report and serving manifest describe different catalogues.')
        self.areas, self.geometries, self.displays = {}, {}, {}
        self.required_displays = set()
        self.children = defaultdict(list)
        self.pending_ids, self.pending_shapes, self.unknown_ids = [], [], []
        self.add({'id': 'ca', 'name': 'Canada', 'kind': 'country', 'level': 'country',
                  'parent_id': None, 'source_id': 'CA', 'assignment_status': 'hierarchy_only'})
        for code, (abbr, name) in PROVINCES.items():
            self.add({'id': f'ca-{abbr.lower()}', 'name': name, 'kind': 'territory' if int(code) >= 60 else 'province',
                      'level': 'province', 'parent_id': 'ca', 'source_id': code, 'code': abbr,
                      'assignment_status': 'hierarchy_only'})
        connection = sqlite3.connect((self.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True)
        with closing(connection) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
                raise CatalogueError('Invalid serving database.')
            tables = {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {'csd', 'region', 'csd_region', 'city_area', 'area_revision', 'boundary_revision', 'jurisdiction_revision', 'electoral_area', 'municipal_electoral_area'} or 'csd' not in tables:
                raise CatalogueError('Unexpected serving database tables.')
            memberships = dict(db.execute('SELECT csd_id, region_id FROM csd_region')) if 'csd_region' in tables else {}
            self.source_ids = {}
            for table, level in [('csd', 'municipality'), ('region', 'region'), ('city_area', 'city_area')]:
                if table not in tables:
                    continue
                for source in db.execute(f'SELECT * FROM {table} ORDER BY id'):
                    record = json.loads(source['record'])
                    if record['id'] != source['id'] or record['province'] not in PROVINCES:
                        raise CatalogueError('Inconsistent area identity.')
                    uid = f"ca-csd-{source['id']}" if table == 'csd' else source['id']
                    province_id = f"ca-{PROVINCES[record['province']][0].lower()}"
                    parent = (memberships.get(source['id'], province_id) if table == 'csd' else
                              record.get('parent_area_id') or record.get('municipality_id', f"ca-csd-{source['parent_csd_id']}") if table == 'city_area' else province_id)
                    item = {'id': uid, 'source_id': record.get('source_id', source['id']), 'name': record['name'],
                            'level': level, 'kind': record.get('kind', 'municipality_or_equivalent'),
                            'source_type': record.get('type'), 'parent_id': parent, 'province_id': province_id,
                            'assignment_status': record['assignment_status'], 'aliases': record.get('aliases', []),
                            'issues': record.get('issues', []), 'bbox': record.get('bbox')}
                    for key in ('parent_overlap', 'relationship_basis', 'coverage_policy',
                                'coverage_note', 'boundary_basis', 'evidence', 'uncertainty_basis',
                                'parent_exception_evidence', 'scheme', 'repair'):
                        if key in record:
                            item[key] = record[key]
                    self.add(item)
                    if table == 'city_area':
                        item['municipality_id'] = record.get('municipality_id', f"ca-csd-{source['parent_csd_id']}")
                    self.source_ids[(level, source['id'])] = uid
                    full = source['geometry']
                    if full is not None:
                        geometry = shapely.from_wkb(full)
                        if geometry_issue(geometry) or record['assignment_status'] not in {'validated_source', 'validated_derived'}:
                            raise CatalogueError('Invalid assignment geometry in serving release.')
                        self.geometries[uid] = geometry
                        self.required_displays.add(uid)
                    else:
                        # Candidates identify uncertainty only; never become normal matches.
                        candidate = source['repair_candidate'] if 'repair_candidate' in source.keys() else None
                        if candidate is not None:
                            geometry = shapely.from_wkb(candidate)
                            if geometry_issue(geometry):
                                raise CatalogueError('Invalid review candidate.')
                            self.required_displays.add(uid)
                        elif record.get('bbox'):
                            geometry = box(*record['bbox'])
                        else:
                            self.unknown_ids.append(uid)
                            continue
                        self.pending_ids.append(uid)
                        self.pending_shapes.append(geometry)
            if 'area_revision' in tables:
                if 'quebec_refresh' not in self.report:
                    raise CatalogueError('Area revisions require a qualified refresh report.')
                self.load_revisions(db)
            if 'boundary_revision' in tables:
                self.load_boundary_revisions(db)
            load_migrations(self, db, 'jurisdiction_revision' in tables)
            load_electoral(self, db, 'electoral_area' in tables)
            load_municipal(self, db, 'municipal_electoral_area' in tables)
        counts = Counter(r['level'] for r in self.areas.values() if r.get('lifecycle_status') != 'superseded')
        expected_municipalities = self.report.get('quebec_refresh', {}).get('active_municipality_count', self.report['feature_count'])
        migrations = [r['migrations'] for r in self.report.get('jurisdiction_refreshes', {}).values() if 'migrations' in r]
        expected_municipalities += sum(r['added_municipality_count'] - r['superseded_municipality_count'] for r in migrations)
        expected_regions = self.report.get('regions', {}).get('feature_count', 0) + sum(r['added_region_count'] - r['retired_region_count'] for r in migrations)
        for level, expected in [('municipality', expected_municipalities),
                                ('region', expected_regions),
                                ('city_area', self.report.get('city_areas', {}).get('feature_count', 0))]:
            if counts[level] != expected:
                raise CatalogueError('Serving layer count differs from the report.')
        for uid, item in self.areas.items():
            parent = item['parent_id']
            if parent is not None:
                if parent not in self.areas or parent == uid:
                    raise CatalogueError('Missing or invalid area parent.')
                if item.get('lifecycle_status') != 'superseded' and self.areas[parent].get('lifecycle_status') == 'superseded':
                    raise CatalogueError('Current area may not retain a superseded parent.')
                if item.get('lifecycle_status') != 'superseded':
                    self.children[parent].append(uid)
            item['geometry_available'] = uid in self.geometries
        default_editions = {layer:selected_editions(self,layer) for layer in LAYERS}
        for uid in self.areas:
            ancestors = self.ancestors(uid)  # also rejects cycles before accepting traffic
            if self.areas[uid]['level'] == 'city_area':
                municipal = self.areas[uid]['municipality_id']
                if (municipal not in {a['id'] for a in ancestors} or
                        self.areas[municipal].get('lifecycle_status') == 'superseded' or
                        self.areas[municipal]['province_id'] != self.areas[uid]['province_id']):
                    raise CatalogueError('Invalid city-area municipal ancestry.')
            self.areas[uid]['child_count'] = sum(self.areas[c].get('layer') in {'administrative','shared'} for c in self.children[uid])
            if self.editions:
                self.areas[uid]['child_counts_by_layer'] = {
                    layer: sum(in_layer(self.areas[c], layer, default_editions[layer])
                               for c in self.children[uid]) for layer in LAYERS}
        for children in self.children.values():
            children.sort(key=lambda uid: (normalize(self.areas[uid]['name']), uid))
        self.ordered = sorted(self.areas, key=lambda uid: (normalize(self.areas[uid]['name']), uid))
        self.search_text = {uid: normalize(' '.join([r['name'], uid, r['source_id'], r.get('code', ''), r.get('authority_name', ''), *r['aliases']]))
                            for uid, r in self.areas.items()}
        self.load_displays()
        self.geometry_ids = sorted(uid for uid in self.geometries if self.areas[uid].get('lifecycle_status') != 'superseded')
        self.tree = STRtree([self.geometries[uid] for uid in self.geometry_ids])
        self.pending_tree = STRtree(self.pending_shapes)
        self.summary = {'dataset_version': self.version, 'label': self.manifest['label'],
                        'country': 'CA', 'qualification': 'review_required', 'counts': dict(counts),
                        'assignment_geometries': len(self.geometry_ids),
                        'unavailable_geometries': sum(uid not in self.geometries for uid in set(self.pending_ids + self.unknown_ids)),
                        'boundary_difference_review_count': sum(uid in self.geometries for uid in self.pending_ids),
                        'sources': [self.report['source']], 'coverage': {},
                        'limitations': ['Geographic qualification remains incomplete.',
                            'Unapproved repair candidates never contribute direct matches.',
                            'Province and country matches are inferred through the hierarchy.',
                            'Missing city areas do not imply that a city has no subdivisions.']}
        self.summary['limitations'].append(
            'Some regions contain selected communities only. Their boundaries are community footprints; '
            'a missing region match does not mean the location has no regional identity.')
        if 'province_display_source' in self.report:
            self.summary['sources'].append(self.report['province_display_source'])
        if 'regions' in self.report:
            self.summary['sources'].extend(self.report['regions']['sources'])
            self.summary['coverage']['regions'] = self.report['regions']['jurisdictions']
        if 'city_areas' in self.report:
            self.summary['sources'].extend(self.report['city_areas']['sources'].values())
            self.summary['coverage']['city_areas'] = self.report['city_areas']['municipalities']
        if 'quebec_refresh' in self.report:
            refresh = self.report['quebec_refresh']
            self.summary['sources'].extend(refresh['sources'].values())
            self.summary['coverage']['quebec_refresh'] = refresh
            self.summary['historical_counts'] = dict(Counter(r['level'] for r in self.areas.values() if r.get('lifecycle_status') == 'superseded'))
        if 'topology_reviews' in self.report:
            self.summary['coverage']['topology_reviews'] = self.report['topology_reviews']
        if 'ontario_refresh' in self.report:
            refresh = self.report['ontario_refresh']
            self.summary['sources'].extend(refresh['sources'].values())
            self.summary['coverage']['ontario_refresh'] = refresh
        if 'jurisdiction_refreshes' in self.report:
            self.summary['coverage']['jurisdiction_refreshes'] = self.report['jurisdiction_refreshes']
            for refresh in self.report['jurisdiction_refreshes'].values():
                self.summary['sources'].extend(refresh['sources'].values())
        if any(r.get('lifecycle_status') == 'superseded' for r in self.areas.values()):
            self.summary['historical_counts'] = dict(Counter(r['level'] for r in self.areas.values() if r.get('lifecycle_status') == 'superseded'))
        self.summary['layers'] = layer_inventory(self)
        if 'electoral' in self.report:
            self.summary['coverage']['electoral'] = self.report['electoral']
            self.summary['sources'].extend(self.report['electoral']['sources'].values())
        if 'municipal_elections' in self.report:
            self.summary['coverage']['municipal_elections'] = self.report['municipal_elections']
            self.summary['sources'].extend(self.report['municipal_elections']['sources'].values())
        self.summary['sources'] = [source_metadata(source) for source in self.summary['sources']]

    def load_boundary_revisions(self, db):
        """Scoped source revisions; preserve unresolved repairs and previous extents."""
        refreshes = dict(self.report.get('jurisdiction_refreshes', {}))
        if 'ontario_refresh' in self.report:
            refreshes['35'] = self.report['ontario_refresh']
        if not refreshes or any(p not in PROVINCES or r.get('state') != 'review_required' for p, r in refreshes.items()):
            raise CatalogueError('Boundary revisions require qualified jurisdiction reports.')
        by_province = {'ca-' + PROVINCES[p][0].lower(): r for p, r in refreshes.items()}
        rows = db.execute('SELECT * FROM boundary_revision ORDER BY id').fetchall()
        allowed = {'id', 'name', 'source_name', 'aliases', 'evidence', 'assignment_status', 'bbox',
                   'vertices', 'boundary_basis', 'effective_date', 'boundary_source', 'boundary_source_ids',
                   'previous_boundary_reference_date', 'uncertainty_basis', 'coverage_note', 'comparison', 'issues', 'update_status',
                   'proposed_boundary_source', 'proposed_boundary_source_ids', 'proposed_effective_date'}
        for source in rows:
            uid, operation = source['id'], source['operation']; row = json.loads(source['record'])
            if (uid not in self.areas or self.areas[uid]['province_id'] not in by_province or
                    row.get('id') != uid or not row.get('evidence') or set(row) - allowed):
                raise CatalogueError('Invalid Ontario boundary revision identity or metadata.')
            area = self.areas[uid]
            if operation == 'metadata':
                if (area['level'] != 'municipality' or source['geometry'] is not None or source['review_geometry'] is not None or
                        set(row) - {'id', 'name', 'source_name', 'aliases', 'evidence'}):
                    raise CatalogueError('Invalid Ontario name revision.')
                area.update(row); continue
            if operation not in {'boundary', 'deferred_boundary', 'region'} or area['level'] != ('region' if operation == 'region' else 'municipality'):
                raise CatalogueError('Invalid boundary revision operation.')
            was_pending = uid not in self.geometries
            full, review = source['geometry'], source['review_geometry']
            if (was_pending != (full is None) or (operation in {'boundary', 'deferred_boundary'} and was_pending) or
                    row.get('assignment_status') != ('unreviewed_repair' if was_pending else 'validated_derived' if operation == 'region' else 'validated_source')):
                raise CatalogueError('Boundary revision cannot approve or downgrade an existing repair.')
            if uid in self.pending_ids:
                index = self.pending_ids.index(uid); self.pending_ids.pop(index); self.pending_shapes.pop(index)
            if uid in self.unknown_ids: self.unknown_ids.remove(uid)
            if full is not None:
                geom = shapely.from_wkb(full)
                if geometry_issue(geom): raise CatalogueError('Invalid revised assignment geometry.')
                if operation == 'deferred_boundary' and (row.get('update_status') != 'deferred' or not geom.equals_exact(self.geometries[uid], 0)):
                    raise CatalogueError('Deferred update must retain the previous assignment boundary.')
                self.geometries[uid] = geom
            if review is not None:
                geom = shapely.from_wkb(review)
                if geometry_issue(geom): raise CatalogueError('Invalid boundary review geometry.')
                self.pending_ids.append(uid); self.pending_shapes.append(geom)
            elif was_pending:
                raise CatalogueError('Unresolved region lacks its review candidate.')
            area.update(row); self.required_displays.add(uid)
        for province_id, refresh in by_province.items():
            scoped = [r for r in rows if self.areas[r['id']]['province_id'] == province_id]
            expected = {'ca-csd-' + r['csd_id'] for a in refresh['adjustments'] for r in a['members']}
            deferred = {'ca-csd-' + r['csd_id'] for a in refresh.get('deferred_adjustments', []) for r in a['members']}
            if ({r['id'] for r in scoped if r['operation'] == 'boundary'} != expected or
                    {r['id'] for r in scoped if r['operation'] == 'deferred_boundary'} != deferred or
                    len(expected) != refresh['updated_municipality_count'] or
                    len(deferred) != refresh.get('deferred_municipality_count', 0) or
                    sum(r['operation'] == 'region' for r in scoped) != refresh['updated_region_count']):
                raise CatalogueError('Jurisdiction revision counts differ from report.')

    def load_revisions(self, db):
        """Apply explicit current identities without altering retained source rows."""
        rows = db.execute('SELECT * FROM area_revision ORDER BY id').fetchall()
        allowed_metadata = {'id', 'name', 'source_name', 'aliases', 'evidence', 'lifecycle_status', 'valid_to', 'successor_ids'}
        for source in rows:
            record = json.loads(source['record']); uid = source['id']; operation = source['operation']
            if record.get('id') != uid or not record.get('evidence'):
                raise CatalogueError('Inconsistent or unevidenced area revision.')
            if operation == 'metadata':
                if (uid not in self.areas or self.areas[uid]['level'] != 'municipality' or
                        self.areas[uid]['province_id'] != 'ca-qc' or set(record) - allowed_metadata or source['geometry'] is not None):
                    raise CatalogueError('Invalid municipal metadata revision.')
                if record.get('lifecycle_status') not in (None, 'superseded'):
                    raise CatalogueError('Unsupported municipal lifecycle revision.')
                self.areas[uid].update(record)
                continue
            if operation == 'new':
                if (uid in self.areas or not uid.startswith('ca-qc-mun-') or record.get('level') != 'municipality' or
                        record.get('province') != '24' or not record.get('predecessor_ids')):
                    raise CatalogueError('Invalid municipal successor revision.')
                item = {k: record[k] for k in ('id', 'source_id', 'name', 'level', 'kind', 'parent_id', 'assignment_status',
                        'aliases', 'issues', 'bbox', 'source_name', 'lifecycle_status', 'predecessor_ids', 'effective_date',
                        'evidence', 'boundary_basis', 'coverage_note', 'comparison')}
                item.update(province_id='ca-qc', source_type=record['type'])
                self.add(item)
                self.source_ids[('municipality', uid)] = uid
            elif operation == 'region':
                if uid not in self.areas or self.areas[uid]['level'] != 'region' or record.get('province') != '24':
                    raise CatalogueError('Invalid regional revision.')
                for key in ('bbox', 'member_count', 'boundary_basis', 'evidence', 'coverage_note'):
                    self.areas[uid][key] = record[key]
            else:
                raise CatalogueError('Unsupported area revision operation.')
            if source['geometry'] is None or uid in self.pending_ids or uid in self.unknown_ids:
                raise CatalogueError('Cannot replace an unresolved boundary through a revision.')
            geom = shapely.from_wkb(source['geometry'])
            if geometry_issue(geom):
                raise CatalogueError('Invalid revised boundary.')
            self.geometries[uid] = geom; self.required_displays.add(uid)
        for uid, area in self.areas.items():
            if area.get('lifecycle_status') == 'superseded':
                successors = area.get('successor_ids', [])
                if not successors or uid in self.pending_ids or uid in self.unknown_ids:
                    raise CatalogueError('Invalid superseded municipality.')
                for successor in successors:
                    other = self.areas.get(successor, {})
                    if (other.get('lifecycle_status') != 'current' or uid not in other.get('predecessor_ids', []) or
                            area['parent_id'] != other.get('parent_id')):
                        raise CatalogueError('Broken municipal succession relationship.')
            for predecessor in area.get('predecessor_ids', []):
                other = self.areas.get(predecessor, {})
                if other.get('lifecycle_status') != 'superseded' or uid not in other.get('successor_ids', []):
                    raise CatalogueError('Broken municipal predecessor relationship.')
        refresh = self.report['quebec_refresh']
        if (sum(r['operation'] == 'new' for r in rows) != refresh['added_municipality_count'] or
                sum(a.get('lifecycle_status') == 'superseded' for a in self.areas.values()) != refresh['superseded_municipality_count']):
            raise CatalogueError('Municipal revision counts differ from the report.')

    def add(self, item):
        if item['id'] in self.areas:
            raise CatalogueError('Duplicate area identity.')
        item.setdefault('layer', 'administrative' if item['level'] not in {'country', 'province'} else 'shared')
        item.setdefault('aliases', [])
        item.setdefault('issues', [])
        item['country_id'] = 'ca'
        self.areas[item['id']] = item

    def ancestors(self, uid):
        output, visited = [], {uid}
        while self.areas[uid]['parent_id'] is not None:
            uid = self.areas[uid]['parent_id']
            if uid in visited or uid not in self.areas:
                raise CatalogueError('Cyclic or incomplete area hierarchy.')
            visited.add(uid)
            output.append(self.areas[uid])
        return list(reversed(output))

    def load_displays(self):
        for name in self.manifest['files']:
            if not name.startswith('display/'):
                continue
            collection = read_json(self.root / name, MAX_FILE_BYTES)
            if collection.get('type') != 'FeatureCollection' or not isinstance(collection.get('features'), list):
                raise CatalogueError('Invalid display collection.')
            level = ('province' if name == 'display/provinces.geojson' else 'region' if '/regions-' in name
                     else 'city_area' if '/city-areas-' in name else 'electoral_district' if '/electoral-' in name or '/municipal-' in name else 'municipality')
            for feature in collection['features']:
                source_id = feature['properties']['id']
                if level == 'province':
                    if source_id not in PROVINCES:
                        raise CatalogueError('Unexpected province display identity.')
                    uid = f'ca-{PROVINCES[source_id][0].lower()}'
                else:
                    uid = self.source_ids.get((level, source_id))
                if uid not in self.areas or uid in self.displays:
                    raise CatalogueError('Unexpected or duplicate display identity.')
                geometry = shape(feature['geometry'])
                if geometry_issue(geometry) or any(not math.isfinite(v) for v in geometry.bounds):
                    raise CatalogueError('Invalid display geometry.')
                self.displays[uid] = mapping(geometry)
                self.areas[uid]['display_status'] = feature['properties'].get('assignment_status', self.areas[uid]['assignment_status'])
        if any(f'ca-{abbr.lower()}' not in self.displays for abbr, _ in PROVINCES.values()):
            raise CatalogueError('Incomplete province display.')
        if self.required_displays - self.displays.keys():
            raise CatalogueError('A source boundary is missing its display representation.')
        self.displays['ca'] = mapping(shapely.union_all([shape(self.displays[f'ca-{abbr.lower()}']) for abbr, _ in PROVINCES.values()]))
        for uid, area in self.areas.items():
            area['display_available'] = uid in self.displays

    def page(self, *, parent_id=None, level=None, query=None, offset=0, limit=100, include_historical=False, layer='administrative', editions=None, within_id=None):
        if parent_id is not None and parent_id not in self.areas:
            raise KeyError(parent_id)
        selected = ([uid for uid in self.ordered if self.areas[uid]['parent_id'] == parent_id]
                    if parent_id is not None and include_historical else
                    self.children[parent_id] if parent_id is not None else self.ordered)
        chosen = selected_editions(self, layer, editions)
        if within_id is not None and within_id not in self.areas: raise KeyError(within_id)
        term = normalize(query or '')
        selected = [uid for uid in selected if (level is None or self.areas[uid]['level'] == level)
                    and (include_historical or self.areas[uid].get('lifecycle_status') != 'superseded')
                    and in_layer(self.areas[uid], layer, chosen)
                    and (within_id is None or within_id in {a['id'] for a in self.ancestors(uid)})
                    and (not term or term in self.search_text[uid])]
        return {'dataset_version': self.version, 'total': len(selected), 'offset': offset, 'limit': limit,
                'next_offset': offset + limit if offset + limit < len(selected) else None,
                'items': [self.areas[uid] for uid in selected[offset:offset+limit]]}

    def boundary(self, uid, resolution='display'):
        area = self.areas[uid]
        geometry = self.displays.get(uid) if resolution == 'display' else mapping(self.geometries[uid]) if uid in self.geometries else None
        if geometry is None:
            raise CatalogueError('The requested boundary representation is unavailable; review coverage and geometry status.')
        return {'type': 'Feature', 'id': uid, 'properties': {**area, 'resolution': resolution,
                'suitable_for_assignment': resolution == 'full' and area.get('lifecycle_status') != 'superseded', 'geography_qualified': False},
                'geometry': geometry, 'dataset_version': self.version, 'sources': self.summary['sources']}

    def lookup(self, longitude, latitude, *, layers=None, editions=None):
        requested = ['administrative'] if layers is None else layers
        if (not isinstance(requested, (list, tuple)) or not requested or len(requested) > len(LAYERS)
                or any(not isinstance(layer, str) for layer in requested)
                or len(set(requested)) != len(requested) or set(requested) - LAYERS.keys()):
            raise CatalogueError('Unknown or repeated lookup layer.')
        editions = {} if editions is None else editions
        if not isinstance(editions, dict): raise CatalogueError('Expected an edition map keyed by layer.')
        if set(editions) - set(requested): raise CatalogueError('Edition supplied for an unrequested layer.')
        results = {layer: self._lookup_layer(longitude, latitude, layer, editions.get(layer)) for layer in requested}
        if len(requested) == 1 and requested[0] == 'administrative': return results['administrative']
        statuses = {r['status'] for r in results.values()}
        status = next((s for s in ('review_required', 'ambiguous', 'matched', 'no_match') if s in statuses))
        matches = {m['id']: m for result in results.values() for m in result['matches']}
        return {'dataset_version': self.version, 'qualification': 'review_required',
                'longitude': longitude, 'latitude': latitude, 'status': status,
                'ambiguous': any(r['ambiguous'] for r in results.values()), 'matches': list(matches.values()),
                **{key: sorted({uid for r in results.values() for uid in r[key]}) for key in
                   ('direct_match_ids', 'review_candidate_ids', 'unlocated_missing_geometry_ids')},
                'hierarchy_geometry_disagreements': [d for r in results.values() for d in r['hierarchy_geometry_disagreements']],
                'layers': results}

    def _lookup_layer(self, longitude, latitude, layer, editions):
        chosen = selected_editions(self, layer, editions)
        accepts = lambda uid: (in_layer(self.areas[uid], layer, chosen) and
                               (layer != 'municipal' or self.areas[uid].get('layer') == 'municipal'))
        if (type(longitude) not in (float, int) or type(latitude) not in (float, int)
                or not math.isfinite(longitude) or not math.isfinite(latitude)
                or abs(longitude) > 180 or abs(latitude) > 90):
            raise CatalogueError('Expected finite WGS84 longitude/latitude in range.')
        point = Point(longitude, latitude)
        direct = sorted(self.geometry_ids[int(i)] for i in self.tree.query(point, predicate='covered_by'))
        pending = sorted(self.pending_ids[int(i)] for i in self.pending_tree.query(point, predicate='covered_by'))
        direct = [uid for uid in direct if accepts(uid)]
        pending = [uid for uid in pending if accepts(uid)]
        unknown = [uid for uid in self.unknown_ids if accepts(uid)]
        related, disagreements = set(direct), []
        for uid in direct:
            for ancestor in self.ancestors(uid):
                related.add(ancestor['id'])
                if ancestor['id'] in self.geometries and not self.geometries[ancestor['id']].covers(point):
                    disagreements.append({'area_id': uid, 'ancestor_id': ancestor['id']})
        # A quartier and its arrondissement are expected to both cover a point.
        # Multiple incomparable areas at the same level still mean ambiguity.
        ancestor_ids = {uid: {a['id'] for a in self.ancestors(uid)} for uid in direct}
        leaves = [uid for uid in direct if not any(uid in ancestor_ids[other] and
                  self.areas[uid]['level'] == self.areas[other]['level'] for other in direct)]
        # Independent publisher schemes (e.g. Toronto former municipalities and
        # neighbourhoods) can both match. Same-scheme siblings remain ambiguous.
        counts = Counter((self.areas[uid]['level'], self.areas[uid].get('scheme', 'default')
                          if self.areas[uid]['level'] == 'city_area' else self.areas[uid].get('edition', '')) for uid in leaves)
        ambiguous = any(n > 1 for n in counts.values())
        status = ('review_required' if pending or unknown or disagreements else
                  'ambiguous' if ambiguous else 'matched' if direct else 'no_match')
        coverage = (layer_coverage(self,chosen,explicit=editions is not None) if layer == 'municipal' else
                    selection_coverage(self.editions, self.edition_coverage, chosen, explicit=editions is not None)
                    if layer != 'administrative' else {})
        municipal_coverage = []
        if layer == 'municipal':
            municipal_coverage, uncertain = lookup_coverage(self,point,chosen,direct,explicit=editions is not None)
            if uncertain: status = 'review_required'
        if layer in {'federal','provincial'} and not direct and any(c['status'] in {'partial', 'unavailable'} for c in coverage.values()):
            status = 'review_required'
        if layer in {'federal','provincial'}:
            matched_editions = {self.areas[uid].get('edition') for uid in direct}
            if any(spec['status'] in {'partial', 'unavailable'} for uid in chosen - matched_editions
                   for spec in self.edition_coverage[uid].values()):
                status = 'review_required'
        order = {'country': 0, 'province': 1, 'region': 2, 'municipality': 3, 'city_area': 4, 'electoral_district': 5}
        return {'dataset_version': self.version, 'qualification': 'review_required', 'status': status,
                'longitude': longitude, 'latitude': latitude, 'ambiguous': ambiguous,
                'matches': [{**self.areas[uid], 'match_basis': 'geometry' if uid in direct else 'hierarchy'}
                            for uid in sorted(related, key=lambda uid: (order[self.areas[uid]['level']], uid))],
                'direct_match_ids': direct, 'review_candidate_ids': pending,
                'unlocated_missing_geometry_ids': unknown,
                'hierarchy_geometry_disagreements': disagreements,
                **({'layer': layer, 'selected_editions': sorted(chosen), 'coverage': coverage} if layer != 'administrative' else {}),
                **({'municipal_coverage': municipal_coverage} if layer == 'municipal' else {})}
