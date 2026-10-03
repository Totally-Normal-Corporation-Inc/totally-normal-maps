# Municipal exclusion review — 2026-10-03

This follow-up reviews the 13 municipal/statistical areas retained by the
[first boundary review](boundary-repairs-2026-10.md). All 13 pass the focused
`csd-exclusion-partition.v1` review as topology-only repairs. No source boundary
linework is moved, no exclusion is filled and no existing assignment is edited.
Production activation remains separate from this local build.

## What the earlier check missed

The earlier check required a newly represented hole to equal valid neighbouring
polygon components. It did not account for separate islands belonging to the
municipality inside that hole, or allow two pending neighbours to qualify jointly.
Those restrictions left these 13 cases unresolved despite agreement between
repair methods and unchanged source boundary linework.

The focused review accounts for each hole using **whole** neighbouring components
and **whole** retained island components. Their union and boundary exactly equal
the hole; the retained islands and neighbouring territory do not overlap. No
neighbour is clipped to manufacture an exact match. Thirty-two newly represented
exclusions are corroborated this way; unchanged source holes retain their prior
evidence.

Pending neighbours qualify as one complete group, with every member independently
passing the source-ledger, boundary, method-agreement, discarded-coordinate,
roundoff and compatibility checks. Previously approved candidates may contribute
evidence only when they reproduce the loaded assignment bytes and source hash.
The group also has zero polygon overlap between its 13 members in the serving CRS.

