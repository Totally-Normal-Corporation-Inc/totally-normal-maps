# Ontario refresh — 18 September 2026

The local refresh retains all **40 Ontario regional identities and 578 municipal /
statistical identities**, updates nine municipal boundaries for four adopted changes,
and adds **520 city-area identities**, of which **518 have assignment geometry**.
Ontario's 414 local municipalities remain covered; the remaining national identities
are reserves, settlements and unorganized statistical areas. Geographic parentage
never asserts municipal jurisdiction over an Indigenous community.

## Current boundaries and preserved history

| Effective date | Change | Current boundary publisher |
|---|---|---|
| 2026-01-01 | Barrie / Oro-Medonte / Springwater | Land Information Ontario |
| 2026-01-01 | Woodstock / Norwich | Land Information Ontario |
| 2026-01-01 | Casselman / The Nation | Land Information Ontario |
| 2026-05-01 | Hanover / West Grey | County of Grey |

Adoption evidence: [Barrie decision](https://ero.ontario.ca/notice/025-1324),
[Woodstock ministerial order](https://www.ontario.ca/document/ontario-gazette-volume-159-issue-03-january-17-2026/government-notices-other),
[Casselman approval](https://www.casselman.ca/en/news/the-province-has-approved-a-municipal-restructuring-proposal-to-transfer-a-portion-of-land-from-the-nation-municipality-to-the-municipality-of-casselman),
and [Hanover effective-date announcement](https://www.hanover.ca/news/looking-future-ministerial-order-supports-long-term-economic-prosperity-town-hanover-and).
The [provincial municipal layer](https://www.arcgis.com/home/item.html?id=64fb702e16204c3e88b528d9759f1174)
still has pre-expansion Hanover / West Grey geometry. The
[county's layer](https://www.arcgis.com/home/item.html?id=1915f2e37a5c4ea7801a075eccaad32a)
contains the expansion; its two records were updated 30 April 2026. The layer and
parent service explicitly select the **Grey County Open Data Licence**. That is a
separate section of the [Terms page](https://maps.grey.ca/pages/terms), not its
restricted general GIS viewing licence. The complete section is also available in
[the publisher's page data](https://www.arcgis.com/sharing/rest/content/items/9bada6ae370e479f8fa98774a0219bd5/data?f=json).

The national CSD identifiers and original database rows are unchanged. A separate
`boundary_revision` table supplies current full publisher polygons; Oro-Medonte
includes all three source extent parts (mainland, islands and water). The four
affected regional unions are rebuilt. Simcoe remains an unapproved regional
candidate because Ramara's original repair is still unapproved.

These sources have different precision, shorelines and water coverage. A difference
in total area is **not** a measure of annexed land. Every old/new municipal symmetric
difference is stored as review uncertainty, including old extents omitted by the
new source. Such locations return `review_required`, with current full-source matches
where available; uncertainty polygons never contribute assignments. Complete original
boundaries remain in the source table and the earlier immutable release. Display
simplification is separate. The adopted effective date is the change date, not a
claim that every source vertex was legally certified on that date.

Tarbutt's current name follows [the municipality](https://tarbutt.ca/), while
`3557014` and the national alias “Tarbutt and Tarbutt Additional” are retained.

## City areas

| City | Added identities | Usable assignment boundaries | Navigation |
|---|---:|---:|---|
| Toronto | 6 former municipalities + 158 neighbourhoods | 164 | Switch between two independent schemes |
| Ottawa | 116 ONS generation 3 study areas | 114 | Neighbourhood study areas under Ottawa |
| Hamilton | 6 communities + 234 neighbourhoods | 240 | Neighbourhoods nested under the publisher's COMMUNITY attribute |

Sources: Toronto [former municipalities](https://open.toronto.ca/dataset/former-municipality-boundaries/)
and [neighbourhoods](https://open.toronto.ca/dataset/neighbourhoods/),
[Ottawa ONS](https://www.arcgis.com/home/item.html?id=439875b741f34985a7001a1491c2d79b),
Hamilton [communities](https://www.arcgis.com/home/item.html?id=b47b85ebd505425e959e26dadf16448f)
and [neighbourhoods](https://www.arcgis.com/home/item.html?id=30e74cacb3b641d799629ebccad9d615).
Exact downloads, checksums, identities, licences and parent evidence are pinned in
`totally_normal_maps/ontario-refresh-2026-09.json`. Original download bytes stay
under ignored `.local/`, outside public source code and serving releases.

Toronto neighbourhoods are not forced under former municipalities. Coordinate
lookup can match both independent schemes without false ambiguity; overlapping
siblings in the same scheme remain ambiguous. Hamilton's community field supplies
explicit parentage. One Hamilton neighbourhood (East Mountain Industrial Business
Park) lacks a planning-unit code: its pinned OBJECTID 178 is the explicit fallback;
the other 233 retain planning-unit codes.

Full outlines cover approximately 96.3% / 96.4% of Toronto's national outline,
99.997% of Ottawa's (including the two unapproved candidates), and 99.7% / 97.9%
of Hamilton's. These are source comparison measurements, including water differences,
not proof of exhaustive local community coverage. ONS uses generalized research
geographies and does not represent every locally named community separately.

## Repairs and outstanding coverage

Seven national municipal repairs remain unapproved. All change hole topology even
though their area changes are near zero; none loses a nonpolygon vertex in the
existing repair ledger.

| Municipality / statistical area | Original → candidate holes |
|---|---:|
| Scugog | 1 → 2 |
| Ramara | 9 → 10 |
| Chippewas of the Thames First Nation 42 | 1 → 4 |
| Cochrane, Unorganized, North Part | 15 → 16 |
| Algoma, Unorganized, North Part | 7 → 8 |
| Thunder Bay, Unorganized | 17 → 18 |
| Kenora, Unorganized | 90 → 92 |

Provincial comparison polygons leave about 1.19 km² of the Scugog candidate and
138.48 km² of the Ramara candidate uncovered. They cannot silently replace complete
national geometry or certify the disputed holes. Seven associated regional outlines
also retain unapproved status. Near-zero area change alone is not repair approval.

Ottawa ONS **3050 Greenbelt (East)** and **3051 Greenbelt (West)** have ring
self-intersections in both the canonical open-data service and the municipal map
service. Their identities and labelled display candidates are included, but full
assignment boundaries are unavailable. Their bounding boxes mark local uncertainty.

The official GeoOttawa former-municipality layer contains 11 identities, including
Kanata, Nepean and Gloucester. An explicit reuse licence for that particular layer
was not established, so its geometry is deferred. Orléans also has no separately
qualified broad community outline here. Other Ontario cities still need city-area
sources. GTA and other overlapping informal regions are not administrative parents.
The 17 direct Ontario children without a regional parent remain intentional.

## Verification

The refresh builds offline and refuses existing output directories, changed source
bytes, altered identities, omitted municipal extent parts and repair promotion.
Focused synthetic tests cover retained source rows, transfer lookup, uncertainty in
removed extents, independent schemes, nested parentage and unavailable repairs.
Real-data acceptance separately checks all 652 usable city areas across Québec and
Ontario, 604 Ontario municipal / regional representative points, preserved Québec
lookups and every original database row. Browser acceptance checks Toronto's layer
selector, Hamilton nesting, Ottawa repair labels and existing province navigation.
No deployment, push or publication is part of this refresh.
