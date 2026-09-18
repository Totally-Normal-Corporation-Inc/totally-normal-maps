# Security model

## Public source and private operations

This repository contains no live deployment credentials or consumer database
records. Keep company-specific infrastructure, operator runbooks and production
configuration in private infrastructure automation. Keep credentials in a secrets
manager, including for private deployments. Public source is not permission to use
a hosted API. Source and data licences are documented separately in NOTICE.md.

If reporting a suspected credential exposure or exploitable vulnerability, contact
a maintainer privately using their repository profile or GitHub private vulnerability
reporting if enabled. Do not include secrets or exploit details in a public issue.
Rotate/revoke an exposed credential; deleting a Git commit is insufficient.

## Serving boundary

- The API loads a checksummed immutable release and has no mutation endpoints.
- Production mode requires an independently pinned manifest and at least one API
  key. Every geography request must authenticate; anonymous hosting is unsupported.
  Only loopback development without configured keys permits anonymous API requests.
- Public map browsing uses separate display files without API credentials. Keep
  keys out of browser JavaScript, public assets, URLs and request logs.
- Use TLS at the gateway. Tokens are independent per consumer and compared without
  ordinary string timing comparisons. The service never requires cloud write access
  or consumer database credentials.
- No arbitrary URLs, SQL, uploaded geometry or filesystem paths are accepted in
  API requests. Bound request bodies, batches, pages, query strings, response sizes
  and server concurrency. Rate limits are per client/process, not a distributed quota.
- Proxy headers are disabled. Authentication never trusts X-Forwarded-For. Configure
  gateway-level rate limits across replicas rather than enabling spoofable IP headers.
- Minimal health checks intentionally allow load-balancer IP Host headers. Geography
  routes use an explicit host allowlist. CORS is disabled unless explicitly configured.
- Uvicorn access logs are disabled to avoid coordinates in URL logs. Validation errors
  omit submitted values. Unexpected errors return generic responses and log tracebacks
  once. Apply equivalent privacy controls to external proxies and log collectors.
- The old-style map preview remains loopback-only and serves a fixed asset allowlist.
  It is not a public administrative surface or a production authentication layer.

## Data trust and integrity

Only operators choose source manifests and S3 locations. Verify source provenance
and licensing; source bytes are pinned before parsing. Geometry parsers still process
complex external files: run preparation jobs with resource limits and separate
permissions from serving tasks. Read-only serving tasks cannot publish releases.

S3 downloads require a trusted manifest hash, safe filenames, file/total byte budgets
and per-file hashes. They stage complete data before an atomic local publish. There
are no HTTP-triggered S3 fetches. SQLite uses read-only/query-only access and untrusted
schema execution is disabled; assignment queries operate on in-memory indexes.

Hashes verify bytes, not geographical correctness. Missing coverage, invalid polygons,
candidate repairs, partial subdivisions and differing source vintages remain visible.
Do not promote an experimental dataset merely because its API or geometry tests pass.

## Contribution and release automation

Public CI uses hosted disposable runners with read-only repository permissions and
no AWS access. Workflow dependencies are pinned to commit hashes. Do not execute
untrusted pull-request code with `pull_request_target`, privileged `workflow_run`
jobs, production credentials or a runner on a private/home network. Treat public
issue/PR text as untrusted input to AI agents as well.

Production promotion belongs to a separate private workflow. Use short-lived cloud
authentication restricted to its repository and environment. Pin the reviewed image
digest and dataset manifest digest. A public contributor cannot deploy by changing
a branch, tag, package version or release title.

Before publishing, inspect the exact Git file list, scan it for secrets and review
build artifacts. `.gitignore` does not remove a file already tracked. `.dockerignore`
uses an allowlist so local datasets and credentials cannot enter the build context.
Publication scans are useful safeguards, not a complete security audit.

Use `tools/check_publication.py --staged` and `tools/check_secrets.py --staged` before
committing; a clean working copy does not prove that the staged bytes are clean.
Both scanners read the exact index, including ignored files explicitly staged.
The secret scanner works offline in a private temporary snapshot and never prints
credential values. Keep scanners current and review findings rather than broadly
excluding source files. Source-checksum exceptions apply only to named checksum
fields in the explicitly allowlisted geographic manifests, including reviewed
parent-catalogue/report digests in jurisdiction plans. These exceptions do not
approve changes to geographic evidence or exclude whole files from scanning.

Build in a clean checkout. `tools/check_artifacts.py --staged` rejects archive files
outside the reviewed public set and rejects changed source bytes, unsafe paths and
symlinks. JSON package data uses explicit filenames; source archives also exclude
credential filenames. Never publish arbitrary local build directories unchecked.

## Verification record

The extraction is tested with synthetic datasets for integrity failures, immutable
outputs, safe S3 paths, authentication, request bounds, raw-file isolation, lookup
ambiguity and unapproved repairs. Real-data and browser acceptance are separate.
See docs/MIGRATION.md for the completed checks and remaining deployment validation.
