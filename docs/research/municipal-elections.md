# Municipal electoral coverage review — September 2026

The municipal electoral layer is independent of administrative neighbourhoods,
federal districts and provincial/territorial districts. Its scope includes council
wards and districts, Nova Scotia council polling districts, New Brunswick rural
advisory wards, and BC regional district electoral areas. It does not represent
school board boundaries, voting locations or every council seat elected at large.

The first national acquisition reviewed all 486 municipal-like boundary sets in
Open North Represent's inventory. Full shapes were joined to stable external IDs
using an independent inventory; no simplified shape endpoint was used. Newer
provincial and municipal sources supplement or replace the available snapshots.
The pinned plan records every considered set and its inclusion/exclusion reason.
Municipal/statistical equivalents retain their official identity, including
Indigenous communities and unorganized areas whose governance has not been
classified as an ordinary municipal council.

## Sources and scope

| Jurisdiction | Sources used and remaining limits |
| --- | --- |
| Newfoundland and Labrador | St. John's reference wards from Represent; other authorities remain unverified. |
| Prince Edward Island | Official provincial wards/polls feed; group polling areas by municipality and council district number. Cornwall's `Open` polling areas are not treated as wards. |
| Nova Scotia | Official provincial council polling districts and explicit `AL` at-large records. County government districts use county groupings for navigation, with partial scope notes for incorporated towns and Indigenous communities. |
| New Brunswick | Official Elections NB/GeoNB local-government electoral feed, including rural advisory wards and explicit at-large records. Post-reform official entity numbers map to current CSD identities; contradictory descriptive labels are recorded in the source audit. |
| Québec | Broad dated reference coverage from Represent, supplemented by official municipal downloads. Explicit 2025 editions include Montréal, Repentigny, Rimouski, Shawinigan and Saint-Hyacinthe. Older or undated snapshots are clearly marked reference. Sherbrooke city and borough council districts use separate schemes. |
| Ontario | Broad Represent ward coverage, with source dates retained and current applicability unverified. Fort Erie's projected coordinates were rejected because the API supplies no usable native CRS; St. Catharines failed the unique complete identity join. |
| Manitoba | Winnipeg reference wards; further municipal sources remain unverified. |
| Saskatchewan | City wards and rural municipal divisions available through Represent, retained as dated references. |
| Alberta | Current official Calgary ward inventory, supplemented by Represent city/county references. An official Edmonton ArcGIS item still contains old numbered wards and was rejected as a current source; the dated Represent reference remains available. |
| British Columbia | Official GeoBC regional electoral areas and Lake Country's four wards. At-large classification is limited to ordinary incorporated municipal types and is based on Lake Country's official statement that it is BC's only municipality using wards. Indigenous government districts and other governance types were not inferred. |
| Yukon | Whitehorse is explicitly recorded as at large using its official council page; other local governance coverage remains unverified. |
| Northwest Territories | Municipality-by-municipality coverage inventory exists; municipal electoral systems and shapes remain unverified. |
| Nunavut | Municipality-by-municipality coverage inventory exists; municipal electoral systems and shapes remain unverified. |

## Primary evidence

