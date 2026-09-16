# Public-source release review

Review date: 2026-09-16. Scope: the initial standalone repository, its source/wheel
packages, public CI and the API's security boundaries. This is an engineering review,
not a penetration-test certification or a guarantee against future vulnerabilities.

## Decision

No unresolved blocker was found for publishing the reviewed source repository.
This conclusion does not qualify the geographic data for production or approve a
public service deployment. Large datasets and private integration material remain
outside the public file set.

## Findings resolved before publication

1. **Staged files could differ from scanned working files.** Both publication
   scanners now support `--staged` and read the complete Git index. Tests prove
   that cleaning or deleting a working file cannot hide its staged contents,
   including explicitly staged ignored files. Scanning never prints secret values.
2. **Broad JSON packaging could include ignored local data.** Wheel data now names
   the five intended JSON files explicitly. Archive exclusions and Docker exclusions
   cover credentials, keys and database exports. The artifact checker compares
   packaged source bytes with the reviewed Git file set and rejects extra files,
   changed bytes, traversal paths and symlinks. Builds should use a clean checkout.
3. **Attribution needed the prescribed Statistics Canada notice.** The notice now
   appears in the project notices, map preview and API source metadata. Boundary
   Features carry source/licence/modification metadata for downstream reuse.
   Dataset URLs and retrieval dates are retained by the public metadata projection.
4. **Commit metadata could expose a personal email.** The requested GitHub no-reply
   address was configured for this repository only. No identity is stored in the
   public source files; no commit or push was performed during review.

## Verification completed

- Inspected all tracked/nonignored publication candidates, including documentation,
  manifests, tests, examples, workflows and vendored assets. No consumer database,
  credentials, real infrastructure identifiers, personal workspace paths or original
  application history are included. The private-looking IP in the health test is a
  synthetic load-balancer fixture, not a deployment address.
- Publication guard and offline secret scanner passed for the working files and
  an isolated Git-index snapshot. There were zero unresolved secret findings;
  131 source/identity checksum fields were recognized as public geographic digests.
  The original repository's index remained untouched.
- Clean-snapshot wheel and source builds passed. Artifact inspection confirmed that
  packaged source files match the reviewed public bytes; generated package metadata
  was also checked. No local data, credentials or private recovery material entered
  either archive.
- All **81 regression tests** passed. Security cases include authentication on encoded
  paths, duplicate security-sensitive headers, streamed oversized bodies, redacted
  validation/500 responses, rate limits, file isolation, release corruption and S3
  path/size restrictions. Public test runs use synthetic geography and no cloud writes.
- Real-data API acceptance passed for 5,054 municipal/statistical areas, 121 regions,
  46 city areas and a lookup inside each city area. Desktop/mobile browser acceptance
  passed with no page errors after the attribution change.
- The pinned runtime, optional S3 and development dependencies were checked with
  `pip-audit`; no known vulnerabilities were reported at this review date. This does
  not audit the container OS or native libraries embedded in Python wheels.
- All eight vendored Leaflet assets/licence files were compared with upstream 1.9.4.
  CSS and images are identical. JavaScript differs only by the omitted final
  source-map reference; its executable contents match the official release.
- CI uses pinned GitHub actions, hosted runners and read-only repository permissions.
  It has no cloud credentials, deployment step, publishing step or privileged PR trigger.

## Licence evidence

- Original code uses MIT; Leaflet retains its [upstream BSD-2-Clause licence](https://raw.githubusercontent.com/Leaflet/Leaflet/v1.9.4/LICENSE).
  The script and stylesheet were checked against the official
  [Leaflet release integrity information](https://leafletjs.com/download.html).
- The [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence)
  requires source acknowledgement for adapted products. Product names and reference
  dates are recorded in NOTICE.md and the source metadata.
- Official Données Québec catalogue API metadata for
  [Québec administrative divisions](https://www.donneesquebec.ca/recherche/api/3/action/package_show?id=decoupages-administratifs)
  and [Gatineau administrative divisions](https://www.donneesquebec.ca/recherche/api/3/action/package_show?id=vgat_296280560)
  identified CC BY 4.0 and the corresponding government publishers. Preserve attribution,
  licence links and modification notices under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  Geographic data is not relicensed as MIT.

## Limits and ongoing release checks

The local user cannot access the Docker daemon, so container build/run and container
OS vulnerability scanning remain unverified locally. Public CI includes a container
build, but CI has not been executed remotely because this review made no push.
AWS/TLS/IAM, production load and hosted-repository protection settings were not changed
or certified. Geographic qualification remains incomplete as documented elsewhere.

Before each commit, stage the intended files and run the two `--staged` checks in
README.md. Before distributing packages, build from the reviewed commit and run the
artifact check. Findings and dependency advisories must be reassessed after changes;
this report applies to this review checkpoint, not all future revisions.
