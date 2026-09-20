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
| GET | `/` | Combined deployments: redirect to the public map explorer |
| GET/HEAD | `/maps/{website_version}/{asset}` | Combined deployments: allowlisted public display assets |
| GET | `/v1/datasets/current` | Version, source attribution, counts, coverage and limitations |
| GET | `/v1/countries` | Available countries (currently Canada) |
| GET | `/v1/layers` | Geography families, boundary editions and coverage |
| GET | `/v1/areas` | Search/filter all area metadata |
| GET | `/v1/areas/boundaries` | National or scoped display FeatureCollection, filtered by layer/edition |
| GET | `/v1/areas/{id}` | One area |
| GET | `/v1/areas/{id}/children` | Next browsing level |
| GET | `/v1/areas/{id}/ancestors` | Ordered country-to-parent chain |
| GET | `/v1/areas/{id}/boundary` | GeoJSON Feature; `resolution=display` (default) or `full` |
| GET | `/v1/areas/{id}/children/boundaries` | Paginated GeoJSON FeatureCollection, display shapes only |
| GET/POST | `/v1/lookup` | WGS84 coordinate lookup |
| POST | `/v1/lookup/batch` | Up to 100 coordinate lookups, preserving input order |

In a combined deployment, `/readyz` also returns `deployment_version`,
`dataset_manifest_sha256`, `website_manifest_sha256` and `code_sha256` for promotion
and rollback checks. Both ready (200) and not-ready (503) responses send
`Cache-Control: no-store`, including requests using load-balancer IP Host headers.
Website routes are public and versioned by their manifest
SHA-256, with immutable caching. They never serve databases or full assignment
geometry. `/v1/` authentication and dataset-version preconditions are unchanged.
API-only deployments return 404 for the website routes.

Area pages accept `offset` (default 0), `limit` (default 100, maximum 500).
`/v1/areas` additionally accepts `q` (accent-insensitive names/aliases/source IDs),
`level`, `parent_id`, and `include_historical` (default false). Pages return `total`,
`next_offset` and `dataset_version`.
An unknown area or parent is a 404; an existing parent without children has an
empty page. Countries and administrative kinds can be extended in future releases;
the current builder and serving-release schema explicitly support Canada only.

Levels are navigation roles: `country`, `province`, `region`, `municipality`,
`city_area`, `electoral_district`. `kind` and `source_type` retain distinctions such as territory,
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
| New La Pocatière municipality | `ca-qc-mun-14082` |

National municipal source IDs remain strings in `source_id`. API IDs are
namespaced to avoid collisions with future countries and datasets. Do not use
names, translations or a local application's primary keys as service identities.
Region and city-area IDs retain their original catalogue namespaces.

In the Québec refresh, new municipal identities use provincial codes under
`ca-qc-mun-`, without inventing national CSD codes. Six predecessors retain their
original IDs, full boundaries and `lifecycle_status: superseded`, with `valid_to`
(exclusive effective date) and `successor_ids`. New records expose `predecessor_ids`
and `effective_date`. The successor assignment boundary is the complete union of
national predecessor boundaries (`boundary_basis: predecessor_csd_union`); the
current provincial polygon is retained separately as comparison evidence.
Historical records are excluded from default browsing and coordinate lookup.
They remain accessible by ID, or through `/v1/areas?include_historical=true`.
Their boundary responses have `suitable_for_assignment: false`.

Both arrondissements and their quartiers/sectors use `level: city_area`. A nested
area's `parent_id` is its arrondissement; `municipality_id` identifies the containing
city throughout that hierarchy. Follow children and ancestors rather than assuming
every city area is directly below a municipality. Terrebonne's three documented
sector identities have `assignment_status: missing_geometry`; their municipal
bounding box limits lookup uncertainty and is never a sector assignment polygon.

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
- `ambiguous`: multiple incomparable direct matches at the same navigation level.
  A quartier and its own arrondissement are an expected ancestor/descendant pair;
  overlapping siblings or unrelated arrondissements still signal ambiguity.

`status` is `matched`, `no_match`, `ambiguous`, or `review_required`. Uncertainty or
cross-source disagreement takes precedence over the ambiguous status; the boolean
still reports ambiguity. `no_match` means no match in this dataset, not that a
location is outside every possible territory. A missing city-area match never
establishes that no neighbourhood or subdivision exists.

Every response retains `qualification: review_required` where applicable. A
geometrically valid polygon is not a legal-boundary or dataset-quality approval.

## Boundaries and versions

### Parallel electoral layers

The existing browsing and lookup defaults remain administrative. Select
`layer=federal` or `layer=provincial` for electoral browsing. The latter includes
territorial districts. Every district has a province/territory parent; a national
view aggregates those branches without extra identities or parents.

