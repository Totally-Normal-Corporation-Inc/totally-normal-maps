# Reproduce the Canada catalogue

Install the project as described in README.md. All commands use local files; none
write a consumer application database. The original source snapshots and generated
datasets belong in ignored `.local/` storage, not Git.

## 1. Obtain pinned source bytes

```bash
.venv/bin/maps download --output .local/sources/municipalities.zip
.venv/bin/maps download-provinces --output .local/sources/provinces.zip
.venv/bin/maps download-regions --output .local/sources/quebec-regions.geojson
.venv/bin/maps download-city-areas --source quebec --output .local/sources/quebec-city-areas.geojson
.venv/bin/maps download-city-areas --source gatineau --output .local/sources/gatineau-sectors.geojson
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
  --output .local/canada/current
```

Every output is a fresh immutable directory. Rebuilds require a different output
path. Earlier municipal rows and geometry remain unchanged when adding regions or
city areas. Source archives, crosswalk evidence, review candidates and licences stay
with the run. Full assignment geometry is independent of simplified display data.

The initial local extraction already includes `.local/canada/current` on its
development machine. It contains every official source needed to reproduce the
current result: `source.zip`, `province-source.zip`, `regional-sources/quebec.geojson`
and `city-area-sources/{quebec,gatineau}.geojson`. These local files are not committed
or uploaded by the project. They require a deliberate external backup before the
machine is discarded.

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
