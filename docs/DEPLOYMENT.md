# Deployment guide

The public repository supplies one portable image with a public map explorer,
read-only API and pinned dataset. Real account
IDs, role policies, networking and release promotion belong to private deployment
automation. Nothing here creates AWS resources or publishes an image/dataset.

## Local API without Docker

```bash
.venv/bin/maps api --dataset .local/releases/canada --port 8000
```

Local mode permits unauthenticated loopback callers when no tokens are configured.
Supplying tokens requires authentication even locally. Binding a non-loopback
address automatically enforces production settings.

## Configuration

| Variable | Meaning |
|---|---|
| `MAPS_BUNDLE` | Complete deployment directory; default image sets `/opt/maps/bundle` |
| `MAPS_DATASET` | API-only mode: directory containing a serving release, not a raw build run |
| `MAPS_MANIFEST_SHA256` | API-only mode: trusted exact SHA-256 of manifest.json; required in production |
| `MAPS_MODE` | `local` or `production`; image defaults to production |
| `MAPS_API_TOKENS` | Required in production: JSON object mapping consumer names to unique random 32–256-character API keys |
| `MAPS_ALLOWED_HOSTS` | Comma-separated hostnames; no unrestricted `*` |
| `MAPS_REQUESTS_PER_MINUTE` | Per-client, per-process quota; default 120 |
| `MAPS_CORS_ORIGINS` | Explicit HTTPS browser origins; empty by default |
| `MAPS_DATASET_S3_URI` | Optional s3://bucket/prefix/manifest.json bootstrap source |

The CLI does not automatically load `.env` files. `.env.example` documents names
only. Inject actual tokens through your runtime's secret mechanism; do not commit
them or put them in image build arguments. Token characters are URL-safe ASCII.
Use distinct tokens per application; rotate via a controlled deployment.

The combined image derives its dataset pin from the sealed bundle. It rejects
conflicting dataset paths, hashes and S3 bootstrap configuration. In API-only mode,
CLI `--dataset` and `--manifest-sha256` override their environment settings.
The default concurrency limit is 64; configure `--limit-concurrency`
after measuring latency and memory with representative data.

## Public map and key-protected API

The hosting model is a public map explorer with no visitor accounts, plus an API
whose geography routes require manually issued keys. Billing, subscriptions and
self-service developer accounts are outside the current scope.

The combined image serves the explorer at `/`, redirecting to
`/maps/<website-sha256>/index.html`. Its fixed asset allowlist contains the public
catalogue, display GeoJSON, UI assets and attribution. The explorer does not call
`/v1/` or need a secret in browser JavaScript. These display files are public and
downloadable. Databases, full assignment geometry and deployment metadata are not
exposed through the website routes. The separate development preview server
remains loopback-only.

Route `/v1/` to the API in production mode, with `MAPS_API_TOKENS` injected from a
secret store. Missing or invalid keys return 401; docs and health endpoints remain
public. Production refuses to start without keys and a pinned manifest. The former
`MAPS_ALLOW_ANONYMOUS=true` setting now fails startup; remove it when upgrading.

Generate each key with a cryptographically secure generator, for example Python's
`secrets.token_urlsafe(32)`, and distribute it privately to that application's
operator. Store it on the consuming server and send it over HTTPS as
`Authorization: Bearer <key>`. Do not put it in a URL, public map bundle, repository
or request log. The environment value is a JSON object mapping an application name
to its key, with at most 100 entries. No real keys belong in this repository.

To rotate without interruption, configure the replacement under a second client
name and deploy both keys to every serving instance before updating the consumer.
Then remove the old entry and roll out that configuration to every instance.
Removing an entry revokes that key once all instances have updated. Each configured
name has an independent rate limit; the built-in counters are per process, so
shared limits belong at ingress.

## Container

```bash
docker build -t totally-normal-maps:local .
```

The default image runs as UID/GID 10001 and contains code, dependencies, the public
website and verified dataset. The build downloads the exact public attachment in
`dataset.lock.json`; a missing attachment or checksum mismatch fails the build.
It never downloads data at startup. No dataset volume or S3 setup is needed.
See [release preparation](RELEASING.md) for the initial attachment publication.

Inject `MAPS_API_TOKENS` and `MAPS_ALLOWED_HOSTS` at runtime, publish port 8000
behind HTTPS, and use `/readyz` for readiness. This endpoint records the dataset,
website and code hashes after startup verification. Supply `localhost` or
`127.0.0.1` in allowed hosts for direct local checks.
Health endpoints deliberately accept load-balancer IP Host headers.

