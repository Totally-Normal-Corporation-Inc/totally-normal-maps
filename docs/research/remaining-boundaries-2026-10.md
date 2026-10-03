# Remaining boundary review — 2026-10-03

This review attempts every one of the 67 records left after the municipal exclusion batch. It qualifies **38 additional records** (33 municipal electoral records and five PEI provincial districts), and retains **29** with individual evidence. All 58 constituent electoral districts in the pinned Montréal borough/district edition retain their assignment bytes and gain their evidenced borough parent. These electoral editions remain independent of administrative neighbourhoods and retain their original applicability qualifications.

No new source geometry was downloaded. Pinned local source snapshots supplied all repairs. Public metadata research for the unresolved scopes did not supply a qualified replacement. No publication, dataset-lock activation or deployment is part of this review.

## Evidence and decisions

The exact audit is embedded in the new release. It preserves source and candidate hashes, original metadata hashes, per-check decisions, affected areas and hierarchy changes. The [repair policy](../BOUNDARY_REPAIRS.md) documents original-ring face classification, exact retraces, measured narrow-strip corrections and source-child unions.

- The Montréal source combines 19 boroughs and 58 districts. Eighteen borough candidates exactly equal their unchanged district union. Lachine’s linework candidate differs from its three-district union by approximately 1,876,911 m²; both alternative source repairs agree exactly with the union. The source-child union replaces that candidate for assignment, and its display is regenerated using the existing simplification. This is explicit source evidence, not a minor-area exception.
- Five PEI districts relinquish narrow overlaps to existing validated owners. The measured strips satisfy the five-metre and 0.01% tests; a source-face-proven tier admits accumulated areas up to 6,000 m².
- Grande-Rivière, Sainte-Luce and Princeville contain disappearing slivers smaller than 1 m². La Tuque’s removed source components total approximately 15.076 m². Existing validated neighbours retain those pieces. Measurement densification avoids false projected-chord differences; stored coordinates are not densified.
- Kent District 2 is an importer-created collection of two polygon source parts. Comparing the unchanged parts as a MultiPolygon permits the bounded repair without discarding non-polygon source data.
- Bonnyville Ward 4 remains unresolved: source overlap totals approximately 93,918 m²; even an experimental enlarged area budget fails the five-metre displacement and source-corridor checks. No enlarged experimental budget was applied.
- Marysville passes the topology/minor-overlap tests but crosses Nashwaak and Devon 30. Enfield has an approximately 807,904 m² repair-method disagreement, plus a municipal-parent discrepancy. Neither is reduced to a topology-only approval.

## Unresolved relationships and missing sources

Calgary 11B and 13N lie mostly on Tsuu T’ina territory in the loaded municipal geography. Dunbar-Southlands crosses Musqueam 2 and small portions of Richmond and Metro Vancouver A. Saint Mary’s First Nation crosses Devon 30; the two Saskatoon development areas cross Corman Park. These are material parent/source-model discrepancies, not small boundary repairs. Halifax includes offshore/unmatched extents and two cases crossing other municipalities. “Unmatched” is a measurement, not proof that an area contains no land.

