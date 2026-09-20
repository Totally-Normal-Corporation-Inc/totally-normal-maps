# Saskatchewan council divisions: MuniSoft terms and replacement sources

Reviewed 2026-09-20. This is source research, not a boundary import or a new
publication approval. The 36 MuniSoft sources remain unresolved. Following the
maintainer's later instruction, their 213 boundaries are excluded from the
selected release and are on standby with explicit coverage gaps. The research
below is retained for future work. Their Represent reference date is 2014-05-16; a newly retrieved
map must not silently replace that edition or be called current without checking
its effective date.

## Findings

The search found one downloadable electoral GIS layer, for Edenwold, and three
useful non-MuniSoft map leads: Estevan, Vanscoy and Torch River. None is a fully
qualified replacement yet. Nineteen other municipalities have alternative-hosted
maps carrying express reproduction restrictions; these do not resolve the reuse
question. For the remaining thirteen, no usable internal-division source was
verified in this pass. This is an inventory of all 36 targets, not proof that no
other sources exist.

Searches covered provincial administrative GIS, the public ArcGIS catalogue,
each of the 36 municipality names, official municipal pages and their linked
maps, MuniSoft's public website and policy, and Open North's source documentation.
All 36 received an ArcGIS catalogue search; three broad searches were repeated
with a Saskatchewan constraint. Search results contain unrelated namesakes and
outer-municipality layers, which were not treated as council divisions.

## What was found about MuniSoft's licence

