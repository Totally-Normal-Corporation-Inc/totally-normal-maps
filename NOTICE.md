# Third-party code and geographical data

The MIT licence applies to original project code. It does not relicense sources.

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
  Découpages administratifs, administrative regions and arrondissements,
  V2026-08 reference snapshots. CC BY 4.0:
  https://creativecommons.org/licenses/by/4.0/
  Dataset: https://www.donneesquebec.ca/recherche/dataset/decoupages-administratifs
- Ville de Gatineau: Découpage administratif, former-city sectors, source file
  updated 2025-04-24. CC BY 4.0:
  https://creativecommons.org/licenses/by/4.0/
  Dataset: https://www.donneesquebec.ca/recherche/dataset/vgat_296280560

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
municipal members. Display boundaries are simplified separately. Candidate
repairs are explicitly labelled and are excluded from normal coordinate matches.
These transformations and cross-source differences are described in docs/research.
The data publishers do not endorse the project. Preserve attribution and source
licences when distributing source data, derived datasets or map displays.
