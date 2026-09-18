# Québec refresh: municipal identities, city areas and remaining gaps

Reviewed 2026-09-18 UTC. This is an additive, review-required release. It preserves
all original national source rows and the original 46 city areas. The
[refresh manifest](../../totally_normal_maps/quebec-refresh-2026-09.json) pins six
source downloads, their complete identity sets, parent relationships, licensing
and evidence. The [build workflow](../DATA.md) keeps source files in ignored local
storage and creates a new immutable run and serving release.

## Regions and municipalities

All **17 administrative regions** remain. The earlier audit matched regional
codes for all 1,267 municipal codes shared by the national snapshot and the current
[Québec municipal register](https://www.donneesquebec.ca/recherche/dataset/repertoire-des-municipalites-du-quebec).
The register and national CSD catalogue have different coverage definitions; their
raw counts cannot be treated as interchangeable.

Two documented mergers update current municipal identities:

| Current identity | Effective date | Retained predecessor CSDs | Region |
|---|---|---|---|
| La Pocatière, `ca-qc-mun-14082` | 2025-09-03 | `2414085` La Pocatière; `2414090` Sainte-Anne-de-la-Pocatière; `2414080` Saint-Onésime-d’Ixworth | Bas-Saint-Laurent |
| Hébertville, `ca-qc-mun-93022` | 2026-01-01 | `2493020` Hébertville; `2493025` Hébertville-Station; `2493030` Saint-Bruno | Saguenay–Lac-Saint-Jean |

Evidence: [La Pocatière merger announcement](https://www.lapocatiere.ca/regroupement-de-la-ville-de-la-pocatiere-de-la-paroisse-de-sainte-anne-de-la-pocatiere-et-de-la-municipalite-de-saint-onesime-dixworth/)
and [Québec's Hébertville announcement](https://www.quebec.ca/nouvelles/actualites/details/saint-bruno-hebertville-et-hebertville-station-se-regroupent-et-consolident-leurs-services).
Provincial identities and regional codes are checked against the
[MRNF SDA municipal layer](https://servicescarto.mern.gouv.qc.ca/pes/rest/services/Territoire/SDA_WMS/MapServer/2),
V2026-08, licensed under CC BY 4.0. The provincial codes do not become invented
StatCan CSD identities.

Successor assignment polygons use the **complete union of the national predecessor
polygons**. Current SDA polygons are archived as comparison evidence, not substituted
silently. In EPSG:3347, La Pocatière's provincial polygon covers 81.38% of the
250.81 km² national predecessor union; Hébertville covers 99.57% of its 382.44 km²
union. Those figures measure geometric source differences, not missing population.
The La Pocatière discrepancy is explicitly flagged. No omitted portion is discarded
or assumed to be water. The affected regional outlines remain unions of their
current members; their geographic extent is preserved.

The six old identities remain directly queryable with their original full
boundaries, successor links and an exclusive `valid_to` date. They are excluded
from current navigation and coordinate assignment. The current Québec layer has
**1,274 municipal/statistical identities**, down from 1,278; the Canadian current
count becomes **5,050**, with six additional historical records.

Two names are updated by their existing geographic codes:

- `2409020`: Sainte-Jeanne-d'Arc → Sainte-Jeanne-d'Arc-de-la-Mitis.
- `2414045`: Saint-Germain → Saint-Germain-de-Kamouraska.

Original names remain searchable aliases and retained source names. Seven
source-specific Indigenous land names remain unchanged, with provincial register
names added as aliases: Wôlinak, Manawan, Wemotaci, Obedjiwan, Uashat, La Romaine and
Natashquan. This does not equate a community's governance with a statistical land
boundary.

## Added city areas

| Municipality | Addition | Parent in the map | National municipal outline covered¹ |
|---|---|---|---:|
| Québec | 35 quartiers | Six existing arrondissements | 96.15% |
| Lévis | 10 sectors | Three existing arrondissements | 98.76% |
| Laval | 14 quartiers / former municipalities | Municipality | 99.51% |
| Trois-Rivières | 29 named quartiers | Municipality | 85.67%, explicitly partial |
| Terrebonne | Terrebonne, Lachenaie, La Plaine | Municipality | Boundaries unavailable |

¹ Intersection of the union of full source polygons with the national municipal
polygon, in EPSG:3347. This is not population coverage or a legal completeness
certificate. Québec's comparison uses its unapproved repair candidate and remains
flagged accordingly. No source polygons are clipped to make sources agree.

Together with the original layer, the catalogue contains **137 city-area
identities in 12 municipalities**, of which **134 have full source boundaries**.
The original 41 arrondissements and five Gatineau sectors remain unchanged.

Source qualification:

- [Ville de Québec — Quartiers](https://www.donneesquebec.ca/recherche/dataset/vque_9):
  35 `ID`/`NOM` identities; file modified 2026-09-13. Parentage is pinned using the
  city's [arrondissement/quartier listing](https://www.ville.quebec.qc.ca/apropos/portrait/quelques_chiffres/quartiers/index.aspx).
- [Ville de Lévis — Secteurs](https://www.donneesquebec.ca/recherche/dataset/secteur-levis):
  ten `ID`/`NOM` identities; file modified 2022-05-16. Parentage follows the city's
  [presentation of its arrondissements](https://levis.ca/fr/ville/decouvrir-levis/presentation-de-la-ville).
- [Ville de Laval — Limites des anciennes municipalités](https://www.donneesquebec.ca/recherche/dataset/limites-des-anciennes-municipalites):
  14 `NOM` identities; file modified 2017-02-13. The source has no numeric feature
  identity, so each exact source name and its permanent catalogue ID is pinned.
  These are the familiar 14 former-city quartiers, distinct from six planning
  sectors; see the city's [sociodemographic portrait](https://www.laval.ca/wp-content/uploads/2025/02/portrait-sociodemographique-jeunes.pdf).
- [Ville de Trois-Rivières — Quartiers, noms populaires](https://www.donneesquebec.ca/recherche/dataset/quartier-nom-populaire-v3r):
  29 `ID`/`NOM` identities; file modified 2026-09-01. This is the publisher's named
  quartier layer, not an inferred partition into six former municipalities.

All four boundary datasets are published under **CC BY 4.0**. A modification date
does not establish the effective date of every boundary. Bytes, identity properties,
feature counts, WGS84 coordinates, valid full polygons, vertex limits and explicit
parentage are checked before import. Simplification is used only for display.

Terrebonne's [urban plan](https://terrebonne.ca/wp-content/uploads/2026/01/reglement-1000-plan-urbanisme.pdf)
documents the three former-city sectors. No reusable full polygon source was
qualified during this review. Names are selectable and searchable; the map states
that their boundaries are unavailable. Full and display boundary requests return
409. Their common municipal bounding box supplies conservative lookup uncertainty,
not assignment geometry. Electoral districts, newer planning sectors and a traced
PDF outline are not substitutes for these three boundaries.

## Cross-source discrepancies

Parentage is an explicit semantic relationship; different polygon sources can
cross it. Saint-Sauveur belongs to La Cité-Limoilou in the city's listing, but
approximately **16.4%** of its quartier source lies outside the retained SDA
arrondissement. A single evidenced manifest exception allows up to 17% for this
identity. Other sources retain the default 10% maximum outside a parent; any
outside fraction over 1% receives a review note. The municipality comparison
threshold remains 10% for every child.

Québec's Des Châtels and Neufchatel Est—Lebourgneuf also produce parent discrepancy
notes. Lookup returns both geometric matches and semantic ancestors, reports
hierarchy/geometry disagreement, and never clips a child to remove the evidence.
An arrondissement and its own quartier are a normal nested match. Incomparable
siblings at a shared edge remain ambiguous.

Sibling overlap is checked within each source partition, with a tolerance of the
greater of 1 m² and one millionth of union area. Numerical residual overlaps in
Québec and Trois-Rivières are below that threshold. Trois-Rivières's uncovered
14.33% remains a declared gap, as does the original partial MacNider coverage in
Métis-sur-Mer. Neither gets an invented remainder quartier.

## Repair review

All four Québec municipal repair candidates remain **unapproved**. Their original
and candidate geometries remain retained; none is promoted to ordinary assignment.
The national total of 58 unapproved municipal repairs is unchanged.

| Municipality / CSD | Original → candidate holes | Candidate versus provincial reference: symmetric difference / candidate area |
|---|---:|---:|
| Québec, `2423027` | 4 → 5 | 1.43% |
| Oka, `2472032` | 10 → 12 | 8.03% |
| Notre-Dame-du-Nord, `2485090` | 3 → 5 | 2.57% |
| Côte-Nord-du-Golfe-du-Saint-Laurent, `2498015` | 1 → 2 | 84.35% |

These measurements compare the national repair candidate with the current SDA
polygon in EPSG:3347. They do not establish that a repair is correct. Small net
area change does not resolve changed hole topology. The large Côte-Nord discrepancy
requires source-boundary reconciliation before any decision. Its GeoJSON response
was incomplete and rejected; the complete native ArcGIS JSON polygon contains
425,109 vertices in EPSG:3857, transformed for comparison. Reference request URLs
and snapshot hashes are retained in `repair_review` in the manifest.

## Remaining municipal source differences

The register's provincial-only codes after accounting for the mergers are:
`12802`, `12804`, `90801`, `99820`, `99908`, `99910`, `99914`, `99916`, `99918`,
`99920`, `99922`, `99924`. National-only codes are `2472802`, `2485803`, `2485804`,
`2489802`, `2498802`. These concern Indigenous land/community distinctions and
unorganized territories. They require a separately evidenced crosswalk; retaining
an unmatched national identity is preferable to silently deleting its geometry.
No assertion that all current Québec municipal definitions have been reconciled
is made by this refresh.

## Acceptance

Synthetic offline tests cover immutable source rows, complete merger unions,
historical filtering and aliases, nested lookup semantics, localized missing-shape
uncertainty, changed checksums/identities, explicit parent exceptions and malformed
or overlapping sources. The explicit real-data API acceptance checks all 1,270
available current Québec municipal polygons and all 134 available city-area
polygons. It also checks the missing shapes, historical identities and unchanged
baseline rows. Browser acceptance covers nested navigation, all added cities,
partial/missing coverage, predecessor-name search, keyboard use and mobile layout.
Passing these checks does not approve the outstanding geographic discrepancies.
