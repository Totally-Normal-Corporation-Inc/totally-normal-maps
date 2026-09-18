# Jurisdiction expansion: source qualification and remaining work

Review date: 2026-09-18. This is a **partial implementation of the nationwide
research plan**, with an explicit inventory of all 3,198 remaining baseline
municipal/statistical areas. It is not a completed audit of every municipal website
or a reconciliation of every municipal legal change since 2025. Of those inventory
rows, 3,184 still have `pending_municipal_site_review`; nine have qualified complete
or partial city-area sources and five have specific source-discovery barriers.

The new offline engine accepts province-scoped, parent-pinned plans. All eleven
jurisdictions have manifests and coverage reports. Existing regional memberships
remain unchanged: 87 groupings across these jurisdictions, with Saskatchewan's
regional layer deliberately absent. Municipal boundaries retain their explicitly
dated national source. All 47 existing municipal repairs in these jurisdictions
remain unapproved; the national total remains 58.

## Imported city areas

| Province/territory | City | Publisher identities imported | Assignment boundaries | Review-only boundaries |
|---|---|---:|---:|---:|
| BC | Vancouver | 22 | 21 | 1 parent mismatch |
| Alberta | Calgary | 313 | 311 | 2 parent mismatches |
| Alberta | Edmonton | 407 | 407 | 0 |
| Manitoba | Winnipeg | 237 | 237 | 0 |
| Saskatchewan | Saskatoon | 96 | 94 | 2 parent mismatches |
| New Brunswick | Saint John | 33 | 33 | 0 |
| New Brunswick | Fredericton | 74 | 72 | 1 repair, 1 parent mismatch |
| Nova Scotia | Halifax | 200 | 186 | 1 repair, 13 parent mismatches |
| Yukon | Whitehorse | 36 | 32 | 4 unresolved overlaps |
| **Added** | **9 cities** | **1,418** | **1,393** | **25** |

Together with Québec/Ontario, the local expansion release has 2,075 city-area
identities in 24 cities, 2,045 assignment boundaries and 30 unavailable assignment
boundaries. The latter comprise three missing Québec sector geometries, four
unapproved city-area repairs, 19 parent mismatches and four unresolved overlaps.
There are still 5,050 current municipal/statistical identities and 144 regions.

Counts above are independently pinned to the retrieved publisher collections and
checked against count endpoints where available. The manifests pin complete source
bytes, source identities, relevant name and classification attributes, and expected
invalid-feature sets. No electoral ward layer was substituted.

### Source decisions

