# Reproduce the Canada catalogue

Install the project as described in README.md. All commands use local files; none
write a consumer application database. The original source snapshots and generated
datasets belong in ignored `.local/` storage, not Git.

The current plan adds 23 familiar regional groupings to the original 121. No new
geometry download is needed: all their outlines use the existing StatCan source.
Thirteen groups have selected-community coverage rather than complete regional
outlines. See [regional expansion decisions](research/regional-expansion.md) before
using these polygons for geofencing or interpreting gaps.

## 1. Obtain pinned source bytes

```bash
.venv/bin/maps download --output .local/sources/municipalities.zip
.venv/bin/maps download-provinces --output .local/sources/provinces.zip
.venv/bin/maps download-regions --output .local/sources/quebec-regions.geojson
.venv/bin/maps download-city-areas --source quebec --output .local/sources/quebec-city-areas.geojson
.venv/bin/maps download-city-areas --source gatineau --output .local/sources/gatineau-sectors.geojson

for source in quebec-quartiers levis-secteurs laval-quartiers trois-rivieres-quartiers municipality-14082 municipality-93022; do
  .venv/bin/maps download-quebec-refresh --source "$source" --output ".local/quebec-sources/$source.geojson"
done
```

Downloads verify their checksums before atomically publishing a file and never
overwrite an existing destination. Government query services can change their
output. If bytes differ, use an archived matching snapshot or explicitly qualify a
new manifest; do not change a hash merely to make an import pass.

The manifests beside the package code record source URLs, licences, versions,
reference dates, identity digests, counts and parent relationships. Preserve exact
source snapshots in an appropriately backed-up artifact store. A Git clone contains
the recipes and manifests, not large source archives or ready-made serving data.

## 2. Build the layers

Run these as separate commands. Successful review builds deliberately return exit
code **1** when geographic issues remain. A complete `report.json` distinguishes
that result from rejected input (exit 2) or an unexpected exception. Do not put
the steps behind `&&` without handling the review-required exit explicitly.

```bash
.venv/bin/maps build \
  --source .local/sources/municipalities.zip \
  --province-source .local/sources/provinces.zip \
  --output .local/canada/municipal

.venv/bin/maps regions \
  --run .local/canada/municipal \
  --quebec-source .local/sources/quebec-regions.geojson \
  --province-source .local/sources/provinces.zip \
  --output .local/canada/regional

.venv/bin/maps city-areas \
  --run .local/canada/regional \
  --quebec-source .local/sources/quebec-city-areas.geojson \
  --gatineau-source .local/sources/gatineau-sectors.geojson \
  --output .local/canada/city-areas

.venv/bin/maps quebec-refresh \
  --run .local/canada/city-areas \
  --source-dir .local/quebec-sources \
  --output .local/canada/current
```

Every output is a fresh immutable directory. Rebuilds require a different output
path. Earlier municipal rows and geometry remain unchanged when adding regions or
city areas. Source archives, crosswalk evidence, review candidates and licences stay
with the run. Full assignment geometry is independent of simplified display data.

The optional Québec refresh is offline and additive: original municipal, regional,
membership and city-area rows remain unchanged. `area_revision` supplies current
municipal identities, names and regional member counts; six superseded CSDs remain
queryable historically. Municipal successors use complete predecessor unions for
assignment, with the newer provincial polygons archived as comparison evidence.
The refresh adds 88 source boundaries and three documented Terrebonne sector
identities without boundaries. Read [the evidence and limits](research/quebec-refresh.md)
before interpreting coverage. It does not approve any repair candidate.

The initial local extraction includes an earlier `.local/canada/current` on its
development machine. It contains the original official source snapshots:
`source.zip`, `province-source.zip`, `regional-sources/quebec.geojson`
and `city-area-sources/{quebec,gatineau}.geojson`. These local files are not committed
or uploaded by the project. They require a deliberate external backup before the
machine is discarded. The later Québec refresh additionally archives its six
source files and plan under `quebec-refresh-sources/`. Existing local directories
are never updated in place; use fresh output paths when following this workflow.

