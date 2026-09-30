# Local display-package acceptance, 2026-09-30

Implementation and local release preparation are complete. Nothing in this report
establishes deployment or live package availability. The committed dataset source
pin and deployment lock remain unchanged. See [the contract](DISPLAY_PACKAGES.md)
for routes, consumer validation, release commands, limits and rollback requirements.

## Coverage

The existing locally available population-enriched Canadian release produced
5,337 ready bundles: 5,194 municipality/region scopes and 143 shared agglomerations.
All 5,194 eligible request roots resolve to ready packages: 908 select shared
agglomerations, 4,142 select municipality scopes and 144 select region scopes.
No supported scope exceeded the package limits. Ninety-four request roots resolve
to partial display coverage, with missing members explicitly inventoried.

All 100 largest municipalities among the 2,535 available comparable 2021 municipal
population records resolve to ready packages. This qualification matters: the
existing population policy does not supply compatible population records for
every current municipal boundary. Toronto, Montréal, Ottawa and Vancouver were
therefore also checked explicitly, independently of population ranking. Outaouais
was checked as its own region scope. Readiness does not imply complete real-world
neighbourhood coverage, approved geography or 90% of actual queries. No query
frequency data was available to measure that last objective.

Montréal, Laval and Longueuil share one artifact and retain separate focus bounds.
Ottawa and Gatineau likewise share one cross-province artifact. Montréal's shared
inventory includes three explicitly unavailable Terrebonne sector outlines.

Nine dated grouping definitions cannot be reconciled by exact current IDs:

| Group | Statistical area code | Reason |
|---|---|---|
| Moncton | 305 | Unresolved 2021 member IDs |
| Saint John | 310 | Unresolved 2021 member IDs |
| Fredericton | 320 | Unresolved 2021 member IDs |
| Bathurst | 328 | Unresolved 2021 member IDs |
| Miramichi | 329 | Unresolved 2021 member IDs |
| Campbellton | 330 | Unresolved 2021 member IDs |
| Edmundston | 335 | Unresolved 2021 member IDs |
| Amos | 481 | Unresolved 2021 member IDs |
| North Battleford | 735 | Unresolved 2021 member IDs |

The support index and build report enumerate every missing ID. Existing matched
municipalities use their independently prepared scopes with an explicit preferred
group exception. Other current municipalities also retain ordinary scope packages.
Resolving these groups requires reviewed identity/membership evidence and a new
release, not name matching or changes to administrative parents.

## Reproduction and release evidence

Run the preparation, fixture and acceptance commands in the contract against an
existing reviewed local release. Reports record the actual input/output version,
every supported and unsupported scope, top-100 IDs, all sampled artifact hashes,
per-bundle build durations, counts, bytes, vertices and machine measurements.
The executable fixture generator produces complete, partial, unavailable,
oversized and version-change cases with computed hashes and reproducible gzip.

Two complete builds produced identical manifests and all file hashes. The final
build took 92.19 seconds with a process peak RSS of 990.56 MiB. Package files add
71,668,332 bytes (68.35 MiB). The complete serving release contains 16,073 files
totalling 471,044,453 content bytes, plus a 3,387,060-byte manifest. Allocated disk
usage is approximately 497 MiB; small files incur filesystem overhead. The local
distribution archive is 240,576,918 bytes. These are existing-workflow local
artifacts, not published release assets.

The largest descriptor is Edmonton's shared bundle: 441 members and 228,472 bytes
for its largest focus envelope. Its geometry is 443,175 decoded bytes, 113,076 gzip
bytes and 8,786 vertices. The original 500-member, 256 KiB descriptor and 4 MiB
geometry limits did not need expansion.

All ordinary tests are synthetic and offline. Structural tests cover exact scope
membership, cross-province sharing, focus-specific bounds, determinism, gaps,
malformed data, admission limits, provenance, publication failure, release
integrity, auth and conditional requests, gzip/identity, and read-only request
paths. Existing assignment/circle outputs and older endpoint contracts are tested.
Distribution extraction and combined deployment verification are exercised with
synthetic package-enabled releases; package files remain outside the public site.

Final regression command: `.venv/bin/python -m unittest discover -q` — **286 tests
passed** in 77.42 seconds. Wheel/source-distribution checks and staged publication
and offline secret checks are part of the implementation handoff; they do not
upload anything.

## Serving measurements

Intel Core i5-3210M at 2.50 GHz, four logical CPUs; Python 3.14.7 on Linux
7.2.5 x86-64. Each row uses 20 sequential descriptor requests, 20 sequential
artifact requests and 20 artifact requests at concurrency four. Each request opens
a new loopback TCP connection. Descriptors use identity; artifacts use stored gzip.
There is no TLS, network-distance or browser rendering in these measurements.
The ordinary 120/minute consumer quota and concurrency limit remain unchanged.

Full verified startup took **59.38 seconds**, with **934.67 MiB peak process RSS**.
Startup loads the existing national dataset and verifies all package files; this
cost must be budgeted before readiness. No package geometry is constructed during
HTTP requests. The release was already in filesystem cache; advisory DONTNEED
file reads below are not guaranteed cold physical-disk measurements.

