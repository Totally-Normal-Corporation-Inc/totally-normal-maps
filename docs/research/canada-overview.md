# Canada evidence and remaining qualification

Research snapshot: 2026-09-16. This document carries forward the geographic findings
from the local prototype. Historical timings below are observations, not production
capacity commitments or results of the new HTTP API.

## Source coverage

The pinned Statistics Canada 2025 digital Census Subdivision file has 5,054
identities across all 13 jurisdictions, reference date 2025-01-01. It includes
municipalities and statistical equivalents such as unorganized territory; it is
not a complete governance or traditional-territory inventory. Its national digital
extent legitimately includes Arctic waters approaching the pole.

The national build preserves full original bytes and transforms EPSG:3347 to WGS84
with explicit longitude/latitude order. Map simplification does not change full
assignment geometry. Every source ID, jurisdiction count and identity digest is
pinned. Features have 4,132,456 source vertices in total.

- 4,996 municipal polygons validate directly.
- 58 original polygons contain invalid rings; their assignment geometry remains
  unavailable and their proposed repairs remain separate and unapproved.
- The original repair experiment changed hole topology for all 58 despite maximum
  absolute area differences of only about 0.004 square metres. Small area differences
  are not sufficient approval evidence.
- Regional outlines dissolve full municipal members. A region inheriting an
  unapproved municipal repair also lacks normal assignment geometry.
- The country overview uses the separate 2021 generalized cartographic province
  layer, simplified for display. It never drives coordinate classification.

See [regional decisions](canada-regions.md) for all provinces and territories,
including deferred jurisdictions. The 121 groupings cover 2,931 municipal areas;
2,123 remain directly under their provinces. See [Québec city areas](quebec-city-areas.md)
for the 46 areas in nine municipalities, partial coverage and boundary discrepancies.

## Historical local comparison

A 500-point, three-round geometry experiment explicitly included all 58 unapproved
municipal repair candidates. A bbox/covers loop and Shapely STRtree agreed on every
checked point. Fixtures included all jurisdictions, outside points, interiors and
exact source vertices. The experiment's repeated-pass p95 was approximately 1.56 ms
for the linear baseline and 0.86 ms for STRtree. Loading geometry took about 0.64 s,
index construction about 0.0035 s, and peak process memory about 261 MiB.

These results exclude network latency, application queries, concurrent traffic,
ancestors, source correctness and controlled cold-cache behaviour. PostGIS was not
available for an actual database comparison. Use the retained benchmark command to
measure new hardware and datasets; do not extrapolate the numbers to global coverage.

## Outstanding work

1. Review repairs, including holes, components and source-level geographic effects.
2. Check gaps/overlaps against appropriate same-vintage reference data.
3. Adjudicate cross-source city/parent differences where required by consumers.
4. Qualify regional schemes deferred in NL, MB, SK, AB, YT and NT.
5. Expand city-area coverage with explicit scope and source attribution.
6. Measure API load, memory, startup and replica behaviour in the actual hosting
   environment before choosing capacity or committing to availability targets.
7. Introduce a documented approval/release process before treating the catalogue as
   production-qualified geography. The current schema deliberately remains review-required.

Geographic expansion and a consuming application's launch/crawling policy are
separate decisions. Adding an area here does not publish or enable anything in a
consumer application.
