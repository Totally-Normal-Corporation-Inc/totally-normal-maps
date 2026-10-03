# Offline boundary repair and confirmation

`audit-boundary-repairs` and `apply-boundary-repairs` review checksum-pinned local
source snapshots. They do not download sources, change an existing release,
publish data, or deploy. The contract is `boundary-topology-review.v1`.

The [2026-10-03 acceptance record](research/boundary-repairs-2026-10.md) reports
the first batch, unresolved cases, immutable identities and measured build costs.
The follow-up [municipal exclusion review](research/municipal-exclusions-2026-10.md)
resolves the 13 municipal cases through exact source partitions.
The [remaining-record review](research/remaining-boundaries-2026-10.md) accounts
for the next 67 records individually, including repaired electoral hierarchy.

Topology approval qualifies a particular source geometry for assignment. It does
not reconcile different source vintages, certify legal boundaries, approve source
licences, infer missing neighbourhoods, or remove the dataset's `review_required`
qualification. Display packages remain display-only even after their underlying
full assignment geometry is approved.

## Decisions

The audit accounts for every stored pending repair, dependent regional record,
city-area parent/overlap warning, and missing city outline. It distinguishes
retained editions and superseded identities. Source snapshots and original
candidate ledgers must reproduce exactly. Missing local snapshots are recorded;
checksum, identity, ledger or unexpected geometry failures reject the audit.

`approve_topology_only` requires a valid polygon candidate, unchanged source
boundary linework, no discarded coordinates, agreement with `buffer(0)` and
`make_valid(method="structure")`, and area differences limited to floating-point
roundoff. Unchanged original holes retain their source evidence. Newly represented
holes must exactly equal complete valid polygon components from the same source
scheme, including their boundaries. No component is clipped to manufacture proof.
Neighbour overlap is bounded by **both 1 m² and 0.00001%** of the candidate area;
the actual residual is recorded, not silently snapped away. Current assignment
neighbours are checked separately from the original source snapshot.

`approve_minor_correction` implements an explicit practical correction policy:

- At most **5 metres** of boundary displacement, tested with whole-line coverage
  in local proof corridors, not merely sampled vertices.
- At most **100 m² and 0.01%** of the feature's area. Both bounds apply to the
  combined affected area, including method disagreement and uncorroborated holes.
- Small changes must remain near original source boundary linework. A large
  exclusion cannot pass just because its perimeter is unchanged.
- The existing linework candidate is preferred. For small overlaps, existing
  valid source neighbours retain their whole territory; the pending candidate
  relinquishes the shared sliver. Overlaps with unresolved peers are not arbitrated.
- No already validated assignment is edited. Conflicts beyond these limits,
  significant parent disagreements and unexplained non-polygon sources remain
  unresolved. A small total area alone does not authorize a long displaced line.

The remaining-record review adds explicit, reproducible evidence rules:

- For non-CSD sources, node the original ring linework, classify every bounded
  face using the original coordinates' even/odd fill rule, and compare the
  complete filled surface with the candidate, `buffer(0)` and the structure
  repair. Exact agreement can substantiate source-defined exclusions without
  assigning those exclusions to a neighbour. The CSD joint-review policy stays
  unchanged.
- Exactly balanced directed source segments can be discarded as retraces. Their
  hashes are recorded; all filled-surface, method-disagreement and area checks
  still apply. A thin positive-area finger is not a retraced line.
- With that complete source-face proof, accumulated narrow overlap strips may
  total up to **6,000 m²**, still subject to **0.01%**, **5 metres**, valid existing
  owners and the combined affected-area budget. This measured exception admits
  the PEI strips (largest approximately 5,127 m²), not broad boundary shifts.
- A disappearing sliver of at most **100 m²**, already owned by validated peers,
  need not leave an artificial perimeter behind. Only old linework exactly inside
  the removed surface is exempted from the reverse displacement test. The
  correction must still lie within five metres of original source linework;
  method disagreement, relative area and combined area remain bounded.
- An importer-created GeometryCollection of exclusively polygon parts may be
  represented as a MultiPolygon for comparison, preserving every coordinate.
  The pinned source ledger and its original assembly hash remain unchanged.

Metric comparisons densify WGS84 edges for measurement only, including signed
source-area and displacement checks. This prevents differences in edge segmentation
from creating false projected-chord changes. Actual assignment coordinates are
never densified. Original source ledgers remain historical evidence.

`approve_source_child_union` is a separate source-partition decision, not a minor
area exception. The pinned combined Montréal borough/district source declares
borough.district codes. All child assignments must reproduce the source bytes;
their complete union must agree exactly with both alternative source repairs.
Ordinary peer overlap checks exclude only these proved children. A failed union
or changed child retains the warning. The audit records every reparented child,
its original metadata hash and unchanged geometry hash. Startup verifies the
complete hierarchy and exact union. Existing child assignments remain identical.
The Lachine repair uses this evidence; its display is regenerated with the existing
40-metre municipal-electoral simplification. Other approved displays retain their
existing coordinates. Editions, IDs, authority, attribution and applicability
dates remain unchanged.

Parent and overlap cases that cannot be resolved now include reproducible source
hashes, projected outside areas, intersected municipal identities and peer
containment/overlap measurements. Containment alone never manufactures parentage;
an unmatched area is not automatically classified as water.

`retain_unapproved` includes the individual failed check names. A retained parent
or overlap warning is a source/relationship review, not necessarily malformed
polygon topology. Missing outlines remain missing. Unknown gaps are never filled.

