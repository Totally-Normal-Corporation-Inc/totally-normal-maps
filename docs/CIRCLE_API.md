# Municipal circle discovery

`POST /v1/lookup/circle` is an additive, read-only API v1 operation. It finds all
active Canadian catalogue areas at `level: municipality` whose filled assignment
polygon intersects a closed circle. It requires the same server-side bearer key
as point lookup. No summary, catalogue download or boundary download is required
before calling it. Existing point, batch, catalogue and boundary contracts remain
unchanged. This document describes the implementation; deployment is a separate
release action. Check the selected deployment's `/openapi.json` for availability.

## Request and pagination

```http
POST /v1/lookup/circle
Authorization: Bearer <server-held-key>
Content-Type: application/json
If-Match: "<dataset_version>"
If-Circle-Revision: 1
```

```json
{
  "latitude": 45.4,
  "longitude": -75.8,
  "radius_m": 30000,
  "level": "municipality",
  "layer": "administrative",
  "offset": 0,
  "limit": 100
}
```

Latitude and longitude are finite JSON numbers in `[-90,90]` and `[-180,180]`.
`radius_m` is an integer from 1,000 through 100,000 metres, inclusive. Booleans and
numeric strings are rejected. Only the administrative municipality selection is
supported; those two fields default to the values above. There are no edition or
province filters. Extra fields and URL query parameters are rejected with 422.
Keep coordinates in the POST body, out of URLs and logs.

`offset` defaults to 0 and is an integer in `[0,100000]`; `limit` defaults to 100
and is an integer in `[1,100]`. Items are sorted by stable catalogue ID, with no
duplicates, and contain **only** `id` and `level`. A successful page contains
`min(limit, total-offset)` records. `next_offset` is `offset + len(items)` until
the final page, where it is null. An offset equal to total returns an empty final
page; an offset greater than total returns 422. The provider reports the actual
total, including totals above 500. A consumer's 500-municipality/five-page limit
must be an explicit consumer limitation, never a truncated complete result.

The first page can discover the version without `If-Match`. Every continuation
(`offset > 0`) requires the quoted dataset version in `If-Match`; omission returns
428 and a mismatch returns 412. A pin is a precondition on the release currently
served, not a request to load a historical release. Keep the query and limit
unchanged across pages. Changing offset alone is the intended continuation.

`If-Circle-Revision: 1` is an optional calculation precondition. A different value
returns 412, even when the dataset did not change. Consumers should send it on
every page and validate `representation_revision`, query and dataset version on
every response. Changes affecting population, uncertainty or numerical semantics
require a revision increment. Representation revision belongs in consumer cache
keys alongside the exact point, radius, dataset and local publication epoch.

## Successful response

Every 200 response contains:

| Field | Meaning |
|---|---|
| `dataset_version` | Actual immutable dataset manifest SHA-256; also in `X-Maps-Dataset-Version` |
| `representation_revision` | `1` |
| `qualification` | `review_required`; complete discovery does not approve the geography |
| `query` | The five semantic request fields, with defaults applied; coordinates are not rounded |
| `status`, `coverage_complete` | `complete`, `true` |
| `match_semantics` | `area_intersects_circle` |
| `distance_model`, `edge_model` | `wgs84_ellipsoid`, `linear_lon_lat` |
| `distance_tolerance_m` | `0.01`, the outward numerical band described below |
| `coverage_basis` | `active_catalogue_municipalities` |
| `offset`, `limit`, `total`, `next_offset` | Applied pagination and exact complete total |
| `items` | Array such as `[{"id":"ca-csd-2481017","level":"municipality"}]` |

Zero matches is a complete success with `total: 0`, `items: []`, `next_offset:
null`. The centre can be outside Canada; an intersecting Canadian municipality
is still included. City centres, administrative parents and optional city areas
do not determine this result. IDs are the same identities as `/v1/areas`,
including provincial successor IDs rather than only `ca-csd-*` identifiers.

“Municipality” includes the catalogue's statistical municipal equivalents and
unorganized territories. “Active” excludes `lifecycle_status: superseded`.
“Current” means current in the selected immutable catalogue, not an independent
certification that all legal changes have been incorporated. Source vintage and
other dataset qualifications still apply. The operation establishes completeness
against this population, not against every possible real-world settlement.

## Distance and intersection

The circle is defined by shortest WGS84 ellipsoidal distance from the input
point. The filled polygon includes its exterior and hole boundaries, excludes
hole interiors, and includes every component of multipart geometry. Tangency,
partial overlap, a municipality containing the whole circle, and a municipality
wholly inside the circle all count. Display simplification never participates.

