# HTTP API v1

The API is read-only and serves one immutable dataset per process. In production,
all geography endpoints require an API key, sent as `Authorization: Bearer <key>`.
Local development permits anonymous loopback requests only when no keys are
configured. `/healthz`, `/readyz`, `/docs` and
`/openapi.json` are public; none expose credentials or operator configuration.

Keys are issued manually per consuming application. Missing or invalid keys return
401 with `WWW-Authenticate: Bearer`. Send keys only in the Authorization header over
HTTPS, never in a URL or public browser code. The public map explorer reads separate
display files and does not need an API key. There are no subscriptions or billing.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Process liveness |
| GET | `/readyz` | Ready only after verified data and spatial indexes load |
| GET | `/v1/datasets/current` | Version, source attribution, counts, coverage and limitations |
| GET | `/v1/countries` | Available countries (currently Canada) |
| GET | `/v1/areas` | Search/filter all area metadata |
| GET | `/v1/areas/{id}` | One area |
| GET | `/v1/areas/{id}/children` | Next browsing level |
| GET | `/v1/areas/{id}/ancestors` | Ordered country-to-parent chain |
| GET | `/v1/areas/{id}/boundary` | GeoJSON Feature; `resolution=display` (default) or `full` |
| GET | `/v1/areas/{id}/children/boundaries` | Paginated GeoJSON FeatureCollection, display shapes only |
| GET/POST | `/v1/lookup` | WGS84 coordinate lookup |
| POST | `/v1/lookup/batch` | Up to 100 coordinate lookups, preserving input order |

Area pages accept `offset` (default 0), `limit` (default 100, maximum 500).
`/v1/areas` additionally accepts `q` (accent-insensitive names/aliases/source IDs),
`level`, and `parent_id`. Pages return `total`, `next_offset` and `dataset_version`.
An unknown area or parent is a 404; an existing parent without children has an
empty page. Countries and administrative kinds can be extended in future releases;
the current builder and serving-release schema explicitly support Canada only.

Levels are navigation roles: `country`, `province`, `region`, `municipality`,
`city_area`. `kind` and `source_type` retain distinctions such as territory,
statistical municipal equivalent, regional district, arrondissement or sector.

## Identity and hierarchy

| Example | ID |
|---|---|
| Canada | `ca` |
| Québec | `ca-qc` |
| Outaouais | `ca-qc-ra-07` |
| Interlake | `ca-mb-gr-interlake` |
| Gatineau municipality | `ca-csd-2481017` |
| Gatineau sector | `ca-qc-2481017-sector-15` |

National municipal source IDs remain strings in `source_id`. API IDs are
namespaced to avoid collisions with future countries and datasets. Do not use
names, translations or a local application's primary keys as service identities.
Region and city-area IDs retain their original catalogue namespaces.

The hierarchy skips missing regions. Ontario's ungrouped municipalities, including
Toronto and Ottawa, remain directly under Ontario alongside its regions. Québec's
Montréal region and City of Montréal remain separate identities. A geographic
parent does not establish governmental jurisdiction or Indigenous governance.

Named regional additions include `coverage_policy`, `coverage_note`,
`boundary_basis` and an `evidence` array (publisher, URL, claim and review date).
These fields are also included in boundary properties and lookup matches.
`whole_divisions` describes membership built from the listed complete census
divisions; it does not certify an official regional boundary. `selected_members`
means the outline is only the union of explicitly selected community polygons.
It must not be treated as an exhaustive regional geofence. For example, the
North Slave group includes Łutselk’e but does not assign unorganized land nearby.

Dataset regional coverage lists every `excluded_csd_id` in `excluded_csd_ids`,
along with wholly excluded `excluded_cd_ids` and `partially_assigned_cd_ids`.
The `included`/`partial`/`deferred` jurisdiction status concerns membership coverage,
not geometric approval. The regional level is deliberately absent in Saskatchewan.
See [regional evidence and limits](research/regional-expansion.md).

## Lookups

