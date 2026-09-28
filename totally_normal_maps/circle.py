"""Municipal discovery over full polygons, with conservative distance bounds.

Edges retain the catalogue's linear longitude/latitude interpolation. Distance
is WGS84 ellipsoidal distance, not Euclidean degrees or projected chords. See
docs/CIRCLE_API.md for the bound, numerical band and completeness contract.
"""
from collections import Counter
from dataclasses import dataclass
import math
from threading import BoundedSemaphore
import time
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from pyproj import Geod
from shapely.geometry import Point, box
from shapely.strtree import STRtree

from .catalogue import CatalogueError

REVISION = 1
TOLERANCE_M = .01
ROUNDING_M = .00001
MAX_RESPONSE_BYTES = 128 * 1024
# Outward bounds on BOTH principal WGS84 radii of curvature at all latitudes.
# M_min = 6335439.327..., M_max = N_max = 6399593.625... metres.
MIN_METRIC_RADIUS = 6_335_000.0
MAX_METRIC_RADIUS = 6_400_000.0
CHUNK = 8192
MAX_EVALUATIONS = 1_000_000
MAX_VERTICES = 5_000_000
MAX_SECONDS = 5.0


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CircleQuery(Model):
    latitude: Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]
    longitude: Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]
    radius_m: Annotated[int, Field(strict=True, ge=1000, le=100000)]
    level: Literal['municipality'] = 'municipality'
    layer: Literal['administrative'] = 'administrative'


class CircleInput(CircleQuery):
    offset: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 100

    def query(self):
        return CircleQuery.model_validate(self.model_dump(exclude={'offset', 'limit'})).model_dump()


class CircleIdentity(Model):
    id: str = Field(min_length=1, max_length=100)
    level: Literal['municipality'] = 'municipality'


class CircleEnvelope(Model):
    dataset_version: str
    representation_revision: Literal[1] = REVISION
    qualification: Literal['review_required'] = 'review_required'
    query: CircleQuery
    match_semantics: Literal['area_intersects_circle'] = 'area_intersects_circle'
    distance_model: Literal['wgs84_ellipsoid'] = 'wgs84_ellipsoid'
    edge_model: Literal['linear_lon_lat'] = 'linear_lon_lat'
    distance_tolerance_m: Literal[.01] = TOLERANCE_M
    coverage_basis: Literal['active_catalogue_municipalities'] = 'active_catalogue_municipalities'


class CircleResult(CircleEnvelope):
    status: Literal['complete'] = 'complete'
    coverage_complete: Literal[True] = True
    offset: int = Field(ge=0, le=100000)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    next_offset: int | None
    items: list[CircleIdentity] = Field(max_length=100)


class CoverageReason(Model):
    code: Literal['municipal_geometry_unavailable', 'municipal_extent_unlocated', 'boundary_disagreement']
    count: int = Field(ge=1)


class CircleIncomplete(CircleEnvelope):
    status: Literal['incomplete'] = 'incomplete'
    coverage_complete: Literal[False] = False
    error: Literal['coverage_incomplete'] = 'coverage_incomplete'
    reasons: list[CoverageReason] = Field(max_length=3)
    affected_count: int
    sample_area_ids: list[str] = Field(max_length=20)
    sample_is_complete: bool
    evidence_url: str = '/v1/datasets/current/coverage?layer=administrative&area_id=ca&include_descendants=true'


class CircleUnavailable(Exception):
    """Fixed, non-sensitive reason codes; never include query coordinates."""

    def __init__(self, code='circle_query_budget_exceeded'):
        self.code = code
        super().__init__(code)


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + MAX_SECONDS
        self.evaluations = 0
        self.vertices = 0

    def check(self, *, evaluations=0, vertices=0):
        self.evaluations += evaluations
        self.vertices += vertices
        if (self.evaluations > MAX_EVALUATIONS or self.vertices > MAX_VERTICES
                or time.monotonic() > self.deadline):
            raise CircleUnavailable()


