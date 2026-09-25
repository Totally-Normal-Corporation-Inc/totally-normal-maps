# Compact reference responses

API v1 adds bounded reference resources without changing lookup or the existing
full dataset report. A consumer can POST directly to `/v1/lookup/batch`; neither
a summary nor `/v1/layers` is required first. These routes read the same verified,
immutable serving dataset. They do not approve geography or rebuild source data.
The generated `/openapi.json` describes their response schemas.

## Resources and budgets

All paths below begin with `/v1/datasets/current`. Every successful representation
contains `representation_revision: 1`, `dataset_version` and the existing
`qualification: review_required`. Sizes are decoded UTF-8 JSON bytes, before
compression. These limits are enforced by the server, including per-item sizes.

| Resource | Selection | Maximum decoded response |
|---|---|---:|
| `/summary` | `layer=administrative` by default; repeated `edition` allowed for electoral layers | 16 KiB |
| `/coverage` | Required `area_id`; `layer`, `include_descendants`, repeated `edition` | 128 KiB |
| `/sources` | Same scope as coverage | 128 KiB |
| `/editions` | `layer`, `area_id=ca`, `include_descendants=true`; all retained editions | 128 KiB |
| `/evidence/{evidence_id}` | The linked evidence node; no geographic query filters | 128 KiB |

Pages accept `limit` (default 50, maximum 100) and an opaque `cursor`. Each item
is at most 16 KiB. A page can contain fewer than `limit` items to satisfy the byte
budget; follow `next` until it is null. Nothing is discarded to fit a success
response. If a representation cannot satisfy its published budget, it returns
503, not truncated evidence. Source strings and nested audits have bounded
representations described below.

The existing maximum query string is still 2 KiB. Up to 30 unique edition IDs can
be selected, provided the encoded query also fits that limit. Unknown parameters,
repeated singleton parameters and unsupported combinations return 422. There is
no `area_id` parameter on the national summary, and administrative geography has
no electoral editions.

## Summary semantics

For example:

```text
GET /v1/datasets/current/summary
GET /v1/datasets/current/summary?layer=municipal
GET /v1/datasets/current/summary?layer=provincial&edition=qc-2017
```

Use `/editions?layer=provincial` to discover valid IDs in the served dataset; an
example ID is not a guarantee that every release retains that edition.

The summary contains country identity, available layer identifiers, an explicit
selection, aggregate counts, bounded limitation codes/messages and relative links.
It never embeds source catalogues, area inventories, boundary coordinates or audit
reports. `limitations[].evidence_link` names a key in the summary's `links` object.
The fixed aggregate warning `coverage_evidence_requires_review` covers the full
set of detailed coverage issues; it is not a claim that unlisted individual issues
are resolved. Missing geometries, disagreement, area flags, reference editions,
default electoral coverage gaps and incomplete provenance mapping also have
specific aggregate codes when applicable.

`selection.edition_mode` is `none` for administrative geography, `defaults` for
the release's pinned electoral defaults, or `explicit` for requested editions.
`edition_ids` lists only explicit selections. `edition_count` counts the selected
editions; hundreds of municipal defaults are not expanded into IDs. `/editions`
instead uses `edition_mode: all` and paginates retained editions, including their
`default` and `status` fields. Defaults do not change with today's date.

| Count | Meaning within the selection |
|---|---|
| `catalogue_entries` | Active administrative identities, or districts in selected electoral editions |
| `assignment_geometries` | Entries with usable, full assignment geometry |
| `unavailable_assignment_geometries` | Entries requiring geometry that have none approved for assignment |
| `hierarchy_only_entries` | Identities intentionally matched through hierarchy, including administrative country/provinces |
| `display_geometries` | Entries with rendering geometry, including unapproved candidates |
| `boundary_disagreements` | Entries with usable geometry and a retained boundary-difference/review candidate |
| `entries_with_review_flags` | Entries with area issues, pending candidates or unlocated missing geometry |
| `by_level` | The same catalogue selection grouped by navigation level |

The first three geometry categories partition catalogue entries: usable,
unavailable and hierarchy-only. Display counts overlap those categories. Electoral
counts exclude shared country/province and administrative navigation entries;
administrative counts exclude superseded identities. Explicit historical electoral
editions retain their own district counts. Counts do not certify national coverage,
current electoral applicability or geographical qualification. Municipal gap counts
refer to authority inventory under the default selection, not a district count;
they are not presented as counts for an explicitly selected historical edition.

## Geographic scope and provenance

Coverage and source requests require an existing `area_id`:

```text
GET /v1/datasets/current/coverage?layer=municipal&area_id=ca-csd-2481017
GET /v1/datasets/current/sources?layer=administrative&area_id=ca-qc-ra-07&include_descendants=true
```

