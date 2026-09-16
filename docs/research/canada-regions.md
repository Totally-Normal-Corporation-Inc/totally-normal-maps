# Canada regional source decisions

Research snapshot: 2026-09-16. Dataset remains subject to review.

## Province-by-province decisions

| Jurisdiction | Added | Choice and limits |
|---|---:|---|
| Newfoundland and Labrador | Deferred | Numbered census divisions are unsuitable as the default browsing labels. Tourism regions are promising; a current reproducible polygon set and membership mapping need qualification. [Provincial tourism regions](https://www.gov.nl.ca/tcar/tourism-product-development2/) |
| Prince Edward Island | 3 | Kings, Queens and Prince geographic counties. No county-government relationship is asserted. [Provincial reference](https://www.princeedwardisland.ca/en/information/executive-council-office/provincial-flag) |
| Nova Scotia | 18 | Geographic counties. County geography stays separate from similarly named regional municipalities such as Halifax. [Provincial county statistics](https://novascotia.ca/finance/statistics/news.asp?id=21657) |
| New Brunswick | 12 | Post-reform regional service commission geographies, already present in the 2025 StatCan source. This avoids the obsolete 15-county division layer. [2025 source type table](https://www150.statcan.gc.ca/n1/pub/92-162-g/2025001/tbl/tbl4.3-eng.htm) |
| Québec | 17 | Régions administratives. A pinned CD-to-region crosswalk is cross-checked against provincial polygons; MRCs are not substituted for regions. [Official divisions](https://www.quebec.ca/gouvernement/portrait-quebec/cartes-donnees-quebec/decoupage-administratif) |
| Ontario | 40 | Named geographic counties/united counties, regional municipalities, Muskoka district municipality geography, and northern territorial districts. The nine generic CDR entries are excluded, leaving 17 CSDs ungrouped (including Ottawa and Toronto). A geographic county may contain a city that is administratively separate. [Ontario municipal structure](https://www.ontario.ca/document/ontario-municipal-councillors-guide/5-municipal-organization) |
| Manitoba | Deferred | Economic, tourism and service regions differ. Familiar names such as Interlake and Parkland are candidates, but a preferred complete boundary set has not been qualified. This does not mean Manitoba lacks regions. [Travel Manitoba regional examples](https://www.travelmanitoba.com/trip-essentials/know-before-you-go/) |
| Saskatchewan | Deferred | Tourism travel zones and numbered statistical divisions serve different purposes. A preferred complete geographic partition and reusable boundary source need qualification. [Tourism Saskatchewan travel zones](https://www.tourismsaskatchewan.com/places-to-go/travel-zones/learn-about-travel-zones) |
| Alberta | Deferred | The seven land-use regions follow major watersheds; numbered census divisions provide another scheme. Review the fit for geographic browsing before choosing either as the default. [Provincial land-use regions](https://landuse.alberta.ca/RegionalPlans/Pages/default.aspx) |
| British Columbia | 28 | 27 regional district geographies plus Stikine, explicitly labelled an unincorporated region. Northern Rockies remains municipal; its census division is not duplicated as a regional district (5 CSDs remain ungrouped). These spatial groupings do not assert jurisdiction over Indigenous communities. [Provincial Stikine explanation](https://www2.gov.bc.ca/gov/content/governments/local-governments/improvement-districts-governance-bodies/stikine) |
| Yukon | Deferred | The single census division duplicates the territory. Tourism regions exist, but a reusable boundary source and grouping have not been qualified. [Territorial tourism maps](https://www.travelyukon.com/en/trade/maps) |
| Northwest Territories | Deferred | Named departmental regions and the six numbered census divisions do not provide one interchangeable hierarchy. Select a current scheme with matching polygons first. [Regional centres](https://www.gov.nt.ca/careers/en/regional-centres), [departmental regional map](https://www.gov.nt.ca/ecc/en/content/enr-administrative-regions-map) |
| Nunavut | 3 | Qikiqtaaluk, Kivalliq and Kitikmeot geographic regions. No Inuit land-ownership/governance layer is inferred. [Territorial regional business search](https://nni.gov.nu.ca/business/search) |

Counts, exact source divisions, source types, member counts and member-ID
checksums are pinned in
[`regions-2026-09.json`](../../totally_normal_maps/regions-2026-09.json).
Every source census division must be assigned exactly once or explicitly
recorded as excluded. A new source release must be qualified with a new plan.

## Boundary and identity approach

Regional outlines are **derived by dissolving their member StatCan 2025 CSD
polygons**: interior municipal boundaries disappear while the full outer
coordinates, islands and holes remain. They are not represented as direct
copies of current provincial legal boundary files. This keeps the regional
and municipal layers on the same national geography vintage and avoids
silently moving the Québec/Labrador boundary or changing coastlines when
combining data from different publishers.

- Municipal rows, IDs and full geometries remain byte-for-byte unchanged.
- Region IDs have separate namespaces, such as `ca-qc-ra-07` and
  `ca-on-cd-3510`. The municipal ID for Gatineau stays `2481017`.
- `region` holds the local region metadata and full geometry; `csd_region`
  holds geographic membership with its evidence basis. Relationships describe geography, not governance.
- Québec's Montréal region includes all 16 municipal-level areas of the
  Montréal census division. It is distinct from the City of Montréal.
- `Greater Vancouver` keeps its source name and has a `Metro Vancouver`
  search alias.
- A region containing an unapproved repaired member has **NULL normal
  assignment geometry** and a separate unapproved regional candidate. A
  missing member geometry prevents a partial regional outline being published.
- Display geometry is simplified separately, at 200 metres by default.

### Québec crosswalk evidence

The independent reference is the government's
[Découpages administratifs dataset](https://www.donneesquebec.ca/recherche/fr/dataset/decoupages-administratifs),
[regional polygon service](https://servicescarto.mern.gouv.qc.ca/pes/rest/services/Territoire/SDA_WMS/MapServer/0),
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The snapshot was retrieved on September 16, 2026; its per-feature version is
`V2026-08`. The exact reference day is not supplied and is not invented.

The source query returns **18 features for 17 codes**, including the separate
`Côte-Nord (Tracé de 1927)` feature with code `09`. Its bytes remain in the
archived reference; it is explicitly excluded from crosswalk matching and is
not treated as an eighteenth administrative region or appended to the map.
The file's SHA-256 is
`c8d68716d2bff0d68cce417eca90e3aa475c6853abff2b6e39f8f92e514ac7a3`.

Every Québec census division was compared with the 17 named region polygons
using area intersections in EPSG:3347. Each has one clear best match; overlap
fractions range from **94.8266% to 100%**. Differences include river/coastal
geometry between the two sources. The smallest match is La Matanie; its
runner-up is about 5.13%. Builds recheck the pinned choices and reject a
changed winner, an overlap below 90%, or a runner-up above 10%.

These thresholds provide **crosswalk evidence for local review**, not automatic
production approval or a claim that provincial polygons exactly equal the
derived map. In particular, the 2025 divisions Brome-Missisquoi (`2446`) and
La Haute-Yamaska (`2447`) are grouped under Estrie, and Gatineau (`2481`) under
Outaouais. The code/label mapping and all measured overlaps are retained.
