# Totally Normal Maps

Standalone reference geography: countries, provinces/territories, regions,
municipalities and city areas, with an HTTP API and an offline map preview.
Python 3.13+. No Django, database server, Docker or cloud account is needed locally.

**Current coverage:** Canada, 13 provinces/territories, 5,054 municipal/statistical
areas, 121 regional groupings and 46 Québec arrondissements/sectors in nine cities.
The catalogue is **review-required**, not a fully qualified legal boundary service.
58 municipal boundaries have separate unapproved repair candidates. Source-vintage
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
loads its assets from a public CDN; the separate offline map has no external assets.

```bash
curl 'http://127.0.0.1:8000/v1/areas/ca/children'
curl 'http://127.0.0.1:8000/v1/areas/ca-qc/children'
curl 'http://127.0.0.1:8000/v1/areas/ca-qc-ra-07/children'
curl 'http://127.0.0.1:8000/v1/areas/ca-csd-2481017/children'
curl 'http://127.0.0.1:8000/v1/lookup?longitude=-75.72&latitude=45.43'
```

The standalone map retains country → province → region → municipality → city-area
navigation. Missing regional levels are skipped without hiding municipalities.

```bash
.venv/bin/maps serve --run .local/canada/current --port 9010
```

Open **http://127.0.0.1:9010**. This preview server is loopback-only and serves only
display assets. The API uses a production ASGI server and separate serving releases.

## Documentation

- [API contract, examples and lookup semantics](docs/API.md)
- [Source downloads, builds, releases and benchmarks](docs/DATA.md)
- [Container and S3 deployment](docs/DEPLOYMENT.md)
- [Architecture and consumer integration](docs/ARCHITECTURE.md)
- [Geography evidence and outstanding work](docs/research/canada-overview.md)
- [Province-by-province regional decisions](docs/research/canada-regions.md)
- [Québec city-area coverage and discrepancies](docs/research/quebec-city-areas.md)
- [Migration inventory and verification](docs/MIGRATION.md)
- [Security model](SECURITY.md) and [third-party attribution](NOTICE.md)

## Tests

Tests use synthetic geography and perform no source downloads or cloud calls.

```bash
.venv/bin/python -m unittest tests.test_catalogue tests.test_regions tests.test_city_areas -q
.venv/bin/python -m unittest tests.test_api tests.test_releases tests.test_publication -q
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
