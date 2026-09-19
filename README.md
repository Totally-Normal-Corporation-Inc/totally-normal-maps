# Totally Normal Maps

Standalone reference geography: countries, provinces/territories, regions,
municipalities and city areas, with an HTTP API and a public map explorer.
Python 3.13+. No Django, database server, Docker or cloud account is needed locally.

**Current coverage with the Québec and Ontario refreshes:** Canada, 13 provinces/territories,
5,050 current municipal/statistical areas, 144 regional groupings and 657 city-area
identities in 15 cities. Of those city areas, 652 have assignment boundaries;
Terrebonne's three sectors still need boundaries and two Ottawa neighbourhood
repairs remain unapproved. Ontario adds 520 identities in Toronto, Ottawa and Hamilton
and applies four municipal boundary updates; five proposed updates remain deferred.
Six former Québec municipal identities remain
available as historical records. The original national source contains 5,054 areas.
The initial expansion to other jurisdictions adds **1,418 city-area identities in
nine cities**, bringing the local expansion release to **2,075 identities in 24
cities**, with 2,045 assignment boundaries. Its eleven coverage reports inventory
all 3,198 remaining baseline municipal/statistical areas; **the exhaustive municipal
source audit and post-2025 boundary reconciliation remain unfinished**.
The corrected Ontario rebuild applies four municipal boundary updates and defers
five municipalities across two adjustment groups after checking overlap against
both extents. Earlier immutable releases are unchanged.
The catalogue is **review-required**, not a fully qualified legal boundary service.
The published baseline has 58 municipal repair candidates; the optional
[La Romaine topology review](docs/research/cote-nord-topology.md) resolves one
without changing its territory, leaving 57. Source-vintage
differences and deferred regions remain explicit. An API response is not approval
to replace a consumer's established geographic assignments.

## Start locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
```

Build a dataset using [the reproducible data workflow](docs/DATA.md), then:

```bash
.venv/bin/maps release --run .local/canada/current --output .local/releases/canada
.venv/bin/maps verify-release --dataset .local/releases/canada
.venv/bin/maps api --dataset .local/releases/canada
```

The API is at **http://127.0.0.1:8000**. Its interactive reference is `/docs` and
machine-readable OpenAPI contract is `/openapi.json`. The Swagger documentation UI
loads its assets from a public CDN. The map explorer bundles its code and boundaries;
its optional topographic background loads images from Natural Resources Canada.

Hosted geography endpoints require an API key sent as `Authorization: Bearer <key>`.
Keys are issued manually per application; there is no billing or signup system.
The map explorer uses separate display files and needs no visitor account or API
key. See [public maps and protected API deployment](docs/DEPLOYMENT.md#public-map-and-key-protected-api).
The loopback-only development API below permits requests without a key when none
are configured.

```bash
curl 'http://127.0.0.1:8000/v1/areas/ca/children'
curl 'http://127.0.0.1:8000/v1/areas/ca-qc/children'
curl 'http://127.0.0.1:8000/v1/areas/ca-qc-ra-07/children'
curl 'http://127.0.0.1:8000/v1/areas/ca-csd-2481017/children'
curl 'http://127.0.0.1:8000/v1/lookup?longitude=-75.72&latitude=45.43'
```

The standalone map retains country → province → region → municipality → city-area
navigation, with quartiers/sectors nested under arrondissements where applicable.
Missing regional levels are skipped without hiding municipalities.
The default topographic background shows water, terrain, roads and place names.
Use **Shaded relief** for additional terrain shading and **Boundary fill** to adjust
transparency (0% leaves outlines). Region names appear when they fit without
overlapping; smaller regions remain identifiable by hover or selection.
Choose **None · offline**, or open `/?background=none`, for no external image requests.
Background images are visual context, never boundary or coordinate-assignment data.

```bash
.venv/bin/maps serve --run .local/canada/current --port 9010
```

Open **http://127.0.0.1:9010**. This preview server is loopback-only and serves only
display assets. The API uses a production ASGI server and separate serving releases.

## Deploy website, API and maps together

The default Dockerfile builds one image containing the website, API and exact
dataset selected by [dataset.lock.json](dataset.lock.json). It downloads the
checksummed GitHub Release ZIP during the build and verifies all contents before
serving. Runtime needs API keys and allowed hosts, with no dataset mount or upload.
Deploy and roll back the whole image by digest. The Python wheel remains data-free.

Select an exact `main` commit with passing CI and build with that commit's lock.
An `app-*` GitHub Release is optional. The locked dataset attachment must already
be published; reuse it for code-only updates. Data updates publish a new attachment
and change the lock through a PR. See [the release workflow](docs/RELEASING.md).
Ordinary PR CI tests a synthetic bundle offline; private deployment automation
owns production promotion.

## Documentation

- [API contract, examples and lookup semantics](docs/API.md)
- [Source downloads, builds, releases and benchmarks](docs/DATA.md)
- [Combined website, API and dataset deployment](docs/DEPLOYMENT.md)
- [Dataset attachments and application release workflow](docs/RELEASING.md)
- [Architecture and consumer integration](docs/ARCHITECTURE.md)
- [Geography evidence and outstanding work](docs/research/canada-overview.md)
- [Province-by-province regional decisions](docs/research/canada-regions.md)
- [Québec city-area coverage and discrepancies](docs/research/quebec-city-areas.md)
- [Québec municipal refresh, added areas and remaining gaps](docs/research/quebec-refresh.md)
- [Ontario boundary updates, city areas and remaining gaps](docs/research/ontario-refresh.md)
- [Other jurisdictions: additions, source decisions and unfinished audit](docs/research/jurisdiction-refresh.md)
- [Migration inventory and verification](docs/MIGRATION.md)
- [Security model](SECURITY.md) and [third-party attribution](NOTICE.md)

## Tests

Tests use synthetic geography and perform no source downloads or cloud calls.

```bash
.venv/bin/python -m unittest tests.test_catalogue tests.test_regions tests.test_city_areas -q
.venv/bin/python -m unittest tests.test_api tests.test_releases tests.test_deployment tests.test_publication -q
.venv/bin/python -m unittest tests.test_quebec_refresh tests.test_ontario_refresh -q
.venv/bin/python -m unittest tests.test_topology_review -q
.venv/bin/python -m unittest tests.test_jurisdiction_refresh tests.test_source_acquisition -q
.venv/bin/python tools/check_publication.py
.venv/bin/python tools/check_secrets.py
```

Real-data acceptance is separate:

```bash
.venv/bin/python tools/check_real_data.py --dataset .local/releases/canada
```

Docker is optional. The repository contains no deployment credentials, company
account configuration, original application history or consumer database exports.
Public source code does not imply that a deployed API or S3 bucket is public.
MIT-licensed project code; data and vendored code retain their original licences.

## Before a public commit or package release

After staging the intended files, check the exact proposed commit. These commands
inspect Git's index even if a staged file differs from its working copy:

```bash
.venv/bin/python tools/check_publication.py --staged
.venv/bin/python tools/check_secrets.py --staged
```

Build packages from a clean checkout of the reviewed commit. Verify their contents
against that same commit before uploading either archive:

```bash
.venv/bin/python -m build --no-isolation
.venv/bin/python tools/check_artifacts.py --staged dist/*.whl dist/*.tar.gz
```

Keep source data and consumer inventories under ignored `.local/`, outside the
Python package. See [the public-release review](docs/PUBLIC_RELEASE_REVIEW.md).
