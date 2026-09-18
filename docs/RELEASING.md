# Combined releases

A dataset release contains a reviewed ZIP. An application release pins that ZIP
alongside the code. The default Dockerfile assembles both with the website into
one image. Any deployment system can build and run that image using the contract
below. This repository has no cloud credentials or company deployment configuration.

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
The first pinned distribution on this branch is `dataset-2026-09-18-review`; its
initial publication is a separate operator action, not performed by implementing
the workflow.

## Release code and deploy

1. Merge reviewed code and any lock update through a PR. Keep the lock unchanged
   for code-only releases; there is no need to repackage or re-upload the dataset.
2. On `main`, manually run **Release combined application** with a new tag such as
   `app-2026.09.18.1`. It tests the code, audits dependencies, downloads the pinned
   attachment, builds the combined image and smoke-tests the public website and
   protected API with a read-only filesystem. Only after success does a separate
   job create the application GitHub Release with its lock and deployment record.
3. Choose that application release in your deployment system. Check out its exact
   commit and build the default Dockerfile. Configure runtime API tokens,
   allowed hosts, HTTPS and ingress routing. No manual dataset/S3 upload is
   required. Route `/`, `/maps/` and `/v1/` to this same service.
4. Compare `/readyz` fingerprints with the release's `deployment.json`, then switch
   traffic to the new image. Record the image digest and deployment fingerprints.
   Rollback selects the previous complete image digest.

The public workflow publishes release metadata, not images or infrastructure.
Deployment integrations must honor this build/readiness contract. Pin the approved
base-image digest in your build
automation, and retain each deployed image: rebuilding a tag later may pick up
different base OS bytes even though code and dataset fingerprints are unchanged.

Use [controlled cutovers](DEPLOYMENT.md#availability-and-integration) if clients
must stay on one version throughout a rollout. A single image makes code and data
inseparable within each instance; routing several instances is still the hosting
platform's responsibility.

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
named context. `python tools/check_container.py --image maps-ci` checks the runtime
without mounting any data or giving the service write access.
