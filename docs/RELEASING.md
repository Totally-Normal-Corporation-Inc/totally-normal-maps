# Combined releases

A dataset release contains a reviewed ZIP. Each selected code commit pins that ZIP
through `dataset.lock.json`. The default Dockerfile assembles both with the website
into one image. Any deployment system can build an exact `main` commit with passing
CI; a manual `app-*` release is optional. This repository has no cloud credentials
or company deployment configuration.

## Publish a dataset once

First complete geography, attribution and real-data acceptance using the existing
[data workflow](DATA.md). Packaging does not approve repairs or close coverage
gaps. Distribution metadata continues to say `review_required`.

```bash
.venv/bin/maps package-dataset \
  --dataset .local/releases/canada-jurisdictions-reviewed \
  --manifest-sha256 '<independently-reviewed-manifest-sha256>' \
  --repository Totally-Normal-Corporation-Inc/totally-normal-maps \
  --tag dataset-YYYY-MM-DD-review --notice NOTICE.md \
  --output .local/distributions/dataset-YYYY-MM-DD-review
```

This creates a deterministic ZIP, checksum file and `dataset.lock.json` in a new
directory. The ZIP contains only `dataset/manifest.json`, its named serving files,
`NOTICE.md` and `README.txt`. Raw archives, build inputs, local paths and unrelated
working files are excluded. Review the distribution before making it public.

Verify the package without uploading anything:

```bash
.venv/bin/python -m tools.publish_dataset \
  --package .local/distributions/dataset-YYYY-MM-DD-review \
  --commit '<reviewed-40-character-commit-already-on-GitHub>'
```

Add `--publish` to that command only when ready to create the public GitHub Release.
It verifies the complete archive again, refuses an existing tag, and uploads the
ZIP and lock using `gh`. Dataset tags use `dataset-*`, are marked prerelease and
never become GitHub's latest application release. The helper never overwrites an
asset. Enable immutable releases in the repository settings; corrections need a
new dataset tag and a new lock, even if the old release was incorrect.

Copy the generated lock to the repository root and submit it through a PR. Only
the small lock belongs in Git; keep generated archives and datasets under ignored
`.local/`. The attachment must be published before merging a lock that production
builds will consume. A missing, truncated, changed or unsafe ZIP stops the build.
The first pinned distribution, `dataset-2026-09-18-review`, was published on
2026-09-18. Future dataset publications remain explicit operator actions.

## Release code and deploy

1. Merge reviewed code and any lock update through a PR. Keep the lock unchanged
   for code-only releases; there is no need to repackage or re-upload the dataset.
2. Select an exact `main` commit whose CI passed. Check out that SHA and retain
   its `dataset.lock.json`. A moving branch name or a separately fetched latest
   dataset is not a deployment input. For data changes, publish a new dataset
   attachment and merge the new lock through a PR before selecting the commit.
3. Build the default Dockerfile from that checkout. Run the container check with
   `--lock dataset.lock.json --receipt /path/to/deployment.json` (see below), and
   retain the verified record with the built image's immutable digest. Configure runtime API tokens,
   allowed hosts, HTTPS and ingress routing. No manual dataset/S3 upload is
   required. Route `/`, `/maps/` and `/v1/` to this same service.
4. Compare `/readyz` fingerprints with that build's `deployment.json`, then switch
   traffic to the new image. Record the image digest and deployment fingerprints.
   Rollback selects the previous complete image digest.

Optionally run **Release combined application** on `main` with a new `app-*` tag
such as `app-2026.09.18.1`. It tests code, audits dependencies, builds the real
combined image, and checks the website and protected API before publishing the
lock and deployment record in a GitHub Release. Consumers can select that release's
exact commit instead; the manual workflow is not a prerequisite for deployment.
The public workflow publishes release metadata, not images or infrastructure.
Deployment integrations must honor this build/readiness contract. Pin the approved
base-image digest in your build
automation, and retain each deployed image: rebuilding a tag later may pick up
different base OS bytes even though code and dataset fingerprints are unchanged.

Use [controlled cutovers](DEPLOYMENT.md#availability-and-integration) if clients
must stay on one version throughout a rollout. A single image makes code and data
inseparable within each instance; routing several instances is still the hosting
platform's responsibility.

## Release immutability

On 2026-09-18, the repository's release-immutability setting was disabled and
`dataset-2026-09-18-review` reported `immutable: false`. Its ZIP metadata matched
the committed lock. This is a dated observation, not a permanent setting guarantee.

A repository administrator should enable immutable releases for future releases
when authorized. GitHub documents that [enabling the setting applies only to future
releases](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes).
It does not protect the existing attachment retroactively. Keep its current bytes
and tag unchanged, keep checksum verification enabled, and retain deployed images
for rollback. A changed or missing attachment will block a new build. If a protected
dataset release is required, publish a separately reviewed new release after enabling
the setting and update the lock through a PR; never replace or recreate the old one.

## Local verification and CI

```bash
.venv/bin/maps assemble-deployment --lock dataset.lock.json \
  --archive /path/to/exact-reviewed-attachment.zip --output .local/deployment
.venv/bin/maps verify-deployment --bundle .local/deployment
MAPS_BUNDLE=.local/deployment .venv/bin/maps api --port 8000
```

Open `http://127.0.0.1:8000/` for the public map. Local mode permits anonymous
loopback API calls when no keys are configured. Production always requires keys.
For browser acceptance, install the optional browser dependencies and run:

```bash
.venv/bin/python -m totally_normal_maps.check_preview \
  --url http://127.0.0.1:8000/ --output .local/deployment-browser
```

Ordinary tests and PR CI use small synthetic datasets and mocked downloads. The
container fixture is built with `python -m tools.make_ci_bundle --output /tmp/maps-ci-bundle`,
then supplied to Docker's `bundled-local` target through the `deployment_bundle`
named context. Verify against the fixture's lock, not the real-data lock:

```bash
python tools/check_container.py --image maps-ci \
  --lock /tmp/maps-ci-bundle/dataset.lock.json
```

The checker disables container networking and runs HTTP probes over loopback inside
the container. It checks the public map, protected API, private-file exclusion,
readiness cache headers and deployment fingerprints without data mounts or a
writable root filesystem. It resolves the supplied image tag to one local image
identity before inspecting and running it. `--receipt` retains the deployment
record format used by the release workflow.

For a real-data check, build the default target from the selected checkout:

```bash
docker build --tag maps-real .
mkdir -p .local/container-check
.venv/bin/python tools/check_container.py --image maps-real \
  --lock dataset.lock.json --memory-mib 2048 \
  --receipt .local/container-check/deployment.json \
  --report .local/container-check/runtime.json
```

Replace the example memory limit with the intended API-container allocation.
`--memory-mib` sets both Docker memory and memory-plus-swap to the same value,
disabling swap. A Linux cgroup memory high-water counter is required for peak
measurements. The report records observed startup time, peak memory (including
the in-container checker and filesystem cache), architecture, host CPU/RAM,
limits and fingerprints. No CPU cap is imposed; repeat on the target architecture
and CPU allocation if those differ. Startup is measured from container launch to
observed readiness, with one-second polling. The container is removed afterward.

This is a startup and basic-request check, not a concurrent-load capacity test or
geographic-quality approval. Repeat after substantial dataset or loading changes;
ordinary code-only CI continues to use the offline synthetic fixture. Ingress,
TLS, health-check routing and total task memory including other containers must
also be verified by the deployment system in staging.
