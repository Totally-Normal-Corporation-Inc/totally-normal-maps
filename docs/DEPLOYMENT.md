# Deployment guide

The public repository supplies a portable image and read-only API. Real account
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
| `MAPS_DATASET` | Directory containing a serving release, not a raw build run |
| `MAPS_MANIFEST_SHA256` | Trusted exact SHA-256 of manifest.json; required in production |
| `MAPS_MODE` | `local` or `production`; image defaults to production |
| `MAPS_API_TOKENS` | JSON object mapping consumer names to unique random 32–256-character tokens |
| `MAPS_ALLOWED_HOSTS` | Comma-separated hostnames; no unrestricted `*` |
| `MAPS_ALLOW_ANONYMOUS` | Exact `true` deliberately exposes read access without tokens |
| `MAPS_REQUESTS_PER_MINUTE` | Per-client, per-process quota; default 120 |
| `MAPS_CORS_ORIGINS` | Explicit HTTPS browser origins; empty by default |
| `MAPS_DATASET_S3_URI` | Optional s3://bucket/prefix/manifest.json bootstrap source |

The CLI does not automatically load `.env` files. `.env.example` documents names
only. Inject actual tokens through your runtime's secret mechanism; do not commit
them or put them in image build arguments. Token characters are URL-safe ASCII.
Use distinct tokens per application; rotate via a controlled deployment.

CLI `--dataset` and `--manifest-sha256` override their corresponding environment
settings. The default concurrency limit is 64; configure `--limit-concurrency`
after measuring latency and memory with representative data.

## Container

```bash
docker build -t totally-normal-maps:local .
```

The image runs as UID/GID 10001 and contains code and dependencies only. It expects
a verified dataset at `/data/release` by default. Mount the release read-only, pass
the configuration above, publish port 8000 behind HTTPS, and use `/readyz` for
readiness. Supply `localhost` or `127.0.0.1` in allowed hosts for direct local checks.
Health endpoints deliberately accept load-balancer IP Host headers.

Use a read-only root filesystem, drop Linux capabilities and prevent privilege
escalation. Provide a bounded writable temporary/data volume only if downloading
from S3. Ensure mounted data is readable by UID 10001 without granting write access
to adopted releases. Source-builder output directories default to private local
permissions; publishing/mounting jobs must explicitly set the intended read access.

The base image uses a version tag for convenient rebuilding. Private release
automation should resolve and pin its approved digest and deploy the built image
by immutable digest. Dependencies are pinned in requirements.lock and
requirements-s3.lock; CI audits these and builds the container without publishing it.

## S3 bootstrap

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

Code and data deploy independently. Pin an image digest and dataset digest together
for each task deployment. Stage source changes, compare classifications, and let
consumers adopt deliberately using `If-Match`. During rolling updates, a client
pinned to one version may receive 412 from another replica; retrying indefinitely
is not a rollout strategy. Use separate versioned service targets or a controlled
cutover when consumers require a consistent long-running backfill.

Keep consumer memberships and manual corrections in the consumer's database.
Use bounded retries and queue new classifications when this API is unavailable.
The service never owns or rewrites those application records.