By default, results include records attached directly to that area and applicable
ancestor context. `include_descendants=true` additionally includes evidence
attached to descendants in the catalogue hierarchy. Each result labels its
`relation` as `direct`, `inherited` or `descendant`; direct takes precedence for
records with multiple scope anchors. `scope_count` counts those anchors, not
features, warnings or complete jurisdictions. Context at a province/country level
remains context and does not imply that every issue in it applies locally.

Administrative requests accept administrative areas. Federal/provincial requests
accept Canada, a province/territory or a district from that layer. Municipal
requests also accept administrative regions and municipalities. No geometric
intersection is inferred: federal evidence scoped to a municipality is unsupported
and returns 422. A district scope limits evidence to that district's edition;
explicitly requesting another edition there returns 422. Query the province or
authority to compare editions. An explicit edition outside the requested scope
also returns 422. The returned `scope` records the applied filters and relevant
edition count.

Coverage items distinguish their evidence basis:

- `area_record`: the area's existing quality/uncertainty fields.
- `edition`: validation or coverage for the identified `edition_id`, reusing the
  existing loaded edition coverage, including compatibility for older releases.
- `default_selection`: the existing default federal/provincial coverage assessment
  for a province/territory. It is excluded from explicit-edition queries.
- `authority_inventory`: the original municipal authority inventory, which may
  describe multiple retained/default editions. Its linked counts and statuses are
  inventory context, not recalculated historical-edition assignment counts.
- `report_context`: an existing report section, labelled with its scope relation.

A selected municipal edition's own validation is returned separately from authority
inventory. An authority on standby retains an `unavailable` inventory record.
An empty page reports `evidence_status: no_records_for_selection`, preserves
qualification and does not assert complete coverage, absence of wards or at-large
representation. A missing area/evidence ID is 404; unavailable reference processing
is 503. Neither is a successful empty classification.

Source records are deduplicated by complete metadata and connected through explicit
edition, report and catalogue source references. `roles` distinguishes baseline,
province display, electoral boundary and reported source usage. Province overview
credits are not attached to municipality boundaries. Publisher names alone are
never used to infer applicability. Records lacking a reliable local mapping remain
in the national inventory with `unscoped_report_source` role. The
`unscoped_provenance_in_national_inventory` link returns national context without
expanding descendants; a local page must not be treated as complete provenance
when that link is present. The summary also flags `source_scope_incomplete`.

Short authority, licence, attribution and redistribution status fields are inline.
`metadata_not_inlined` explicitly identifies fields whose size/type requires their
full evidence node. Follow `evidence_url` for source URLs, modification notices,
licence decisions, required notices and complete values. No source text is shortened
without a link to its complete original. Preserve required attribution when
redistributing boundaries or displaying maps, including unmapped national credits
when local provenance is incomplete. Source licences remain separate from the code
licence; public availability of an API response is not additional permission.

## Reading a detailed evidence node

Each evidence page exposes one node of an existing JSON report, source record,
edition or area-quality projection. It never recursively expands nested documents.
The scope identifies the `evidence_id` and `node_type` (`object`, `array`, `string`
or `scalar`). Object fields are sorted deterministically; arrays retain original
order. An item contains `index`, `value_type` and either an inline scalar `value`
or a same-service `evidence_url` for a nested container/long string. Null remains
a real JSON null; use `value_type` and the link to distinguish it from a linked
value. Empty objects/arrays have zero items, preserving their type.

Object items also have `name`. Names longer than 256 characters instead have
`name_evidence_url`. Strings longer than 512 characters have a linked string node;
its ordered pages contain lossless fragments with `character_offset`. Concatenate
their `value` fields in order to reconstruct a full notice. A string fragment is
not a complete licence notice on its own. Node IDs are opaque and version-scoped,
not permanent geographic IDs. Consumers can lazily expand specific branches;
walking an entire tree is an explicit audit export operation.

Pages contain `total` (items in that resource/node), the requested `limit`, `items`,
`next_cursor`, and the equivalent relative `next` URL. Cursors bind dataset,
representation revision, resource, scope and limit. Reusing a cursor with different
filters returns 422; a cursor from a no-longer-served dataset returns 412. Pages
are deterministic within the immutable dataset. Use the returned link instead of
constructing or editing cursors.

## Conditional requests and cache policy

Send the **quoted dataset version** as the existing `If-Match` precondition. A
representation ETag is a different value and cannot replace that dataset pin.
Changing scope, layer, edition, page or representation content changes the ETag.
The representation revision is part of the response content and identity.

```text
If-Match: "<dataset_version>"
If-None-Match: "<representation_etag>"
```

Authentication and rate limits run before response reuse. The dataset precondition
is checked before `If-None-Match`; a stale pin returns 412 even with a matching
ETag or `If-None-Match: *`. Authenticated reference GETs support weak ETag comparison,
lists and `*`, returning 304 only after those checks pass. Missing/revoked credentials
return 401. Existing gateway 403, request-size 413, rate-limit 429 and service 503
errors must remain distinguishable; consumers must not translate them into empty
geography. Errors remain `no-store`.

