# Parallel electoral geography

Reviewed 2026-09-19. Electoral districts are independent of regions, municipalities
and city areas. Every district has exactly one province/territory parent. A national
view gathers those branches; it creates no duplicate district or extra parent.

The optional electoral release includes 343 federal districts, 783 current
provincial/territorial districts and 125 historical Québec districts: 1,251 boundary
records in 15 editions. The existing published dataset lock is unchanged.
The [implementation review](electoral-review.md) records subsequent fixes,
regression cases and real-data verification.

## Pinned source inventory

The pinned plan is `totally_normal_maps/electoral-2026-09.json`. It records exact
file hashes, CRS, publisher fields, identity digests, provincial counts, edition
selection and source/reuse evidence. Archives stay outside the Python package.

| Layer/jurisdiction | Districts | Boundary edition and evidence |
|---|---:|---|
| Federal | 343 | [Elections Canada, 2023 representation orders](https://www.elections.ca/content.aspx?dir=cir%2FmapsCorner%2Fedb&document=index&lang=e&section=res); names include the September 16, 2026 changes |
| Newfoundland and Labrador | 40 | [2015 district polygons linked by Elections NL](https://opendata.gov.nl.ca/public/opendata/page/?id=361&page-id=datasetdetails) |
| Prince Edward Island | 27 | [Government district layer, 2017](https://gis.princeedwardisland.ca/server/rest/services/Hosted/prov_electoral_districts_2017/FeatureServer/0) |
| Nova Scotia | 56 | [Elections Nova Scotia district finder](https://enstools.electionsnovascotia.ca/edinfo/), its ED2026_Analysis service, including Chéticamp-Margarees-Pleasant Bay |
| New Brunswick | 49 | [Elections NB, 2023 boundaries](https://www.electionsnb.ca/content/enb/en/maps/PED.html), 2026 source snapshot |
| Québec | 127 | [2026 Assembly map](https://www.electionsquebec.qc.ca/cartes-electorales/revision-de-la-carte-electorale-du-quebec/la-carte-electorale-delimitation-finale/), used for the 2026 election |
| Québec historical | 125 | [2017 boundary set, 2022 source edition](https://dgeq.org/archives.html) |
| Ontario | 124 | [2018 boundaries, official 2022 district download](https://www.elections.on.ca/en/resource-centre/electoral-districts/current-electoral-district-maps.html), retained for the 2025 election |
| Manitoba | 57 | [2018 boundaries](https://electionsmanitoba.ca/En/Resources/Maps); combine the 25-feature rural and 32-feature Winnipeg products |
| Saskatchewan | 61 | [2022 boundaries, 2024 constituency shapefile](https://www.elections.sk.ca/candidates-political-parties/maps/); district ZIP inside the publisher archive |
| Alberta | 87 | [Government of Alberta current 2019 division layer](https://open.alberta.ca/dataset/gda-e201c640-1f76-429c-8c24-89ff496f956e), open-government product rather than the separately restricted Elections Alberta download |
| British Columbia | 93 | [2023 boundary set 11](https://catalogue.data.gov.bc.ca/dataset/1cba4b16-263f-4d42-8d84-f5fecaa03d1a), full WFS features |
| Yukon | 21 | [2024 boundaries](https://open.yukon.ca/data/yukon-electoral-districts), used in the 2025 election |
| Northwest Territories | 19 | [GNWT electoral districts](https://www.apps.geomatics.gov.nt.ca/arcgis/rest/services/GNWT/Boundaries_LCC/MapServer/2), ElectoralYear=2023 |
| Nunavut | 22 | [Elections Nunavut 2025 constituencies](https://www.elections.nu.ca/en/document/maps-constituencies-gis-2025) |

Nova Scotia's increase from 55 to 56 is corroborated by the official
[2026 by-election announcement](https://news.novascotia.ca/en/2026/05/24/byelection-called-cheticamp-margarees-pleasant-bay).
PEI's service has misleading copied Nova Scotia descriptive text. Its actual extent,
district numbers and names identify PEI. The explicitly documented blank district 0
is a non-district remainder; it is excluded, leaving the 27 numbered districts.
No polling-area layer is substituted for district boundaries.

## Identity and editions

IDs include the layer/jurisdiction boundary set and the source code, for example
`ca-fed-2023-24001` and `ca-qc-2026-211`. Names are attributes. A rename within a
boundary set can retain its ID across immutable dataset releases. A redistribution
has a new boundary-set namespace, even when the authority reuses a number.
Do not infer legal continuity from a reused number or overlapping polygons.

Where the publisher supplies no electoral code, the plan pins a catalogue identity
mapping and records `identity_basis`. These numbers are not official district codes.
Retain the assigned catalogue identity when updating a source name; do not regenerate
the mapping from alphabetical order. Publisher feature IDs are labelled separately.

Each edition records authority, boundary set, electoral event, status and explicit
default selection. Dates are nullable when only an electoral event is evidenced.
Defaults are fixed by the release and never change according to the server clock.
Historical and upcoming editions remain accessible only through explicit selection.
The importer can append an edition and change default selection while retaining
earlier records. Documented predecessor links require existing IDs and evidence;
none are fabricated for this initial import. Older immutable releases remain intact.

## Geometry and validation

Imports use complete publisher polygons, transformed from the declared source CRS.
Province overview polygons are display-only and are never clipping masks.
Simplification produces separate display files. Invalid input/transformed geometry
has no assignment boundary; any make_valid candidate remains explicitly unapproved.
The initial import retains seven unapproved candidates: Wood River in Saskatchewan
and PEI districts 5, 8, 18, 19, 23 and 26. All have display outlines and no assignment
boundary. Candidate generation stays in WGS84 to avoid reintroducing ring
self-intersections during a projection round trip; area measurements use EPSG:3347.
Shared boundary points can match adjacent districts. Overlaps are evaluated within
each edition, independently of administrative geography and other electoral layers.

Validation checks checksums, complete feature inventories, unique identities,
provincial counts, CRS, geometry, within-edition intersections and representative
point lookup. Intersections over 1 m² are reported without deleting slivers. The largest observed
intersection is about 36,446 m² in New Brunswick; it remains an ambiguous lookup
where both source districts cover the point.
The source inventory is exhaustive for its edition; a claim of gap-free legal
coverage is not made without an independent authoritative jurisdiction envelope.

Nunavut explicitly pins EPSG operation 1842, NAD83(CSRS) to WGS 84 (1), with the
registered 2 m approximation. PROJ's 1 m Helmert alternative crosses the geographic
pole for Quttiktuq's near-pole vertex, causing a longitude discontinuity and invalid
planar polygon. The pinned operation preserves the source vertices without clipping
the pole. The operation, accuracy and reason travel in source and area metadata.
This is not sub-metre or legal-boundary geography.

## Reuse qualification

Public availability and geographic validation do not establish redistribution rights.
Federal data has an explicit [Open Government Portal licence](https://open.canada.ca/data/en/dataset/18bf3ea7-1940-46ec-af52-9ba3f77ed708).
Québec's [specific open-data licence](https://dgeq.org/licence.html) covers the boundary
downloads linked from that portal and requires its full attribution statement.
Ontario district boundaries use the Open Use agreement; its separate polling-division
agreement is not used. BC, Alberta, NB, NL and Yukon have product-specific open terms
or catalogue evidence recorded in the plan.

Reuse of the exact Manitoba, Saskatchewan, Nova Scotia, PEI, NWT and Nunavut products
remains **unconfirmed**. Generic government terms are not automatically treated as
permission from an independent electoral authority. These products are included for
local geographic review, with their publisher attribution and unresolved status.
The public dataset publication command refuses these sources until their reuse
evidence is resolved in a newly reviewed plan and release. Local packaging and
review do not publish data. No publisher has been contacted on the user's behalf.

## Reproduce and verify

Download explicitly, outside tests; a changed live source fails its pinned hash:

```bash
.venv/bin/maps download-electoral --source fed --output .local/electoral-sources/federal.zip
```

Repeat for the source keys/filenames in the plan. ArcGIS downloads enumerate object
IDs, check counts and detect edits during acquisition. WFS acquisition requires the
complete count and removes generated transport IDs before canonical serialization.
Neither builds nor serving processes access these remote services.

```bash
.venv/bin/maps electoral --dataset .local/releases/canada-topology-reviewed-20260919 \
  --source-dir .local/electoral-sources --output .local/releases/canada-electoral-review
.venv/bin/python tools/check_electoral_data.py --dataset .local/releases/canada-electoral-review \
  --baseline .local/releases/canada-topology-reviewed-20260919
.venv/bin/python -m unittest tests.test_electoral tests.test_source_acquisition -q
.venv/bin/python tools/check_map_electoral.py --url http://127.0.0.1:9010
```