## 3. Export a serving release

```bash
.venv/bin/maps release --run .local/canada/current \
  --output .local/releases/canada --label canada-2026-09-16
.venv/bin/maps verify-release --dataset .local/releases/canada
```

The export has `manifest.json`, read-only geography SQLite, a projected public
`report.json`, and display GeoJSON. It excludes source archives, benchmarks,
consumer inventories, private notes and arbitrary preview properties. The printed
`manifest_sha256` identifies the complete release. A deployment should pin it
through trusted configuration. `verify-release` checks the serving representation;
it does not approve geographic repairs or establish legal/topological accuracy.

Keep code and dataset releases independent. An operator may archive and distribute
licensed datasets through S3 or another artifact store. The public project's CI
does not upload datasets. Update a consumer deliberately and keep previous releases
available for rollback; do not mutate an adopted release in place.

## Preview and browser acceptance

```bash
.venv/bin/maps serve --run .local/canada/current --port 9010
```

The preview bundles its boundaries and scripts. Select **None · offline** or use
`/?background=none` to disable its optional NRCan background requests. An
optional Playwright check covers all cities, hierarchy navigation, search, keyboard
selection, deferred/partial coverage and mobile layout:

```bash
.venv/bin/python -m totally_normal_maps.check_preview \
  --url http://127.0.0.1:9010 --output .local/browser-check
```

Install the `browser` extra and Chromium first. The check defaults to system
Chromium at `/usr/bin/chromium` (see its `--help` for available options).

Check the expanded release through the API, optionally comparing all existing
municipality, region, membership and city-area rows against an earlier release:

```bash
.venv/bin/python tools/check_real_data.py --dataset .local/releases/canada-expanded \
  --baseline .local/releases/canada
```

The acceptance check expects the expanded 144-region plan, exercises new membership
and alias cases, and probes every available municipal geometry in the 23 additions.
When a Québec refresh is present, it also checks every available current Québec
municipal boundary, all 134 available city-area boundaries, lifecycle filtering,
complete successor unions, nested parentage and the three unavailable sector shapes.
Keep the baseline as an immutable rollback artifact.

## Geometry-only benchmarks

```bash
.venv/bin/maps benchmark --run .local/canada/current \
  --report .local/benchmark.json --points 500 --rounds 3 \
  --include-repair-candidates
```

This explicit repair option is for comparison only. It does not approve a repair
or change the serving API's exclusion policy. The comparison checks a linear
bounding-box/covers baseline against Shapely STRtree using deterministic locality,
interior, outside and exact-boundary points. It excludes application queries,
network latency, source accuracy, concurrent load and cold operating-system caches.

Optional PostGIS comparison uses the `postgis` extra and an existing local PostGIS
database named **maps_lab**. Pass the name of an environment variable holding its
connection string with `--postgis-dsn-env`. Only explicit loopback hosts and that
database name are accepted. It creates temporary tables, rolls back and never
creates databases or extensions. An actual PostGIS comparison has not been run
on the current development machine.

## Generic consumer reconciliation

`maps reconcile --run RUN --areas inventory.json --report new-report.json` accepts
a local generic inventory:

```json
[
  {"id":"local-qc","kind":"province","code":"QC","parent_id":null,"names":["Québec"]},
  {"id":"local-city","kind":"municipality","parent_id":"local-qc","names":["Gatineau"]}
]
```

It returns suggestions requiring review and never writes consumer records. It
preserves city/sector identity distinctions and reports missing/cyclic ancestry.
Keep inventories and reconciliation reports private. A consumer-specific adapter
belongs in the consuming application's repository, not this public project.

## Ontario refresh

After the Québec refresh, acquire the seven individually pinned sources explicitly:

