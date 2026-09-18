# Québec city-area source decisions

Research snapshot: 2026-09-16. Dataset remains subject to review.

This records the original 46-area layer. See the later [Québec refresh](quebec-refresh.md)
for municipal updates, additional quartiers/sectors and the remaining gaps.

## Included coverage

| Municipality | Official areas | National city outline covered¹ |
|---|---:|---:|
| Montréal | 19 arrondissements | 96.4% |
| Québec | 6 arrondissements | 96.1% |
| Sherbrooke | 4 arrondissements | 99.7% |
| Lévis | 3 arrondissements | 98.8% |
| Longueuil | 3 arrondissements | 94.7% |
| Saguenay | 3 arrondissements | 99.4% |
| Grenville-sur-la-Rouge | 2 arrondissements | 95.5% |
| Métis-sur-Mer | 1 arrondissement: MacNider | 8.9%, partial coverage |
| Gatineau | 5 secteurs: Aylmer, Hull, Gatineau, Masson-Angers, Buckingham | 99.0% |

¹ Geometric intersection with the full 2025 national municipal polygon,
including its statistical water extents. These are **not population or event
coverage percentages**. Differences in source boundaries/vintages have not
been individually adjudicated. MacNider does not partition the whole city;
the map explicitly labels partial coverage and does not invent a remainder.

## Sources and identities

- Québec MRNF [SDA administrative boundaries](https://www.donneesquebec.ca/recherche/dataset/decoupages-administratifs),
  [arrondissement layer 3](https://servicescarto.mern.gouv.qc.ca/pes/rest/services/Territoire/SDA_WMS/MapServer/3),
  release **V2026-08**, queried with longitude/latitude output on 2026-09-16.
  All 41 source codes, names, parent names and versions are pinned. The request
  includes only these identity fields, not contact attributes.
- Ville de Gatineau [administrative boundaries](https://www.donneesquebec.ca/recherche/dataset/vgat_296280560),
  GeoJSON file updated **2025-04-24**; its effective boundary date is unspecified.
  Source `CODEID`, `MUNID`, `ENTITEID`, name and `TYPE: Ex ville` are retained.
  The display type **Secteur** follows the city's
  [sector terminology](https://www.gatineau.ca/portail/default.aspx?p=guide_marque%2Fnos_normes%2Fnormes_redaction%2Fterminologie%2Fsecteurs).
- Both sources use **CC BY 4.0**. Attribution is visible in the preview.

The [checked manifest](../../totally_normal_maps/city-areas-quebec-2026-09.json)
pins the two source checksums, explicit national parent IDs, 46 identities,
per-city counts, scope and partial-coverage decision. Parent links do not rely
on runtime name matching. `2481017` is Gatineau city; `ca-qc-2481017-sector-15`
is the Gatineau sector. Québec source codes use IDs such as `ca-qc-arr-rem21`.
Source spelling is retained, including `LÎle-Bizard - Sainte-Geneviève` in SDA.
No electoral districts or informal neighbourhoods are added.

## Boundary validation and limits

All 46 source geometries are valid, with **55,569 full-boundary vertices**.
The original WGS84 polygons are stored without clipping or repair. Display
polygons are simplified independently at **20 metres**, approximately 392 kB
for the Québec city-area GeoJSON. The preview is not suitable for deciding
which side of a street or boundary an address occupies.

Parent intersections and sibling overlaps are measured in EPSG:3347:

- Every child must overlap its explicit parent by at least **90%**. Every city
  declared citywide must cover at least **90%** of the national parent polygon.
  A gross mismatch rejects the build. Partial coverage is allowed only when
  explicitly declared in the manifest.
- Sibling intersection area must stay below the greater of **1 m²** and
  **one millionth of the union area**. No substantive sibling overlap was
  found; reported residuals are under 0.000001 m².
- More than **1% outside the parent** produces a review note. Five areas cross
  that threshold: Aylmer, Lachine, Pierrefonds - Roxboro,
  LÎle-Bizard - Sainte-Geneviève and La Haute-Saint-Charles. The maximum is
  approximately **4.23%**. These are evidence thresholds, not approval rules.
- Québec city's existing national boundary requires an unapproved repair.
  Comparisons for its six arrondissements disclose that dependency. Their own
  valid source polygons remain intact. There are **10 city areas with review
  notes**, including the overlap of those two categories; the overall map
  review counter is **86**.

Smaller discrepancies are also recorded in `report.json`. Exact source
alignment, boundary adjudication and production geography approval remain
pending. Invalid or changed future city-area sources fail closed and require
an explicitly reviewed source/manifest update.