All sizes below are bytes; build time is per bundle, excluding shared input load
and final release verification. Members include the requested municipalities and
their available catalogue descendants, not an assertion of exhaustive neighbourhoods.

| Requested focus | Members / features / gaps | Vertices | Descriptor | Decoded | Gzip | Build seconds |
|---|---:|---:|---:|---:|---:|---:|
| Outaouais | 81 / 81 / 0 | 3,041 | 41,362 | 131,521 | 39,357 | 0.054 |
| Gatineau | 146 / 146 / 0 | 3,756 | 80,430 | 169,259 | 49,725 | 0.157 |
| Montréal | 132 / 129 / 3 | 4,507 | 69,835 | 201,018 | 58,296 | 0.324 |
| Laval | 132 / 129 / 3 | 4,507 | 69,836 | 201,018 | 58,296 | 0.324 |
| Longueuil | 132 / 129 / 3 | 4,507 | 69,834 | 201,018 | 58,296 | 0.324 |
| Toronto | 188 / 188 / 0 | 6,011 | 107,939 | 266,159 | 75,428 | 0.197 |
| Ottawa | 146 / 146 / 0 | 3,756 | 80,430 | 169,259 | 49,725 | 0.157 |
| Vancouver | 60 / 60 / 0 | 1,115 | 37,122 | 56,851 | 14,751 | 0.108 |
| Qikiqtaaluk | 16 / 16 / 0 | 6,415 | 12,436 | 253,535 | 107,951 | 0.094 |

Times below are **median / p95 milliseconds**. First-byte and full transfer are
measured separately. Concurrent throughput is a short bounded burst, not sustained
capacity or permission to bypass quotas. CPU is process CPU time for the entire
60-request experiment for that focus.

| Focus | Descriptor complete | Artifact first byte | Artifact complete | Concurrent complete | Requests/s | MiB/s | CPU seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| Outaouais | 2.19 / 3.80 | 3.28 / 5.79 | 3.36 / 5.90 | 12.89 / 15.17 | 294.8 | 11.07 | 0.249 |
| Gatineau | 2.11 / 3.43 | 3.30 / 4.74 | 3.52 / 4.88 | 13.21 / 16.20 | 282.2 | 13.38 | 0.211 |
| Montréal | 1.86 / 3.42 | 3.16 / 4.81 | 3.30 / 4.91 | 13.12 / 16.67 | 291.9 | 16.23 | 0.208 |
| Laval | 2.88 / 4.75 | 3.60 / 5.99 | 3.75 / 6.04 | 12.92 / 15.53 | 289.6 | 16.10 | 0.235 |
| Longueuil | 2.23 / 2.97 | 3.17 / 4.63 | 3.34 / 4.66 | 13.08 / 16.42 | 283.9 | 15.78 | 0.213 |
| Toronto | 2.50 / 4.02 | 3.39 / 4.79 | 3.85 / 5.38 | 15.00 / 18.88 | 256.7 | 18.47 | 0.242 |
| Ottawa | 2.21 / 5.79 | 3.44 / 4.57 | 3.48 / 4.66 | 13.72 / 16.27 | 280.6 | 13.31 | 0.221 |
| Vancouver | 2.68 / 3.38 | 4.12 / 6.64 | 4.16 / 6.68 | 15.96 / 25.86 | 227.1 | 3.19 | 0.248 |
| Qikiqtaaluk | 2.26 / 3.66 | 3.19 / 4.81 | 3.85 / 5.83 | 14.73 / 17.81 | 255.4 | 26.30 | 0.238 |

| Focus | Warm file read, median / p95 ms | Advisory cold file read, median / p95 ms |
|---|---:|---:|
| Outaouais | 0.006 / 0.018 | 0.338 / 0.442 |
| Gatineau | 0.006 / 0.007 | 0.499 / 0.625 |
| Montréal | 0.007 / 0.009 | 0.631 / 0.846 |
| Laval | 0.010 / 0.016 | 0.534 / 1.568 |
| Longueuil | 0.007 / 0.017 | 0.631 / 1.673 |
| Toronto | 0.012 / 0.025 | 0.549 / 1.292 |
| Ottawa | 0.007 / 0.008 | 0.568 / 0.735 |
| Vancouver | 0.006 / 0.012 | 0.216 / 0.491 |
| Qikiqtaaluk | 0.016 / 0.018 | 0.616 / 1.309 |

These results support the prepared-file request design. They do not establish a
sub-500 ms interactive map on a representative internet connection. Consumer
routing, basemaps, parsing and rendering need separate adoption measurements.

## Deployment considerations

This adds startup integrity work and serialized descriptor caches to the existing
worker, with no new service. Startup verification is deliberately separate from
request latency. The measured peak RSS is for the whole dataset process, not an
estimate of incremental package memory or a safe worker-count recommendation.
Serialized package response bodies occupy 63,122,925 bytes per worker; geometry
artifacts remain file-backed. Validate the real deployment's startup allowance
and memory at its existing worker count before activation. Do not compensate by
disabling verification or raising request/payload limits.

Schema-2 datasets require the new code. Publish/select the dataset and deploy its
paired code through the separately authorized release process. Roll back the
complete verified pair. Retain the earlier pre-package release for future
population/electoral transformations and the active/rollback artifacts under the
existing retention policy.
