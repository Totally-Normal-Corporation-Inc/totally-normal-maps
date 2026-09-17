# Standalone extraction and validation

Date: 2026-09-16. The repository starts with a curated working-tree extraction;
no unrelated application Git history is imported.

## Preserved work

| Original capability | Standalone location |
|---|---|
| National StatCan importer and immutable catalogue | `totally_normal_maps/catalogue.py` |
| Province overview and original 121 regional groupings | `regions.py`, pinned manifests, regional research |
| All 46 Québec arrondissements/sectors | `city_areas.py`, pinned manifest, city-area research |
| Full hierarchy map, search, keyboard and mobile behaviour | `web/`, `preview.py`, `check_preview.py` |
| Geometry comparison, fixtures and optional local PostGIS adapter | `benchmark.py`, `points.json` |
| Existing-area reconciliation safeguards | Generic inventory adapter in `reconcile.py` |
| Original importer/region/city-area regressions | 50 tests across the three migrated test modules |
| All required map assets | Vendored Leaflet, images and original BSD licence |
| Sources, decisions, exclusions and outstanding qualification | `docs/research/`, manifests and local source snapshots |

The complete current run was copied into ignored `.local/canada/current`, including
the SQLite catalogue, original government archives, region reference, both city-area
sources, review evidence and preview. It is independent of the previous workspace.
The serving release is under ignored `.local/releases/canada`.

Original application-specific planning documents, the old framework-specific
reconciliation helper, committed branch diff, working-tree diff and untracked
city-area work are preserved separately in a private handoff outside this repository.
Their filenames and environment details are intentionally not included here. The
old branch was not reset, deleted, committed or pushed as part of extraction.

## New service capabilities

- Versioned metadata/search/hierarchy API, display/full GeoJSON boundaries,
  single and bounded batch coordinate lookups, OpenAPI and health endpoints.
- Immutable serving exports, per-file hashes, explicit dataset pinning,
  startup validation and optional read-only S3 bootstrap.
- Authentication, host/CORS policy, request/resource limits, private cache policy,
  redacted validation errors and no coordinate-bearing access logs.
- Independent package/CLI, MIT licence, container definition, dependency locks,
  unprivileged CI, publication guard and offline secret scanning.
- Integration/deployment instructions without real company deployment identifiers.

## Local verification

- All 50 migrated geography tests passed independently of the original application.
- API/release tests passed for hierarchy, search, boundary ambiguity, repair
  exclusion, authentication, limits, corruption, safe S3 downloads and version pinning.
- Real-data API acceptance verified 5,054 municipal/statistical areas, 121 regions,
  46 city areas and an interior lookup for each city area. It checked Outaouais,
  Gatineau, Montréal, partial Métis-sur-Mer, municipal fallback and missing repairs.
- Desktop/mobile browser acceptance passed with no page errors; screenshots were
  inspected. Tests include all 13 jurisdictions and all nine cities.
- Runtime and optional S3 dependency audit reported no known vulnerabilities at
  this checkpoint. This is time-dependent and does not audit bundled native libraries.
- Source/wheel packaging was built locally; publication and secret checks inspect
  the exact nonignored Git surface. Source/identity checksum fields are explicitly
  distinguished from credentials; scanning does not claim complete security assurance.

## Remaining external validation

The local user cannot access the Docker daemon, so a local container build/run has
not been verified. CI includes a container build without publishing. Actual AWS
networking, TLS, role permissions, S3 access and multi-replica load are deployment
acceptance work. S3 transfer behaviour has been tested against a fake client; no
cloud account was contacted or changed. PostGIS remains an optional unrun comparison.

Geographic qualification remains incomplete: source repair/topology and cross-source
boundary decisions still need review. These limitations are preserved in API output.
No consumer place IDs, stored memberships, manual overrides or publication rules
were changed by the extraction.