```bash
for source in toronto-former toronto-neighbourhoods ottawa-neighbourhoods-canonical hamilton-communities hamilton-neighbourhoods ontario-municipalities grey-boundaries; do
  .venv/bin/maps download-ontario-refresh --source "$source" --output ".local/ontario-refresh/sources/$source.geojson"
done
.venv/bin/maps ontario-refresh --run .local/quebec-refresh/ready \
  --source-dir .local/ontario-refresh/sources --output .local/ontario-refresh/ready
.venv/bin/maps release --run .local/ontario-refresh/ready \
  --output .local/releases/canada-ontario-refresh --label canada-ontario-review
.venv/bin/python tools/check_real_data.py --dataset .local/releases/canada-ontario-refresh \
  --baseline .local/releases/canada-quebec-refresh
.venv/bin/maps serve --run .local/ontario-refresh/ready --port 9030
```

Use fresh output paths; neither downloads nor builds replace existing artifacts.
Builds perform no network requests. Like earlier review builds, `ontario-refresh`
returns exit status 1 when it successfully produces a review-required catalogue;
status 2 means an input/validation error. Keep downloaded bytes under ignored `.local/`.
Live municipal services may change: a failed checksum requires renewed evidence and
identity review, not just a replacement digest.

See [Ontario source evidence and qualification](research/ontario-refresh.md). The
`boundary_revision` table retains current assignment geometry and separate review
uncertainty. Original CSD and regional rows remain untouched. Municipal source parts
are complete, regional unions retain unresolved member repairs, and Ontario's two
unapproved city-area repairs have no assignment geometry. The serving export adds
`display/city-areas-35.geojson`; display files never supply coordinate assignments.

## Other jurisdictions: qualified additions and audit inventory

The September jurisdiction manifests provide an initial source qualification pass,
not the completed nationwide municipal-site audit. Read
[the exact coverage and unfinished work](research/jurisdiction-refresh.md).
The shared builder is offline, province-scoped, and requires the exact parent
catalogue and report digests recorded in the plan. Preserve archived inputs; a
fresh run with different parent metadata requires explicit requalification.

First rebuild Ontario with the corrected two-sided comparison, using a fresh
output path. The Barrie/Oro-Medonte/Springwater and Hanover/West Grey groups are
deferred as whole groups. The Québec run remains its input:

```bash
.venv/bin/maps ontario-refresh --run .local/quebec-refresh/ready \
  --source-dir .local/ontario-refresh/sources \
  --output .local/jurisdiction-refresh/ontario-checked
```

For each plan, download its named sources explicitly, then build locally. Example:

```bash
.venv/bin/maps download-jurisdiction-refresh \
  --plan totally_normal_maps/jurisdiction-bc-2026-09.json \
  --source vancouver-local-areas \
  --output .local/jurisdiction-refresh/sources/vancouver-local-areas.geojson

.venv/bin/maps jurisdiction-refresh --province 59 \
  --run .local/jurisdiction-refresh/ontario-checked \
  --source-dir .local/jurisdiction-refresh/sources \
  --plan totally_normal_maps/jurisdiction-bc-2026-09.json \
  --output .local/jurisdiction-refresh/ready-59
```

Apply the remaining plans in pinned order: AB/48, MB/46, SK/47, NB/13, NS/12,
PE/11, NL/10, YT/60, NT/61, NU/62. Each uses the previous `ready-<code>` run.
Plans without qualified downloads still add their explicit audit inventory.
Exit 1 means a completed review-required build; do not treat it as rejected input.
A source count/hash/schema change is a rejection, requiring source requalification.

Acquisition also supports manifests with an explicit ArcGIS `acquisition` block
(`kind`, `layer_url`, `layer_name`). It fetches full polygons in object-ID chunks,
checks counts, missing/duplicate IDs, transfer limits and edit metadata, then checks
the complete snapshot checksum. It never requests display/generalized geometry.
This is an operator command, never an ordinary-test or public-CI download.