```bash
curl -X POST 'http://127.0.0.1:8000/v1/lookup' \
  -H 'Content-Type: application/json' \
  --data '{"longitude":-75.72,"latitude":45.43}'

curl -X POST 'http://127.0.0.1:8000/v1/lookup/batch' \
  -H 'Content-Type: application/json' \
  --data '{"points":[{"longitude":-75.72,"latitude":45.43},{"longitude":-73.57,"latitude":45.50}]}'
```

For a hosted service add `Authorization: Bearer <your-client-token>` over HTTPS.
Prefer POST for coordinates that should not appear in browser history or proxy
query-string logs. The bundled server disables access logging and never logs
request bodies. Configure the same policy at your gateway/load balancer.

Matching uses full-resolution geometry with `covers`: exact shared boundaries can
match more than one area. The response includes:

- `matches`: all direct areas and their ancestors; each has `match_basis` equal
  to `geometry` or `hierarchy`.
- `direct_match_ids`: only full, validated source/derived polygons.
- `review_candidate_ids`: unapproved candidates intersecting the point, or a
  conservative bounding box where that is the only available uncertainty evidence.
  These IDs are never silently promoted to direct matches.
- `unlocated_missing_geometry_ids`: missing polygons with no spatial evidence;
  their existence prevents a confident negative classification anywhere.
- `hierarchy_geometry_disagreements`: a child source covers the point while an
  available parent polygon does not. Original source boundaries remain intact.
- `ambiguous`: multiple direct matches at the same navigation level.

`status` is `matched`, `no_match`, `ambiguous`, or `review_required`. Uncertainty or
cross-source disagreement takes precedence over the ambiguous status; the boolean
still reports ambiguity. `no_match` means no match in this dataset, not that a
location is outside every possible territory. A missing city-area match never
establishes that no neighbourhood or subdivision exists.

Every response retains `qualification: review_required` where applicable. A
geometrically valid polygon is not a legal-boundary or dataset-quality approval.

## Boundaries and versions

Display polygons may be simplified or labelled unapproved repair candidates. They
are for rendering only. Full boundaries are unavailable for unapproved repairs,
and province/country full boundaries are not fabricated from display outlines.
Requesting an unavailable representation returns 409. Country/province coordinate
matches come from hierarchy relationships, not the 2021 overview map.

The manifest's SHA-256 is `dataset_version`, also returned in
`X-Maps-Dataset-Version`. To prevent mixing releases during an update, send:

```text
If-Match: "<dataset_version>"
```

A different release produces 412. Consumers that need an old release should route
to an explicitly retained old deployment; the API does not silently switch datasets
per request. API `/v1` and dataset versions have independent lifecycles.

Boundary responses include content-derived ETags and support `If-None-Match`/304.
Default responses are `Cache-Control: no-store` to avoid shared-cache leakage for
authenticated deployments. A private deployment can separately publish licensed,
immutable display files through a CDN with its chosen access/cache policy.

Dataset metadata and boundary Features include `sources` with attribution,
licence links and modification notices. Preserve these when redistributing data
or building map displays. Source-data licences remain separate from the MIT code licence.

## Bounds and failure behaviour

- Finite WGS84 longitude −180…180, latitude −90…90. POST rejects booleans and strings.
- Maximum request body 128 KiB; maximum batch 100 points; query string 2 KiB.
- Maximum boundary response 16 MiB; use smaller pages or display geometry.
- Default 120 requests/minute per client per process; HTTP 429 with `Retry-After`.
- Configured Uvicorn concurrency limit returns 503 when overloaded.
- Dataset corruption prevents startup. Unexpected failures return a generic 500
  and are logged once server-side with traceback, without request bodies.
- No upload, arbitrary URL fetch, raw file download, SQL or data-mutation endpoints.

Treat 401/403/404/409/412/422 as conditions to handle, not infinite retries. Retry
429/503 with a bounded delay. Store consumer memberships locally, preserve manual
overrides, and queue new classifications during an outage.
