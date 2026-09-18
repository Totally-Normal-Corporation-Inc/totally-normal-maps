# Ontario coverage audit

Reviewed 2026-09-18 against the local Québec-refresh serving release and current
public provincial/municipal sources. This audit does not change Ontario geography
or approve any repair. Source downloads and detailed lookup results are retained
under ignored `.local/ontario-audit/`.

## Current coverage

| Layer | Present | Qualification / gap |
|---|---:|---|
| Regional groupings | 40 | Names match the province's 30 upper-tier municipalities and ten districts. Seven derived outlines have unapproved repairs. |
| Municipal/statistical areas | 578 | 414 local municipalities, 144 reserve CSDs, four settlement CSDs and 16 unorganized areas. Seven assignment polygons unavailable pending repair review. |
| City areas | 0 | No Ontario former-city sectors, neighbourhoods or comparable city subdivisions are imported. |

The municipal source has a **2025-01-01 boundary reference date**. A valid polygon
and a successful lookup do not establish that a boundary is current in 2026.

The provincial comparison uses [Ontario's municipal boundary catalogue](https://data.ontario.ca/dataset/municipal-boundaries),
whose lower/single-tier and upper-tier/district layers are published by Land
Information Ontario under the Open Government Licence – Ontario:

- [Lower/single-tier layer 14](https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/LIO_OPEN_DATA/LIO_Open03/MapServer/14):
  685 records represent **414 municipality names**, with mainland, island and water
  records separated. Those records must not be counted as 685 municipalities or
  reduced to mainland polygons when preparing an assignment layer.
- [Upper-tier/district layer 13](https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/LIO_OPEN_DATA/LIO_Open03/MapServer/13):
  98 records represent **40 names**, all represented in our region layer.

All 414 local municipality names reconcile after punctuation/diacritic and bilingual
normalization and explicit Prince Edward County / Prince Edward and Tarbutt and
Tarbutt Additional / Tarbutt variants. Hamilton city and Hamilton township remain
separate identities. This checks identity coverage, not all current boundaries.
Ontario's [444-municipality list](https://www.ontario.ca/page/list-ontario-municipalities)
also counts the 30 upper-tier municipalities; it should not be compared directly
with the number of local municipal CSDs.

## Regional structure

The existing layers include Durham, York, Peel, Halton, Niagara, Waterloo, Simcoe,
Muskoka and the geographic counties and northern districts. They describe geographic
groupings, not municipal government jurisdiction. For example, a geographic county
can include administratively separate cities or reserve geography.

**561 of 578 CSDs** have a regional parent. The remaining **17 CSDs**, in nine
excluded generic census-division groups, appear directly below Ontario. These are
intentional omissions of a duplicate regional level, not missing municipalities:

- Ottawa, Toronto, Hamilton, Prince Edward County, Kawartha Lakes;
- Haldimand County and Norfolk County, with the two associated reserve-part CSDs;
- Brant and Brantford, with two reserve-part CSDs;
- Chatham-Kent and Moravian 47;
- Greater Sudbury and Wahnapitei 11.

Peel should remain: its [official transition update](https://peelregion.ca/transition/service-transfer-updates)
confirms that dissolution was cancelled. Changes to service responsibilities do not
by themselves remove the geographic regional identity.

Broad areas such as the GTA or Eastern Ontario are not an additional imported
layer. They would need their own explicit definition and hierarchy/overlap policy;
their absence is a product-scope choice, not evidence that York or Durham is missing.

## Confirmed boundary freshness gaps

At least **four completed boundary adjustments affecting nine municipalities**
postdate the retained national boundary reference:

| Effective date | Municipalities / retained CSD IDs | Evidence |
|---|---|---|
| 2026-01-01 | Barrie `3543042`, Oro-Medonte `3543023`, Springwater `3543009` | [Ontario decision: approximately 1,673 hectares transferred to Barrie](https://ero.ontario.ca/notice/025-1324); [city update](https://www.barrie.ca/BoundaryExpansion) |
| 2026-01-01 | Woodstock `3532042`, Norwich `3532002` | [Adopted restructuring order, Ontario Gazette January 17, 2026](https://www.ontario.ca/document/ontario-gazette-volume-159-issue-03-january-17-2026/government-notices-other) |
| 2026-01-01 | Casselman `3502044`, The Nation / La Nation `3502025` | [Municipality's confirmation of provincial approval](https://www.casselman.ca/en/news/the-province-has-approved-a-municipal-restructuring-proposal-to-transfer-a-portion-of-land-from-the-nation-municipality-to-the-municipality-of-casselman) |
| 2026-05-01 | Hanover `3542029`, West Grey `3542004` | [Municipal announcement of the adopted order](https://www.hanover.ca/news/looking-future-ministerial-order-supports-long-term-economic-prosperity-town-hanover-and) |

The early Woodstock consultation proposed January 2025; the adopted order specifies
January 2026. Use the adopted instrument, not the older proposal. Provincial feature
edit timestamps likewise do not establish a legal effective date.

The current provincial Barrie polygon was also inspected as a source cross-check.
It intersects portions of our old Oro-Medonte and Springwater polygons and differs
from our old Barrie outline. Differences include boundary-family/water differences;
a raw symmetric difference must not be labelled the legal annexation footprint.
A refresh must reconcile the complete affected municipal polygons and preserve
history and source provenance rather than patching a displayed outline.

This is a list of confirmed gaps, not an assertion that every Ontario boundary
change has now been exhaustively reconciled. The identity comparison does not audit
current Indigenous land or unorganized-territory definitions against separate sources.

A smaller naming improvement is to expose the current preferred municipal name
[Tarbutt](https://tarbutt.ca/) while retaining the national source name, stable CSD
identity and searchable historic variant. Prince Edward naming is a source-label
variant, not a missing municipality.

## Existing repair gaps

| CSD | Name | Affected regional outline |
|---|---|---|
| `3518020` | Scugog | Durham |
| `3543019` | Ramara | Simcoe |
| `3539017` | Chippewas of the Thames First Nation 42 | Middlesex |
| `3556092` | Cochrane, Unorganized, North Part | Cochrane |
| `3557095` | Algoma, Unorganized, North Part | Algoma |
| `3558090` | Thunder Bay, Unorganized | Thunder Bay |
| `3560090` | Kenora, Unorganized | Kenora |

All seven repairs change hole topology, despite very small net area changes. They
remain unapproved. Full assignment geometry is absent for these seven CSDs and
seven derived regions; display candidates do not substitute for assignment shapes.
Other members can still match by their valid municipal geometry, with the region
returned through the hierarchy and uncertainty reported. Source comparison and
repair adjudication are still required.

## City-area gaps and practical next sources

The entire Ontario city-area layer is missing. Familiar names such as Scarborough,
North York, Etobicoke, Kanata, Nepean, Orléans, Ancaster, Dundas, Stoney Creek,
Streetsville and Port Credit are not separately selectable city-area identities.
Their absence does not mean their enclosing present-day municipalities are missing.

| Priority source | What is available | What remains to qualify |
|---|---|---|
| Toronto | [158 social planning neighbourhoods](https://www.toronto.ca/city-government/data-research-maps/neighbourhoods-communities/neighbourhood-profiles/about-toronto-neighbourhoods/), with current and historical downloads in the city's [open-data catalogue](https://open.toronto.ca/dataset/neighbourhoods/) | Pin the current 158-area version, identities, full geometry, terms and parent coverage. The historical 140-area layer is a different version. A separate former-city layer is needed for broad Scarborough/North York/Etobicoke navigation. |
| Ottawa | [ONS Gen 3 neighbourhood source](https://open.ottawa.ca/datasets/ottawa::ottawa-neighbourhood-study-ons-neighbourhood-boundaries-gen-3/about); the city's [Gen 3 map service](https://maps.ottawa.ca/arcgis/rest/services/Neighbourhoods/MapServer/2) returns 116 identities | Qualify publisher version and polygons. ONS explicitly uses generalized study boundaries and may combine smaller communities. Broad former-city/community sectors require a separate evidenced definition. |
| Hamilton | [Six former-community polygons](https://services.arcgis.com/rYz782eMbySr2srL/arcgis/rest/services/Community_Boundaries/FeatureServer/17): Ancaster, Dundas, Flamborough, Glanbrook, Hamilton and Stoney Creek | Good candidate for the first broad sector layer. Check full geometry, names/IDs, terms and parent coverage. The separate neighbourhood service currently has 234 records and requires its own qualification. |
| Mississauga | City-published neighbourhood and character-area sources exist, including a 2016 neighbourhood dataset and newer official-plan material | Select the appropriate current familiar-area definition; do not treat old census neighbourhoods, planning character areas and wards as interchangeable. |
| London | City-published [planning districts](https://www.arcgis.com/home/item.html?id=5e086120a5c54832b7aa358887f388a8) used for neighbourhood profiles | Confirm suitability as the intended city-area layer and qualify source boundaries and terms. |
| Other Ontario cities | No imported city areas, including Brampton, Kitchener, Waterloo, Cambridge, Windsor, Kingston and Greater Sudbury | Separate city-by-city source and identity review remains. |

The city-area sources above are discovered candidates, not approved imports.
Toronto's social planning units and Ottawa's study areas do not capture every
colloquial neighbourhood. Wards are electoral geography and should not silently
replace familiar city areas, particularly around the 2026 municipal elections.

## Checks completed and recommended order

Original Ontario rows are unchanged from the earlier serving release: 578 CSDs,
40 regions and zero city areas. Representative interior lookups succeeded for all
**571 available CSD polygons and 33 available regional polygons**. Of those 604
probes, 182 retained review-required status because of uncertainty; none failed to
return its own full-geometry identity. These checks verify the implementation's
use of the retained source geometry, not its currency or legal completeness.

Recommended sequence:

1. Refresh the nine affected municipalities from the four confirmed adjustments,
   preserving old versions and checking complete shared boundaries.
2. Review the seven existing repair candidates without automatic approval.
3. Add familiar former-city/community sectors and neighbourhoods, beginning with
   Toronto, Ottawa and Hamilton, then Mississauga and other large cities.
4. Retain the 40-region structure; document any later broad-region overlay separately.

## Implementation follow-up

The [Ontario refresh](ontario-refresh.md) implements the nine boundary updates and
first three city-area layers. This audit remains the pre-refresh baseline; consult
the refresh report for current counts, source decisions and unresolved repairs.
