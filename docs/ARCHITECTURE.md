# Architecture

One focused codebase provides source preparation, a pure read-only query layer,
an HTTP API and a local preview. Data builders and the API run as separate jobs.
No application framework settings, consumer database credentials or cloud writes
are required to serve a published dataset.

## Data ownership

The service owns geographic identities, sources, boundaries, hierarchy and coverage
evidence. Applications own places, events, user preferences, public launch rules,
manual inclusion/exclusion and their saved assignments. Consumers map stable service
IDs to their own stable IDs; they do not send database dumps to the API.

Persist the adopted dataset version alongside classifications. During a source
update, compare results, retain manual decisions, stage the new assignments and
activate them deliberately. Avoid a remote lookup on every ordinary page view.
If the service is unavailable, preserve existing assignments and queue new work.

## Storage and scaling

A builder produces an immutable run containing sources and evidence. `maps release`
exports only a checked SQLite geography artifact, projected public metadata and
display GeoJSON. The manifest checksums every file. The API verifies the release
once at startup, opens SQLite read-only, loads full geometry into Shapely indexes,
then closes the connection. Requests read memory; there is no database server.

Optional S3 bootstrapping downloads a pinned manifest and every referenced file
before opening a listener. The API needs GetObject only and does not read S3 on
each request. The trusted manifest digest must arrive through deployment
configuration. A checksum does not prove source accuracy or make an untrusted
publisher trustworthy.

Each API process holds its own data/index. Measure loaded memory and startup time
before adding workers. Replicas handle availability and request volume; ingress
must enforce aggregate quotas because the built-in rate limiter is per process.

Future worldwide coverage should introduce country/source adapters and partitioned
datasets. The current release loader deliberately accepts Canada only. Do not assume
every country has a province-region-city tree: preserve local kinds, provenance,
multiple relevant relationships and explicit partial coverage. API compatibility
and stable IDs allow a later PostGIS-backed implementation without exposing its
database to consumers. Street maps, address geocoding and routing are separate scope.

## Repository and deployment boundaries

This repository contains reusable code, generic configuration, tests and public
geographic research. A private infrastructure repository owns actual AWS accounts,
networking, authentication configuration, deployment permissions and promotion.
Private deployment automation selects an exact tested container digest plus an
exact dataset manifest digest. It does not follow a mutable latest tag.

The intended hosting target is an independent ECS/Fargate service in a company-owned
workload account. It may first run as a separate service in an existing cluster.
The same image can run elsewhere. A company's admin website is a client of the
service; it need not host this backend. Production secrets stay outside Git.

Code and data have separate release workflows. Public pull-request CI has no AWS
permissions. A source update must retain its original bytes, identity/geometry
evidence and licences, then be adopted independently of the code release.