```bash
curl 'http://127.0.0.1:8000/v1/layers'
curl 'http://127.0.0.1:8000/v1/areas?layer=federal&level=electoral_district&within_id=ca'
curl 'http://127.0.0.1:8000/v1/areas/ca-qc/children?layer=provincial'
curl 'http://127.0.0.1:8000/v1/areas/boundaries?layer=federal&within_id=ca-qc'
curl 'http://127.0.0.1:8000/v1/areas?layer=provincial&edition=qc-2017&level=electoral_district'
curl -X POST 'http://127.0.0.1:8000/v1/lookup' \
  -H 'Content-Type: application/json' \
  --data '{"longitude":-75.72,"latitude":45.43,"layers":["administrative","federal","provincial"]}'
```

Area browsing, children and display collections accept repeated `edition` values.
`within_id` selects descendants of an existing country/province or other area;
it is hierarchy membership, not polygon clipping. `parent_id` means immediate
children. `child_count` retains the administrative count, while
`child_counts_by_layer` reports counts under each family's default editions.

An omitted edition selects explicit defaults pinned by the dataset, independent
of the server date. Historical/upcoming editions require their IDs. Administrative
`include_historical` does not select electoral editions. An unknown edition or
one belonging to another layer returns 422. IDs include the boundary-set namespace,
such as `ca-fed-2023-24001`; names are attributes. `identity_basis` distinguishes
official codes, publisher feature IDs and stable catalogue mappings. Inspect
authority, `boundary_set`, electoral event, nullable effective date and source
evidence; a reused district number does not prove legal continuity.

POST lookups accept `layers` and an optional `editions` map, for example
`{"provincial":["qc-2017","qc-2026"]}`. Include that family in `layers`.
Each batch point accepts the same fields. GET uses repeated `layer` and `edition`
parameters. Selecting electoral layers adds a `layers` object with an independent
lookup result for each requested family. The top-level result aggregates IDs and
uses the highest-severity status; consumers should inspect individual results.

Each electoral result's `coverage` describes the selected editions, with entries
for all 13 jurisdictions. Each entry includes `editions`, a single `edition` when
applicable, `expected_count`, `unavailable_count`, `status` and a coverage note.
Historical selections use their own inventories and notes. An explicitly scoped
selection marks other jurisdictions `not_selected`; missing default coverage is
`unavailable` and cannot produce a confident `no_match`. A match in one edition
does not hide a missing match in another selected edition with partial coverage.
The release report retains this inventory in `coverage.electoral.edition_coverage`.
Empty or duplicate layer/edition selections return 422.

One administrative, one federal and one provincial match is expected. Ambiguity
is evaluated within the same layer and edition, including exact shared boundaries.
Comparing editions does not itself cause ambiguity. A pending administrative
repair does not make an otherwise valid electoral result uncertain. Unapproved
electoral repairs remain review candidates, never direct matches, and full-boundary
requests return 409. Coverage and topology limits are in `coverage.electoral`.

### Geometry and release pinning

Display polygons may be simplified or labelled unapproved repair candidates. They
are for rendering only. Full boundaries are unavailable for unapproved repairs,
and province/country full boundaries are not fabricated from display outlines.
Requesting an unavailable representation returns 409. Country/province coordinate
matches come from hierarchy relationships, not the 2021 overview map.

In a release with `coverage.topology_reviews`, the narrowly reviewed La Romaine
repair exposes full geometry for `ca-csd-2498015` and its region `ca-qc-ra-09`.
The municipality has `assignment_status: validated_derived` and
`repair.status: reviewed_topology`, with the original problem and pinned evidence.
Its maritime extent is unchanged and provincial source reconciliation remains
unresolved. Other unapproved candidates still return 409 for full geometry.
See [the evidence and reproduction command](research/cote-nord-topology.md).

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

## Ontario refresh semantics

The Ontario refresh keeps all existing CSD and regional identities. Four accepted
municipal replacements use full publisher geometry, with `boundary_source`,
`boundary_source_ids`, `effective_date`, `previous_boundary_reference_date` and
`comparison` metadata. Original national rows and previous immutable releases remain
available for historical provenance. Every old/new boundary difference is indexed
as uncertainty. A changed municipality can therefore appear in both
`direct_match_ids` and `review_candidate_ids`: the first is its current full boundary,
the second flags source/vintage disagreement at that point. An uncovered old extent
returns review uncertainty rather than a confident absence of geography.

`boundary_difference_review_count` counts available boundaries with these comparison
polygons. `unavailable_geometries` counts unavailable assignment boundaries only.
Seven original municipal repairs and their affected regional candidates remain
unapproved. Updated regional outlines cannot approve an unresolved member repair.

