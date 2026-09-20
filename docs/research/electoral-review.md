# Electoral implementation review — 2026-09-19

Scope: source acquisition and import, immutable releases, electoral identities and
edition lifecycle, browsing and lookup APIs, map controls, packaging and local
Docker deployment. This review also rechecks the existing administrative geography,
background opacity, region labels and surrounding-area navigation.

## Findings patched

| Finding | Correction and regression evidence |
|---|---|
| Historical lookup and map coverage reused the default edition's inventory. Missing default jurisdictions could return `no_match`. | Coverage is derived per edition and projected onto the actual selection. All 13 jurisdictions are reported; absent explicit selections are `not_selected`, absent defaults are `unavailable`. Tests cover historical counts and missing default coverage. |
| A match could hide incomplete coverage in a second selected edition. | A missing match from a partially covered selected edition retains `review_required`. A synthetic comparison reproduces this case. |
| An upcoming edition could be imported but could not subsequently become current without changing its identity. | Evidenced `edition_updates` create a new release with revised metadata/defaults while preserving all district IDs, geometry blobs and the earlier release. Validity dates are retained on imported and updated records. |
| An output directory could be created inside its immutable input release. | The importer rejects output paths inside the resolved input directory before writing. |
| A collapsed invalid polygon could crash the importer when no polygonal repair survived. | Missing candidates retain their source identity and available uncertainty bounds. Empty display collections are emitted where needed. No repair is approved automatically. |
| Reprojection rounding could make an invalid publisher polygon appear valid. | Validity is recorded in the original source CRS before transformation. Invalid originals remain unavailable for assignment even if the transformed outline passes validity checks. |
| Mapped, padded or prefixed catalogue codes could overwrite the publisher's original identity. | Source records carry publisher IDs independently from catalogue codes; padding precedes prefixes. Tests exercise a mapped publisher name and padded catalogue number. |
| Source-key reuse did not pin the complete parser/CRS/identity specification. | A canonical specification digest accompanies the byte hash. Changed specifications require new source keys. Legacy releases without this digest also require new keys for subsequent imports. |
| Import representative-point checks only tested polygons against their own points. | Validation now invokes the serving lookup engine for every assignable imported district and rejects an absent result. A test simulates a broken lookup and confirms atomic rejection. |
| Malformed source responses or metadata could produce Python errors or invalid canonical JSON. | ArcGIS/WFS responses, finite JSON, counts, IDs, fields, edition dates, coverage references and predecessor relationships are validated explicitly. |
| A failed comparison download removed otherwise available active boundaries. | Boundary files load independently; available outlines remain visible and a retry control reloads failures. The browser check injects a 503, retains all 78 Québec federal districts, then restores the comparison layer. |
| District search did not accept the stable catalogue ID. | Search includes the full ID and catalogue code; browser acceptance locates Avalon using `ca-fed-2023-10001`. Empty and duplicate API selections are rejected explicitly. |

The regression cases are in `tests/test_electoral_review.py`, with source-response
cases in `tests/test_source_acquisition.py` and browser cases in
`tools/check_map_electoral.py`. The first seven review tests were run against the
original implementation and all seven exposed failures before being patched.

## Source limits retained

The original-CRS audit of every pinned publisher source found the same seven
invalid district geometries: Saskatchewan's Wood River and PEI districts 5, 8,
18, 19, 23 and 26. They remain display candidates only. Their full-boundary API
requests must return 409, and lookup results must keep them as review candidates.

Source overlaps remain reported and ambiguous where applicable. This review does
not establish gap-free legal coverage: independent authoritative jurisdiction
envelopes are still unavailable. No boundaries were clipped to background water
features, and display geometry is never used for assignment.

The six previously unconfirmed source reuse permissions remain unconfirmed;
see [the source inventory](electoral-layers.md). Public data publication remains
blocked for those products. Local packaging and Docker deployment do not change
the public dataset lock or publish any source, image or package.

## Verification

- All 169 synthetic tests passed, including the review regressions and API tests.
- Real-data acceptance passed 7,596 administrative lookups, 1,244 electoral
  representative-point lookups and seven pending-candidate checks.
- All administrative database tables match the administrative baseline. All
  electoral identity fields, assignment/candidate geometry blobs and display
  files match the previous local electoral build byte for byte.
- Chromium checks passed for all 13 electoral branches, historical selection,
  comparisons and failed-download retry; background and boundary opacity,
  collision-free region labels, provider failure, neighboring-area mouse and
  keyboard navigation, rapid selection changes, and desktop/mobile layout.
- Python wheel/source archives passed the publication-content checks; the wheel
  contains no downloaded boundary data. The offline secret scan found no
  unresolved findings.
- The combined Docker image passed offline, read-only startup, authentication,
  private-file protection and deployment fingerprint checks under a 2,048 MiB
  memory limit with swap disabled. Startup was 21.34 seconds; peak container
  memory was 560.9 MiB, including the verification probe.
- The updated loopback deployment passed the electoral browser checks and live
  API checks for historical coverage, default counts, all seven full-boundary
  409 responses and their review-candidate lookups. Docker reports healthy; the
  previous local container is retained for rollback.

Audited dataset manifest SHA-256:
`9f65f49423d7f07c882c66729abca375d77cd688a2f32b0eb10ba96b95f7900e`.

Reproduce the compatibility check by adding `--previous PATH_TO_EARLIER_ELECTORAL_RELEASE`
to `tools/check_electoral_data.py`; this checks identities, geometry blobs and
display bytes alongside the normal lookup acceptance. See [DATA.md](../DATA.md)
for import and activation commands.