White Pass Industrial is completely contained by the Marwell polygon; MacRae and Whitehorse Copper overlap partially. The [city’s Marwell planning report](https://www.whitehorse.ca/wp-content/uploads/2022/09/Marwell-Area-Planning-Report.pdf) discusses White Pass land ownership within the broader area, but does not establish the exact two catalogue identities as parent and child. A qualified subdivision relationship or corrected ownership boundary is still needed.

Terrebonne’s [city history](https://terrebonne.ca/presentation-de-la-ville/) supports the three former-city identities. The [official map page](https://terrebonne.ca/cartes-interactives/) links services, zoning and electoral maps; no qualified reusable three-sector polygon source was obtained. The services application configuration and its 45-service public GIS inventory were inspected; the named administrative boundary layer covers the municipality rather than the three former-city sectors. No electoral or zoning geometry was substituted for the missing sectors. A licensed full sector source remains necessary.

## Every record

Outside and overlap measurements below use full source geometry and EPSG:3347 measurement, not display outlines. All unresolved identities and their displays remain available under their existing explicit qualifications.

| Stable ID / name | Disposition and evidence |
| --- | --- |
| `ca-ab-4806016-community-district-11b` — 11B | Retained: outside parent 3595805.7 m² (97.202%). Intersects ca-csd-4806804. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ab-4806016-community-district-13n` — 13N | Retained: outside parent 560139.4 m² (100.000%). Intersects ca-csd-4806804. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-bc-5915022-local-planning-area-dunbar-southlands` — Dunbar-Southlands | Retained: outside parent 2177128.4 m² (24.003%). Intersects ca-csd-5915015, ca-csd-5915020, ca-csd-5915803. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-nb-1331069-neighbourhood-5` — Marysville | Retained: topology repair passes; parent discrepancy 509307.2 m². Reconcile Nashwaak/Devon 30 geography. |
| `ca-nb-1331069-neighbourhood-6` — Saint Mary's First Nation | Retained: outside parent 1530431.9 m² (80.605%). Intersects ca-csd-1331034. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-169` — INDIAN HARBOUR | Retained: outside parent 4140146.5 m² (16.733%). Intersects ca-csd-1206009. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-174` — PEGGYS COVE PRESERVATION AREA | Retained: outside parent 9365079.6 m² (34.887%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-179` — DUNCANS COVE | Retained: outside parent 11350702.3 m² (39.720%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-182` — PROSPECT | Retained: outside parent 15449339.4 m² (44.746%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-184` — WEST DOVER | Retained: outside parent 4288347.9 m² (21.407%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-185` — PEGGYS COVE | Retained: outside parent 3581262.6 m² (55.731%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-191` — LOWER PROSPECT | Retained: outside parent 2294497.7 m² (16.150%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-50` — ECUM SECUM WEST | Retained: outside parent 4372460.3 m² (15.614%). Intersects ca-csd-1213001. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-58` — ENFIELD | Retained: detached source hole; alternative methods disagree by approximately 807,904 m²; East Hants parent discrepancy. Publisher correction needed. |
| `ca-ns-1209034-community-69` — SHEET HARBOUR PASSAGE | Retained: outside parent 19901412.0 m² (18.451%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-73` — SPRY BAY | Retained: outside parent 6462223.1 m² (11.976%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-75` — TANGIER | Retained: outside parent 6085239.9 m² (10.769%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-79` — SOBER ISLAND | Retained: outside parent 6754782.7 m² (13.757%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-ns-1209034-community-84` — POPES HARBOUR | Retained: outside parent 9121287.3 m² (15.767%). Parent/source-vintage reconciliation required; no large clipping. |
| `ca-qc-2464008-sector-la-plaine` — La Plaine | Retained: no qualified full source polygon; official sector geometry required. |
| `ca-qc-2464008-sector-lachenaie` — Lachenaie | Retained: no qualified full source polygon; official sector geometry required. |
| `ca-qc-2464008-sector-terrebonne` — Terrebonne | Retained: no qualified full source polygon; official sector geometry required. |
| `ca-sk-4711066-neighbourhood-901` — South East Development Area | Retained: outside parent 62177.4 m² (24.359%). Intersects ca-csd-4711065. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-sk-4711066-neighbourhood-908` — South Development Area | Retained: outside parent 190724.8 m² (41.467%). Intersects ca-csd-4711065. Parent/source-vintage reconciliation required; no large clipping. |
| `ca-yt-6001009-subdivision-013a8bf8-334f-4a18-9e00-c1fca84acdae` — MacRae Industrial Subdivision | Retained: ca-yt-6001009-subdivision-5e9ef638-e37d-4411-b184-1635eeef88c1: 220910.5 m² (partial overlap). Publisher relationship/ownership evidence needed. |
| `ca-yt-6001009-subdivision-5e9ef638-e37d-4411-b184-1635eeef88c1` — Whitehorse Copper Subdivision | Retained: ca-yt-6001009-subdivision-013a8bf8-334f-4a18-9e00-c1fca84acdae: 220910.5 m² (partial overlap). Publisher relationship/ownership evidence needed. |
| `ca-yt-6001009-subdivision-b1eec340-5853-4148-9eee-991cf76b368b` — Whitehorse Industrial Subdivision (Marwell) | Retained: ca-yt-6001009-subdivision-df51c9cb-b833-41bb-a5e6-0f6e5369abe7: 33650.9 m² (containment). Publisher relationship/ownership evidence needed. |
| `ca-yt-6001009-subdivision-df51c9cb-b833-41bb-a5e6-0f6e5369abe7` — White Pass Industrial Subdivision | Retained: ca-yt-6001009-subdivision-b1eec340-5853-4148-9eee-991cf76b368b: 33650.9 m² (containment). Publisher relationship/ownership evidence needed. |
| `ca-pe-2017-18` — Rustico - Emerald | Qualified: bounded correction/retrace; conservative affected-area budget 936.811395 m². |
| `ca-pe-2017-19` — Borden - Kinkora | Qualified: bounded correction/retrace; conservative affected-area budget 663.655646 m². |
| `ca-pe-2017-23` — Tyne Valley - Sherbrooke | Qualified: bounded correction/retrace; conservative affected-area budget 771.988190 m². |
| `ca-pe-2017-26` — Alberton - Bloomfield | Qualified: bounded correction/retrace; conservative affected-area budget 1349.722873 m². |
| `ca-pe-2017-8` — Stanhope - Marshfield | Qualified: bounded correction/retrace; conservative affected-area budget 3961.884470 m². |
| `ca-mun-1326106-nb-current-2` — District 2 | Qualified: bounded correction/retrace; conservative affected-area budget 0.595222 m². |
| `ca-mun-2402015-grande-riviere-districts-6` — District 6 | Qualified: bounded correction/retrace; conservative affected-area budget 0.819962 m². |
| `ca-mun-2407018-causapscal-districts-1` — District 1 | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². |
| `ca-mun-2409092-sainte-luce-districts-3` — District 3 | Qualified: bounded correction/retrace; conservative affected-area budget 0.041836 m². |
| `ca-mun-2432033-princeville-districts-2` — District 2 | Qualified: bounded correction/retrace; conservative affected-area budget 0.000881 m². |
| `ca-mun-2453052-sorel-tracy-districts-2` — Richelieu | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². |
| `ca-mun-2466023-montreal-boroughs-and-districts-1` — Ahuntsic-Cartierville | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-10` — Pierrefonds-Roxboro | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-11` — Plateau-Mont-Royal | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-12` — Rivière-des-Prairies—Pointe-aux-Trembles | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-13` — Rosemont—La Petite-Patrie | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-14` — Saint-Laurent | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-15` — Saint-Léonard | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-16` — Sud-Ouest | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-17` — Verdun | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-18` — Ville-Marie | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-19` — Villeray—Saint-Michel—Parc-Extension | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-2` — Anjou | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-3` — Côte-des-Neiges—Notre-Dame-de-Grâce | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-4` — Lachine | Qualified: exact union of three validated source districts; corrected borough hierarchy and display. |
| `ca-mun-2466023-montreal-boroughs-and-districts-5` — LaSalle | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-6` — L'Île-Bizard—Sainte-Geneviève | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-7` — Mercier—Hochelaga-Maisonneuve | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-8` — Montréal-Nord | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2466023-montreal-boroughs-and-districts-9` — Outremont | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². Exact child partition; district parents restored. |
| `ca-mun-2470040-saint-stanislas-de-kostka-districts-5` — District 5 | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². |
| `ca-mun-2470052-salaberry-de-valleyfield-districts-5` — District 5 | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². |
| `ca-mun-2472032-oka-districts-1` — District 1 | Qualified: exact source-face exclusion; unchanged territory. |
| `ca-mun-2472032-oka-districts-3` — District 3 | Qualified: exact source-face exclusion; unchanged territory. |
| `ca-mun-2490012-la-tuque-districts-1` — Parent | Qualified: bounded correction/retrace; conservative affected-area budget 15.076311 m². |
| `ca-mun-2494068-saguenay-districts-1` — District 1 | Qualified: bounded correction/retrace; conservative affected-area budget 0.000000 m². |
| `ca-mun-3518039-brock-wards-4` — Ward 4 | Qualified: exact source-face exclusion; unchanged territory. |
| `ca-mun-3526065-grimsby-wards-2` — Ward 2 | Qualified: bounded correction/retrace; conservative affected-area budget 243.089139 m². |
| `ca-mun-4812004-bonnyville-no-87-wards-4` — Ward 4 | Retained: neighbour_overlap_bounded, current_assignment_conflict. Source ownership/extent must be reconciled. |

## Verification and release state

- Full synthetic suite: **350 tests passed**; final focused boundary suite: **51 passed**.
- Build verification: **1,472 assignment probes** passed; every previous full assignment stayed byte-identical.
- Read-only real-data API acceptance passed, including **58** municipal hierarchy probes and unchanged-row comparisons across all administrative and electoral tables.
- Pre-package manifest: `c1568ab8f9675e42c61fba03233e4a8a0ae69858b4081afafe63fb80f6dd1d63`.
- Canonical audit digest: `fac6ec1b2b31a9b43d6040dfafd2ce41ed72f400112a9c053aadd663895b2035`.
- Packaged manifest: `bd29719079d3a0814b8b75ccd75f9bd2b16dae09a3d0671f2c0a12168030c740`.
- Audit plus re-audit/apply/verification: **315.4 seconds**, peak RSS **2369.6 MiB** on an Intel Core i5-3210M at 2.50 GHz, Python 3.14.7 / Shapely 2.1.2 / GEOS 3.13.1. These are local build observations, not serving benchmarks.
- Display preparation: **121.7 seconds**, peak RSS **1013.4 MiB**, **71,659,624 bytes** of package files. **5,337 ready** bundles and **nine unchanged unsupported** definitions. All **10,674** prepared administrative geometry files retain the previous release's exact hashes.

Use the documented audit/apply workflow with the previous municipal-exclusion **pre-package** release as input and all four pinned local source directories. No StatCan repair candidates remain, so that archive is unnecessary for this batch. Rebuild display packages afterward; package only the verified result with the current NOTICE. Every destination must be new.

The code handling reviewed electoral parentage must accompany this dataset. Older loaders require flat authority parentage and will reject the reviewed hierarchy. Clients should retain `authority_id` for authority grouping and traverse the actual `parent_id` relationships; see [the API contract](../API.md#municipal-electoral-geography). No new environment variables, service, queue or cloud changes are required. Existing code/dataset retention and rollback apply. Repository dataset selectors remain unchanged; production activation needs its separate release authorization.

The local distribution `canada-topology-batch-reviewed-v1.zip` is **255,754,873 bytes**, SHA-256 `ab359c3feb650abd5bfb6999a4ea366ad8b5e38719416d41fa679f4485d08524`. It was unpacked through the bounded distribution reader and the unpacked dataset passed `maps verify-release` against the packaged manifest. The generated lock proposes `dataset-bd29719079d3a0814b8b-r1`; that tag and asset have **not** been published.

Reproduction commands (set paths to new destinations and the recorded immutable inputs):

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python -m unittest tests.test_boundary_review
.venv/bin/python tools/check_real_data.py --dataset "$REVIEWED" --baseline "$PREVIOUS_REVIEWED"
.venv/bin/maps verify-release --dataset "$UNPACKED/dataset" --manifest-sha256 "$PACKAGED_SHA256"
```

Implemented and locally tested, release-built, packaged and unpack-verified. **Not pushed, published, activated or deployed.**