- MuniSoft's [website](https://www.munisoft.ca/home) has an all-rights-reserved
  copyright footer. Its [products page](https://www.munisoft.ca/products) advertises
  mapping services. No public map-data redistribution licence was located in the
  public home, about, products, contact or registration pages or the targeted
  licence searches. This does not establish what its customer contracts permit.
- The linked [2024 privacy policy](https://www.munisoft.ca/fileadmin/munisoft/storage/ClientDocuments/Important_Documents_and_Forms/MuniSoft_Privacy_Policy_-_2024.pdf)
  addresses personal-information handling, not permission to redistribute map
  geometry.
- Actual published maps provide more specific evidence. For example, the
  [Bone Creek map](https://www.rmofbonecreek.ca/Home/DownloadDocument?docId=fb652801-24db-427c-a570-96fe9ed89d5a)
  identifies MuniSoft and ISC-supplied data and says:
  **“Duplication in whole or in part is prohibited.”** Similar notices appear in
  the Caledonia, Clayton, Excelsior, Fish Creek, Frenchman Butte, Gull Lake, Hart
  Butte, Maryfield, Moose Mountain, Rudy, Silverwood, South Qu'Appelle, Webb,
  Whiska Creek and Willowdale maps reviewed here. The Wawken scan also retains
  a MuniSoft notice. These are map-specific restrictions, not the missing 2014
  Represent agreement.
- The [Represent metadata for Edenwold](https://represent.opennorth.ca/boundary-sets/edenwold-no-158-divisions/)
  names MuniSoft but leaves `source_url` and `licence_url` empty. The pinned local
  metadata for the other 35 has the same missing licence/source fields.
  [Open North's repository documentation](https://github.com/opennorth/represent-canada-data#license)
  distinguishes dataset-specific permissions and warns that API availability
  does not establish a right to redistribute every source shapefile. No licence
  for these 36 was found in the local public repository or its linked public
  source register. Its code's attribution rule is not a licence grant either.

The evidence supports **reuse unconfirmed for the exact 2014 datasets**, not a
claim that all MuniSoft geometry is prohibited. The newer map restrictions also
mean that changing the download host to a municipal website is insufficient by
itself. The earlier good-faith government-source decision did not resolve these
third-party notices. No licence statuses were changed by this research.

## Best replacement leads

### Edenwold No. 158: actual GIS, but an older edition

[ArcGIS item](https://www.arcgis.com/home/item.html?id=5bc41fec7abc40b1ab56da8bec1d80d9)
and [queryable polygon layer](https://services3.arcgis.com/Y4VT6T3VJuLXIpQ2/arcgis/rest/services/Electoral_Division/FeatureServer/29).
The item is owned by `Paigboha-Edenwold` in the same organisation as the
[RM-branded public maps hub](https://public-maps-for-rm-158-rmofedenwold.hub.arcgis.com).
That hub links back to the municipal website. This is a strong municipal-source
lead; its production provenance and reuse terms still need qualification.

A public GeoJSON query returned seven valid Polygon geometries, with division
numbers 1–7. The service uses EPSG:26913 and can return EPSG:4326. This is a
genuine machine-readable internal electoral layer, not a municipality outline.
The existing 2014 source has six divisions.

The item describes December 2023 council/division data. Its layer's data-edit
timestamp is **2024-01-26**; the item's later modification timestamp is not proof
of a boundary update. `licenseInfo`, `accessInformation` and layer copyright
text are empty. These observations do not constitute an open licence.

The RM's [current boundary-review page](https://rmedenwold.ca/divisional-boundaries)
reports that Council adopted Option A on May 5, 2026 and the Minister signed the
alteration on August 27, 2026, with consequences for the 2026 elections. It links
the [adopted Option A map](https://rmedenwold.ca/uploads/dm/107865/Option_A_2026_Boundary_Review).
That download is a **JPEG**, despite having no extension. Its northern division
layout differs from the older GIS layer. The page also documents earlier changes
in 2016, 2018 and 2020.

Recommended treatment: qualify the older GIS as a dated reference edition, and
obtain or reconstruct the approved 2026 edition from its authoritative order and
map. Confirm the exact effective date. Do not relabel the 2023/2024 service as
the approved 2026 boundaries. Geometry validity alone is not full topology or
assignment acceptance.

### Estevan No. 5, Vanscoy No. 345 and Torch River No. 488

- **Estevan:** the [official map page](https://www.rmestevan.ca/rm-map) links a
  scanned PDF showing numbered divisions and division lines. The map credits
  Bradley Geoservices and says revised September 18, 2025. This is an alternative
  producer, but no express redistribution grant was found. It would require
  georeferencing/digitisation or a source GIS export, plus provenance and date
  checks.
- **Vanscoy:** the [official maps page](https://www.rmvanscoy.ca/maps) provides a
  complete map and a division booklet showing divisions 1–6. The full map credits
  WSP and says revised January 19, 2026. The PDF text and visual review identify
  internal divisions, but no open-data licence or downloadable GIS was located.
  A PDF's vector artwork is not automatically georeferenced assignment geometry.
- **Torch River:** the [official map page](https://www.rmtorchriver.ca/map.html)
  links a large JPEG, updated June 8, 2026, with numbered council divisions and
  a division/township inset. It is a useful government-published reference;
  source rights, boundary effective date and georeferencing still need review.
  It is not an API or ready-to-import polygon dataset.

## Province-wide route

The most promising central authority is **Saskatchewan's Ministry of Government
Relations**, rather than Elections Saskatchewan's provincial election files.
The province explains that [RM creation orders describe the municipality and its
divisions](https://www.saskatchewan.ca/government/government-structure/local-federal-and-other-governments/your-local-government/about-the-saskatchewan-municipal-system)
and that [division alterations are ordered by the Minister](https://www.saskatchewan.ca/Government/Municipal-Administration/Community-Planning-Land-Use-and-Development/Municipal-Status-and-Boundary-Changes/division-boundary-changes-within-a-rural-municipality).
Alteration requests include maps and descriptions of the new divisions. Those
records are a concrete route to the authoritative definitions for all 36.

No province-wide public GIS download of **internal RM electoral divisions** was
located. The [provincial cartographic RM metadata](https://gisappl.saskatchewan.ca/metadata/RuralMunicipalityCarto.htm)
and [ISC administrative overlays](https://www.saskregistries.ca/MapsandPhotos/GISData/AdministrativeBoundaryOverlays)
describe outer municipal boundaries. They cannot substitute for the missing
internal divisions; the cartographic metadata also contains its own reuse
restriction. SARM's six member regions, census divisions, provincial polling
divisions and municipal zoning districts are different geographies.

A single request to the Ministry could ask for current and historical internal
division GIS for the 36 RMs, or the consolidated ministerial orders, legal
descriptions, schedules and effective dates if GIS is unavailable. Request terms
for publishing derived polygons and any required attribution. This is a proposed
next step; no correspondence was sent. Reconstruction would use appropriately
licensed survey/reference geometry, not inherit private-map tracing rights by
changing its format.

## Inventory of all 36 existing source records

Dates below describe the retrieved map or its label unless expressly stated
otherwise; they are not independently verified legal effective dates.
“No verified source” records the limits of this search, not nonexistence.

| Municipality | Alternative source or lead | Assessment and remaining work |
|---|---|---|
| Birch Hills No. 460 | [Official elections page](https://rmbirchhills460.ca/elections/) | No complete internal-division source verified. The site's “New Boundary Map” link concerns RCMP service areas, not these council divisions. |
| Bone Creek No. 108 | [Municipal PDF](https://www.rmofbonecreek.ca/Home/DownloadDocument?docId=fb652801-24db-427c-a570-96fe9ed89d5a) | MuniSoft/ISC notice restricts duplication. |
| Buffalo No. 409 | [Municipal map page](https://www.rmofbuffalo.com/map) | Downloaded PDF shows division boundaries but expressly restricts duplication and identifies ISC-licensed data. |
| Caledonia No. 99 | [2023 PDF](https://milestonesk.ca/wp-content/uploads/2023/09/2023-RM99-Map.pdf) | MuniSoft/ISC restriction. |
| Canaan No. 225 | [Municipal directory](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory) | No usable internal-division source verified. Ministry/RM records route. |
| Clayton No. 333 | [2025-labelled PDF](https://rm333.ca/wp-content/uploads/2026/04/RM333_2025v1.0-002.pdf) | MuniSoft/ISC restriction; website upload year is 2026. |
| Connaught No. 457 | [Municipal map download page](https://www.rm457.net/contact) | Page labels February 2020. PDF is Prairie Mapping Industries, expressly requiring written permission for reproduction. A different private supplier, not an unrestricted replacement. |
| Edenwold No. 158 | [GIS layer](https://services3.arcgis.com/Y4VT6T3VJuLXIpQ2/arcgis/rest/services/Electoral_Division/FeatureServer/29), [2026 decision](https://rmedenwold.ca/divisional-boundaries) | Seven downloadable polygons; older than adopted 2026 map. Qualify provenance, terms and editions. |
| Elcapo No. 154 | [Municipal directory](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory) | No usable internal-division source verified. Ministry/RM records route. |
| Elfros No. 307 | [Municipal directory](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory) | No usable internal-division source verified. Ministry/RM records route. |
| Estevan No. 5 | [Official map page](https://www.rmestevan.ca/rm-map) | Bradley Geoservices map, September 2025; divisions visible. Conversion/export and rights/date checks needed. |
| Excelsior No. 166 | [2025 PDF](https://rm166.ca/wp-content/uploads/2025/10/2025-RM-Map.pdf) | MuniSoft/ISC restriction. |
| Fish Creek No. 402 | [Official maps page](https://rmoffishcreek.ca/maps/) | Scanned August 2024 MuniSoft map; restriction visible in footer. |
| Frenchman Butte No. 501 | [2026 PDF](https://rmfrenchmanbutte.ca/fileadmin/rmoffrenchmanbutte/template/version1/images/RM501_2026v1-2PFinal.pdf) | MuniSoft/ISC restriction. Older indexed 2021 URL redirects to the municipal homepage; current PDF followed from there. |
| Gravelbourg No. 104 | [Official directory record](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory?s=%7Bb2c0c5ca-5bee-4236-9407-ded85e731916%7D) | Directory points to municipal Facebook. A zoning-map search result is not electoral divisions; no usable council geometry verified. |
| Gull Lake No. 139 | [2025 PDF](https://rmgulllake.ca/wp-content/uploads/2025/08/RM139_2025.pdf) | MuniSoft/ISC restriction. |
| Happy Valley No. 10 | [Official directory record](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory?s=%7B2aec1d68-f5d3-44b3-875d-0c3940d0908f%7D) | Directory points to municipal Facebook. Search found a 2020 ISC cadastral map on South Sask Ready, but no verified usable internal electoral layer. |
| Hart Butte No. 11 | [Municipal digital-map page](https://www.rmofhartbutte.ca/rm-digital-map) | Page links a PDF, despite describing an interactive map. July 2026 MuniSoft map; duplication restriction visible. |
| Kingsley No. 124 | [Municipal directory](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory) | No usable internal-division source verified. Ministry/RM records route. |
| Lac Pelletier No. 107 | [Official website](https://www.rmlacpelletier.com/) | Zoning bylaw located; zoning districts do not replace council divisions. No usable electoral geometry verified. |
| Last Mountain Valley No. 250 | [Municipal zoning-map page](https://rmoflastmountainvalley.ca/documents/rm-zoning-bylaw-maps/) | Zoning maps only in the reviewed search results; no usable council-division geometry verified. |
| Maryfield No. 91 | [Official maps page](https://www.rmofmaryfield.com/municipal-documents/maps) | 2022 MuniSoft/ISC map with restriction. |
| Montmartre No. 126 | [Municipal directory](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory) | No usable internal-division source verified. Do not confuse village of Montmartre with the RM. |
| Moose Mountain No. 63 | [Official map page](https://www.rmofmoosemountain.com/map) | 2025 MuniSoft/ISC map with restriction. |
| Perdue No. 346 | [Official directory record](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory?s=%7B04130fc2-2bf1-40cf-85fd-a2a8a485a93c%7D) | No usable internal-division source verified. Ministry/RM records route. |
| Rudy No. 284 | [Official map page](https://oursask.info/rm284/document/map/rm-of-rudy-no-284-municipal-map/) | August 2024 MuniSoft/ISC map with restriction. A division-review policy is not itself a boundary definition. |
| Silverwood No. 123 | [Official map page](https://www.rmofsilverwood.com/rm-map) | Linked MuniSoft/ISC PDF restricts duplication. Free ratepayer copies do not establish redistribution rights. |
| South Qu'Appelle No. 157 | [Official maps page](https://rm157.ca/general-services/maps/) | 2024 MuniSoft/ISC PDF with restriction. |
| Spiritwood No. 496 | [RM website](https://www.rmofspiritwood.ca/) | Municipal map lead, but HTTPS retrieval failed certificate verification. No map contents/licence verified; do not interpret the fetch failure as absence. |
| Tisdale No. 427 | [Official directory record](https://www.saskatchewan.ca/government/municipal-administration/municipal-directory?s=%7B92C1B4DB-263E-4F89-AFEF-E67DBF5F9BA7%7D) | No usable public internal-division GIS/map verified. Commercial landowner-map listing is not a reuse grant. |
| Torch River No. 488 | [Official map page](https://www.rmtorchriver.ca/map.html) | June 8, 2026 JPEG with divisions and inset; promising reference, requires conversion/provenance/terms review. |
| Vanscoy No. 345 | [Official maps and booklet](https://www.rmvanscoy.ca/maps) | Six divisions visible; WSP full map revised January 19, 2026. No express open licence found; conversion/export and qualification needed. |
| Wawken No. 93 | [Flying Dust First Nation lands page](https://flyingdust.horizontotalcare.ca/lands) | Linked scan is a MuniSoft RM map with its original notice, not independent government geometry. |
| Webb No. 138 | [Official map page](https://rm138.ca/municipal-map/) | 2024 MuniSoft/ISC PDF with restriction. |
| Whiska Creek No. 106 | [Official website](https://www.rmwhiskacreek106.com/) | Linked grader map retains MuniSoft/ISC reproduction restriction; not a cleared replacement electoral dataset. |
| Willowdale No. 153 | [Official map page](https://rmofwillowdale.ca/p/rm-map) | Linked October 2025 MuniSoft/ISC PDF with restriction. |

## Follow-through and evidence

When this work resumes, prioritise reconciliation of Edenwold's dated GIS and approved 2026 boundaries,
then investigate the three other map leads. A batch request for the 36
ministerial boundary records is likely more productive than treating all the
landowner maps as independent sources. Separately, MuniSoft/Open North could
clarify whether an existing agreement covers onward distribution of the exact
2014 boundary-only geometries, including derivatives, commercial use and public
downloads. Neither request has been sent.

Evidence is kept under ignored `.local/munisoft-alternatives-20260920/` inside
this repository: fetched-page/PDF receipts with URLs and content hashes, extracted
text, selected rendered maps, search results, 36 ArcGIS searches, and
`edenwold-validation.json`. The research cache is not a deployable dataset.
The research itself did not change boundaries, source manifests or licensing.
The subsequent standby release excludes all 36 sources and can be published
without resolving them. Their return to the dataset requires a reviewed source
and redistribution basis; the publication guard remains enabled.
