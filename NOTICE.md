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

The local electoral review also includes products from Elections Saskatchewan,
Elections Manitoba, Elections Nova Scotia / Government of Nova Scotia, Government
of Prince Edward Island, GNWT Centre for Geomatics, and Elections Nunavut. Exact
product redistribution permission remains unconfirmed for these six jurisdictions.
Their public availability does not imply an open licence. Preserve the individual
source links, copyright notices and unresolved reuse status in the release report;
the public dataset publication command blocks these products pending qualification.
See `docs/research/electoral-layers.md` and `electoral-2026-09.json` for provenance.

Municipal electoral source releases may additionally contain data from Open North
Represent and the municipal/provincial authorities identified in the release's
`municipal_elections.sources` inventory. Represent is an aggregator; its inclusion
is not a blanket redistribution licence for every upstream dataset. Individual
source URLs, licences, dates and reuse status are retained in the report and map.

Contains information licensed under the Open Government Licence – Nova Scotia
and the Open Government Licence – British Columbia. Québec municipal sources
identified as CC BY 4.0 retain attribution to each publishing municipality.
Additional city source terms, including Calgary and Lake Country, must be reviewed
as recorded in the release. These sources do not endorse this project. Adaptations
include identity normalization, coordinate transformation, expressly documented
multipart unions and separate simplified display boundaries. Source polygons may
include water. Unapproved repairs are display candidates only.
