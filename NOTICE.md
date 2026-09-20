# Third-party code and geographical data

The MIT licence applies to original project code. It does not relicense sources.

Optional online backgrounds: Natural Resources Canada, Atlas of Canada Toporama
and Digital Relief (hillshade), used under the Open Government Licence – Canada:
https://open.canada.ca/en/open-government-licence-canada
Service images are requested live and are not packaged in dataset distributions.
Boundary colours and optional translucent hillshade are visual overlays. No NRCan
endorsement is implied. Attribution is displayed while the background is enabled.

- Leaflet 1.9.4 is distributed under BSD-2-Clause. Its licence and copyright
  notice are retained in `totally_normal_maps/vendor/leaflet/LICENSE` and its JS.
  The JavaScript matches the upstream release with only the final source-map
  reference removed; the source map is not distributed. CSS and images are unchanged.
- Statistics Canada: 2025 Census Subdivision Digital Boundary File and 2021
  Province/Territory Generalized Cartographic Boundary File. These are used
  under the Statistics Canada Open Licence:
  https://www.statcan.gc.ca/en/terms-conditions/open-licence
  This project is independent and is not endorsed by Statistics Canada.
- Gouvernement du Québec, Ministère des Ressources naturelles et des Forêts:
  Découpages administratifs, administrative regions, arrondissements and municipal
  comparison polygons,
  V2026-08 reference snapshots. CC BY 4.0:
  https://creativecommons.org/licenses/by/4.0/
  Dataset: https://www.donneesquebec.ca/recherche/dataset/decoupages-administratifs
- Ville de Gatineau: Découpage administratif, former-city sectors, source file
  updated 2025-04-24. CC BY 4.0:
  https://creativecommons.org/licenses/by/4.0/
  Dataset: https://www.donneesquebec.ca/recherche/dataset/vgat_296280560
- Ville de Québec: Quartiers, pinned September 2026 snapshot. CC BY 4.0.
  Dataset: https://www.donneesquebec.ca/recherche/dataset/vque_9
- Ville de Lévis: Secteurs, file modified 2022-05-16. CC BY 4.0.
  Dataset: https://www.donneesquebec.ca/recherche/dataset/secteur-levis
- Ville de Laval: Limites des anciennes municipalités, file modified 2017-02-13.
  CC BY 4.0. Dataset:
  https://www.donneesquebec.ca/recherche/dataset/limites-des-anciennes-municipalites
- Ville de Trois-Rivières: Quartiers (noms populaires), pinned September 2026
  snapshot. CC BY 4.0. Dataset:
  https://www.donneesquebec.ca/recherche/dataset/quartier-nom-populaire-v3r

## Notices for adapted Statistics Canada data

Adapted from Statistics Canada, Census Subdivision Boundary File (digital),
2025-01-01. This does not constitute an endorsement by Statistics Canada of this product.

Adapted from Statistics Canada, Province and Territory Generalized Cartographic
Boundary File, 2021-01-01. This does not constitute an endorsement by Statistics Canada
of this product.

When redistributing unchanged source archives, retain the source notice required
by the Statistics Canada Open Licence, including the product and reference date.

## Transformations and redistribution

Exact source URLs, checksums and reference dates are in the checked manifests.
Boundaries are transformed to WGS84. Regional outlines dissolve national
municipal members. Merged Québec municipality boundaries retain complete national
predecessor unions, linked to provincial successor identities. City-area boundaries
retain the full publisher geometry; parent relationships and source differences
are documented separately. Display boundaries are simplified separately. Candidate
repairs are explicitly labelled and are excluded from normal coordinate matches.
These transformations and cross-source differences are described in docs/research.
The separately reviewed La Romaine topology repair splits an invalid exclusion ring
without changing its area or extent; exact same-source reserve geometry corroborates
the exclusions. Its evidence and original repair ledger remain in the derived release.
The data publishers do not endorse the project. Preserve attribution and source
licences when distributing source data, derived datasets or map displays.

## Ontario additions

- Land Information Ontario, Municipal Boundary — Lower and Single Tier, selected
  September 2026 source snapshot. Contains information licensed under the Open
  Government Licence – Ontario:
  https://www.ontario.ca/page/open-government-licence-ontario
- County of Grey, Municipality Boundary, including the May 2026 Hanover expansion.
  Contains information licensed under the Grey County Open Data Licence.
  See the **Grey County Open Data Licence** section of https://maps.grey.ca/pages/terms
  (distinct from the general GIS viewing terms).
- City of Toronto, Former Municipality Boundaries and 158 Neighbourhoods.
  Contains information licensed under the Open Government Licence – Toronto:
  https://open.toronto.ca/open-data-licence/
- City of Ottawa, Ottawa Neighbourhood Study generation 3. Open Data Licence v2.0:
  https://ottawa.ca/en/city-hall/get-know-your-city/open-data#open-data-licence-version-2-0
- City of Hamilton, Community Boundaries and Neighbourhood Boundaries. Open Data
  Licence terms and conditions:
  https://www.hamilton.ca/city-initiatives/strategies-actions/open-data-licence-terms-and-conditions