For a local container check, set the two runtime variables in your shell using
your normal secret/configuration mechanism, then pass them through without
embedding values in the image:

```bash
docker run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges \
  -e MAPS_API_TOKENS -e MAPS_ALLOWED_HOSTS \
  -p 127.0.0.1:8000:8000 totally-normal-maps:local
```

Open `/` for the map. Include `127.0.0.1` in `MAPS_ALLOWED_HOSTS` for this example.

Use a read-only root filesystem, drop Linux capabilities and prevent privilege
escalation. The combined image works without writable data volumes. Do not mount
over `/opt/maps/bundle`, change `MAPS_BUNDLE`, or provide independent data overrides
in private deployment automation: doing so defeats the combined-release contract.

The base image uses a version tag for convenient rebuilding. Private release
automation should resolve and pin its approved digest and deploy the built image
by immutable digest. Dependencies are pinned in requirements.lock and
requirements-s3.lock. PR CI builds the same serving image with a small synthetic
bundle supplied as an explicit named context, then tests it with a read-only
filesystem. It does not download the real dataset or publish anything.

For an already verified local distribution, build without a GitHub download:

```bash
.venv/bin/maps assemble-deployment --lock dataset.lock.json \
  --archive /path/to/exact-reviewed-attachment.zip --output .local/deployment
docker build --target bundled-local \
  --build-context deployment_bundle=.local/deployment -t totally-normal-maps:local .
```

The bundle must be assembled from the same package code being built; code drift
fails verification. The normal Docker context still excludes local data. The
named context contains only the deliberately assembled bundle.

Operators retaining separate data management can explicitly build
`docker build --target api-only -t totally-normal-maps:api .` and mount a verified
release read-only at `/data/release`, with `MAPS_MANIFEST_SHA256` supplied separately.
That compatibility target contains no public website or bundled dataset.

## S3 bootstrap (API-only compatibility mode)

An operator can download a release separately:

```bash
.venv/bin/maps fetch-release \
  --uri s3://example-maps/releases/canada-review/manifest.json \
  --manifest-sha256 '<trusted-manifest-sha256>' \
  --output .local/releases/downloaded
```

Or set `MAPS_DATASET_S3_URI`, `MAPS_DATASET` to an initially nonexistent writable
directory, and `MAPS_MANIFEST_SHA256` before starting the container. The CLI downloads
and verifies all artifacts before accepting traffic. If the local directory already
exists, it must match the configured digest; it is never silently replaced.

Use the task role/default SDK credential chain. Only `s3:GetObject` for the selected
release prefix is needed, plus decryption permission if using a customer-managed
encryption key. No S3 write or consumer database permissions are required. Configure
regional endpoints and network access in private infrastructure. Original source
archives should be backed up separately from the minimal serving release.

Upload complete immutable files before publishing the manifest in an independent
trusted data-release job. The checksum pin must come from that workflow, not simply
from whatever manifest an untrusted server returns. Never overwrite a release prefix.

## Availability and integration

Each process verifies data and builds its own in-memory index at startup. Measure
startup, memory and request capacity before setting CPU/RAM and worker counts.
Use readiness health checks so a new task receives no traffic before its data loads.
Two or more replicas across availability zones improve service availability.

Enforce TLS, aggregate client quotas and request timeouts at ingress. The built-in
rate limiter is local to a process and does not coordinate replicas. Avoid public
geometry-preparation or upload endpoints. Restrict egress where appropriate; the
API itself needs no runtime network after loading a local release.

Deploy one combined image by immutable digest and record its `/readyz` fingerprints.
Rollback restores that same image, including its website and dataset. A code-only
release reuses the existing data attachment. Stage source changes, compare classifications, and let
consumers adopt deliberately using `If-Match`. During rolling updates, a client
pinned to one version may receive 412 from another replica; retrying indefinitely
is not a rollout strategy. Use separate versioned service targets or a controlled
cutover when consumers require a consistent long-running backfill. Versioned map
URLs prevent mixed assets; an old URL returns 404 on a new image. Use a controlled
cutover or retain old versioned targets when existing browser sessions must survive
a rollout. Private automation must verify readiness before switching traffic.

Keep consumer memberships and manual corrections in the consumer's database.
Use bounded retries and queue new classifications when this API is unavailable.
The service never owns or rewrites those application records.
