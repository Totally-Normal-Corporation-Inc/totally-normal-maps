# Familiar regional names: implementation decisions

Reviewed September 16, 2026. These are geographic browsing groupings, not new
governments, service entitlements, Indigenous territories or legal boundaries.
The selection favours names used by residents and public institutions.

## Coverage and interpretation

| Phase | Jurisdiction | New groups | Grouped CSDs | Still directly under province/territory |
|---|---|---:|---:|---:|
| 1 | Manitoba | 8 | 241 | 0 |
| 1 | Northwest Territories | 5 | 33 | 8 |
| 2 | Newfoundland and Labrador | 5 | 142 | 230 |
| 2 | Yukon | 3 | 11 | 22 |
| 3 | Alberta | 2 | 27 | 392 |
| 4 | Saskatchewan | 0 | 0 | 995 |

The catalogue now contains **144 regions**, with 3,385 of 5,054 CSDs grouped.
The previous 121 region identities and memberships are preserved. Existing Ontario
and British Columbia gaps remain explicit too. CSD means census subdivision:
municipalities and statistical equivalents, including reserves and unorganized land.

**A region's familiar name does not give us an exact polygon or an exhaustive
community list.** Thirteen of the new groups use explicitly selected communities.
Their outlines are the union of those communities' existing CSD polygons, not
complete regional boundaries. Do not use them as exhaustive regional geofences.
Unassigned towns remain available directly under their province or territory.
Missing assignment means insufficient qualified evidence, not lack of regional identity.

Membership and geographic qualification are separate. Even a complete list of CSDs
does not make a derived outline an official legal boundary. Existing unapproved
repairs remain excluded from normal geometric matches; they are never approved
merely because a new regional grouping uses them.

## 1. Manitoba and Northwest Territories

### Manitoba