Ontario current boundaries retain complete publisher geometry in separate revisions;
original national source boundaries remain intact. Differences are separately indexed
for review, including source water-coverage gaps. Two Ottawa neighbourhood repairs
are display candidates only. Publisher identity codes and explicit Hamilton community
attributes supply city-area identities and hierarchy. Toronto's two boundary schemes
remain independent. See docs/research/ontario-refresh.md for evidence and limitations.

## Other jurisdiction additions

- City of Vancouver, Local area boundary. Contains information licensed under the
  Open Government Licence – Vancouver: https://opendata.vancouver.ca/pages/licence/
- City of Calgary, Community District Boundaries. Contains information licensed
  under the Open Government Licence – City of Calgary:
  https://data.calgary.ca/d/Open-Data-Terms/u45n-7awa
- City of Edmonton, Neighbourhoods. Distributed under the City of Edmonton Open
  Data Terms of Use, version 2.1. Preserve these terms when redistributing:
  https://www.edmonton.ca/public-files/assets/document?path=Web-version2.1-OpenDataAgreement.pdf
- City of Winnipeg, Neighbourhoods. Contains information licensed under the Open
  Government Licence – Winnipeg: https://data.winnipeg.ca/open-data-licence
- City of Saskatoon, Neighbourhood, public open-data map service. Reuse statement:
  https://www.saskatoon.ca/services-residents/connect-your-city/open-data
- City of Saint John, Neighbourhoods. Contains information licensed under the Open
  Government Licence – City of Saint John. The publisher supplies the licence in
  the dataset metadata:
  https://www.arcgis.com/sharing/rest/content/items/338f69c642454516b877085043966e96?f=json
- City of Fredericton, Neighbourhoods. Contains information licensed under the
  Open Government License – City of Fredericton:
  https://data-fredericton.opendata.arcgis.com/pages/open-data-license
- Halifax Regional Municipality, Community Boundaries. Contains information
  licensed under the Open Data Licence – Halifax Regional Municipality:
  https://data-hrm.hub.arcgis.com/pages/open-data-licence
- Government of Yukon on behalf of the City of Whitehorse, NG911 Subdivisions.
  Contains information licensed under the Open Government Licence – Yukon:
  https://open.yukon.ca/data/open-government-licence-yukon

These are complete publisher polygons, separately simplified for display. Invalid
geometry and unresolved parent/overlap cases are excluded from normal assignment.
Source licences remain separate from the MIT code licence. See
`docs/research/jurisdiction-refresh.md` for exact scope and unfinished qualification.

## Optional electoral geography

Electoral source and edition evidence accompanies the dataset in `report.json`.
Complete source polygons are transformed to WGS84; display copies are simplified.
Candidate repairs are unapproved and excluded from point assignment. Nunavut uses
the explicitly recorded EPSG 1842 coordinate approximation. No authority endorses
these transformations or this project.

- Elections Canada, federal electoral districts under the 2023 representation
  orders, September 2026 names. Contains information licensed under the Open
  Government Licence – Canada: https://open.canada.ca/en/open-government-licence-canada
- Directeur général des élections du Québec / Élections Québec, 2026 Assembly
  electoral map and historical 2017 boundaries (2022 snapshot). Specific open-data
  licence: https://dgeq.org/licence.html
- Elections Ontario, electoral districts, 2022 downloadable snapshot of the
  2018 boundaries. Open Use Data Product Licence Agreement:
  https://www.elections.on.ca/en/voting-in-ontario/electoral-district-shapefiles/open-use-data-product-licence-agreement.html
- Elections BC, 2023 electoral districts, boundary set 11. Contains information
  licenced under the Elections BC Open Data Licence:
  https://www.elections.bc.ca/docs/EBC-Open-Data-Licence.pdf
- Government of Alberta, 2019 provincial electoral divisions. Contains information
  licensed under the Open Government Licence – Alberta: https://open.alberta.ca/licence
- Elections New Brunswick / Service New Brunswick, 2023 provincial districts.
  Contains information licensed under the Open Government Licence – New Brunswick.
  Product and reuse evidence: https://www.gnb.ca/en/campaign/geonb/data-catalogue/electoral-provincial.html
- Government of Newfoundland and Labrador, 2015 electoral districts. Contains
  information licensed under the Open Government Licence – Newfoundland and Labrador:
  https://opendata.gov.nl.ca/public/opendata/page/?page-id=licence
- Government of Yukon / Elections Yukon, 2024 electoral districts. Contains
  information licensed under the Open Government Licence – Yukon:
  https://yukon.ca/en/your-government/open-government/open-government-licence-yukon

Required Québec attribution:

Comprend des données ouvertes octroyées sous la licence d'utilisation des données
ouvertes du directeur général des élections disponible à l'adresse Web dgeq.org.
L'octroi de la licence n'implique aucune approbation par le directeur général des
élections de l'utilisation des données ouvertes qui en est faite.

This statement also accompanies the 282 DGEQ municipal boundary sources obtained
through Represent. Their application of the DGEQ open-data licence was accepted
in the maintainer's 2026-09-20 licence review. The statement is retained in each
source's metadata and displayed in the map footer without opening the detailed
source credits. This review does not change the licences of other publishers.