```bash
.venv/bin/maps release --run .local/jurisdiction-refresh/ready-62 \
  --output .local/releases/canada-jurisdictions --label canada-jurisdictions-2026-09-18
.venv/bin/python tools/check_real_data.py --dataset .local/releases/canada-jurisdictions \
  --baseline .local/releases/canada-ontario-checked
```

All stages refuse to overwrite prior outputs. No source data, package, image or
release is pushed or published by this workflow.

## Municipal and regional migration contract

The generic jurisdiction plan optionally accepts `mergers`, `region_updates` and
`membership_updates`. Every operation requires source evidence and an ISO
`effective_date` no later than `reviewed_on`. Original CSD, region, city-area and
membership rows remain unchanged; the separate `jurisdiction_revision` table
records current identities and relationships. Serving checks verify these rows
against the scoped report and complete current member geometry before accepting
traffic.

- A merger names a publisher `source`, `source_id`, `name`, `type`, stable
  `id` (`ca-<province>-mun-<publisher-id>`), all `predecessor_csd_ids`, the current
  `region_id` (or null), and every existing `city_area_id` in `city_area_ids`.
  Its assignment geometry is the complete predecessor union. The comparison
  publisher polygon must overlap at least 80% of both extents; otherwise the
  whole succession is deferred and predecessors remain current. A predecessor
  with an unapproved repair cannot be merged. Simultaneous predecessor boundary
  adjustments or renames require separate qualification.
- An existing city area keeps its identity, source geometry and any nested
  city-area parent. Its current municipal ancestor changes only through the
  merger's explicit city-area list. A new city layer for a successor supplies
  `parent_municipality_id`, its current `parent_name`, and a predecessor
  `parent_csd_id` as the retained national source association. Parent geometry
  checks use the complete successor boundary.
- A regional definition supplies `id`, `operation` (`add`, `update`, or `retire`)
  and the exact current `member_ids`, using API municipal IDs. Add/update also
  requires `source_id`, `name`, `kind`, `type`, `coverage_policy`
  (`whole_divisions`, `selected_members`, or `complete_members`) and `coverage_note`.
  Names or spatial containment never establish membership.
- Each municipal move supplies `municipality_id`, `previous_region_id` and
  `region_id`; null means direct province membership. All affected regional
  boundaries are rebuilt from complete current members. Unapproved member or
  existing regional repairs remain review-only. Retiring a region requires an
  empty member list and explicit reassignment of every member; its old identity
  remains historical. An empty current grouping is rejected.

Migration reports include the current regional IDs, member count and every
ungrouped current municipal ID. They supplement the retained baseline regional
inventory. Historical municipalities and regions remain accessible by ID and
through `include_historical=true`, but never participate in current point lookup.
No provincial publisher identity is represented as an invented Statistics Canada
CSD code. The eleven supplied plans currently import city areas and audit gaps;
they do not claim completed post-2025 municipal change reconciliation.

## Parallel electoral releases

The electoral importer takes an existing verified serving release and creates a
new one, preserving every administrative table and existing edition. It adds an
`electoral_area` table, edition/source metadata and province-partitioned display
files. Imports never download data or approve repairs. A later edition uses a new
namespace; a changed source uses a new source key to preserve older provenance.
The report retains import-plan digests. Default selections are release metadata,
not date-driven server behaviour.

```bash
.venv/bin/maps download-electoral --source fed --output .local/electoral-sources/federal.zip
# Obtain the remaining filenames using the source keys in electoral-2026-09.json.
.venv/bin/maps electoral --dataset .local/releases/canada \
  --source-dir .local/electoral-sources --output .local/releases/canada-electoral
.venv/bin/maps verify-release --dataset .local/releases/canada-electoral
.venv/bin/python tools/check_electoral_data.py --dataset .local/releases/canada-electoral \
  --baseline .local/releases/canada
```

