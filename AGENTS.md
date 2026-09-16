# Working on Totally Normal Maps

Read README.md, docs/API.md and SECURITY.md first. This is a standalone public
reference-geography project. Keep consuming applications and company deployments
outside this repository. Never copy credentials, application exports, private
operational documents, local datasets or unrelated repository history here.

Preserve stable geographic/source identities, complete assignment geometry,
immutable release checksums, explicit coverage gaps and unapproved repair status.
Display geometry must never be used for point assignment. Keep the serving API
read-only. Changes to source manifests require evidence, not just updated hashes.

Run focused tests for the changed subsystem. The documented project suites are
small and synthetic; real-data acceptance is an explicit separate command.
Do not download source data during ordinary tests. Keep external operations out
of tests and public pull-request CI. No cloud credentials belong in this repo.

Local development uses Python directly; Docker is optional deployment packaging.
Production deployment belongs to private infrastructure automation. Do not push,
publish packages/images/data, or change cloud resources unless requested.

