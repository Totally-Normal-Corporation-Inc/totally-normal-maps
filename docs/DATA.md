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

The preview runs entirely from local assets, without remote tiles or scripts. An
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