All comparison areas use EPSG:3347. Original municipal-electoral ledgers in older
releases incorrectly labelled square-degree areas as `*_m2`; these are reproduced
as historical ledgers, explicitly labelled when approved, and superseded by the
review's projected measurements. New municipal-electoral imports measure in
EPSG:3347 while retaining the repair itself in EPSG:4326.
For WGS84 changes, intersections and differences are extracted before projection
and their linear edges are densified to 0.00001 degrees for measurement only.
This avoids apparent slivers caused by projecting different vertex sequences.
Stored assignment coordinates are not densified. Current-overlap evidence records
the pre-correction conflicts; `current_overlap_correction` records the remaining
overlap after any final trim.

## Joint municipal exclusion review

The opt-in `--csd-exclusions-only` mode reviews the pending StatCan municipal
repairs together. Other record families remain outside that batch's scope.
It produces `csd-exclusion-partition.v1` evidence inside the existing audit
contract and permits topology-only approvals, without clipping or minor corrections.

A polygon hole can surround separate islands belonging to the same municipality.
The review requires an exact partition of each newly represented hole into whole
neighbouring polygon components and whole retained municipal island components.
Their union and boundary must equal the hole exactly, and the islands must not
overlap the neighbouring components. An unexplained gap, clipped neighbour or
unaccounted-for overlap cannot pass. The island area is retained territory, not
the size of a correction.

Pending neighbours may corroborate each other only as one complete group. Every
member must independently pass the unchanged-boundary, repair-method agreement,
discarded-coordinate, area-roundoff, source-ledger, identity and neighbour checks.
Projected assignment polygons are also checked against each other. Previously
reviewed source candidates can contribute evidence only when they exactly
reproduce the loaded assignment bytes and original source hash. A failed member
rejects the joint audit; no tentative member is independently promoted. Startup
checks the complete joint approval and rejects missing or inconsistent members.

Run the audit and apply commands below with `--csd-exclusions-only`, using the
previous reviewed **pre-package** release as input and a new audit/output path.
Only `--statcan-source` is needed; the other source directories are unnecessary.
The apply command must use the same mode as the audit. Previous audit evidence
and approvals are preserved in release history.

## Reproduce an audit and release

Use the exact pre-package release and its manifest SHA-256. Repeat `--source-dir`
for local source directories; filenames and checksums come from the existing
provider manifests. Source paths are not copied into public evidence.

```bash
.venv/bin/maps audit-boundary-repairs \
  --dataset "$INPUT" --manifest-sha256 "$INPUT_SHA256" \
  --statcan-source "$STATCAN_ARCHIVE" \
  --source-dir "$ONTARIO_SOURCES" --source-dir "$JURISDICTION_SOURCES" \
  --source-dir "$ELECTORAL_SOURCES" --source-dir "$MUNICIPAL_SOURCES" \
  --report "$AUDIT"

.venv/bin/maps apply-boundary-repairs \
  --dataset "$INPUT" --manifest-sha256 "$INPUT_SHA256" \
  --statcan-source "$STATCAN_ARCHIVE" \
  --source-dir "$ONTARIO_SOURCES" --source-dir "$JURISDICTION_SOURCES" \
  --source-dir "$ELECTORAL_SOURCES" --source-dir "$MUNICIPAL_SOURCES" \
  --audit "$AUDIT" --output "$REVIEWED"

.venv/bin/maps verify-release --dataset "$REVIEWED"
.venv/bin/maps prepare-display-packages \
  --dataset "$REVIEWED" --manifest-sha256 "$REVIEWED_SHA256" \
  --output "$PACKAGED" --report "$PACKAGE_REPORT"
.venv/bin/maps verify-release --dataset "$PACKAGED"
```

Inspect the audit before applying it. Apply recomputes the entire audit and refuses
any difference, including input release, source hashes, decisions, checks or runtime
versions. Both commands fail on unexpected errors. A successfully completed audit
may retain unresolved cases; its counts must be read rather than interpreting exit
zero as universal approval. Output destinations must be new.

Apply checks every existing assignment remains byte-identical and probes all new
components and holes plus sampled shell boundaries at 0.1-metre offsets. These
regression probes are recorded separately from territory evidence. They do not
claim exhaustive venue or legal-boundary validation. The final staged release is
loaded and verified before atomic publication to the new local directory.

Dependent regions qualify only when every member has assignment geometry and the
complete union equals their stored regional candidate. Otherwise they retain an
explicit reason. Missing population bindings may be rebound to the approved
territory without inventing counts; an existing positive population match blocks
automatic municipal promotion until that match is separately reviewed.

The release records `boundary_review`, `boundary_review_effects`, and compact
per-area proofs; subsequent batches retain `boundary_review_history`. Startup
rejects reviewed assignment bytes that differ from their approval. Sources,
licences and historical qualifications remain available through existing scoped
reference evidence resources.
Startup requires proof for every approval in the current and historical audit
inventories, independently of the stored record's repair marker. Missing rows,
missing assignment geometry and removed or changed audit links fail validation;
removing a repair marker cannot turn an approved record into an unchecked one.

Prepared package inputs are rejected: rebuild the final packages after repairs.
Geometry bytes may be reusable when only qualification changes; descriptors and
the dataset version still change. Tiny corrected assignments retain the existing
reviewed simplified display representation; full assignment and display geometry
remain separate contracts.

Create a distribution with the existing `package-dataset` command and a new
immutable dataset tag. Code supporting the reviewed-assignment proof must ship
with that dataset. Upload, lock activation and deployment are separate release
operations. Roll back using the previous verified code/dataset pair; do not edit
either immutable release or delete retained rollback artifacts.

## Tests

```bash
.venv/bin/python -m unittest tests.test_boundary_review tests.test_topology_review \
  tests.test_electoral tests.test_municipal_elections
.venv/bin/python -m unittest discover -s tests -t .
```

Tests use synthetic polygons and local fixtures only. Real-source audit/build and
release verification are separate acceptance operations, never ordinary CI source
downloads or production calls.