The 2026-09-20 government-source publication review records source terms and
maintainer publication decisions separately. Exact licence applicability remains
unconfirmed where stated in report.json. The government sources are approved for
publication by the maintainer with the notices below. The 36 private MuniSoft
sources remain unresolved and are excluded from the selected serving release;
their Saskatchewan municipal electoral divisions are on standby pending
redistribution permission or licensed replacements. Administrative municipal
boundaries are retained. See docs/research/government-source-licences.md.

Municipal electoral source releases may additionally contain data from Open North
Represent and the municipal/provincial authorities identified in the release's
`municipal_elections.sources` inventory. Represent is an aggregator; its inclusion
is not a blanket redistribution licence for every upstream dataset. Individual
source URLs, licences, dates and reuse status are retained in the report and map.

Contains information licensed under the Open Government Licence – Nova Scotia
and the Open Government Licence – British Columbia. Québec municipal sources
identified as CC BY 4.0 retain attribution to each publishing municipality.
Additional city source terms and publication decisions, including Calgary and Lake
Country, are recorded in the release and the government review below. These sources do not endorse this project. Adaptations
include identity normalization, coordinate transformation, expressly documented
multipart unions and separate simplified display boundaries. Source polygons may
include water. Unapproved repairs are display candidates only.

## Government source review and contact

We publish publicly available government boundary data in good faith and acknowledge the sources identified in our data credits. If you believe any data or attribution raises a licensing issue, please contact info@totallynormal.io. We will review the issue promptly and take the steps needed to comply with applicable licence terms, rules and regulations, including correcting attribution, updating the data or removing affected material where required. This project is independent and is not endorsed by the source authorities.

All data remain subject to the applicable publisher terms linked below and in
report.json. Use of the Burlington and London data indicates acceptance of their
respective linked terms; preserve those terms or their URLs on redistribution,
without imposing further restrictions on those source datasets. Source credits
may be corrected or removed at the publisher’s request where its licence requires
this. These notices do not expand a publisher’s licence or warrant that an
unconfirmed product has an open licence. Modified boundaries are unofficial,
provided as-is, and do not imply publisher endorsement.

- **Elections Saskatchewan** — Source: Elections Saskatchewan. No publisher endorsement is implied.
  Terms / reuse information: https://www.elections.sk.ca/candidates-political-parties/maps/
- **Elections Manitoba** — Source: Elections Manitoba. No publisher endorsement is implied. OpenMB attribution, where applicable: Contains information from the Manitoba government, licensed under the OpenMB Information and Data Use Licence (Manitoba.ca/OpenMB).
  Terms / reuse information: https://www.gov.mb.ca/legal/copyright.html
- **Elections Nova Scotia** — Source: Elections Nova Scotia. No publisher endorsement is implied. Adapted from Elections Nova Scotia / Government of Nova Scotia electoral boundaries. Crown copyright acknowledged. This is a modified, unofficial representation.
  Terms / reuse information: https://www.novascotia.ca/copyright
- **Government of Prince Edward Island** — Source: Government of Prince Edward Island. No publisher endorsement is implied. Open-data attribution, where applicable: Contains information licensed under the Open Government Licence – Prince Edward Island.
  Terms / reuse information: https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- **Government of the Northwest Territories** — Source: Government of the Northwest Territories. No publisher endorsement is implied. Open-data attribution, where applicable: Contient des renseignements visés par la licence du gouvernement ouvert des Territoires du Nord-Ouest. Copyright: Elections NWT, NWTCG.
  Terms / reuse information: https://www.gov.nt.ca/en/open-government-licence-northwest-territories
- **Elections Nunavut** — Source: Elections Nunavut. No publisher endorsement is implied.
  Terms / reuse information: https://www.elections.nu.ca/en/document/maps-constituencies-gis-2025
- **Town of Ajax** — Contains public sector Information made available under The Corporation of the Town of Ajax's Open Data Licence.
  Terms / reuse information: https://townofajax.maps.arcgis.com/sharing/rest/content/items/22e2d8e248724d7cb0310dc2db675abd/data
- **City of Barrie** — Contains information licensed under the Open Government Licence – Barrie.
  Terms / reuse information: https://www.barrie.ca/Online%20Services/PublishingImages/OpenData_Images/COB_DataLicense.pdf
- **City of Belleville** — Source: City of Belleville. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/belleville-wards/
- **Municipal District of Bonnyville No. 87** — Source: Municipal District of Bonnyville No. 87. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/bonnyville-no-87-wards/
- **Regional Municipality of Peel** — Contains public sector Information made available under The Regional Municipality of Peel's Open Data Licence - Version 1.0.
  Terms / reuse information: https://data.peelregion.ca/pages/license
- **City of Brantford** — Contains information licensed under the Open Government Licence – Brantford.
  Terms / reuse information: https://www.brantford.ca/your-government/open-data/open-data-licence/
