# Prepared display packages

Maps prepares administrative display bundles offline. Opening a municipality returns
its preferred agglomeration bundle and that municipality's viewport. Opening another
municipality in the same bundle returns the same geometry hash and download path.
The descriptor changes with the requested focus; the geometry does not.

See [local acceptance evidence](DISPLAY_PACKAGE_ACCEPTANCE.md) for measured
coverage, build/storage costs, timings and outstanding grouping limitations.

These are delivery groupings, not new administrative identities, legal metropolitan
boundaries, merged polygons or point-assignment regions. Existing area, boundary,
lookup and circle contracts remain unchanged. The public map UI is unchanged.

## Group membership and scope

The checked-in `display-groups-2021.json` contains 41 Census Metropolitan Area and
111 Census Agglomeration definitions, extracted from Statistics Canada's
[Statistical Area Classification](https://www.statcan.gc.ca/en/subjects/standard/sgc/2021/sac-additionalinfo).
The two source pages and their SHA-256 pins are recorded in the plan. This dated
membership is applied to exact active Maps municipality identities, using their
current published display polygons. It is not a claim that 2021 metropolitan
membership has been reconciled with every subsequent municipal change.

An explicit identity update preserves Notre-Dame-de-la-Salette in the
Ottawa–Gatineau bundle: `ca-csd-2482010` becomes `ca-csd-2480087` under Statistics
Canada [transaction 240018](https://www150.statcan.gc.ca/n1/pub/92f0009x/2022001/tbl/tbl01-eng.htm),
a code change effective 2021-12-22. This does not alter the catalogue or geometry.
No name matching or geographical overlap is used to infer replacements.

Membership includes all administrative descendants of every member municipality,
including variable-depth city areas. A group may span provinces. Each municipality
has at most one preferred agglomeration. Actual administrative parents remain
unchanged, even where a municipal root's parent is outside the bundle. Non-root
members must have their complete ancestry to a scope root present. Retired entries
and electoral layers are excluded.

Every active municipality and region also has an independently prepared catalogue
scope. Municipalities outside an adopted group use their municipality scope;
regions use their actual region subtree. Unknown group members make that entire
group unsupported, with `membership_unresolved` evidence in `packages/index.json`.
Existing members then use their prepared municipal scopes, explicitly labelled
`selection.reason: preferred_group_unavailable`. This is not silently presented as
a complete agglomeration. Oversized preferred groups return 409; they are not
silently replaced, clipped or truncated.

Montréal, Laval and Longueuil select `ca-sac-2021-462`. Ottawa and Gatineau select
`ca-sac-2021-505`. Requesting the Montréal administrative region still selects that
region's subtree; it is distinct from requesting Montréal municipality.

Neither membership nor bundle eligibility depends on population or popularity.
Warming popular bundle hashes is a consumer policy. The top-100 acceptance list
uses available comparable 2021 municipal population records, not metro population.
Without query-frequency evidence, this implementation does not claim 90% of queries.

To reproduce the membership plan from saved, checksum-matching reference HTML:

```bash
.venv/bin/python -m tools.prepare_display_groups \
  --cma-html /path/to/cma-structure.html --ca-html /path/to/ca-structure.html \
  --output .local/reproduced-display-groups.json
```

This command is offline. Ordinary builds and tests never fetch those pages.
Changing definitions requires a reviewed plan and a newly prepared release.

## HTTP contract

| Method | Route | Representation |
|---|---|---|
| GET/HEAD | `/v1/areas/{area_id}/display-package?layer=administrative` | Current focus-specific descriptor |
| GET/HEAD | `/v1/display-packages/{geometry_sha256}.geojson` | Prepared identity or gzip artifact |

Both routes use existing bearer authentication and per-consumer request limits.
The established tokenless loopback-only development exception remains. Production
requires bearer tokens. Neither endpoint initiates preparation or source requests.
Only active municipality/region roots and `layer=administrative` are supported.
Unknown parameters, repeated singleton parameters, editions and other formats are
422. Artifact routes accept no query parameters or byte ranges. Responses never
redirect to an external artifact host.

`If-Match: "<dataset_version>"` pins the dataset, not the representation ETag.
Authentication and throttling run first. The dataset pin is evaluated before any
ETag shortcut, including when an artifact's bytes are identical across releases.
An old pin returns 412. Clients should pin both descriptor and artifact requests.

Both representations support `If-None-Match`, weak comparison, lists and `*`.
GET and HEAD share ETag, content type, encoded Content-Length and cache headers;
HEAD has no body. A 304 has no representation body or Content-Length.
Descriptors use a strong hash of their actual serialized bytes. Artifacts use
strong hashes of the selected identity/gzip file; the two ETags differ. The
`geometry.sha256` always covers decoded canonical GeoJSON, independently of HTTP
encoding and ETags. Gzip is precomputed, with fixed timestamp and empty filename.

All successful package responses and 304s use `Cache-Control: private, no-store`.
Descriptors vary on `Authorization`; artifacts on `Authorization, Accept-Encoding`.
No shared HTTP cache may retain bearer responses. Separately, an authorized
consumer may ingest and retain verified reference artifacts server-side with
required notices and credential isolation. Reuse a retained hash only after the
current descriptor and current consumer catalogue selection validate. Retaining
an artifact does not permit silently serving obsolete membership after an update.

## Descriptor revision 1

`contract` is `area-display-package.v1`; `representation_revision` is 1.
The generated OpenAPI schema gives the typed JSON structure.

| Field | Meaning |
|---|---|
| `dataset_version` | Loaded immutable manifest SHA-256 |
| `requested_area_id`, `root_id`, `root_level`, `layer` | Exact requested focus; both ID fields agree |
| `bundle_id`, `bundle_kind` | Shared delivery identity; agglomeration, municipality or region |
| `scope_root_ids` | Actual roots of the inventory forest |
| `grouping` | Dated membership basis, sources and explicit identity updates; null for catalogue scopes |
| `selection` | Chosen bundle and reason; preferred-group exceptions are explicit |
| `status` | `ready` with geometry, or `unavailable` when no known member has a display |
| `unavailable_reason` | Null for ready; `no_display_geometry` for unavailable |
| `inventory_complete` | True: all current catalogue members of this scope are accounted for |
| `coverage` | `complete`, `partial`, or `none` relative to those known members |
| `qualification` | `review_required`, independent of readiness |
| `counts` | Exact areas, available and unavailable; available + unavailable = areas |
| `viewport_bbox`, `viewport_basis` | Requested root's display bounds (`root_display`), otherwise available bundle bounds (`available_features`), or null |
| `bundle_bbox` | Extent of available features, not a coverage polygon |
| `areas` | Stable-ID-sorted complete metadata inventory |
| `geometry` | Artifact contract, decoded SHA-256, relative path, sizes and counts, or null |
| `sources`, `common_source_ids`, `attribution` | Deduplicated provenance and required notices |
| `source_mapping_complete` | False when unmapped source context must be retained |

`selection.reason` is `catalogue_scope`, `preferred_agglomeration` or
`preferred_group_unavailable`. The last includes `preferred_bundle_id` and
`preferred_unavailable_reason: membership_unresolved`. A ready agglomeration also
records its preferred ID and a null preferred-unavailable reason.

Each area retains `id`, actual `parent_id`, `level`, `municipality_id`,
`display_status: available|unavailable`, and `unavailable_reason: missing_geometry`
when unavailable. `assignment_status`, `provider_display_status` and `issues`
preserve provider vocabulary and repair warnings. `suitable_for_assignment` is
always false; qualification remains review-required. `evidence` links to the
existing version-pinned area evidence resource and retains available scheme,
coverage-policy, boundary-basis and uncertainty-basis fields. Detailed repair and
source investigations are linked rather than repeated for every polygon.

An area's source references are **the union of `common_source_ids` and its own
`source_ids`**. Every ID resolves in `sources`. Unscoped notices are conservatively
retained with `scope_basis: unscoped_context`, rather than asserted to be locally
mapped. Source entries retain required attribution, licence links, modification
notices and publication disclaimers, with links for further evidence. Keep the
current descriptor and these notices alongside retained geometry.

Known missing geometry produces an honest partial or unavailable descriptor.
Unexpected missing display files, malformed shapes, identity conflicts, failed
builds and runtime errors never become known gaps. Complete display coverage does
not establish complete real-world neighbourhood coverage or geographic approval.

## Geometry revision 1

The decoded object has `contract: area-display-geometry.v1`,
`purpose: display_only`, `type: FeatureCollection`, `bundle_id`, `bbox`, and
`features`. Each Feature has `type`, stable string `id`, `bbox`, empty `properties`,
and Polygon/MultiPolygon geometry. Feature IDs exactly equal available inventory
IDs, in stable lexical ID order. There are no labels, population, language,
dataset hash, timestamps, source URLs or consumer IDs in this file.

Coordinates are finite two-dimensional WGS84 longitude/latitude pairs. Rings are
closed; holes and multipolygons are retained from the published display data.
Every coordinate pair counts as one vertex, including each closing coordinate.
JSON uses UTF-8, sorted object keys, compact separators and rejects nonfinite
numbers. The provider serializes loaded display coordinates without additional
rounding or simplification.

The geometry descriptor includes `sha256`, relative `path`,
`media_type: application/geo+json`, `decoded_bytes`, `feature_count`, `vertex_count`,
and exact `encodings.identity.bytes` and `encodings.gzip.bytes`. A changed available
feature membership, shape, bundle identity or format changes artifact identity.
Names, population, unrelated geography and hierarchy-only changes do not. Adding
only an unavailable member changes the descriptor, not otherwise identical geometry.

## Bounds and errors

| Budget | Maximum |
|---|---:|
| Scope members, including gaps | 500 |
| Child levels below each scope root | 10 |
| Decoded geometry | 4 MiB |
| Compressed transfer | 4 MiB + 4 KiB (gzip overhead allowance) |
| Vertices per artifact / feature | 200,000 / 50,000 |
| Decoded descriptor | 256 KiB |
| Package support index | 8 MiB |
| Serialized descriptor cache per worker | 128 MiB |

The existing generic boundary/metadata limits do not increase. A consumer needs a
separate bounded reader for package artifacts; changing the provider alone does
not expand an existing consumer's 2 MiB reader.

| Status | Package meaning/code |
|---|---|
| 200 | Valid descriptor (including partial/none), or complete verified artifact |
| 304 | Authorized representation unchanged after dataset preconditions |
| 401 / 403 | Existing authentication/access rejection; 403 may be imposed by ingress |
| 404 | `unknown_area` or `unknown_artifact` |
| 406 | `encoding_not_acceptable` (identity and gzip both refused) |
| 409 | `package_not_built` or `scope_too_large` |
| 412 | Existing dataset If-Match mismatch |
| 422 | `unsupported_root`, `unsupported_parameter`, `invalid_accept_encoding`, `range_not_supported`, or existing parameter validation |
| 429 | Existing quota, with Retry-After |
| 503 | `artifact_unavailable` or unloaded dataset |

Package-specific errors use `{"error":"<code>","code":"<code>"}`. Existing
validation, authentication and dataset-precondition envelopes remain unchanged.
There is no 202/polling state. A hash URL serves only a listed, verified file in
the currently loaded release; no path search or dynamic fetch occurs. Runtime
file identity/size/mtime changes fail delivery; the deployment must remain immutable.
Unexpected integrity failures are logged once with traceback, without credentials
or geometry bodies. Startup integrity failure prevents readiness.

## Build, verify and activate separately

Run package preparation **after** all geography, electoral and population preparation:

```bash
.venv/bin/maps prepare-display-packages \
  --dataset .local/releases/input-release \
  --manifest-sha256 '<reviewed-input-manifest-sha256>' \
  --output .local/releases/prepared-display-release \
  --report .local/display-package-build.json
.venv/bin/maps verify-release \
  --dataset .local/releases/prepared-display-release \
  --manifest-sha256 '<returned-output-manifest-sha256>'
```

The default builds every eligible catalogue scope and every resolvable group.
`--plan` selects an explicit alternative reviewed membership plan. No per-request
builder, queue or selection based on population is introduced. Preparation writes
into the existing atomic staging-directory mechanism and refuses existing outputs.
Failure leaves every previous release intact. Timings and machine measurements
are written to the separate operator report, not the immutable content identity.

The output uses **serving manifest schema 2**, covering every base descriptor,
identity artifact, gzip artifact and the support index by size and SHA-256.
Package paths are fixed allowlisted forms under `packages/`. Base descriptors do
not embed the final manifest hash. Startup binds that hash into each serialized
focus-specific HTTP envelope and computes its ETag once. Geometry remains file-backed.

Schema 2 permits at most 20,000 files and an 8 MiB manifest; legacy schema 1 keeps
its existing 100-file/128 KiB limits. The 1 GiB serving-data budget is unchanged.
Individual package files have their smaller representation bounds enforced before
reading. Distribution ZIP extraction, S3 acquisition and deployment verification
honour the same manifest and exact allowlist. The ordinary distribution ZIP is
unchanged as a deployment mechanism; HTTP consumers receive GeoJSON/gzip, not ZIP.

The index binds all input serving-file checksums. Copying packages into a changed
catalogue/report makes startup fail. Population/electoral import commands reject
already prepared inputs: transform the retained pre-package release, then prepare
again. Re-preparing a verified package release into a new directory is allowed.
Package-format corrections require a new release/version; files are never patched
under an existing version.

New code accepts old datasets and returns `package_not_built`. Old code cannot
load schema 2: deploy and roll back the complete paired image/dataset. Existing
`/readyz` dataset/code/website fingerprints cover the new artifacts through the
manifest. The compact summary retains revision 1 and adds a
`links.display_package_template` capability only for package-enabled releases.

Package files are excluded from the public website exporter. The existing image,
API token injection, ingress routing and retention model remain; startup and
per-worker memory must be assessed for the chosen worker count. No new cloud
service or runtime source permission is needed. Keep active and rollback images.

After local acceptance, the separately authorized release process can select the
new source pin, publish a new dataset attachment, update the deployment lock and
build/deploy the paired image. This implementation does **not** change the current
`dataset.source.json` or `dataset.lock.json`, publish data, or deploy the service.

## Consumer example, fixtures and acceptance

```bash
.venv/bin/python -m tools.make_display_package_fixtures \
  --output .local/display-package-fixtures
.venv/bin/python -m unittest tests.test_display_packages -q
.venv/bin/python -m tools.check_display_packages \
  --dataset .local/releases/prepared-display-release \
  --manifest-sha256 '<output-manifest-sha256>' \
  --samples 20 --output .local/display-package-acceptance.json
```

Fixtures cover complete, partial, unavailable, oversized and version-change cases,
with real computed canonical/gzip checksums. Their small fixture manifests identify
synthetic consumer inputs; they are not deployable dataset releases. The version
change alters a label and manifest identity while preserving geometry bytes.
Generated binary fixtures remain local; the reproducible generator is in Git.

`tools.read_display_package` provides a bounded reader and standalone
`validate_pair` function. It rejects redirects/arbitrary artifact paths, pins both
requests, checks transfer/expansion bounds, decoded hashes, inventory, hierarchy,
geometry statistics and source references, and only then writes a new snapshot:

```bash
# Supply MAPS_CONSUMER_TOKEN privately in the server environment.
.venv/bin/python -m tools.read_display_package \
  --url https://provider.example --area-id ca-csd-2481017 \
  --dataset-version '<current-dataset-version>' --output .local/consumer-snapshot
```

Consumers still validate their current local catalogue/selectability, retain the
last valid snapshot on failure, and may skip downloading a hash they already hold
and have verified against the current descriptor. Labels and selection state come
from their own catalogue. Browser integration and end-to-end map latency are separate.

The acceptance tool reports every eligible root, qualified top-100 readiness,
selected scopes, file-read timings, loopback first-byte and complete-body latency,
modest four-request concurrency, CPU and peak RSS. Each scope experiment has its
own ordinary consumer quota; no throttle or server concurrency limit is raised.
DONTNEED is advisory file-cache eviction, not proof of a cold disk. Timing is
reported evidence, never a machine-dependent CI gate or a claim of sub-500 ms
interactive map rendering over a representative internet connection.