Ontario city areas expose `scheme`. Toronto's `former_municipality` and
`neighbourhood` schemes are independent; both remain children of `ca-csd-3520005`.
Matching one polygon in each scheme is expected and does not alone cause ambiguity.
Same-scheme sibling overlaps still do. Hamilton communities contain neighbourhoods
through explicit publisher parent attributes; follow `children` and `ancestors`.
Ottawa's ONS study areas have neighbourhood scope, not every locally named community.

Examples: `ca-on-3520005-former-01`, `ca-on-3506008-ons-3050`, and
`ca-on-3525005-community-6`. The two Ottawa Greenbelt source polygons have
`assignment_status: unreviewed_repair`: display candidates are available, full boundary
requests return 409, and their bounding boxes flag uncertainty only. Current counts,
coverage measurements and remaining gaps are in `coverage.ontario_refresh`.

## Jurisdiction refreshes and deferred updates

`coverage.jurisdiction_refreshes` is keyed by national province code. Each entry
contains its qualified sources, imported layers, unresolved work, repair review,
adjustments and municipal audit inventory. `audit.inventory_complete` accounts for
all baseline municipal/statistical identities; it does not mean the source audit
is complete. Check `source_audit_complete` and each municipality's `status`.
`pending_municipal_site_review` explicitly identifies unfinished research.

Qualified future jurisdiction plans can also provide `migrations` in their coverage
report. Municipal successors retain full predecessor unions and explicit historical
links; regional membership changes rebuild complete current member unions. A
retired region remains available through `include_historical=true` and by ID,
with `lifecycle_status: superseded`; it is excluded from current lookup. The
migration report's `regional_coverage` supplies the current membership inventory
alongside the retained baseline inventory. Existing city-area identities and source
geometry survive an explicitly evidenced municipal parent change.

Municipal replacement overlap must cover at least 80% of both old and proposed
extents. If any participant fails, the whole adjustment group is deferred.
`deferred_adjustments` and `deferred_municipality_count` describe those groups;
`adjustments` contains applied groups only. Retained municipalities have
`update_status: deferred`, `boundary_basis: retained_previous_boundary`, and both
ratios in `comparison`. The old/new difference still contributes review uncertainty,
including proposed additions outside the retained boundary. Regional unions use
only retained or accepted assignment geometry. Existing immutable releases retain
their original data; the corrected rebuilt Ontario release applies four municipal
replacements and defers five municipalities across two groups.

New city-area states `unreviewed_parent` and `unreviewed_overlap` mean the publisher
polygon is shown for review but has no assignment geometry. Full-boundary requests
return 409. Its bounding box is uncertainty evidence only. These states do not
approve a geometry repair or infer hierarchy from containment. City-area reports
separate repair, parent and overlap review counts, and explicitly identify whether
coverage measurements include unapproved candidates.

### Municipal electoral geography

Releases with municipal electoral data add `layer=municipal` to the existing
area, children, boundary and lookup endpoints. Municipal wards are independent
of administrative neighbourhoods, federal districts and provincial districts.
Their `parent_id` and `authority_id` identify the municipality or regional
browsing authority. `source_id` retains the publisher's district identity;
`authority_name`, `scheme`, `edition` and `source_date` describe its context.

`GET /v1/municipal-coverage?province=24&status=reference&limit=100` provides the
complete, paginated authority inventory. Filters are optional. Statuses are
`included`, `reference`, `partial`, `at_large`, `unverified`, `unavailable` and
`historical_only`. The inventory includes municipal/statistical equivalents;
these are not all incorporated municipalities or ordinary municipal councils.
Absence of ward data is never treated as evidence of at-large representation.

Municipal editions have `current`, `reference`, `historical` or `upcoming`
status. Defaults are chosen independently for each authority and representation
scheme. Reference defaults are available for exploration, but a default lookup
using them returns `review_required`. An explicit edition selects that dated
snapshot without asserting current applicability. `municipal_coverage` in the
municipal lookup result explains the local coverage. An evidenced at-large
municipality has no fabricated ward polygon; its administrative outline remains
available from the administrative layer. Unknown coverage returns
`review_required`, rather than a confident negative.

A point may be queried in all four layers in one request:

```json
{"longitude":-73.57,"latitude":45.50,"layers":["administrative","federal","provincial","municipal"]}
```

Use `/v1/areas?layer=municipal&level=electoral_district&within_id=ca-qc` to list
Québec districts, or a municipality's ID in `parent_id` for its direct wards.
The existing maximum of 30 explicit edition IDs per request still applies;
omitting editions uses all relevant defaults. Districts with invalid source
geometry remain unavailable at `resolution=full`; unapproved display candidates
cannot become coordinate matches. Political boundaries are not clipped to
coastlines or to a different publisher's municipal outline.