- **Township of Brock** — Contains public sector Information made available under The Regional Municipality of Durham's Open Data Licence.
  Terms / reuse information: https://www.durham.ca/en/regional-government/resources/Documents/OpenDataLicenceAgreement.pdf
- **City of Burlington** — Source: City of Burlington. These modified datasets are publicly available under the City of Burlington Open Data Terms of Use. Use of the Burlington data is subject to those terms; recipients must agree to them. No City endorsement is implied.
  Terms / reuse information: https://opendata.burlington.ca/opendata-terms-of-use/City%20of%20Burlington%20-%20Open%20Data%20Terms%20of%20Use.pdf
- **City of Calgary** — Contains information licensed under the Open Government Licence – City of Calgary.
  Terms / reuse information: https://data.calgary.ca/stories/s/Open-Calgary-Terms-of-Use/u45n-7awa
- **Regional Municipality of Waterloo** — Contains information provided by the Regional Municipality of Waterloo under licence.
  Terms / reuse information: https://www.regionofwaterloo.ca/government-and-council/transparency-and-accountability/open-data/
- **Municipality of Chatham-Kent** — Source: Municipality of Chatham-Kent. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/chatham-kent-wards/
- **Municipality of Clarington** — Source: Municipality of Clarington. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/clarington-wards/
- **City of Edmonton** — Contains information licensed under the Open Government Licence – City of Edmonton.
  Terms / reuse information: https://data.edmonton.ca/stories/s/City-of-Edmonton-Open-Data-Terms-of-Use/msh8-if28/
- **County of Grande Prairie No. 1** — Contains information licensed under the Open Government Licence – County of Grande Prairie.
  Terms / reuse information: https://maps.countygp.ab.ca/open-government-licence.pdf
- **City of Greater Sudbury** — Contains information licensed under the Open Data Licence – City of Greater Sudbury.
  Terms / reuse information: https://www.greatersudbury.ca/city-hall/open-government/open-data/licence/
- **Town of Grimsby** — Contains information licensed under the Open Government Licence - Town of Grimsby.
  Terms / reuse information: https://niagaraopendata.ca/pages/open-government-license-2-0-town-of-grimsby
- **City of Guelph** — Contains information licensed under the Open Government Licence – City of Guelph.
  Terms / reuse information: https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf
- **Corporation of Haldimand County** — Source: Corporation of Haldimand County. No publisher endorsement is implied.
  Terms / reuse information: https://opendata.haldimandcounty.on.ca/
- **Town of Halton Hills** — Source: Town of Halton Hills. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/halton-hills-wards/
- **City of Hamilton** — Contains public sector Data made available under the City of Hamilton’s Open Data Licence.
  Terms / reuse information: https://www.hamilton.ca/city-initiatives/strategies-actions/open-data-licence-terms-and-conditions
- **City of Kawartha Lakes** — Source: City of Kawartha Lakes. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/kawartha-lakes-wards/
- **Township of King** — Source: Township of King. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/king-wards/
- **City of Kingston** — Contains information licensed under the Open Data Licence – City of Kingston.
  Terms / reuse information: https://www.cityofkingston.ca/media/wtpgpkb0/gis_license_opendata.pdf
- **Leduc County** — Source: Leduc County. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/leduc-county-divisions/
- **Town of Lincoln** — Source: Town of Lincoln. No publisher endorsement is implied.
  Terms / reuse information: https://niagaraopendata.ca/pages/open-government-license-2-0-town-of-lincoln
- **City of London** — Source: City of London. These modified datasets are publicly available under the City of London Open Data Terms of Use. Use of the London data is subject to those terms; recipients must agree to them. No City endorsement is implied.
  Terms / reuse information: https://london.ca/government/council-civic-administration/open-data
- **City of Markham** — Contains public sector Information made available under the City of Markham’s Open Data Licence.
  Terms / reuse information: https://data-markham.opendata.arcgis.com/pages/terms-of-use
- **Town of Milton** — Source: Town of Milton. No publisher endorsement is implied.
  Terms / reuse information: https://www.milton.ca/en/townhall/resources/OpenDataAgreement.pdf
- **City of Mississauga** — Source: City of Mississauga. No publisher endorsement is implied.
  Terms / reuse information: https://smartcity.mississauga.ca/wp-content/uploads/2021/04/CityofMississauga_TermsofUse.pdf
- **Town of Newmarket** — Contains information licensed under the Open Data Licence – Town Of Newmarket.
  Terms / reuse information: https://navigate-newmarket.hub.arcgis.com/pages/open-data-licence
- **City of Norfolk County** — Contains public sector Information made available under Norfolk County's Open Data Licence.
  Terms / reuse information: https://data-norfolk.opendata.arcgis.com/pages/terms-of-use
- **Town of Oakville** — Contains information licensed under the Open Government Licence — Town of Oakville.
  Terms / reuse information: https://www.oakville.ca/town-hall/plans-strategies/open-data/open-data-licence/
- **City of Oshawa** — Contains information licensed under the Open Government Licence – The Corporation of the City of Oshawa.
  Terms / reuse information: https://map.oshawa.ca/OpenData/Open%20Government%20Licence%20version%202.0%20-%20Oshawa.pdf