This uses the checksum-pinned 2025 Statistics Canada source already cached for the
original import. Its [reference guide](https://www150.statcan.gc.ca/n1/pub/92-162-g/92-162-g2025001-eng.pdf)
describes the national subdivision coverage and source limitations. No newer
source data was acquired, and the review does not change the dataset's existing
source-vintage or legal-use qualifications.

## Dispositions

All rows below are approved. Island measurements are **retained land**, not land
removed or added by the repair. Measurements shown here are rounded; the release
audit retains the full values and per-component checksums.

| ID | Municipality/statistical area | Evidence resolving the earlier failure |
| --- | --- | --- |
| 3560090 | Kenora, Unorganized | Complete neighbouring components plus 5,131,591.040 m² of own islands |
| 4613056 | St. Clements | Complete neighbouring components plus 263,963.078 m² of own islands |
| 4615070 | Harrison Park | Joint component proof with Rolling River 67 |
| 4615071 | Rolling River 67 | Joint component proof with Harrison Park |
| 4615092 | Clanwilliam-Erickson | Complete components of jointly reviewed Rolling River 67 |
| 4710046 | Big Quill No. 308 | Complete neighbouring components plus 3,445,827.979 m² of own islands |
| 4716013 | Blaine Lake No. 434 | Complete neighbouring components plus 31,009.753 m² of own islands |
| 4716056 | Spiritwood No. 496 | Joint component proof with Pelican Lake 191A |
| 4716894 | Pelican Lake 191A | Joint component proof with Spiritwood No. 496 |
| 4718049 | Denare Beach | Joint proof with Amiskosakahikan 210; 2,405.366 m² of own islands retained |
| 4718090 | Division No. 18, Unorganized | Complete neighbouring components plus 37,491.532 m² of own islands |
| 4718855 | Amiskosakahikan 210 | Joint component proof with Denare Beach |
| 4816860 | Thebathi 196 | Previously approved Wood Buffalo components; 2,500.081 m² of own islands retained |

The stored full repair candidates are promoted without changing their coordinates.
Kenora, Interlake and Westman then qualify because their complete approved member
unions exactly equal their stored regional candidates. There are no remaining
pending CSD or regional assignment geometries in this reviewed release. Other
source/coverage notices on valid features are retained.

The remaining inventory is 67 records: two city-area repairs, 19 city-area parent
disagreements, four city-area overlap warnings, three missing city outlines,
five provincial electoral repairs and 34 municipal electoral repairs. These other
families are explicitly outside this batch's scope; their previous review remains
available in the audit history.

## Reproduction and verification

Start from the first reviewed **pre-package** release, keeping the first audit
and every earlier approval. See the [operating instructions](../BOUNDARY_REPAIRS.md).

```bash
.venv/bin/maps audit-boundary-repairs \
  --dataset "$INPUT" --manifest-sha256 "$INPUT_SHA256" \
  --statcan-source "$STATCAN_ARCHIVE" --csd-exclusions-only --report "$AUDIT"
.venv/bin/maps apply-boundary-repairs \
  --dataset "$INPUT" --manifest-sha256 "$INPUT_SHA256" \
  --statcan-source "$STATCAN_ARCHIVE" --csd-exclusions-only \
  --audit "$AUDIT" --output "$REVIEWED"
.venv/bin/python tools/check_real_data.py --dataset "$REVIEWED" --baseline "$INPUT"
.venv/bin/maps prepare-display-packages \
  --dataset "$REVIEWED" --manifest-sha256 "$REVIEWED_SHA256" \
  --output "$PACKAGED" --report "$PACKAGE_REPORT"
```

The synthetic suite passed 333 tests. Three focused joint-approval tests also
passed after the final guard changes. They cover complete group approval,
reproducibility, rejecting a failed member, rejecting partial/rebound proof and
requiring the joint evidence envelope. Further tests cover retained islands,
unexplained gaps and attempts to clip oversized neighbours into an exclusion.

The application passed 1,463 component, hole and boundary-offset assignment
probes for these 13 areas, preserved every existing full assignment byte-for-byte,
and preserved missing population values while rebinding their territory evidence.
The original pre-package input and previous packaged releases are unchanged.

| Artifact | SHA-256 |
| --- | --- |
| Input release | `6d0f2c5fc777e95bb37f5d663a2a25a7006faf04712d7f8c248a61105894fa63` |
| Canonical audit | `40ca792c99b0d67873f5b6850e779c61f948d3561178fee90a76760b3e327fc4` |
| Reviewed pre-package release | `c0b43df8ce53cabb441df2e58417574827aa5ef9b0c6784e954a1dba6ac8cab1` |
| Reviewed release with display packages | `473f324c3a6e85e634304aca909c834406ca1ab3f4610a5ee0c9136341009ca2` |
| Distribution ZIP | `10d1e2464b7a937076a318fe0cd9c81d0b99e4d38a5ece57b985c0ba19c7c05b` |

One cached-input run on an Intel Core i5-3210M, Linux x86-64, Python 3.14.7,
Shapely 2.1.2 and GEOS 3.13.1 took 308.858 seconds for audit replay, application,
assignment probes and release verification, with peak RSS 2,347,216 KiB. The
synthetic suite ran concurrently and took 215.540 seconds. These single-run
observations are build evidence, not serving-latency benchmarks.

Real-data API acceptance passed in 104.874 seconds against the previous reviewed
release: 2,047 city-area lookups, 1,274 Québec municipal lookups, 618 Ontario
municipal/regional lookups, 3,285 other jurisdiction lookups and 454 grouped-region
member lookups. It preserved 5,041 unchanged CSD rows, every city-area row (2,075),
141 region rows and all 3,385 CSD-to-region membership rows. The 13 approved CSD
changes and three derived regional changes were checked separately.

The display rebuild passed verification with 5,337 ready bundles and the same nine
membership-related unsupported groups. All 10,674 decoded/gzip geometry objects
are identical to the first reviewed packaged release. Package files total
71,659,624 bytes; all release files total 491,168,076 bytes. The rebuild took
118.420 seconds with peak RSS 998.5 MiB on the same machine, concurrently with API
acceptance. Descriptors and the dataset version change to carry the new approvals.

The local `canada-topology-batch-reviewed-v1.zip` distribution is 254,327,350 bytes.
Its generated lock names `dataset-473f324c3a6e85e63430-r1`; no remote tag or release
was created. Archive construction took 90.819 seconds with peak RSS 1,637,056 KiB.
The archive passed the normal bounded, checksummed unpacker, and its extracted
dataset passed `maps verify-release` against the manifest pin above. The 34 focused
boundary-review tests were rerun successfully after the final source-scope changes.

Activation must include the updated joint-approval verification code and the new
dataset. The selected dataset source and published lock remain unchanged. Keep
the prior verified code/dataset pair available for rollback.