The importer accepts `--plan` for a separately qualified future edition. A failed
checksum, changed identity inventory or duplicate edition rejects the import;
use a fresh output directory outside the input release. Source pins include the
complete parsing specification (CRS, coordinate operation, identity mapping and
field selection), as well as the source bytes. Reusing a source key requires an
identical specification digest. Releases created before that digest was recorded
require a new source key when importing another edition from that source.

Geometry validity is checked in the publisher's original CRS before reprojection;
rounding cannot approve an invalid source. A collapsed repair retains its identity
and uncertainty bounds without becoming assignment geometry. Import validation
runs each assignable district's representative point through the actual lookup
engine and rejects the output if that district is absent from its results.
A successful command does not remove the dataset's
`review_required` qualification. Seven initial electoral polygons have display
repair candidates but no assignment geometry.

Read [the complete source inventory and reuse qualification](research/electoral-layers.md).
This local review covers all 13 jurisdictions; redistribution of six exact source
products remains unconfirmed. `tools/publish_dataset.py --publish` rejects such
sources. Local packaging/deployment works without publishing or changing the
repository's existing public `dataset.lock.json`.

An existing upcoming edition can become the default in a new release using an
evidenced metadata-only plan, passed to the same `maps electoral --plan` command:

```json
{
  "schema_version": 1,
  "reviewed_on": "2027-01-01",
  "release_label": "example-edition-activation",
  "sources": {},
  "editions": [],
  "edition_updates": [
    {
      "id": "example-upcoming",
      "status": "current",
      "default": true,
      "effective_date": "2027-01-01",
      "evidence_url": "https://example.org/official-activation-notice"
    },
    {
      "id": "example-previous",
      "status": "historical",
      "default": false,
      "valid_to": "2027-01-01",
      "evidence_url": "https://example.org/official-activation-notice"
    }
  ]
}
```

These are illustrative IDs and evidence URLs; use the installed edition IDs and
an actual authority notice. Updates may change status, default selection, label,
electoral event, validity dates and evidence URL. They preserve district identities,
source pins and geometry bytes; the input release remains unchanged. A default
replacement clears the prior default but does not infer its lifecycle status.
Optional plan `coverage` entries must refer to an installed compatible edition;
missing jurisdictions are derived from the selected inventory.

## Municipal elections

The pinned municipal plan is `totally_normal_maps/municipal-elections-2026-09.json`.
It records source checksums, publisher identity fields, explicit authority joins,
election/snapshot dates, source decisions and evidence for at-large coverage.
`municipal-elections` reads only already acquired files and creates a new release;
it never downloads, modifies its input release, or approves a geometry repair.

```bash
.venv/bin/maps download-municipal --source lake-country-current --output .local/municipal-sources/lake-country-current.geojson
.venv/bin/maps municipal-elections --dataset .local/releases/base --source-dir .local/municipal-sources --output .local/releases/municipal
```

Source filenames must match the plan. Live publishers can change: a changed
snapshot must be requalified and receive new checksums/version evidence, rather
than bypassing integrity checks. Represent acquisition joins the full-shape
response to a separately pinned identity inventory; ambiguous names, pagination,
missing IDs and changed snapshots are rejected. Its simplified endpoint is never
used. ArcGIS acquisition verifies object inventories and snapshot stability.

Some provincial feeds contain multipart records, polling areas, or at-large
features. Only explicit grouping rules may union parts of a ward. PEI polling
areas are grouped by municipality and council district number; open/at-large
areas do not become wards. Nova Scotia council polling districts are a distinct
representation scheme. NB rural advisory wards and BC regional electoral areas
retain distinct kinds. County/regional browsing envelopes do not establish the
legal electorate of incorporated towns or Indigenous governments.

The public Python package contains code and source manifests, not downloaded
geometries. Local downloads and intermediate builds stay under the gitignored
`.local/` directory inside this repository. Redistribution permission is recorded
per source; the publication tool rejects releases with unconfirmed source reuse.
