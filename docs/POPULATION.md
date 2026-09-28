# Population metadata

Population is stored reference data, independent of map rendering, assignment
approval and consumer ordering. Maps does not rank municipalities. Existing
catalogue order, IDs, `source_id`, names, aliases, translations and parents stay
unchanged. The initial importer covers current administrative municipalities and
statistical municipal equivalents; other levels explicitly have no population
source. A municipal figure is never copied to a sector or metropolitan area.

## API contract

`GET /v1/areas?layer=administrative&include_historical=false&offset=0&limit=100`
adds `population` and `population_unavailable_reason` to each item. The same
fields appear on area details, countries, children and ancestors. Point lookup,
circle results and boundary properties retain their existing representations.
The live application's generated `/openapi.json` describes `CatalogueArea` and
`Population`; no new population endpoint or per-item request is needed.

The full `GET /v1/datasets/current` report includes the validated population
coverage aggregates in `coverage.population` (`by_level` and `by_province`) and
population source credits in its top-level `sources` inventory. Releases without
population retain their previous full-report shape. The compact `/summary` remains
bounded to 16 KiB; boundary attribution continues to describe geometry sources.

Real local acceptance example, Gatineau (other existing area fields omitted):

```json
{
  "id": "ca-csd-2481017",
  "population": {
    "count": 291041,
    "reference_year": 2021,
    "measure": "usual_residents",
    "method": "census_count_boundary_adjusted",
    "source": {
      "publisher": "Statistics Canada",
      "dataset": "98-10-0002-01",
      "record_id": "2021A00052481017",
      "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810000201"
    },
    "geography_reference": "statcan-csd-2025-01-01",
    "quality_flags": []
  },
  "population_unavailable_reason": null
}
```

Real known zero, Nanisivik, Nunavut:

```json
{
  "id": "ca-csd-6204019",
  "population": {
    "count": 0,
    "reference_year": 2021,
    "measure": "usual_residents",
    "method": "census_count",
    "source": {
      "publisher": "Statistics Canada",
      "dataset": "98-10-0002-01",
      "record_id": "2021A00056204019",
      "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810000201"
    },
    "geography_reference": "statcan-csd-2021-01-01",
    "quality_flags": []
  },
  "population_unavailable_reason": null
}
```

Missing sector example (no inferred city count):

```json
{
  "id": "ca-qc-2481017-sector-15",
  "population": null,
  "population_unavailable_reason": "no_source"
}
```

Population and unavailable reason are mutually exclusive. Counts are strict
integers from 0 through 1,000,000,000; booleans, fractions, strings and negative
sentinels are rejected. `reference_year` describes measurement, not ingestion.
For this snapshot the internal exact census reference date is **2021-05-11**.
These figures are not 2026 estimates. Geographic vintage is a separate fact:
`statcan-csd-2021-01-01` describes the census territory; an officially adjusted
count names the reviewed target geography instead.

Allowed methods are `census_count` and `census_count_boundary_adjusted`. The latter
applies explicitly identified official population transfers to the census count,
without changing its reference year. No estimates, area-weighted apportionment,
metro substitutions or overlapping aggregate sums are supported.

`quality_flags` is a unique sorted list, at most three entries: `revised`,
`use_with_caution`, `incomplete_enumeration`. The parser retains recognized `r`
and `E` source symbols; unknown symbols fail validation. In this pinned table,
`..` indicates a missing count for an incompletely enumerated reserve/settlement;
it becomes `not_enumerated`, never a zero. The table has 63 such CSDs nationally.

| Unavailable reason | Meaning |
|---|---|
| `no_source` | No selected population source for this level/area; also the default for old bundles |
| `unmatched_geography` | No qualified source identity/crosswalk for the current area |
| `incompatible_boundary` | A candidate census identity exists but territory equivalence or its adjustment is not established |
| `suppressed` | The source explicitly suppresses the count |
| `not_available` | The source reports an unavailable value |
| `not_enumerated` | Census enumeration did not supply a usable count |
| `withdrawn` | A previously usable figure was deliberately withdrawn with operator evidence |

Historic and electoral areas currently return `no_source`. `no_source` does not
claim that no external source exists. A polygon awaiting assignment approval can
have population when its original territory has independent positive evidence.
Population never approves a repair or removes geographic uncertainty.