The [Manitoba Arts Council regional map](https://artistsinschools.ca/wp-content/uploads/2020/03/MB-Regions.pdf)
uses familiar names on a census-division substrate. The
[Manitoba Bureau of Statistics division table](https://www.gov.mb.ca/mbs/publications/manitoba_csd_total_maps.pdf)
independently provides the underlying division groupings. The implementation
crosswalk is our reviewed adaptation of these references to the pinned 2025 CSDs:

| Name | Manitoba census divisions |
|---|---|
| Eastman | 1, 2, 12 |
| Interlake | 13, 14, 18 |
| Parkland | 16, 17, 20 |
| Westman | 5, 6, 7, 15 |
| Central Plains | 8, 9, 10 |
| Pembina Valley | 3, 4 |
| Northern Manitoba | 19, 21, 22, 23 |
| Winnipeg | 11 |

`Parklands` and `Norman` remain aliases. Winnipeg means the census-division
footprint (Winnipeg and Headingley in 2025); **not** the broader metropolitan
region. The Arts Council map's `Capital Region` label is therefore not an alias.
Travel and health-region boundaries can differ from this browsing definition.

### Northwest Territories

Use Municipal and Community Affairs' published community lists:
[Beaufort Delta](https://www.maca.gov.nt.ca/en/beaufort-delta-region),
[Sahtu](https://www.maca.gov.nt.ca/en/sahtu-region),
[Dehcho](https://www.maca.gov.nt.ca/en/dehcho-region),
[North Slave](https://www.maca.gov.nt.ca/en/north-slave-region), and
[South Slave](https://www.maca.gov.nt.ca/en/south-slave-region).
The display name Sahtú has an accent-insensitive `Sahtu` alias.

The crosswalk explicitly puts Łutselk’e in North Slave despite its census division
5, and Fort Providence, Kakisa and Kátł’odeeche in South Slave despite division 4.
Kátł’odeeche maps to the distinct source CSD `Hay River Dene 1`, not Hay River town.
Gametì/Gamètì, Behchokǫ̀/Behchokò, Deline/Déline and other spelling differences are
resolved to pinned IDs, never through runtime fuzzy name matching.

All 33 listed CSDs are included. The six numbered unorganized CSDs, Reliance and
Salt Plains 195 remain unassigned. Their full land extent cannot be inferred from
the location of a nearby community. The
[GNWT departmental polygon layer](https://www.apps.geomatics.gov.nt.ca/arcgis/rest/services/GNWT/Boundaries_LCC/MapServer/9)
was examined but not substituted for a qualified MACA boundary crosswalk. Other
departmental or Indigenous regional systems are not asserted to be interchangeable.

## 2. Newfoundland and Labrador and Yukon

### Newfoundland and Labrador

Avalon Peninsula follows division 1, as identified in Statistics Canada's
[geographic descriptions](https://www150.statcan.gc.ca/n1/pub/71-543-g/2020001/app_ann_a-eng.htm).
Labrador follows divisions 10 and 11. The provincial
[Rural Secretariat map](https://stats.gov.nl.ca/Maps/PDFs/RS_NL.pdf) was visually
checked; it is a different nine-region scheme and is not relabelled as the five
tourism regions. Its Labrador outline supports the broad geographic distinction;
the national source boundary, islands and coastline remain authoritative here.

For the remaining three names, current coverage is deliberately narrow:

- **Central Newfoundland:** Gander, Grand Falls-Windsor, Twillingate, Fogo Island,
  Change Islands. Evidence: [official regional destinations](https://www.newfoundlandlabrador.com/destinations/central-region)
  and [Grand Falls-Windsor's municipal description](https://grandfallswindsor.com/business/economic-development/).
- **Western Newfoundland:** Corner Brook, Deer Lake, Rocky Harbour, St. Anthony,
  Channel-Port aux Basques. Evidence: [official regional description](https://www.newfoundlandlabrador.com/destinations/western-region)
  and the [provincial visitor survey](https://www.gov.nl.ca/tcar/files/Peak-Season-Non-resident-Visitor-Survey_Final.pdf).
- **Eastern Newfoundland:** Bonavista, Trinity (Trinity Bay), Port Rexton, Elliston,
  Fortune, Grand Bank, Clarenville, Marystown. Evidence:
  [official regional destinations](https://www.newfoundlandlabrador.com/destinations/eastern-region)
  and the [resident-facing provincial regional directory](https://www.gov.nl.ca/vpi/information-about-violence/where-to-get-help/eastern-region/).

These are **18 verified communities, not an exhaustive list**. Census divisions 3
and 7 cross the candidate regional groupings; relabelling entire numbered divisions
would misclassify communities. Remaining work is to qualify an exhaustive
community crosswalk and independent regional outlines before claiming full coverage.

### Yukon

Select three well-established names using the territorial
[regions and communities directory](https://www.travelyukon.com/en/discover-yukon/regions-communities),
also used in the [public campground directory](https://yukon.ca/en/find-status-yukon-campgrounds-and-recreation-sites):

- **Klondike:** Carmacks, Dawson.
- **Kluane:** Beaver Creek, Burwash Landing, Destruction Bay, Haines Junction.
- **Southern Lakes:** Carcross, Marsh Lake, Mount Lorne, Tagish, Teslin village.

These names select 11 CSDs. Carcross 4, Teslin Post 13 and Teslin land are distinct
from the settlements; no automatic same-name or enclosing-region relationship is
created. Yukon, Unorganized is not assigned wholesale to any of these regions.

The [open tourism-region dataset](https://open.yukon.ca/data/yukon-tourism-regions)
explicitly warns that its **nine wilderness-statistics regions differ from the
eight visitor regions**. Those polygons were therefore not used as a substitute
for this community-based selection. Other Yukon communities remain direct children
of the territory, including Whitehorse.

## 3. Alberta

Add **Peace Country (Alberta)** and **Central Alberta**, with selected membership.
The Peace name extends into British Columbia; the province hierarchy here includes
only its Alberta portion and leaves BC's existing groupings unchanged.

The [Peace Region Economic Development Alliance membership list](https://peacecountrycanada.com/welcome-to-preda/preda-membership/)
supports ten selected towns/villages plus the municipal districts of Grande Prairie,
Fairview, Peace and Spirit River. Grande Prairie city is additionally supported by
its [resident-facing municipal description](https://cityofgp.com/parks-recreation/facilities-venues/centre-creative-arts).
The result has 15 CSDs. Large peripheral alliance members are not automatically
declared to be entirely inside the familiar Peace Country geography.

Central Alberta has 12 selected CSDs: Red Deer city and county, Lacombe city and
county, Innisfail, Trochu, Kneehill County, Didsbury, Sylvan Lake, Clearwater County,
Rocky Mountain House and Blackfalds. Sources include
[CAEP municipal representation](https://www.investcentralalberta.ca/about-us),
[Red Deer](https://www.reddeer.ca/business/business-environment/why-red-deer/),
[Blackfalds](https://blackfalds.ca/careers),
[Sylvan Lake](https://www.sylvanlake.ca/public/download/files/310484), and
[Lacombe](https://www.lacombe.ca/156/Amenities-Facilities).

Alliance membership is corroborating evidence of regional association, not a
complete cultural boundary definition. Separate towns, reserves and municipalities
surrounded by county polygons are not filled in or assigned automatically.
The other 392 Alberta CSDs remain directly under the province. No land-use watershed
or new destination-marketing brand is substituted as a province-wide layer.

## 4. Saskatchewan

Keep **province → municipality**. This is an intentional product/data decision,
not a missing implementation or a claim that the province lacks regional identity.
[Swift Current](https://www.swiftcurrent.ca/about-us/location-and-map) uses Southwest
Saskatchewan, while [Tourism Saskatchewan](https://business.tourismsaskatchewan.com/marketing-your-business/leveraging-the-saskatchewan-brand)
expressly describes its four travel zones as marketing creations. Neither these
brands nor numbered statistical divisions have been qualified as the desired default.

Reopen this decision when resident-facing evidence supports a useful named region
and we can pin either its explicit community membership or a reusable boundary
source. Partial, well-evidenced coverage is acceptable; an invented complete
partition is not required. All 995 existing CSDs remain browsable and searchable.

## Reproducibility and public data

The version-2 [plan](../../totally_normal_maps/regions-2026-09.json) pins source IDs,
original names/types, counts, identity digests, evidence URLs, review dates and
explicit exclusions. Normal builds do not scrape these websites. Updates to
membership require a reviewed plan change and a new immutable dataset release.
Whole-division and explicit membership share the same selector for validation,
geometry and hierarchy generation; duplicate or cross-province membership is rejected.

Only factual regional associations and citations are recorded from the additional
references. No third-party maps, website content, photographs or proprietary
polygons are redistributed. All new outlines use the already licensed Statistics
Canada source, with its existing attribution. The MIT code licence does not replace
the source-data licences. Downloaded reference PDFs and generated artifacts remain
in ignored local storage. See [DATA.md](../DATA.md) for build and release commands.