Stored full-geometry edges retain linear interpolation in longitude/latitude,
as specified by [RFC 7946 section 3.1.1](https://www.rfc-editor.org/rfc/rfc7946#section-3.1.1).
Reinterpreting them as geodesic arcs would change the published assignment
geometry, particularly along long northern parallels. Point-to-point distances
use [PROJ's WGS84 geodesic calculation](https://proj.org/en/stable/geodesic.html)
through `pyproj.Geod`, with conservative refinement along the stored edges.

The numerical contract is conservative: a completed query includes every area
whose true distance is at most the requested radius. It can also include an area
up to **one centimetre outside** the radius to resolve floating-point tangency.
An area farther than this band cannot be included. Inclusion inside the outward
band is not a promise to expand every circle by exactly one centimetre. This is
a computational tolerance, not a claim of centimetre source accuracy.

The implementation avoids a sampled circle or a projected polygon buffer:

1. WGS84's meridional and prime-vertical curvature radii are bounded outward by
   6,335,000 and 6,400,000 metres. Consequently an ellipsoidal ball lies inside a
   spherical cap of angular radius `(radius + numerical margin) / 6335000`.
   The cap's analytical latitude/longitude extrema provide STRtree candidates,
   splitting at the antimeridian and spanning all longitudes at a pole.
2. Full-polygon containment proves a match immediately. Otherwise, each exterior
   and interior edge whose envelope reaches the cap is refined by midpoint
   subdivision. The midpoint's ellipsoidal distance is a possible witness.
3. An edge interval's coordinate-linear path length is bounded above by
   `6400000 * hypot(delta_lat, max_cos_lat * delta_lon)`, with angles in radians.
   By the triangle inequality, midpoint distance minus half that length is a
   lower bound for the entire interval. A 0.00001 m rounding margin is applied
   outward. Only intervals proved outside the exact circle are discarded.
4. Every remaining interval is subdivided until proved outside or a witness
   lies within the numerical band. Exhausting the work budget returns 503;
   unfinished refinement cannot become a complete answer.

Thus bounding boxes restrict work, while actual geometry and bounded geodesic
distance decide the result. Holes, poles and antimeridian splits use the same
predicate. The ordinary tests use independent tangency fixtures and long edges
whose closest point is neither a vertex nor the initial midpoint.

## Incomplete coverage and failures

Relevant missing or disputed municipal geometry produces **HTTP 409** with the
same version, revision, qualification, query and distance fields, plus:

```json
{
  "status": "incomplete",
  "coverage_complete": false,
  "error": "coverage_incomplete",
  "reasons": [{"code": "municipal_geometry_unavailable", "count": 1}],
  "affected_count": 1,
  "sample_area_ids": ["ca-csd-2423027"],
  "sample_is_complete": true,
  "evidence_url": "/v1/datasets/current/coverage?layer=administrative&area_id=ca&include_descendants=true"
}
```

This fragment illustrates the failure-specific fields, not the full envelope.
There is **no `items` or `total`** in a 409 response. At most 20 affected IDs and
three aggregate reason codes are returned, so growing evidence stays bounded.
The sample is explicitly marked when incomplete. Detailed evidence remains behind
the existing scoped, paginated resource, using the same version precondition.

The uncertainty rules are deliberately conservative:

- `municipal_geometry_unavailable`: use the whole source extent, including holes,
  to decide whether missing assignment geometry could matter. A repaired polygon
  is never used for assignment or as a coverage mask. A candidate-derived extent
  is accepted only with the existing lossless GEOS linework repair ledger: input
  vertices retained, no discarded nonpolygon coordinates, consistent counts and
  candidate bounds. [GEOS documents vertex preservation](https://libgeos.org/doxygen/classgeos_1_1operation_1_1valid_1_1MakeValid.html);
  [Shapely documents collapsed components](https://shapely.readthedocs.io/en/stable/reference/shapely.make_valid.html).
- `municipal_extent_unlocated`: absent, lossy or unrecognized extent provenance
  cannot exclude any circle. Such an area makes every query incomplete until
  qualified extent evidence exists, even for a distant circle. A guessed bbox
  is not proof of complete emptiness.
- `boundary_disagreement`: a circle reaching retained municipal boundary-difference
  evidence returns 409. This is conservative even if both boundary versions would
  include the same municipality. The discovery operation does not approve a
  disputed extent.

Missing optional neighbourhoods, unrelated regional/electoral gaps and the global
`review_required` label do not block a complete municipal result.

| HTTP status | Meaning |
|---|---|
| 401 | Missing or invalid bearer credential |
| 409 | Municipal coverage cannot be established for this query |
| 412 | Dataset or calculation revision precondition differs |
| 413 | Request body exceeds the service's 128 KiB bound |
| 422 | Invalid coordinate, radius, scope or pagination |
| 428 | Continuation omitted `If-Match` |
| 429 | Shared per-client request limit reached; respect `Retry-After` |
| 503 | Index unavailable, concurrency/work budget exhausted, or response cannot fit |

Every successful page and coverage failure is limited to **128 KiB decoded JSON**.
Pages are never shortened to fit. Circle responses use `Cache-Control: no-store`,
no ETag and no 304; authentication and existing service limits still apply.
The provider keeps no coordinate/result cache and logs no request bodies.
Temporary computational failures return fixed reason codes, not locations.

The immutable spatial index is built once at startup; its failure leaves existing
lookup routes operational and circle discovery returns 503. A process permits
two simultaneous circle computations, with a five-second cooperative deadline,
one million distance evaluations and five million visited edge vertices per
query. Saturation/budget failures return 503 with `Retry-After: 5`. This supplements
the common request quota; it does not create a separate 60-request consumer quota
or a distributed rate limiter. No new database service or dependency is needed.

## Verification and release

Ordinary tests use synthetic geometry without external downloads:

```bash
.venv/bin/python -m unittest tests.test_circle tests.test_circle_checker -q
```

Run explicit real-data acceptance against an already verified local release:

```bash
.venv/bin/python tools/check_circle_data.py \
  --dataset .local/releases/canada-municipal-licensed-20260920 \
  --manifest-sha256 "$(.venv/bin/python -c 'import json; print(json.load(open("dataset.lock.json"))["manifest_sha256"])')" \
  --source-archive .local/canada-legacy/run-2025-final/source.zip
```

The optional source archive audit verifies its pinned checksum, each original
geometry hash and all original transformed vertices against every missing
municipal extent. It does not download, repair, approve or rewrite anything.
Adjust the local paths for the selected release; do not substitute another ZIP.

On 2026-09-28, the dataset pinned in `dataset.lock.json` at implementation time
(manifest prefix `44bc84d77060`) contained 5,050 active municipal identities and
57 missing assignment geometries. All 57 conservative extents were independently
verified against **406,569 original source vertices**; none were unlocated. No
source data, repair approval, release checksum or licensing selection changed.
The extra circle index built in about 0.16 s after the existing dataset loaded.

| Public sample | Radius | Result | Decoded bytes | Local query time |
|---|---:|---|---:|---:|
| Gatineau `(45.4,-75.8)` | 30 km | Complete, 8 municipalities | 927 | 0.013 s |
| Montréal `(45.5019,-73.5674)` | 30 km | Complete, 75 | 4,083 | 0.061 s |
| Toronto `(43.6532,-79.3832)` | 30 km | Complete, 9 | 980 | 0.025 s |
| Iqaluit `(63.7467,-68.517)` | 100 km | Complete, 2 | 651 | 0.005 s |
| US border `(44.95,-73.45)` | 30 km | Complete, 23 | 1,635 | 0.019 s |
| Outside `(0,0)` | 30 km | Complete, empty | 549 | <0.001 s |
| Québec City `(46.8139,-71.208)` | 30 km | Incomplete, missing geometry | 777 | 0.001 s |
| Vancouver `(49.2827,-123.1207)` | 30 km | Incomplete, missing geometry | 779 | 0.001 s |
| Gatineau `(45.4,-75.8)` | 100 km | Incomplete, boundary disagreement | 781 | 0.001 s |

These are local, release-specific observations, not production latency promises.
After a separately authorized [application release](RELEASING.md), run the HTTP
acceptance command with `MAPS_ACCEPTANCE_TOKEN` already set in a server-held
environment. Never paste a key into a command or browser:

```bash
.venv/bin/python tools/check_circle_api.py --url https://maps.totallynormal.io
```

It uses public Gatineau and outside-coverage points, pins every continuation,
checks complete ID ordering/totals, decoded size, auth, version/revision 412 and
missing-pin 428. It refuses redirects and prints only versions, counts, byte sizes
and check names. A 409, unavailable endpoint, exhausted acceptance request budget
or outage fails acceptance; none is treated as an empty success. Supply
`--expected-version` to pin the first request too. The public sample must exercise
more than one page; if coverage changes, review the fixture explicitly.

Gati integration differences from the proposed handoff are `area_intersects_circle`,
409 incomplete coverage, explicit qualification/distance/population fields,
required version pinning on continuations, and optional `If-Circle-Revision`.
Refresh Gati's separately imported catalogue to the served dataset, validate its
local IDs, and test GPS/postcode discovery in development before enabling it.
Its manual selection and existing lookup paths remain independent fallbacks.
Source attribution stays available through scoped source/evidence resources and
[NOTICE.md](../NOTICE.md); agree map display credits before a frontend release.
