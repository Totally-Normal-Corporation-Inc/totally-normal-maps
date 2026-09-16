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
            if tables - {'csd', 'region', 'csd_region', 'city_area'} or 'csd' not in tables:
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
                              f"ca-csd-{source['parent_csd_id']}" if table == 'city_area' else province_id)
                    item = {'id': uid, 'source_id': record.get('source_id', source['id']), 'name': record['name'],
                            'level': level, 'kind': record.get('kind', 'municipality_or_equivalent'),
                            'source_type': record.get('type'), 'parent_id': parent, 'province_id': province_id,
                            'assignment_status': record['assignment_status'], 'aliases': record.get('aliases', []),
                            'issues': record.get('issues', []), 'bbox': record.get('bbox')}
                    for key in ('parent_overlap', 'relationship_basis'):
                        if key in record:
                            item[key] = record[key]
                    self.add(item)
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
        counts = Counter(r['level'] for r in self.areas.values())
        for level, expected in [('municipality', self.report['feature_count']),
                                ('region', self.report.get('regions', {}).get('feature_count', 0)),
                                ('city_area', self.report.get('city_areas', {}).get('feature_count', 0))]:
            if counts[level] != expected:
                raise CatalogueError('Serving layer count differs from the report.')
        for uid, item in self.areas.items():
            parent = item['parent_id']
            if parent is not None:
                if parent not in self.areas or parent == uid:
                    raise CatalogueError('Missing or invalid area parent.')
                self.children[parent].append(uid)
            item['geometry_available'] = uid in self.geometries
        for uid in self.areas:
            self.ancestors(uid)  # also rejects cycles before accepting traffic
            self.areas[uid]['child_count'] = len(self.children[uid])
        for children in self.children.values():
            children.sort(key=lambda uid: (normalize(self.areas[uid]['name']), uid))
        self.ordered = sorted(self.areas, key=lambda uid: (normalize(self.areas[uid]['name']), uid))
        self.search_text = {uid: normalize(' '.join([r['name'], uid, r['source_id'], r.get('code', ''), *r['aliases']]))
                            for uid, r in self.areas.items()}
        self.load_displays()
        self.geometry_ids = sorted(self.geometries)
        self.tree = STRtree([self.geometries[uid] for uid in self.geometry_ids])
        self.pending_tree = STRtree(self.pending_shapes)
        self.summary = {'dataset_version': self.version, 'label': self.manifest['label'],
                        'country': 'CA', 'qualification': 'review_required', 'counts': dict(counts),
                        'assignment_geometries': len(self.geometries), 'unavailable_geometries': len(self.pending_ids) + len(self.unknown_ids),
                        'sources': [self.report['source']], 'coverage': {},
                        'limitations': ['Geographic qualification remains incomplete.',
                            'Unapproved repair candidates never contribute direct matches.',
                            'Province and country matches are inferred through the hierarchy.',
                            'Missing city areas do not imply that a city has no subdivisions.']}
        if 'province_display_source' in self.report:
            self.summary['sources'].append(self.report['province_display_source'])
        if 'regions' in self.report:
            self.summary['sources'].extend(self.report['regions']['sources'])
            self.summary['coverage']['regions'] = self.report['regions']['jurisdictions']
        if 'city_areas' in self.report:
            self.summary['sources'].extend(self.report['city_areas']['sources'].values())
            self.summary['coverage']['city_areas'] = self.report['city_areas']['municipalities']
        self.summary['sources'] = [source_metadata(source) for source in self.summary['sources']]

    def add(self, item):
        if item['id'] in self.areas:
            raise CatalogueError('Duplicate area identity.')
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
                     else 'city_area' if '/city-areas-' in name else 'municipality')
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

    def page(self, *, parent_id=None, level=None, query=None, offset=0, limit=100):
        if parent_id is not None and parent_id not in self.areas:
            raise KeyError(parent_id)
        selected = self.children[parent_id] if parent_id is not None else self.ordered
        term = normalize(query or '')
        selected = [uid for uid in selected if (level is None or self.areas[uid]['level'] == level)
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
                'suitable_for_assignment': resolution == 'full', 'geography_qualified': False},
                'geometry': geometry, 'dataset_version': self.version, 'sources': self.summary['sources']}

    def lookup(self, longitude, latitude):
        if (type(longitude) not in (float, int) or type(latitude) not in (float, int)
                or not math.isfinite(longitude) or not math.isfinite(latitude)
                or abs(longitude) > 180 or abs(latitude) > 90):
            raise CatalogueError('Expected finite WGS84 longitude/latitude in range.')
        point = Point(longitude, latitude)
        direct = sorted(self.geometry_ids[int(i)] for i in self.tree.query(point, predicate='covered_by'))
        pending = sorted(self.pending_ids[int(i)] for i in self.pending_tree.query(point, predicate='covered_by'))
        related, disagreements = set(direct), []
        for uid in direct:
            for ancestor in self.ancestors(uid):
                related.add(ancestor['id'])
                if ancestor['id'] in self.geometries and ancestor['id'] not in direct:
                    disagreements.append({'area_id': uid, 'ancestor_id': ancestor['id']})
        counts = Counter(self.areas[uid]['level'] for uid in direct)
        ambiguous = any(n > 1 for n in counts.values())
        status = ('review_required' if pending or self.unknown_ids or disagreements else
                  'ambiguous' if ambiguous else 'matched' if direct else 'no_match')
        order = {'country': 0, 'province': 1, 'region': 2, 'municipality': 3, 'city_area': 4}
        return {'dataset_version': self.version, 'qualification': 'review_required', 'status': status,
                'longitude': longitude, 'latitude': latitude, 'ambiguous': ambiguous,
                'matches': [{**self.areas[uid], 'match_basis': 'geometry' if uid in direct else 'hierarchy'}
                            for uid in sorted(related, key=lambda uid: (order[self.areas[uid]['level']], uid))],
                'direct_match_ids': direct, 'review_candidate_ids': pending,
                'unlocated_missing_geometry_ids': self.unknown_ids,
                'hierarchy_geometry_disagreements': disagreements}