- **City of Ottawa** — Source: City of Ottawa. No publisher endorsement is implied. Contains information licensed under the Open Government Licence – City of Ottawa.
  Terms / reuse information: https://ottawa.ca/en/city-hall/get-know-your-city/open-data#open-data-licence-version-2-0
- **City of Peterborough** — Source: City of Peterborough. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/peterborough-wards/
- **City of Pickering** — Contains public sector Information made available under The City of Pickering's Open Data Licence.
  Terms / reuse information: https://www.pickering.ca/media/depbgebg/opendatalicencepickeringv1_acc.pdf
- **City of Quinte West** — Source: City of Quinte West. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/quinte-west-wards/
- **City of Regina** — Contains information licensed under the Open Government Licence – City of Regina.
  Terms / reuse information: https://www.regina.ca/residents/open-government/open-government-licence/
- **Town of Richmond Hill** — Source: Town of Richmond Hill. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/richmond-hill-wards/
- **Rocky View County** — Source: Rocky View County. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/rocky-view-county-divisions/
- **City of Saskatoon** — Source: City of Saskatoon. No publisher endorsement is implied.
  Terms / reuse information: https://www.saskatoon.ca/services-residents/connect-your-city/open-data
- **City of Sault Ste. Marie** — Source: City of Sault Ste. Marie. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/sault-ste-marie-wards/
- **Township of Scugog** — Contains public sector Information made available under The Regional Municipality of Durham's Open Data Licence.
  Terms / reuse information: https://www.durham.ca/en/regional-government/resources/Documents/OpenDataLicenceAgreement.pdf
- **City of St. John's** — Source: City of St. John's. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/st-johns-wards/
- **Strathcona County** — Contains information licensed under the Open Government Licence – Strathcona County.
  Terms / reuse information: https://opendata-strathconacounty.hub.arcgis.com/pages/licence
- **City of Thunder Bay** — Source: City of Thunder Bay. No publisher endorsement is implied.
  Terms / reuse information: https://webapps.thunderbay.ca/PoliciesAndProcedures/ViewPolicy.aspx?ID=VPfuH8AuK0Q%3D
- **City of Toronto** — Contains information licensed under the Open Government Licence – Toronto.
  Terms / reuse information: https://www.toronto.ca/city-government/data-research-maps/open-data/open-data-licence/
- **Township of Uxbridge** — Contains public sector Information made available under The Regional Municipality of Durham's Open Data Licence.
  Terms / reuse information: https://www.durham.ca/en/regional-government/resources/Documents/OpenDataLicenceAgreement.pdf
- **City of Vaughan** — Source: City of Vaughan. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/vaughan-wards/
- **City of Welland** — Source: City of Welland. No publisher endorsement is implied.
  Terms / reuse information: https://niagaraopendata.ca/pages/open-government-license-2-0-city-of-welland
- **Town of Whitby** — Contains information licensed under the Open Government Licence – The Corporation of the Town of Whitby.
  Terms / reuse information: https://whitby.maps.arcgis.com/sharing/rest/content/items/223810efc31c40b3aff99dd74f809a97/data
- **Town of Whitchurch-Stouffville** — Source: Town of Whitchurch-Stouffville. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/whitchurch-stouffville-wards/
- **City of Windsor** — Source: City of Windsor. No publisher endorsement is implied.
  Terms / reuse information: https://www.citywindsor.ca/Privacy
- **City of Winnipeg** — Contains information licensed under the Open Government Licence – Winnipeg.
  Terms / reuse information: https://data.winnipeg.ca/open-data-licence
- **Regional Municipality of Wood Buffalo** — Source: Regional Municipality of Wood Buffalo. No publisher endorsement is implied.
  Terms / reuse information: https://represent.opennorth.ca/boundary-sets/wood-buffalo-wards/
- **Elections New Brunswick / Service New Brunswick** — Contains information licensed under the Open Government Licence – New Brunswick.
  Terms / reuse information: https://www.gnb.ca/en/campaign/geonb/open-government-license.html
- **District of Lake Country** — Source: District of Lake Country. No publisher endorsement is implied.
  Terms / reuse information: https://www.lakecountry.bc.ca/maps

### Government source citations

