# Côte-Nord water extent and La Romaine topology

Reviewed 2026-09-19. The national municipal source is the pinned StatCan 2025
**digital** CSD boundary file. Digital boundaries include water; the separate 2021
province overview is cartographic. This difference can make a municipal outline
extend far beyond the visible coast. Neither a background map nor the overview
is a basis for clipping full assignment geometry. See the
[StatCan boundary guide](https://www150.statcan.gc.ca/n1/pub/92-162-g/92-162-g2025001-eng.pdf).

Côte-Nord-du-Golfe-du-Saint-Laurent (`2498015`) also has a distinct source defect:
one self-touching exclusion ring near La Romaine, at approximately 50.2180035 N,
60.6739338 W. Its existing display used an unapproved valid candidate. The
[pinned review](../../totally_normal_maps/topology-review-2026-09.json) now qualifies
only this topology repair, using the original source and independent same-vintage
feature Romaine 2 (`2498804`). It does not substitute the different Québec boundary.

Checks in source EPSG:3347:

- The original and candidate both cover 18,470,780,538.045235 m²: zero area change.
- The exterior line is unchanged, including all maritime extent.
- The single invalid hole becomes two valid holes, with areas
  24,169.494530635617 and 1,205,799.6023679273 m².
- Their union **and boundary** exactly equal the complete Romaine 2 source polygon;
  symmetric difference is zero. The original exclusion boundary is also unchanged.
- `make_valid` and `buffer(0)` produce equal polygon surfaces. No non-polygon
  coordinates are discarded. Exact source, candidate and enclave hashes are pinned.
- The stored WGS84 candidate must match byte for byte. Côte-Nord's regional
  candidate must equal the union of all 54 now-valid municipal members.

This is geometry validation, not a legal-boundary decision. The complete Québec
SDA V2026-08 native polygon differs substantially from the StatCan extent; the
earlier comparison, source hash and unresolved reconciliation remain in the report.
All other unapproved repairs, revisions, identities and memberships are retained.

## Reproduce offline

Use the original immutable release identified by the review manifest and the
checksum-pinned StatCan archive. No source download or release upload occurs:

```bash
.venv/bin/maps repair-topology \
  --dataset .local/releases/canada-jurisdictions-reviewed \
  --source .local/canada/current/source.zip \
  --output .local/releases/canada-topology-reviewed-20260919
.venv/bin/maps verify-release --dataset .local/releases/canada-topology-reviewed-20260919
.venv/bin/python tools/check_real_data.py \
  --dataset .local/releases/canada-topology-reviewed-20260919 \
  --baseline .local/releases/canada-jurisdictions-reviewed
```

The new release has 57 municipal candidates remaining and 125 validated regional
outlines (19 still unapproved). Original releases and the published dataset lock
are unchanged. Package and publish a new immutable dataset attachment through the
normal release process before changing the default deployment lock.

## Backgrounds and display acceptance

The viewer uses NRCan's Toporama WMS in EPSG:4326, with an optional Digital Relief
hillshade WMS layer. Labels, transparency and backgrounds are display features;
they do not enter assignment queries. Service availability is external to the
application. The offline view remains usable when images cannot load.

Run the existing full browser acceptance and the appearance check against a local
website generated from the corrected release:

```bash
.venv/bin/python -m totally_normal_maps.check_preview --url http://127.0.0.1:9010
.venv/bin/python tools/check_map_appearance.py --url http://127.0.0.1:9010
```

The appearance check mocks provider images locally and covers backgrounds, relief,
errors, opacity, label fitting/collisions, mobile layout and reviewed repair text.
It is separate from synthetic unit tests; live provider checks are separate again.

## Verification record

On 2026-09-19, all 150 synthetic tests passed. The real-data acceptance completed
7,596 city, municipal and regional lookup probes. Comparison against the parent
release confirmed 5,053 other municipal rows, all 2,075 city-area rows, 143 other
regional rows and all 3,385 memberships unchanged byte for byte. Both components
of Romaine 2 remain excluded from municipal assignment.

Full hierarchy browser acceptance passed with no page errors. Appearance checks
passed on desktop and mobile, including additional labels after zoom, label
click-through, provider failures and an offline reload with zero provider requests.
A separate live check returned 64 successful PNG responses from the two NRCan
services. Publication-file and offline secret scans passed.