Only these five new reference resources use `Cache-Control: private, no-cache`
and `Vary: Authorization`, on both 200 and 304. A permitted private cache can store
them, but must revalidate before reuse. Shared intermediary caches must not store
them. A consumer's server may retain permitted reference evidence by exact dataset
version and representation/scope, with credential isolation. Existing lookups,
area responses, full reports and boundaries retain `no-store`. There is no shared
cache of coordinate request bodies. Serving builds the reference index once after
verified dataset load, precomputes common summaries and bounds its serialized
representation cache; requesting a summary does not serialize the full report.

## Optional compact boundary metadata

All three existing boundary routes accept `representation=compact`:

```text
GET /v1/areas/ca-csd-2481017/boundary?representation=compact
GET /v1/areas/ca-qc/children/boundaries?representation=compact&limit=20
GET /v1/areas/boundaries?layer=municipal&within_id=ca-qc&representation=compact&limit=20
```

The default remains `representation=legacy`. Compact Features replace the repeated
global `sources` array with `source_evidence` links, `attribution_required` and
`local_source_mapping_complete`, and add `representation_revision`. If local
mapping is incomplete, follow the source page's unmapped-national-provenance link.
All geometry, IDs, properties, uncertainty and dataset versions remain identical.
The `resolution=display|full` distinction and unavailable-boundary 409 are unchanged;
display geometry never becomes approved assignment geometry. Existing 16 MiB
boundary limits and `no-store` caching remain in force. Compact metadata does not
make arbitrarily large full-geometry downloads small.

`/v1/datasets/current` and `/v1/layers` remain complete compatibility responses
and can be large. Use summary plus paginated edition discovery for ordinary setup.
Area details retain their existing shape; lookup layer expansions, including
municipal coverage, also retain their original uncertainty and size behavior.
An optional ID-focused lookup is deferred: the measured administrative lookup
already fits a small request. Full reports and audit traversal are explicit large
operations, never prerequisites for point lookup or area search.

## Verification and delivery

Measured locally over HTTP against the currently selected release
`44bc84d770608c083313456bcc60adc30f3bb102dfe37ae1d7a20f4f13396fd9` on
2026-09-25 (decoded JSON; these measurements are examples, not universal sizes):

| Response | Bytes |
|---|---:|
| Existing full dataset report | 6,071,347 |
| New administrative summary | 2,070 |
| New federal / provincial / municipal summaries | 1,336 / 1,645 / 2,022 |
| Existing `/v1/layers` | 411,748 |
| Gatineau area detail | 1,192 |
| Gatineau legacy display boundary | 887,668 |
| Gatineau compact display boundary, identical geometry/properties | 4,075 |
| Direct administrative batch lookup, one public Gatineau point | 3,901 |

Summary and boundary measurements use defaults other than `representation=compact`
on the last boundary row. The lookup value includes its batch wrapper. The separate
single-lookup response was 3,802 bytes. This is local verification of the provider
change against the existing dataset, not evidence that these new routes have been
deployed publicly.

Offline regression tests use synthetic geography, large report/source inventories,
long notices, edition growth and dataset changes:

```bash
.venv/bin/python -m unittest tests.test_reference tests.test_api tests.test_electoral tests.test_municipal_elections -q
```

After deploying the provider through its own [release procedure](RELEASING.md),
run the read-only live checker from a trusted server with `MAPS_ACCEPTANCE_TOKEN`
supplied by its secrets manager/environment. The command does not accept the key
on the command line, print it, follow redirects, fetch full reports or log bodies.
It uses one public central Gatineau coordinate, checks the batch before requesting
any summary, then verifies scoped pages, evidence, decoded bounds, versions, 304,
authentication before cache reuse and stale-version 412.

```bash
.venv/bin/python tools/check_reference_api.py --url https://maps.totallynormal.io
# Optionally require the already known dataset version:
.venv/bin/python tools/check_reference_api.py --url https://maps.totallynormal.io \
  --expected-version 44bc84d770608c083313456bcc60adc30f3bb102dfe37ae1d7a20f4f13396fd9
```

This is a read-only smoke test, not an exhaustive coverage assessment or an
instruction to deploy. It reports only versions, check names and decoded byte
counts. Its bounded run stays below the default 120 requests/minute limit; avoid
concurrent runs on a busy consumer key. Local testing can use an authenticated
loopback HTTP server. Ordinary unit tests never contact the public service.

This provider update reuses the current dataset attachment. Merge the code, select
its passing commit, and deploy that code with the unchanged dataset lock; no new
data package is necessary. Consumers can adopt cached exact-version summaries and
on-demand evidence afterward, independently of their existing lookup-only repair.