- [Represent API](https://represent.opennorth.ca/api/) and [source repository](https://github.com/opennorth/represent-canada-data).
- [Élections Québec's divided municipalities](https://www.electionsquebec.qc.ca/cartes-electorales/municipalites-divisees-en-districts-electoraux/) and the individual Données Québec datasets pinned in the plan.
- [Nova Scotia municipal polling districts](https://data.novascotia.ca/Municipalities/Municipal-Polling-Districts/gcep-xeci).
- [Elections NB local-government electoral GIS](https://geonb.snb.ca/arcgis/rest/services/GeoNB_ENB_Local_Government_Elections/MapServer/1).
- [PEI municipal electoral wards and polls](https://gis.princeedwardisland.ca/server/rest/services/Municipal_Electoral_Wards_and_Polls/FeatureServer/0).
- [BC regional district map explanation](https://www2.gov.bc.ca/gov/content/governments/local-governments/facts-framework/local-government-maps/regional-district-maps).
- [Lake Country's ward system](https://www.lakecountry.bc.ca/our-community/about-lake-country), [elections](https://www.lakecountry.bc.ca/elections) and [official GIS portal](https://www.lakecountry.bc.ca/maps).
- [Calgary ward maps](https://elections-prd.calgary.ca/for-candidates/ward-maps-profiles.html).
- [Edmonton's 2025 boundary update](https://www.edmonton.ca/sites/default/files/public-files/assets/elections/FebruaryEdmontonElectionsNewsletter.pdf).
- [Whitehorse's at-large council](https://www.whitehorse.ca/our-government/city-council/mayor-and-council/).

## Integrity and unresolved questions

Source feature counts, stable ID inventories, file hashes, CRS and geometry are
validated before import. Reprojection and display simplification do not authorize
repairing assignment geometry. Invalid source polygons remain unapproved display
candidates or unavailable boundaries. Source overlaps are reported; no coastline
clipping, invented remainder, gap filling or silent boundary correction occurs.
A legal gap assessment still requires an independent authority envelope.

The geographic authority join does not prove that every resident votes for that
council. Regional and county schemes need particular care around separately
governed communities. The complete local release still has unresolved private
source permissions and cannot yet be uploaded as one public bundle.

On 2026-09-20 the maintainer accepted application of the
[DGEQ open-data licence](https://dgeq.org/licence.html) to the 282 DGEQ municipal
source records acquired through Represent, with its exact French attribution
and non-endorsement statement. The plan records that maintainer review and marks
only those sources permitted; it does not claim a separate publisher confirmation.
The rebuilt release preserves their acquisition hashes, editions and boundaries.
Required source statements appear in the map footer and travel in report.json
and NOTICE.md. This initially left 110 source records requiring review.

The subsequent [government-source review](government-source-licences.md) approved
all 74 remaining government records: 39 under reviewed redistribution terms and
35 under the maintainer's explicit publication decision with unconfirmed exact
licence applicability, source citations and a good-faith contact notice. Their
licence status and publication decision are separate fields. The subsequent
maintainer decision puts **36 private MuniSoft council-division datasets** in
Saskatchewan on standby. The selected release excludes their 213 boundaries,
retains each municipality, and reports `unavailable` coverage with a licensing
explanation. The default import plan excludes these sources and editions;
`standby_licensing` inventory decisions retain the excluded edition IDs and counts.
Other approved western Canadian sources remain included. No licence has been
inferred or changed by this exclusion.

Every active municipal/statistical area has an explicit coverage entry at
`/v1/municipal-coverage`; province totals never imply complete municipal coverage.
The pinned plan's `source_inventory.decisions` is the exhaustive source review
list. The local acceptance report records exact counts, geometry checks and
preservation of all earlier administrative and electoral tables.

## Verified release inventory

The selected release contains **3,512 district records in 495 editions**. The default view
selects **820 current-source boundaries and 2,298 dated reference boundaries**;
394 records belong to other retained editions. There are **195 evidenced at-large
coverage entries**. All 5,050 active municipal/statistical areas are inventoried,
along with 36 regional authority scopes. **4,379 scopes remain unverified** and
**36 are unavailable while licensing is on standby**;
this release does not claim nationwide current municipal electoral coverage.

| Province / territory | District records, all editions | Default boundaries |
| --- | ---: | ---: |
| NL | 5 | 5 |
| PE | 31 | 31 |
| NS | 216 | 216 |
| NB | 295 | 295 |
| QC | 2,275 | 1,939 |
| ON | 409 | 365 |
| MB | 15 | 15 |
| SK | 20 | 20 |
| AB | 83 | 69 |
| BC | 163 | 163 |
| YT | 0 | 0 |
| NT | 0 | 0 |
| NU | 0 | 0 |

Validation checked all **3,455 usable municipal source geometries** through point
lookup. **57 unapproved geometries** remain excluded from full-boundary assignment.
The standby exclusion removes 204 usable boundaries and nine unapproved display
candidates; it does not approve any repairs.
The exact rows and geometry blobs in all seven earlier catalogue tables were
preserved. Federal/provincial acceptance also passed for 1,244 usable geometries
and retained all seven pre-existing unapproved boundaries.

## Earlier application acceptance

The original municipal import's offline suite passed 176 synthetic tests. Focused follow-up coverage tests
passed after the final selection semantics changes. Browser acceptance covers
municipal ward selection, sibling districts, neighbouring municipalities,
reference warnings, at-large and unverified scopes, comparison outlines, fitting
labels and mobile layout. Raw data, source inventories, test receipts and the
exhaustive 5,086-row coverage list remain in this repository's ignored `.local/`.

The packaged local image passed its read-only, offline runtime check with a 2 GiB
limit: startup took 30.66 seconds and peak memory including the probe was
774.2 MiB. The data-free Python wheel was also installed and checked against the
exact deployment code digest. The public publication-surface scan reported zero
unresolved findings.

## Standby release acceptance — 2026-09-20

The selected release is pinned in `dataset.source.json`. The 36 deferred sources
are absent from the database, serving display files and exported electoral area
inventory. All retained database rows and geometry blobs are byte-identical to
the preceding government review release. Only `catalogue.sqlite3`,
`display/municipal-47.geojson` and `report.json` changed, plus the release manifest.
Retained source pins, editions and geometry validation results are unchanged.

All 36 authorities have explicit `unavailable` coverage and zero published
districts. Coordinate checks return `review_required` without a municipal district
match. Three existing administrative polygons (Edenwold, Elcapo and Spiritwood)
remain unapproved; their display candidates have not been promoted to assignment
geometry. Seventy focused tests passed across imports, licensing, release
integrity, publication and deployment. The publication and secret scans passed.

`./package.sh --check` passes for the selected release. The former local release
still fails the unchanged redistribution guard for exactly 36 sources. The new
ZIP was packaged and unpacked with checksum and notice verification under
`.local/packages/dataset-93b6b00d115817a446e5-r1/`; it has not been uploaded.
Real-data, browser and packaging receipts are under
`.local/municipal-standby-20260920/` inside this repository. The normal publication
workflow runs after these changes are merged to clean, synchronized `main`.