- `electoral/sk` — Elections Saskatchewan: https://www.elections.sk.ca/candidates-political-parties/maps/
- `electoral/mb-rural` — Elections Manitoba: https://electionsmanitoba.ca/En/Resources/Maps
- `electoral/mb-urban` — Elections Manitoba: https://electionsmanitoba.ca/En/Resources/Maps
- `electoral/ns` — Elections Nova Scotia: https://enstools.electionsnovascotia.ca/edinfo/
- `electoral/pe` — Government of Prince Edward Island: https://gis.princeedwardisland.ca/server/rest/services/Hosted/prov_electoral_districts_2017/FeatureServer
- `electoral/nt` — Government of the Northwest Territories: https://www.apps.geomatics.gov.nt.ca/arcgis/rest/services/GNWT/Boundaries_LCC/MapServer/2
- `electoral/nu` — Elections Nunavut: https://www.elections.nu.ca/en/document/maps-constituencies-gis-2025
- `municipal_elections/rep-ajax-wards` — Town of Ajax: https://opendata.ajax.ca/datasets/2018-ward-boundaries
- `municipal_elections/rep-barrie-wards` — City of Barrie: https://public-barrie.opendata.arcgis.com/datasets/wards
- `municipal_elections/rep-belleville-wards` — City of Belleville: https://represent.opennorth.ca/boundary-sets/belleville-wards/
- `municipal_elections/rep-bonnyville-no-87-wards` — Municipal District of Bonnyville No. 87: https://represent.opennorth.ca/boundary-sets/bonnyville-no-87-wards/
- `municipal_elections/rep-brampton-wards` — Regional Municipality of Peel: https://data.peelregion.ca/datasets/RegionofPeel::peel-ward-boundary
- `municipal_elections/rep-brantford-wards` — City of Brantford: https://data-brantford.opendata.arcgis.com/datasets/city-of-brantford-ward-boundaries
- `municipal_elections/rep-brock-wards` — Township of Brock: https://city-oshawa.opendata.arcgis.com/datasets/DurhamRegion::brock-ward-boundaries
- `municipal_elections/rep-burlington-wards` — City of Burlington: https://navburl-burlington.opendata.arcgis.com/datasets/ward-boundaries
- `municipal_elections/rep-caledon-wards` — Regional Municipality of Peel: https://data.peelregion.ca/datasets/RegionofPeel::peel-ward-boundary
- `municipal_elections/rep-calgary-wards` — City of Calgary: https://data.calgary.ca/Government/Ward-Boundaries/r9vx-mhnf
- `municipal_elections/rep-cambridge-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/rep-chatham-kent-wards` — Municipality of Chatham-Kent: https://represent.opennorth.ca/boundary-sets/chatham-kent-wards/
- `municipal_elections/rep-clarington-wards` — Municipality of Clarington: https://represent.opennorth.ca/boundary-sets/clarington-wards/
- `municipal_elections/rep-edmonton-wards` — City of Edmonton: https://data.edmonton.ca/Administrative/City-of-Edmonton-Ward-Boundary-and-Council-Composi/b4er-5rp2
- `municipal_elections/rep-grande-prairie-county-no-1-divisions` — County of Grande Prairie No. 1: https://data1-cogp.opendata.arcgis.com/datasets/aec068b7976e432f99b7cbd89fe2abc7_0
- `municipal_elections/rep-greater-sudbury-wards` — City of Greater Sudbury: https://opendata.greatersudbury.ca/datasets/Sudbury::ward-map-and-council-layer/about
- `municipal_elections/rep-grimsby-wards` — Town of Grimsby: https://represent.opennorth.ca/boundary-sets/grimsby-wards/
- `municipal_elections/rep-guelph-wards` — City of Guelph: https://data.open.guelph.ca/dataset/guelph-wards
- `municipal_elections/rep-haldimand-county-wards` — Corporation of Haldimand County: https://opendata.haldimandcounty.on.ca/datasets/wards
- `municipal_elections/rep-halton-hills-wards` — Town of Halton Hills: https://represent.opennorth.ca/boundary-sets/halton-hills-wards/
- `municipal_elections/rep-hamilton-wards` — City of Hamilton: https://open.hamilton.ca/datasets/8b0b1f2bf8bb4e1da3a1bf567b17b77f_7
- `municipal_elections/rep-kawartha-lakes-wards` — City of Kawartha Lakes: https://represent.opennorth.ca/boundary-sets/kawartha-lakes-wards/
- `municipal_elections/rep-king-wards` — Township of King: https://represent.opennorth.ca/boundary-sets/king-wards/
- `municipal_elections/rep-kingston-wards` — City of Kingston: https://www.cityofkingston.ca/explore/data-catalogue
- `municipal_elections/rep-kitchener-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/rep-leduc-county-divisions` — Leduc County: https://represent.opennorth.ca/boundary-sets/leduc-county-divisions/
- `municipal_elections/rep-lincoln-wards` — Town of Lincoln: https://niagaraopendata.ca/dataset/lincoln-ward-map
- `municipal_elections/rep-london-wards` — City of London: https://www.london.ca/city-hall/open-data/Pages/Open-Data-Data-Catalogue.aspx
- `municipal_elections/rep-markham-wards` — City of Markham: https://data-markham.opendata.arcgis.com/datasets/e18e684f2f004f0e98d707cad60234be_0
- `municipal_elections/rep-milton-wards` — Town of Milton: https://www.milton.ca/en/townhall/opendata.asp
- `municipal_elections/rep-mississauga-wards` — City of Mississauga: https://data.mississauga.ca/datasets/mississauga::2022-ward-boundaries/about
- `municipal_elections/rep-newmarket-wards` — Town of Newmarket: https://navigate-newmarket.hub.arcgis.com/datasets/f0537eeb8e7e4f8f8f9922083e34d0e0_0/about
- `municipal_elections/rep-norfolk-county-wards` — City of Norfolk County: https://opendata.norfolkcounty.ca/datasets/wards
- `municipal_elections/rep-north-dumfries-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/rep-oakville-wards` — Town of Oakville: https://portal-exploreoakville.opendata.arcgis.com/datasets/toak::2018-ward-boundaries
- `municipal_elections/rep-oshawa-wards` — City of Oshawa: https://city-oshawa.opendata.arcgis.com/datasets/oshawa-2018-ward-boundaries
- `municipal_elections/rep-ottawa-wards` — City of Ottawa: https://open.ottawa.ca/datasets/ottawa::wards-2022-2026/about
- `municipal_elections/rep-peterborough-wards` — City of Peterborough: https://represent.opennorth.ca/boundary-sets/peterborough-wards/
- `municipal_elections/rep-pickering-wards` — City of Pickering: https://opendata.pickering.ca/datasets/pickering-ward-boundaries
- `municipal_elections/rep-quinte-west-wards` — City of Quinte West: https://represent.opennorth.ca/boundary-sets/quinte-west-wards/
- `municipal_elections/rep-regina-wards` — City of Regina: https://open.regina.ca/dataset/wards
- `municipal_elections/rep-richmond-hill-wards` — Town of Richmond Hill: https://represent.opennorth.ca/boundary-sets/richmond-hill-wards/
- `municipal_elections/rep-rocky-view-county-divisions` — Rocky View County: https://represent.opennorth.ca/boundary-sets/rocky-view-county-divisions/
- `municipal_elections/rep-saskatoon-wards` — City of Saskatoon: https://opendata-saskatoon.cloudapp.net/DataBrowser/SaskatoonOpenDataCatalogueBeta/CurrentWardBoundaries
- `municipal_elections/rep-sault-ste-marie-wards` — City of Sault Ste. Marie: https://represent.opennorth.ca/boundary-sets/sault-ste-marie-wards/
- `municipal_elections/rep-scugog-wards` — Township of Scugog: https://city-oshawa.opendata.arcgis.com/datasets/DurhamRegion::scugog-ward-boundaries
- `municipal_elections/rep-st-johns-wards` — City of St. John's: https://represent.opennorth.ca/boundary-sets/st-johns-wards/
- `municipal_elections/rep-strathcona-county-wards` — Strathcona County: https://data.strathcona.ca/Boundaries/2007-Ward-Boundaries/r8k6-yyk6
- `municipal_elections/rep-thunder-bay-wards` — City of Thunder Bay: https://represent.opennorth.ca/boundary-sets/thunder-bay-wards/
- `municipal_elections/rep-toronto-wards-2010` — City of Toronto: https://www.toronto.ca/city-government/data-research-maps/open-data/open-data-catalogue/#29b6fadf-0bd6-2af9-4a8c-8c41da285ad7
- `municipal_elections/rep-toronto-wards-2018` — City of Toronto: https://www.toronto.ca/city-government/data-research-maps/open-data/open-data-catalogue/#29b6fadf-0bd6-2af9-4a8c-8c41da285ad7
- `municipal_elections/rep-uxbridge-wards` — Township of Uxbridge: https://city-oshawa.opendata.arcgis.com/datasets/DurhamRegion::uxbridge-ward-boundaries
- `municipal_elections/rep-vaughan-wards` — City of Vaughan: https://represent.opennorth.ca/boundary-sets/vaughan-wards/
- `municipal_elections/rep-waterloo-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/rep-welland-wards` — City of Welland: https://niagaraopendata.ca/dataset/city-of-welland-ward-boundaries
- `municipal_elections/rep-wellesley-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/rep-whitby-wards` — Town of Whitby: https://geohub-whitby.hub.arcgis.com/datasets/Whitby::ward-boundaries/about
- `municipal_elections/rep-whitchurch-stouffville-wards` — Town of Whitchurch-Stouffville: https://represent.opennorth.ca/boundary-sets/whitchurch-stouffville-wards/
- `municipal_elections/rep-wilmot-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/rep-windsor-wards` — City of Windsor: https://opendata.citywindsor.ca/opendata/details/222
- `municipal_elections/rep-winnipeg-wards` — City of Winnipeg: https://data.winnipeg.ca/Council-Services/Electoral-Ward/ede3-teb8
- `municipal_elections/rep-wood-buffalo-wards` — Regional Municipality of Wood Buffalo: https://represent.opennorth.ca/boundary-sets/wood-buffalo-wards/
- `municipal_elections/rep-woolwich-wards` — Regional Municipality of Waterloo: https://rowopendata-rmw.opendata.arcgis.com/datasets/8556e15d83d649e69f5806054c83ad8e_15
- `municipal_elections/nb-current` — Elections New Brunswick / Service New Brunswick: https://geonb.snb.ca/arcgis/rest/services/GeoNB_ENB_Local_Government_Elections/MapServer/1
- `municipal_elections/pei-current` — Government of Prince Edward Island: https://gis.princeedwardisland.ca/server/rest/services/Municipal_Electoral_Wards_and_Polls/FeatureServer/0
- `municipal_elections/lake-country-current` — District of Lake Country: https://www.arcgis.com/home/item.html?id=2858a37d67af4842852bff7bbaf97c32
- `municipal_elections/calgary-current` — City of Calgary: https://www.arcgis.com/home/item.html?id=d4c5d57e4327400890bac0e15cc28f53

