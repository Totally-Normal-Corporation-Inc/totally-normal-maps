# Offline boundary repair and confirmation

`audit-boundary-repairs` and `apply-boundary-repairs` review checksum-pinned local
source snapshots. They do not download sources, change an existing release,
publish data, or deploy. The contract is `boundary-topology-review.v1`.

The [2026-10-03 acceptance record](research/boundary-repairs-2026-10.md) reports
the first batch, unresolved cases, immutable identities and measured build costs.

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
  significant parent disagreements and non-polygon source assemblies remain
  unresolved. A small total area alone does not authorize a long displaced line.

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