def circle_envelopes(longitude, latitude, radius):
    """Contain the ellipsoidal ball in a slightly larger spherical cap.

    ds_WGS84 >= MIN_METRIC_RADIUS * ds_unit_sphere, hence every point in the
    ellipsoidal ball is in this cap. Longitude extrema are not four sampled
    compass bearings. A cap meeting either pole spans all longitudes.
    """
    delta = (radius + TOLERANCE_M + ROUNDING_M) / MIN_METRIC_RADIUS
    phi = math.radians(latitude)
    south = max(-90., latitude - math.degrees(delta) - 1e-10)
    north = min(90., latitude + math.degrees(delta) + 1e-10)
    if abs(phi) + delta >= math.pi / 2:
        return [(-180., south, 180., north)]
    width = math.degrees(math.asin(min(1., math.sin(delta) / math.cos(phi)))) + 1e-10
    west, east = longitude - width, longitude + width
    if west < -180:
        return [(-180., south, east, north), (west + 360., south, 180., north)]
    if east > 180:
        return [(west, south, 180., north), (-180., south, east - 360., north)]
    return [(west, south, east, north)]


class CirclePredicate:
    def __init__(self, longitude, latitude, radius, budget):
        self.longitude, self.latitude, self.radius = longitude, latitude, radius
        self.point = Point(longitude, latitude)
        self.envelopes = circle_envelopes(longitude, latitude, radius)
        self.boxes = [box(*bounds) for bounds in self.envelopes]
        self.geod, self.budget = Geod(ellps='WGS84'), budget

    def _edges(self, start, end):
        # This is a complete subdivision with lower/upper bounds on every
        # unvisited interval, not a fixed set of sampled circle/edge points.
        pending = [(start, end)]
        while pending:
            a, b = pending.pop()
            if len(a) > CHUNK:
                pending.extend((a[i:i + CHUNK], b[i:i + CHUNK]) for i in range(0, len(a), CHUNK))
                continue
            self.budget.check(evaluations=len(a))
            midpoint = (a + b) * .5
            _, _, distances = self.geod.inv(np.full(len(a), self.longitude), np.full(len(a), self.latitude),
                                            midpoint[:, 0], midpoint[:, 1])
            distances = np.asarray(distances)
            if not np.all(np.isfinite(distances)):
                raise CircleUnavailable('circle_distance_unavailable')
            # A witness proves that a polygon point lies no farther than the
            # documented 10 mm outward numerical band. No repaired polygon is
            # passed here as assignment geometry.
            if np.any(distances + ROUNDING_M <= self.radius + TOLERANCE_M):
                return True
            delta = np.radians(b - a)
            nearest_equator = np.where(a[:, 1] * b[:, 1] <= 0, 0., np.minimum(abs(a[:, 1]), abs(b[:, 1])))
            cosine = np.cos(np.radians(nearest_equator))
            length_bound = MAX_METRIC_RADIUS * np.hypot(delta[:, 1], cosine * delta[:, 0])
            # Triangle inequality: d(q, any point on interval) >= d(q, mid)
            # minus the maximum length of either half of the coordinate-linear
            # edge. Intervals proved outside the exact radius need no refinement.
            unresolved = distances - ROUNDING_M - length_bound * .5 <= self.radius
            if np.any(unresolved):
                a, b, midpoint = a[unresolved], b[unresolved], midpoint[unresolved]
                if np.any(np.all(midpoint == a, axis=1) | np.all(midpoint == b, axis=1)):
                    raise CircleUnavailable('circle_distance_unavailable')
                pending.append((midpoint, b))
                pending.append((a, midpoint))
        return False

    def intersects(self, polygon):
        self.budget.check()
        if polygon.covers(self.point):
            self.budget.check()
            return True
        for ring in (polygon.exterior, *polygon.interiors):
            self.budget.check(vertices=len(ring.coords))
            coords = np.asarray(ring.coords)[:, :2]
            for i in range(0, len(coords) - 1, CHUNK):
                a, b = coords[i:i + CHUNK], coords[i + 1:i + CHUNK + 1]
                a = a[:len(b)]
                low, high = np.minimum(a, b), np.maximum(a, b)
                relevant = np.zeros(len(a), dtype=bool)
                for west, south, east, north in self.envelopes:
                    relevant |= ((low[:, 0] <= east) & (high[:, 0] >= west)
                                 & (low[:, 1] <= north) & (high[:, 1] >= south))
                if np.any(relevant) and self._edges(a[relevant], b[relevant]):
                    return True
                self.budget.check()
        return False