## Source and territory policy

The pinned [source manifest](../totally_normal_maps/population-2021.json) selects
Statistics Canada [table 98-10-0002-01](https://www150.statcan.gc.ca/n1/en/catalogue/9810000201):
*Population and dwelling counts: Canada and census subdivisions (municipalities)*.
This supplies one comparable national census vintage, including 5,161 CSDs.
The importer reads only the 2021 population column and authoritative CSD DGUIDs.
It ignores dwelling counts, previous-year counts, changes, ranks and higher-level
rows. Names are not identity keys. Census DGUIDs remain separate from Maps
`source_id` values.

Checksums, complete identity inventories, table schema, count syntax and source
symbols must all validate. Source URL, release/snapshot, retrieval date, exact
reference date and source geographic vintage are retained in the database.
Only one snapshot per source product is accepted. Aliases or repeated transaction
rows cannot apply the same population transfer twice. Startup repeats the census
identity, source-type, crosswalk-uniqueness and citation checks on stored records,
in addition to verifying file checksums; regenerated hashes do not approve
malformed provenance.
Census 2021 full digital polygons and official interim lists for 2022–2025 support
the crosswalk. The lists report *population affected by a change*, not replacement
whole-municipality populations; `...`/ellipsis is not an assumed zero transfer.

The automatic crosswalk requires the same authoritative code **and** equivalent
full geometry. Its 1e-10 degree coordinate tolerance permits only floating-point
projection/export roundoff (roughly 0.012 mm in latitude). It does not compare
display polygons, approximate overlap percentages or city centres. A missing
assignment shape can qualify through an identical original source geometry hash;
proposed repair geometry cannot establish this. Any code mentioned in an official
numeric population transfer is excluded from automatic attachment and needs a
reviewed transaction chain. Absence from a change list alone proves nothing.

Reviewed crosswalks bind to the input dataset and a fingerprint of the served
territory. This is an internal stale-evidence guard, not a consumer classification
revision. The importer requires exactly one match or explicit missing reason for
every current municipality. It cannot quietly publish a partial import as success.
A missing classification is an intentional reviewed record, not a download error.

Gatineau and Chelsea have a [reviewed override](../totally_normal_maps/population-crosswalk-20260928.json).
Official [2023 interim transaction 240028](https://www150.statcan.gc.ca/n1/pub/92f0009x/2023001/tbl/tbl01-eng.htm)
records a transfer from Gatineau to Chelsea effective 2022-04-16, with **zero 2021
residents affected**. The 2022–2025 lists contain no other transactions for these
codes. Their served polygons equal the pinned 2025 national polygons. An
independent native EPSG:3347 check finds the combined outlines mutually cover
within 1 mm; the directional transfer checks pass within 2 mm. Their combined
symmetric difference is about 0.5223 m² from tiny coordinate export differences.
These supporting numerical checks are specific to this reviewed pair, not a
national matching threshold. The official transaction establishes the count.
`check_population_data.py --national-boundaries ...` reproduces the checks.

All selected sources use the [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence).
[NOTICE.md](../NOTICE.md) credits the table, interim lists and supporting boundaries
with the required adaptation/no-endorsement wording. Retain source credits when
redistributing. Routine metadata carries a short source citation. Existing scoped
`/v1/datasets/current/sources`, `/coverage` and linked `/evidence/{id}` resources
expose source and calculation evidence without embedding national reports in pages.

## Initial local coverage and limits

Acceptance on 2026-09-28 accounts for all 5,050 current municipal/statistical areas:
**2,535 known counts**, including **180 true zeros**; **31 not enumerated**;
**2,290 incompatible boundaries**; **194 unmatched geographies**. Zero is a subset
of known, not another missing category. No suppressed counts occur among the
qualified matches in this snapshot, although the importer supports them.

| Province/territory | Municipal entries | Known | Incompatible | Unmatched | Not enumerated |
|---|---:|---:|---:|---:|---:|
| Newfoundland and Labrador | 372 | 297 | 75 | 0 | 0 |
| Prince Edward Island | 96 | 73 | 23 | 0 | 0 |
| Nova Scotia | 96 | 63 | 32 | 1 | 0 |
| New Brunswick | 109 | 0 | 0 | 109 | 0 |
| Québec | 1,274 | 1,042 | 219 | 9 | 4 |
| Ontario | 578 | 402 | 165 | 1 | 10 |
| Manitoba | 241 | 38 | 198 | 2 | 3 |
| Saskatchewan | 995 | 95 | 845 | 54 | 1 |
| Alberta | 419 | 39 | 377 | 3 | 0 |
| British Columbia | 765 | 437 | 300 | 15 | 13 |
| Yukon | 33 | 16 | 17 | 0 | 0 |
| Northwest Territories | 41 | 17 | 24 | 0 | 0 |
| Nunavut | 31 | 16 | 15 | 0 | 0 |

Other current levels: 1 country, 13 provinces/territories, 144 regions and 2,075
city areas all have `no_source`. `report.json.population.coverage.by_level` reports
these separately. Its `by_province` totals include **all administrative levels**,
not just municipalities; use the table above or filter the catalogue for municipal
denominators. Historical and electoral records are excluded from these tallies.

This is partial national population coverage, not complete municipal coverage.
Several major cities, including Toronto, Montréal, Ottawa, Vancouver and Calgary,
still need geographic reconciliation; New Brunswick needs explicit crosswalks for
its changed municipal framework. Consumers must retain their missing-value
fallback. More coverage requires reviewed equivalent territory or official
adjustments, not relaxing the identity rule or hand-ranking cities.

Verified examples include Gatineau (291,041), Alleyn-et-Cawood (229), and Trepassey,
Newfoundland and Labrador (405). Same-named Akulivik entries remain distinct:
`ca-csd-2499125` has 642, while `ca-csd-2499883` has zero. Nanisivik has zero.
These are source counts for their respective territories, not interchangeable
place-name totals. Sector values remain explicitly unavailable.

The full local catalogue acceptance covered 7,283 current administrative entries.
The largest compact-encoded 100-item metadata page was **130,173 bytes** (the
consumer budget is 2 MiB). These are measured release-specific values, not a
promise about arbitrary future catalogue expansions.

Local authenticated HTTP acceptance measured a **2,070-byte summary**, a
**125,489-byte first catalogue page**, and a **1,590-byte Gatineau detail**.
The existing batch lookup still succeeds directly; uncertain circle coverage
still returns HTTP 409 without a partial result.

## Offline preparation and repeat runs

No scheduled task or new service is required. Preparation uses the existing
Python environment and local SQLite release. The serving process never downloads
population, contacts source websites or calculates population from polygons.
Complete geography augmentation **before** adding population. Later geographic
changes must requalify the crosswalk; stale stored territory fingerprints fail
startup validation.

Download pinned official inputs explicitly. Each command stages and verifies the
checksum before exposing a complete local source file; keep these outside Git:

```bash
mkdir -p .local/population
.venv/bin/maps download-population --plan totally_normal_maps/population-2021.json \
  --source census2021 --output .local/population/98100002-eng.zip
.venv/bin/maps download-population --plan totally_normal_maps/population-2021.json \
  --source census_boundaries --output .local/population/lcsd000a21a_e.zip
for year in 2022 2023 2024; do
  .venv/bin/maps download-population --plan totally_normal_maps/population-2021.json \
    --source "interim${year}" --output ".local/population/interim-${year}.csv"
done
.venv/bin/maps download-population --plan totally_normal_maps/population-2021.json \
  --source interim2025 --output .local/population/Table1_InterimList_2025_E.csv
```

Set `BASE` and `BASE_SHA` to the reviewed serving release and its independently
verified manifest SHA-256. The supplied two-area override pins the municipal
release selected before this population change; it intentionally rejects another
base version until re-reviewed.

```bash
.venv/bin/python tools/prepare_population.py \
  --dataset "$BASE" --manifest-sha256 "$BASE_SHA" \
  --source-dir .local/population \
  --overrides totally_normal_maps/population-crosswalk-20260928.json \
  --output .local/population/crosswalk-reviewed.json

.venv/bin/maps population-import \
  --dataset "$BASE" --manifest-sha256 "$BASE_SHA" \
  --plan .local/population/crosswalk-reviewed.json --source-dir .local/population \
  --output .local/releases/canada-population-reviewed
```

Review the generated plan, then import it. The importer verifies all files and all
records before writing a new staged release. It adds `area_population` and
`population_source` tables to a **copy**, writes coverage/provenance to `report.json`,
updates manifest checksums, fully loads the candidate, then atomically renames the
complete directory. Failed downloads, malformed/partial inputs and write failures
preserve the last successful snapshot. Existing releases are never overwritten.
Keep generated plans and operator command results under `.local/` for audit.

Repeating the same input plan and output returns `unchanged` after verification.
For a refresh of a population-enriched release, pin the plan to that release.
Unchanged records and source facts return its existing dataset version, without
creating another directory. Changing only the refresh retrieval/review date does
not mint a new dataset; the first successful source retrieval date is retained.
Record refresh attempts separately in operator logs. Source/provenance corrections
or deliberate withdrawals require a new complete plan, reviewed evidence and new
output directory. Never replace missing source bytes with empty records. New
census vintages/formats need a parser and source-policy review; this importer is
intentionally constrained to the 2021 measurement.

To deliberately correct a previously stored retrieval date, pin the plan to the
population-enriched release, edit the incorrect source date and pass
`--retrieval-date-correction-reason 'Reason supported by the retrieval evidence'`
to `population-import`, with a new output directory. This explicit exception to
refresh-date preservation changes the dataset version and records the previous
date, corrected date and reason in operator evidence. Ordinary refreshes continue
to reuse the last successful snapshot without changing its version.

## Verification, versioning and activation

Synthetic unit tests run without downloads:

```bash
.venv/bin/python -m unittest tests.test_population tests.test_population_checker -v
```

For explicit real-data acceptance, set `POPULATION_SHA` to the returned candidate
version and use the actual candidate path:

```bash
.venv/bin/python tools/check_population_data.py \
  --dataset .local/releases/canada-population-reviewed \
  --manifest-sha256 "$POPULATION_SHA" \
  --plan .local/population/crosswalk-reviewed.json --source-dir .local/population \
  --national-boundaries .local/canada-legacy/run-2025-final/source.zip
```

The optional last argument is the checksum-pinned national 2025 source already
used by the original geography build. The checker re-parses source facts, compares
every stored calculation, audits all catalogue pages and prints bounded aggregate
coverage/examples. It does not download or publish anything.

After a separately authorized deployment, use a server-held
`MAPS_ACCEPTANCE_TOKEN` and the exact intended version:

```bash
.venv/bin/python tools/check_population_api.py \
  --url https://maps.totallynormal.io --expected-version "$POPULATION_SHA"
```

The read-only checker uses public area identities, refuses redirects, checks
summary/cache isolation, pinned pages, known/zero examples and stale-version 412.
It prints versions, byte counts and check names, never credentials or bodies.
The known public sample counts and source identities are checked against the
reviewed census snapshot; an official correction needs explicit re-review of
those acceptance fixtures, not removal of the check.
The summary remains bounded to 16 KiB with `representation_revision: 1`.

Population and provenance are included in the immutable dataset manifest identity.
A correction changes `dataset_version` and the summary ETag. Unchanged summaries
retain authenticated 304; stale `If-Match` retains 412, including across pages.
Catalogue responses remain `no-store`; authenticated reference caching remains
`private, no-cache` with credential isolation. No geometry/classification change
manifest currently lets consumers skip reclassification on population-only updates.
Gati must use its full version refresh initially. A future optimization must retain
the dataset version as the update signal and be coordinated separately.

**Prepared, tested and selected for publication.** `dataset.source.json` pins
`canada-population-20260928` at manifest SHA-256
`e64e5b9f92f7722320f68841ee20d110232a7ada5f5941fce4e6d9bd1e283201`.
The normal [release procedure](RELEASING.md) publishes that immutable attachment
and updates `dataset.lock.json` before deployment. Publication does not deploy the
service: production activation needs the new code **and the pinned data bundle**.
New code accepts old bundles and reports
`no_source`; old code rejects the new SQLite tables, so deploy paired code/data and
roll back the complete previous bundle. There is no in-place production migration,
new infrastructure, visitor credential or automatic refresh schedule. Coordinate
the first publication with Gati because a dataset change triggers its full catalogue
refresh and place reclassification; Gati sorting/UI adoption is separate work.