### Town of Grimsby licence — publisher text

Source: https://niagaraopendata.ca/pages/open-government-license-2-0-town-of-grimsby

Retrieved 2026-09-20. The licence requests a copy where possible; the publisher text follows.

Town of Grimsby - Open Government License

Preamble

This Open Government Licence is based on version 2.0 of the Open Government Licence - Canada, and has been adapted for the Town of Grimsby. You are encouraged to use the Information that is available under this Licence with only a few conditions, which are as follows:

Open Government Licence - Town of Grimsby
  1. Use of any Information indicates your acceptance of the terms below.
  2. The Information Provider grants you a worldwide, royalty-free, perpetual, nonexclusive Licence to use the Information, including for commercial purposes, subject to the terms below.
You are free to:
3. Copy, modify, publish, translate, adapt, distribute or otherwise use the Information in any medium, mode or format for any lawful purpose. You must, where you do any of the above:
4. Acknowledge the source of the Information by including any attribution statement specified by the Information Provider(s) and, where possible, provide a copy of this Licence. If the Information Provider does not provide a specific attribution statement, or if you are using Information from several Information Providers and multiple attributions are not practical for your product or application, you must use the following attribution statement:
Contains information licensed under the Open Government Licence - Town of Grimsby 5. The terms of this licence are important, and if you fail to comply with any of them, the rights granted to you under this Licence, or any similar Licence granted by the Information Provider will end automatically.
Exemptions
6. This licence does not grant you any right to use: a) Personal Information; b) Information or Records not accessible under the Freedom of Information and Protection of Privacy Act (Ontario); c) Third party rights the Information Provider is not authorized to licence; d) The names, crests, logos, or other official symbols of the Information Provider; and, e) Information subject to other intellectual property rights, including patents, trademarks and official marks.
Future changes to Datasets/Data Licence
7. The Information Provider may at any time add, delete or change the datasets or this licence. The Information Provider has no obligation whatsoever to provide services and/or updates to you.