def polygon_parts(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if geometry.geom_type == 'MultiPolygon':
        return list(geometry.geoms)
    raise CatalogueError('Circle index requires polygonal geometry.')


def repair_envelope(row, candidates):
    """Only lossless linework provenance supports a candidate-derived envelope.

    GEOS linework make-valid preserves input vertices. If polygon extraction
    dropped collapsed components, or the provenance is absent/unrecognized, its
    bbox is NOT an exclusion proof. The whole envelope (including all holes) is
    uncertain; a candidate polygon is never an assignment or coverage mask.
    """
    repair = row.get('repair', {})
    if (repair.get('method') != 'GEOS make_valid linework; polygon components only'
            or repair.get('nonpolygon_vertices') != 0
            or type(repair.get('source_vertices')) is not int or repair['source_vertices'] < 4
            or type(repair.get('candidate_vertices')) is not int
            or repair['candidate_vertices'] < repair['source_vertices'] or not candidates):
        return None
    bounds = [g.bounds for g in candidates]
    extent = (min(b[0] for b in bounds), min(b[1] for b in bounds),
              max(b[2] for b in bounds), max(b[3] for b in bounds))
    if (not all(math.isfinite(n) for n in extent) or not -180 <= extent[0] <= extent[2] <= 180
            or not -90 <= extent[1] <= extent[3] <= 90 or list(extent) != row.get('bbox')):
        return None
    return box(*extent)


@dataclass(frozen=True)
class Component:
    uid: str
    geometry: object
    reason: str | None = None


class CircleIndex:
    def __init__(self, data):
        self.data, self.slots = data, BoundedSemaphore(2)
        current = {uid: row for uid, row in data.areas.items() if row['level'] == 'municipality'
                   and row.get('layer', 'administrative') == 'administrative'
                   and row.get('lifecycle_status') != 'superseded'}
        self.population = len(current)
        self.components, self.uncertain, self.unlocated = [], [], []
        pending = {}
        for uid, geom in zip(data.pending_ids, data.pending_shapes):
            if uid in current:
                pending.setdefault(uid, []).append(geom)
        for uid, row in sorted(current.items()):
            if not 1 <= len(uid) <= 100:
                raise CatalogueError('Unbounded municipal identity.')
            full = data.geometries.get(uid)
            if full is not None:
                self.components.extend(Component(uid, part) for part in polygon_parts(full))
                for review in pending.get(uid, []):
                    # These are retained differences, not missing assignment
                    # shapes. Conservatively report a conflict if reached.
                    self.uncertain.extend(Component(uid, part, 'boundary_disagreement') for part in polygon_parts(review))
            else:
                envelope = repair_envelope(row, pending.get(uid, []))
                if envelope is None:
                    self.unlocated.append(uid)
                else:
                    self.uncertain.append(Component(uid, envelope, 'municipal_geometry_unavailable'))
        self.tree = STRtree([c.geometry for c in self.components])
        self.uncertainty_tree = STRtree([c.geometry for c in self.uncertain])

    @staticmethod
    def candidates(tree, predicate):
        return sorted({int(i) for bounds in predicate.boxes for i in tree.query(bounds)})

    def lookup(self, request):
        if not self.slots.acquire(blocking=False):
            raise CircleUnavailable('circle_query_busy')
        try:
            return self._lookup(request)
        finally:
            self.slots.release()

    def _lookup(self, request):
        predicate = CirclePredicate(request.longitude, request.latitude, request.radius_m, Budget())
        problems = {uid: 'municipal_extent_unlocated' for uid in self.unlocated}
        for i in self.candidates(self.uncertainty_tree, predicate):
            c = self.uncertain[i]
            if c.uid not in problems and predicate.intersects(c.geometry):
                problems[c.uid] = c.reason
        envelope = {'dataset_version': self.data.version, 'query': request.query()}
        if problems:
            counts = Counter(problems.values())
            ids = sorted(problems)
            return CircleIncomplete(**envelope, reasons=[{'code': k, 'count': v} for k, v in sorted(counts.items())],
                affected_count=len(ids), sample_area_ids=ids[:20], sample_is_complete=len(ids) <= 20)
        matches = set()
        for i in self.candidates(self.tree, predicate):
            c = self.components[i]
            if c.uid not in matches and predicate.intersects(c.geometry):
                matches.add(c.uid)
        predicate.budget.check()
        ids = sorted(matches)
        if request.offset > len(ids):
            raise CatalogueError('Circle offset is beyond the complete result.')
        items = ids[request.offset:request.offset + request.limit]
        end = request.offset + len(items)
        return CircleResult(**envelope, offset=request.offset, limit=request.limit, total=len(ids),
            next_offset=end if end < len(ids) else None, items=[{'id': uid} for uid in items])
