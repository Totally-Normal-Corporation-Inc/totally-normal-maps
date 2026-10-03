# Boundary review acceptance — 2026-10-03

Status: implemented and built locally. No dataset upload, lock activation or
deployment was performed. This review uses the existing cached, checksum-pinned
source snapshots; it does not acquire newer geography.

See [the repair policy and reproduction commands](../BOUNDARY_REPAIRS.md).

## Results

The audit inventories 170 pending records, including derived regions and retained
electoral editions. All 125 source repair candidates reproduce from local source
snapshots. It approves 71 source boundaries: 49 topology-preserving repairs and
22 bounded minor corrections. Sixteen dependent regions then qualify because
their complete approved member union equals the stored regional candidate.

| Record family | Newly approved source boundaries | Remaining source repairs |
| --- | ---: | ---: |
| Municipalities | 44 | 13 |
| City areas | 2 | 2 |
| Provincial electoral districts, including retained editions | 2 | 5 |
| Municipal electoral districts | 23 | 34 |
| Total | 71 | 54 |

The remaining inventory contains those 54 source repairs, three dependent regions
(Kenora, Interlake and Westman), 19 city-area parent disagreements, four city-area
overlap warnings and three missing city outlines: 83 records in total. The audit's
99 `retain_unapproved` decisions describe the input; the separate application
effects record the 16 regions subsequently qualified through member approval.
These counts are not counts of independent current neighbourhood defects.
The viewer's broader review counter also includes valid features with source or
coverage notices; it is not the count of pending topology repairs.

Greenbelt East qualifies without territory correction. Its exclusion matches
Blackburn Hamlet. Greenbelt West's exclusion matches Bells Corners East and West;
a 31.745316 m² assignment-coordinate sliver is relinquished to existing validated
neighbours. The residual measured overlap is approximately 0.00000027 m². Both
Greenbelts are now available for full-geometry assignment; simplified display
geometry remains unsuitable for assignment.

The largest minor correction affects 55.859784 m² (Mermaid–Stratford, retained
PEI edition). Every minor approval satisfies all three ceilings: five metres,
100 m² and 0.01% of feature area. Existing validated assignment polygons are
byte-identical. No positive population value is inferred or modified.

Marysville and Enfield remain unresolved. Parent disagreements inspected in this
batch range from approximately 10.77% to effectively the whole child polygon
outside the recorded parent. Whitehorse overlaps include MacRae Industrial versus
Whitehorse Copper (approximately 220,910 m²) and Marwell versus WhitePass Industrial
(approximately 33,651 m²). These require source/relationship decisions beyond the
minor-correction policy. Terrebonne's three missing outlines remain explicit.

Ottawa's coverage inventories now consistently report 116 assignment boundaries
and zero unapproved repair candidates. Measuring intersections in WGS84 before
projection finds approximately 247.771335 m² of pre-existing sibling overlap,
versus 247.771356 m² after approval. The older report's differently computed
overlap figure is preserved as historical evidence; the measurement change must
not be mistaken for a newly introduced 247 m² conflict.

## Immutable identities

| Artifact | SHA-256 |
| --- | --- |
| Input pre-package release | `e64e5b9f92f7722320f68841ee20d110232a7ada5f5941fce4e6d9bd1e283201` |
| Canonical audit record | `2f52079450f498920c8b799c4daac8873a3cc9c516ebfac934ecffb4278a7312` |
| Reviewed pre-package release | `6d0f2c5fc777e95bb37f5d663a2a25a7006faf04712d7f8c248a61105894fa63` |
| Reviewed release with display packages | `440ab49e827441de1342f8e653ee29e7f9dc0d13ae00c44f268762b973717f82` |
| Distribution ZIP | `40f95aea3b6fcbc981a267cb6f57e2bc410008a37e49fe8ed7039fec9d6dfb01` |

The audit identity hashes canonical JSON as defined by `boundary_review.digest`;
it is not the hash of the pretty-printed audit file. Complete per-area evidence,
source hashes, decisions, measurements and assignment probes are retained in the
release report. Earlier source/candidate ledgers remain on the area records.

The package rebuild contains 5,337 ready bundles for 5,194 eligible roots, plus
the same nine unsupported group definitions with `membership_unresolved`:
`ca-sac-2021-305`, `310`, `320`, `328`, `329`, `330`, `335`, `481`, and `735`
(the same `ca-sac-2021-` prefix applies to each suffix).
The support inventory retains the exact missing identities. All 10,674 decoded
and gzip geometry objects are byte-identical to the prior packaged release
`f9c39a31fdbf64a52d687c6bda29da2c4248813b4f157d69ca8e9b5c58b9de53`.
The new descriptors carry the revised qualifications and dataset binding.

The local distribution is `canada-topology-batch-reviewed-v1.zip`, 250,954,219
bytes, with a generated lock naming `dataset-440ab49e827441de1342-r1`. The tag
identifies the prepared distribution; it has not been created or uploaded remotely.

## Verification and build cost

The full synthetic suite passed: 327 tests. The release application passed 17,506
assignment probes across all 71 approved source boundaries, including component,
hole and boundary-offset samples. It also checked every previously valid polygon
for exact byte preservation and verified the completed release before its atomic
local publication. Failed earlier staging attempts left the input release intact.

Real-data API acceptance passed with the pre-package input as baseline: 2,047
city-area lookups, 1,274 Québec municipal lookups, 616 Ontario municipal/regional
lookups, 3,271 other jurisdiction lookups and 450 grouped-region member lookups.
The baseline check preserved 5,010 unchanged CSD rows, 2,073 city-area rows,
127 region rows and all 3,385 CSD-to-region membership rows. Approved record and
geometry changes were separately checked against the audit.

Loopback Chromium acceptance passed across the 2,075 city-area catalogue, all
13 jurisdictions, nested navigation, issue filtering and mobile layouts, with no
page errors. Both Greenbelt approval labels were checked; West displays the
31.745 m² correction. Browser checks used `background=none` and no online basemap.
The distribution was unpacked through the normal bounded, checksummed archive
reader, then the extracted dataset passed `maps verify-release` against its pin.

Commands:

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python tools/check_real_data.py --dataset "$REVIEWED" --baseline "$INPUT"
node --check totally_normal_maps/web/preview.js
git diff --check
```

One measured run on an Intel Core i5-3210M, Linux x86-64, Python 3.14.7, Shapely
2.1.2 and GEOS 3.13.1, using cached local inputs:

| Operation | Elapsed | Peak resident memory |
| --- | ---: | ---: |
| Source replay, application and release verification | 409.836 seconds | 2,356,168 KiB |
| Display-package rebuild and verification | 129.217 seconds | 997.621 MiB |
| Distribution archive creation | 113.785 seconds | 1,628,384 KiB |
| Full synthetic suite | 149.842 seconds | Not separately measured |
| Real-data API acceptance | 94.293 seconds | Not separately measured |

The final release files total 489,267,536 bytes; package files account for
71,661,296 bytes. The test/build processes shared the machine, OS caches were not
flushed, and these are single-run build observations, not API latency or capacity
benchmarks. No HTTP request performs these repairs or builds.

Activation requires the reviewed-assignment loader code and this new dataset to
ship together. The repository's selected dataset source and lock remain unchanged.
Retain the previous verified code/dataset pair for rollback.