- [Vancouver local areas](https://opendata.vancouver.ca/explore/dataset/local-area-boundary/):
  all 22 local planning areas; the union covers about 87% of the national municipal
  outline. Dunbar-Southlands has a substantial parent mismatch and is review-only.
  The source supplies names rather than numeric area codes; the manifest explicitly
  maps them to stable catalogue suffixes. Preserve that mapping when names change.
- [Calgary community districts](https://data.calgary.ca/d/surr-xmvs): 313 current
  features including residential, industrial, park and residual subareas. Residual
  areas 11B and 13N are almost entirely outside the national municipal parent and
  remain unavailable for assignment. No annexation is inferred from that mismatch.
- [Edmonton neighbourhoods](https://data.edmonton.ca/d/65fr-66s6): 407 current
  residential/industrial neighbourhoods with publisher neighbourhood numbers.
  None has an effective-end date in the pinned snapshot. Ward attributes are not
  city-area identities.
- [Winnipeg neighbourhoods](https://data.winnipeg.ca/d/8k6x-xxsy): 237 current
  neighbourhood characterization areas, distinct from older census partitions.
- [Saskatoon neighbourhood service](https://gisext.saskatoon.ca/arcgisod/rest/services/OD/LandSurface/MapServer/0):
  97 source records. Explicitly exclude ID 000, Planning 4 Growth, a predominantly
  extramunicipal planning envelope. Retain 96 neighbourhood/development-area
  identities; IDs 901 and 908 require parent qualification. The city's
  [open-data page](https://www.saskatoon.ca/services-residents/connect-your-city/open-data)
  documents reuse and the 2024 portal migration. Election-service copies were not used.
- [Saint John neighbourhoods](https://www.arcgis.com/home/item.html?id=338f69c642454516b877085043966e96):
  33 polygons with publisher geographic identifiers. Their union covers about 78%
  of the national municipal extent; uncovered extent is not invented as a neighbourhood.
- [Fredericton neighbourhoods](https://www.arcgis.com/home/item.html?id=3b3c641af58e4acfbee5603a34297ccf):
  The current city open-data licence is verified from its
  [complete publisher page data](https://www.arcgis.com/sharing/rest/content/items/814c4f293308411aba1d6f035e08683b/data?f=json);
  the older provincial-policy link is unavailable.
  74 features and about 64% municipal-extent coverage. OBJECTID 5 has an invalid
  ring and OBJECTID 6 a substantial parent mismatch. Object IDs and names are pinned;
  rebuilding the publisher service does not authorize assigning old IDs to new names.
- [Halifax communities](https://www.arcgis.com/home/item.html?id=b4088a068b794436bdb4e5c31df76fe2):
  200 official community outlines based on E911 and community consultation. The
  publisher identifies remaining consultation work. GSA 58 has an invalid hole;
  13 other areas exceed the parent-extent tolerance. All remain separate review cases.
- [Yukon subdivision metadata](https://www.arcgis.com/home/item.html?id=1e0abb1657404b808ed40c9284ed923a):
  36 Whitehorse neighbourhood/subdivision/commercial areas under the territorial
  open licence. The metadata link to layer 37 is stale: it returns a fire-service
  polygon. The checked subdivision layer is **27**, verified by its name, schema,
  NGUID identities and independent count. Coverage is about 7% of the large city
  extent. Whitehorse Copper, MacRae Industrial, Whitehorse Industrial (Marwell) and
  White Pass Industrial have unresolved overlaps. No parent/child hierarchy was
  inferred from their containment. The restrictive 2012 municipal download was not used.

Some publisher polygons have small sibling overlaps. The explicit source-specific
bounds allow retained, measured slivers; they never alter coordinates or suppress
lookup ambiguity. Significant unresolved overlaps are review-only. Coverage
measurements include review candidates when so labelled; they are not assignment
coverage percentages.

## Explicit gaps and unfinished audit

| Jurisdiction | Baseline inventory | Existing regions | Current gap or next qualification |
|---|---:|---:|---|
| NL | 372 | 5, partial membership | St. John's planning documents found; reusable neighbourhood geometry/licence unresolved. Municipal/planning boundaries must remain distinct. |
| PEI | 96 | 3 geographic counties | Provincial civic-address communities are not a complete inventory of recognized communities; no automatic substitution. |
| NS | 96 | 18 geographic counties | Other municipal community sources and Halifax review candidates need further work. |
| NB | 109 | 12 service commissions | Reconcile post-reform municipality changes; other municipalities and Fredericton exceptions remain. |
| MB | 241 | 8 named groupings | Municipal sources outside Winnipeg remain to be audited. |
| SK | 995 | 0 | Regina's official catalogue API returned 403. Third-party neighbourhood copies lacked sufficient reuse evidence. Other municipal searches remain. |
| AB | 419 | 2, partial membership | Adopted annexation reconciliation and city sources outside Calgary/Edmonton remain. |
| BC | 765 | 28, with exclusions | Other municipal neighbourhood portals and provincial boundary-vintage reconciliation remain. |
| YT | 33 | 3, partial membership | Resolve four Whitehorse overlaps and audit other communities. |
| NT | 41 | 5, partial membership | Yellowknife's public service inventory has boundaries/zoning/infrastructure but no identified neighbourhood layer. Other community sources remain. |
| NU | 31 | 3 | Iqaluit's discovered neighbourhood service requires authentication. Its public planning documents do not establish reusable polygon access/licensing. |

The per-municipality manifest status `pending_municipal_site_review` means exactly
that; it is not a finding that no source exists. `source_blocked` records the
specific inspected source barrier and does not claim an exhaustive municipal search.
No directory reconciliation, legal adoption date, repair approval or complete
national neighbourhood inventory is claimed by these initial manifests.

Continue the remaining audit against official municipal directories, individual
municipal portals and planning sources. Every status change needs the inspected
URL, date and substantive finding. New data must be qualified and rebuilt into
new immutable outputs, with compatible parent plans; changing checksums alone
is not qualification. The generic engine now supports evidenced municipal
succession, explicit city-area parent migration, and regional additions, membership
changes and retirement. These operations have synthetic acceptance tests; none is
asserted as a newly researched legal change in these eleven initial manifests.
Existing Québec lifecycle/history behavior is preserved. See the
[migration plan contract](../DATA.md#municipal-and-regional-migration-contract).

## Verification

The explicit real-data check probes every available city-area boundary, all
available municipal/regional boundaries in the eleven new jurisdiction reports,
Québec succession, Ontario deferrals and the original regional examples. Against
the corrected Ontario release it verifies unchanged original rows: 5,054 CSDs,
657 earlier city areas, 144 regions and 3,385 membership rows. Serving releases
exclude raw source downloads and research snapshots. Publication, secret scanning,
packaging and browser checks are separate from geographic approval.

The reviewed local expansion passed 2,045 city-area lookup probes, 1,270 Québec
municipal probes, 604 Ontario municipal/regional probes and 3,229 probes across the
remaining jurisdictions. Browser acceptance covers every newly imported city,
pagination, mobile layout and review-only boundaries. The local serving release
remains `review_required`; no data or package has been published.
