# Casselman / The Nation circle discovery review

Reviewed 2026-10-21. The affected identities are `ca-csd-3502044` (Casselman)
and `ca-csd-3502025` (The Nation / La Nation). This review makes a **circle
calculation correction**, not a boundary approval or new municipal data release.

## Source findings

The national source has a 2025-01-01 reference date. The Ontario refresh supplies
the complete, pinned Land Information Ontario features `319585900` and `319586012`,
respectively, retrieved 2026-09-18. Both retain valid assignment geometry and the
complete original/current symmetric difference as review evidence.

The [municipal announcement](https://www.casselman.ca/en/news/the-province-has-approved-a-municipal-restructuring-proposal-to-transfer-a-portion-of-land-from-the-nation-municipality-to-the-municipality-of-casselman)
and linked [ministerial order](https://www.casselman.ca/uploads/EN-Minister%E2%80%99s-Restructuring-Order-Filing-Notice.pdf)
confirm a transfer to Casselman effective 2026-01-01. The order describes a specific
parcel perimeter; it does not certify every difference between national and
provincial mapping. The stored differences include other shifts along the shared
boundary and the pair's outer boundary. They cannot all be dismissed as the
annexation or as a harmless few-metre repair. Their qualifications remain intact.

Measured in EPSG:3347 after densifying WGS84 linework for measurement only:

| Evidence | Components | Area |
|---|---:|---:|
| The Nation old/new difference | 176 | 2,731,104.85 m² |
| Casselman old/new difference | 12 | 1,460,119.70 m² |
| Difference between the old and new combined outer extents | — | 1,270,985.15 m² |

Each stored review geometry exactly equals its source/current symmetric difference.
The area figures describe mapping differences, **not** the legal annexation area.

No new source geometry, boundary clipping, repair approval or population rebinding
is included. Independent reconciliation of the residual differences remains open.
Resolving it needs qualified source evidence for the complete affected edges and
their neighbouring municipalities, followed by the existing immutable release
process. Do not remove the disagreement simply because the transfer is documented.

## Why revision 2 is appropriate

Revision 1 rejects any circle touching the difference evidence, even when the
circle unquestionably includes both municipalities under either boundary source.
This is unnecessarily restrictive for returning a complete set of municipality IDs.

For a municipality with explicit old/new difference provenance, let `F` be its
full assignment polygon and `D` the union of all its difference evidence. The
territory `F minus D` is common to the boundary alternatives. If the circle reaches
this common territory, membership is established independently of the disputed
edges. This is a sufficient proof, not a heuristic based on area, distance from
the centre, overlapping bounding boxes or the municipality's name.

Revision 2 uses that proof and retains all source warnings. Disputed-only reach,
unknown warning provenance, missing full polygons and unlocated extents still
fail closed. A complete response still has `qualification: review_required`.
Point lookup and assignment continue to expose the unresolved source differences.
The common polygons are prepared once at startup; HTTP queries perform no overlays
and retain the existing distance, work, memory-response and concurrency limits.

## Reproduction and rollout

The offline acceptance tool uses public sample centres, no consumer records or
credentials. It compares revision 1's conservative uncertainty policy with revision
2 on the exact pinned local release, checks all pages, and independently checks
both original and current municipal polygons. It does not call production:

```bash
.venv/bin/python -m tools.check_circle_disagreements \
  --dataset .local/releases/canada-remaining-boundaries-packages-20261003 \
  --manifest-sha256 bd29719079d3a0814b8b75ccd75f9bd2b16dae09a3d0671f2c0a12168030c740

.venv/bin/python -m unittest tests.test_circle tests.test_circle_checker -q
.venv/bin/python -m unittest discover -s tests -t . -q
```

Local acceptance on the pinned dataset reproduced exactly the two reported IDs
under the old policy. Revision 2 returned **86 municipalities over 13 pages** for
the public 80 km Ottawa sample. The unaffected 30 km sample retained its eight
municipalities over two pages; the outside-Canada sample retained zero. Both
disagreement records remained present. These are reference-point checks, not a
claim to have replayed private consumer venues or production traffic.
Independent tests of the original national and current provincial polygons both
confirmed inclusion of the two municipalities in the 80 km sample. The full
offline suite passed **358 tests**; the final focused run, including an additional
HTTP success/failure regression, passed **32 tests**. The latter verifies revision-1
rejection, revision-2 response envelopes and preserved private/no-store headers.

No dataset bytes change, so the existing dataset identifier remains valid. This
patch increments `representation_revision` and `If-Circle-Revision` to **2**.
Revision-1 requests receive **412** rather than silently receiving new semantics.
Consumers must adopt revision 2, validate it on every response/page and invalidate
their revision-1 reach caches. Coordinate this before provider activation; a
consumer still pinned to 1 cannot use the revised endpoint. Rollback uses the
previous code/image and its revision-1 consumer configuration with the same data.

This work does not publish a new bundle or authorize deployment. A future actual
geometry/evidence correction must produce a new dataset version separately.