Non-endorsement
8. You may not publicly represent or imply that the Town of Grimsby is participating in or has sponsored, approved or endorsed the manner or purpose of, Your Use or reproduction of these datasets.
No Warranty
9. The Information is licensed "as is" and the Information Provider excludes all representations, warranties, obligations, and liabilities, whether express or implied, to the maximum extent permitted by law. 10.
The Information Provider is not liable for any errors or omissions in the Information and will not under any circumstances be liable for any direct, indirect, special, incidental, consequential or other loss, injury or damage caused by its use or otherwise arising in connection with this Licence or the Information, even if specifically advised of the possibility of such loss, injury or damage.
Compliance with Law - Your Responsibility
11. You assume sole responsibility for your use and reproduction of the datasets complying with all applicable laws and industry standards. 12. This licence is governed by the laws of the province of Ontario and the applicable laws of Canada. 13. Legal proceedings related to this licence may only be brought in the courts of Ontario or the Federal Court of Canada.
Exclusion of Liability
14. You agree that you waive any action, cause of action, demand, liability, expense or otherwise against the Town for anything, which the Town does or does not do (even if intentional or negligent) in connection with the datasets and your use or inability to use them.
Without limiting the general scope of the preceding sentence, this means that the Town and its agents are not liable on any legal theory or basis for any direct, incidental, indirect, special, punitive, exemplary, or consequential damages or losses, including without limitation, loss of revenue or anticipated profits, loss of goodwill, loss of business, loss of data, computer failure or malfunction or any other damages or losses.
Liability for Non-Compliance with Licence
15. If, as a result of your breach of the licence, the Town gets sued or is required to pay someone money, you agree to protect the Town and reimburse the Town for everything which you cause the Town to suffer. This means that you agree to defend, indemnify, and hold harmless the Town and all of its agents from any and all liabilities incurred in connection with any claim arising from any breach by you of this Licence, including reasonable legal fees and costs.
You agree to cooperate fully in the defense of any such claim. The Town reserves the right to assume, at its own expense, the exclusive defense and control of any matter otherwise subject to indemnification by you. You agree not to settle any matter without the written consent of the Town.
Definitions
16. In this licence, the terms below have the following meanings:

"Information" means information resources or Records protected by copyright or other information or Records that are offered for use under the terms of this Licence.

"Information Provider" means Town of Grimsby.

"Personal Information" has the meaning set out in section 2(1) of Freedom of Information and Protection of Privacy Act (Ontario).
"Records" has the meaning of "record" as set out in the Freedom of Information and Protection of Privacy Act (Ontario). "You" means the natural or legal person or body of persons corporate or incorporate, acquiring rights under this Licence.
Versioning
17. This is version 2.0 of the Open Government Licence - Town of Grimsby. The Information Provider may make changes to the terms of this Licence from time to time and issue a new version of the Licence. Your use of the Information will be governed by the terms of the Licence in force as of the date you accessed the information.
