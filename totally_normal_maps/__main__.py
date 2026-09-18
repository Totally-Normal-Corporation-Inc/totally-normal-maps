"""Totally Normal Maps: build, inspect, release and serve reference geography."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.request import urlopen

from .catalogue import CatalogueError, MAX_SOURCE_BYTES, ROOT, PROVINCES, build, read_json, sha256


def download(destination, *, manifest=None, max_bytes=MAX_SOURCE_BYTES):
    manifest = manifest or read_json(ROOT / "statcan-2025.json")
    destination = Path(destination).resolve()
    if destination.exists():
        raise CatalogueError("Download destination exists; existing source files are never overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent) as output:
        started, received = time.monotonic(), 0
        with urlopen(manifest["url"], timeout=30) as response:
            while block := response.read(1024 * 1024):
                received += len(block)
                if received > max_bytes or time.monotonic() - started > 180:
                    raise CatalogueError("Download exceeded its byte/time budget.")
                output.write(block)
        output.flush()
        if sha256(output.name) != manifest["sha256"]:
            raise CatalogueError("Downloaded file differs from the pinned release.")
        os.link(output.name, destination)  # atomic, no overwrite, mode 0600
    return {"source": str(destination), "bytes": received, "sha256": manifest["sha256"]}


def save_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download", help="Download and verify the pinned official ZIP")
    fetch.add_argument("--output", required=True, type=Path)
    region_fetch = commands.add_parser("download-regions", help="Download the pinned Québec crosswalk reference")
    region_fetch.add_argument("--output", required=True, type=Path)
    province_fetch = commands.add_parser("download-provinces", help="Download the pinned cartographic country overview")
    province_fetch.add_argument("--output", required=True, type=Path)
    city_fetch = commands.add_parser("download-city-areas", help="Download a pinned Québec city-area source")
    city_fetch.add_argument("--source", required=True, choices=("quebec", "gatineau"))
    city_fetch.add_argument("--output", required=True, type=Path)
    city_areas = commands.add_parser("city-areas", help="Add Québec city areas to a fresh regional review run")
    city_areas.add_argument("--run", required=True, type=Path)
    city_areas.add_argument("--quebec-source", required=True, type=Path)
    city_areas.add_argument("--gatineau-source", required=True, type=Path)
    city_areas.add_argument("--output", required=True, type=Path)
    city_areas.add_argument("--plan", type=Path)
    city_areas.add_argument("--display-tolerance-metres", type=float, default=20)
    refresh = commands.add_parser("quebec-refresh", help="Apply evidenced Québec municipal and city-area updates to a fresh run")
    refresh.add_argument("--run", required=True, type=Path)
    refresh.add_argument("--source-dir", required=True, type=Path)
    refresh.add_argument("--output", required=True, type=Path)
    refresh.add_argument("--plan", type=Path)
    refresh_fetch = commands.add_parser("download-quebec-refresh", help="Download one pinned Québec refresh source")
    refresh_fetch.add_argument("--source", required=True)
    refresh_fetch.add_argument("--output", required=True, type=Path)
    refresh_fetch.add_argument("--plan", type=Path)
    ontario = commands.add_parser("ontario-refresh", help="Apply evidenced Ontario boundary and city-area updates offline")
    ontario.add_argument("--run", required=True, type=Path)
    ontario.add_argument("--source-dir", required=True, type=Path)
    ontario.add_argument("--output", required=True, type=Path)
    ontario.add_argument("--plan", type=Path)
    ontario_fetch = commands.add_parser("download-ontario-refresh", help="Download one pinned Ontario refresh source")
    ontario_fetch.add_argument("--source", required=True)
    ontario_fetch.add_argument("--output", required=True, type=Path)
    ontario_fetch.add_argument("--plan", type=Path)
    jurisdiction = commands.add_parser('jurisdiction-refresh', help='Apply a pinned jurisdiction plan offline')
    jurisdiction.add_argument('--province', required=True, choices=tuple(PROVINCES))
    jurisdiction.add_argument('--run', required=True, type=Path)
    jurisdiction.add_argument('--source-dir', required=True, type=Path)
    jurisdiction.add_argument('--plan', required=True, type=Path)
    jurisdiction.add_argument('--output', required=True, type=Path)
    jurisdiction_fetch = commands.add_parser('download-jurisdiction-refresh', help='Download one qualified, pinned source')
    jurisdiction_fetch.add_argument('--source', required=True)
    jurisdiction_fetch.add_argument('--plan', required=True, type=Path)
    jurisdiction_fetch.add_argument('--output', required=True, type=Path)
    regions = commands.add_parser("regions", help="Add selected regions to a fresh local review run")
    regions.add_argument("--run", required=True, type=Path)
    regions.add_argument("--quebec-source", required=True, type=Path)
    regions.add_argument("--output", required=True, type=Path)
    regions.add_argument("--plan", type=Path, help="Explicitly qualify a different regional plan")
    regions.add_argument("--display-tolerance-metres", type=float, default=200)
    regions.add_argument("--province-source", type=Path, help="Pinned cartographic province ZIP for the country overview")
    stage = commands.add_parser("build", help="Build a review-only local catalogue; no application writes")
    stage.add_argument("--source", required=True, type=Path)
    stage.add_argument("--output", required=True, type=Path)
    stage.add_argument("--manifest", type=Path, help="Explicitly qualify a different pinned source")
    stage.add_argument("--display-tolerance-metres", type=float, default=200)
    stage.add_argument("--province-source", type=Path, help="Pinned cartographic province ZIP for the country overview")
    bench = commands.add_parser("benchmark", help="Compare bbox matching, STRtree and optionally local PostGIS")
    bench.add_argument("--run", required=True, type=Path)
    bench.add_argument("--report", required=True, type=Path)
    bench.add_argument("--points", type=int, default=500)
    bench.add_argument("--rounds", type=int, default=3)
    bench.add_argument("--seed", type=int, default=2025)
    bench.add_argument("--fixtures", type=Path)
    bench.add_argument("--postgis-dsn-env", help="Variable holding an explicit loopback maps_lab DSN")
    bench.add_argument("--include-repair-candidates", action="store_true", help="Use unapproved repairs for this experiment; geography remains unqualified")
    review = commands.add_parser("reconcile", help="Suggest matches for a generic local area inventory")
    review.add_argument("--run", required=True, type=Path)
    review.add_argument("--areas", required=True, type=Path)
    review.add_argument("--report", required=True, type=Path)
    preview = commands.add_parser("serve", help="Serve the map on loopback; Ctrl-C stops it")
    preview.add_argument("--run", required=True, type=Path)
    preview.add_argument("--port", type=int, default=9010)
    release = commands.add_parser("release", help="Export a minimal immutable serving release")
    release.add_argument("--run", required=True, type=Path)
    release.add_argument("--output", required=True, type=Path)
    release.add_argument("--label", default="canada-review")
    fetch_release = commands.add_parser("fetch-release", help="Download a pinned serving release from S3")
    fetch_release.add_argument("--uri", required=True)
    fetch_release.add_argument("--manifest-sha256", required=True)
    fetch_release.add_argument("--output", required=True, type=Path)
    api = commands.add_parser("api", help="Serve the read-only API (localhost by default)")
    api.add_argument("--dataset", type=Path, help="Exported release; alternatively MAPS_DATASET")
    api.add_argument("--manifest-sha256", help="Trusted release digest; alternatively MAPS_MANIFEST_SHA256")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", default=8000, type=int)
    api.add_argument("--limit-concurrency", default=64, type=int)
    verify = commands.add_parser("verify-release", help="Verify hashes, hierarchy and geometry before deployment")
    verify.add_argument("--dataset", required=True, type=Path)
    verify.add_argument("--manifest-sha256")
    args = parser.parse_args(argv)
    if args.command == "download":
        report = download(args.output)
    elif args.command == "download-regions":
        from .regions import PLAN, MAX_REGION_SOURCE_BYTES
        report = download(args.output, manifest=read_json(PLAN)["quebec_source"], max_bytes=MAX_REGION_SOURCE_BYTES)
    elif args.command == "download-provinces":
        report = download(args.output, manifest=read_json(ROOT / "province-display-2021.json"))
    elif args.command == "download-city-areas":
        from .city_areas import PLAN, MAX_CITY_SOURCE_BYTES
        report = download(args.output, manifest=read_json(PLAN)["sources"][args.source], max_bytes=MAX_CITY_SOURCE_BYTES)
    elif args.command == "city-areas":
        from .city_areas import build_city_areas
        report = build_city_areas(args.run, args.output, sources={"quebec": args.quebec_source, "gatineau": args.gatineau_source},
                                  plan_path=args.plan, tolerance=args.display_tolerance_metres)
    elif args.command == "quebec-refresh":
        from .quebec_refresh import build_refresh
        report = build_refresh(args.run, args.output, source_dir=args.source_dir, plan_path=args.plan)
    elif args.command == "ontario-refresh":
        from .ontario_refresh import build_refresh
        report = build_refresh(args.run, args.output, source_dir=args.source_dir, plan_path=args.plan)
    elif args.command == 'jurisdiction-refresh':
        from .jurisdiction_refresh import build_refresh
        report = build_refresh(args.run, args.output, source_dir=args.source_dir, plan_path=args.plan, province=args.province)
    elif args.command in {"download-quebec-refresh", "download-ontario-refresh", 'download-jurisdiction-refresh'}:
        if args.command == 'download-ontario-refresh':
            from .ontario_refresh import PLAN, MAX_BYTES
        elif args.command == 'download-jurisdiction-refresh':
            from .jurisdiction_refresh import MAX_BYTES
            PLAN = args.plan
        else:
            from .quebec_refresh import PLAN, MAX_BYTES
        sources = read_json(args.plan or PLAN)['sources']
        if args.source not in sources:
            raise CatalogueError('Unknown refresh source.')
        if args.command == 'download-jurisdiction-refresh':
            from .source_acquisition import download_source
            report = download_source(sources[args.source], args.output)
        else:
            report = download(args.output, manifest=sources[args.source], max_bytes=MAX_BYTES)
    elif args.command == "regions":
        from .regions import build_regions
        report = build_regions(args.run, args.output, quebec_source=args.quebec_source,
                               plan_path=args.plan, tolerance=args.display_tolerance_metres, province_source=args.province_source)
    elif args.command == "build":
        report = build(args.source, args.output, manifest_path=args.manifest, tolerance=args.display_tolerance_metres, province_source=args.province_source)
    elif args.command == "benchmark":
        from .benchmark import benchmark
        if args.report.exists():
            raise CatalogueError("Report exists; choose a new report filename.")
        report = benchmark(args.run, count=args.points, rounds=args.rounds, seed=args.seed, fixtures_path=args.fixtures, postgis_env=args.postgis_dsn_env, include_repair_candidates=args.include_repair_candidates)
        save_report(args.report, report)
    elif args.command == "reconcile":
        from .reconcile import reconcile
        report = reconcile(args.run, args.areas)
        save_report(args.report, report)
    elif args.command == "release":
        from .releases import export_release
        report = export_release(args.run, args.output, label=args.label)
    elif args.command == "fetch-release":
        from .releases import fetch_s3
        report = fetch_s3(args.uri, args.output, expected_sha256=args.manifest_sha256)
    elif args.command == "verify-release":
        from .dataset import Dataset
        report = Dataset(args.dataset, args.manifest_sha256).summary
    elif args.command == "api":
        from dataclasses import replace
        import uvicorn
        from .api import Settings, create_app
        from .releases import checked_release, fetch_s3
        if not 1 <= args.port <= 65535 or not 1 <= args.limit_concurrency <= 1024:
            raise CatalogueError("Invalid API port or concurrency limit.")
        if args.dataset:
            os.environ["MAPS_DATASET"] = str(args.dataset)
        if args.manifest_sha256:
            os.environ["MAPS_MANIFEST_SHA256"] = args.manifest_sha256
        settings = Settings.from_env()
        if args.host not in {"127.0.0.1", "::1", "localhost"}:
            settings = replace(settings, mode="production")
        if os.environ.get("MAPS_DATASET_S3_URI"):
            if settings.dataset.exists():
                checked_release(settings.dataset, settings.manifest_sha256)
            else:
                fetch_s3(os.environ["MAPS_DATASET_S3_URI"], settings.dataset,
                         expected_sha256=settings.manifest_sha256)
        uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=False,
                    access_log=False, server_header=False, timeout_keep_alive=5,
                    limit_concurrency=args.limit_concurrency)
        return 0
    else:
        from .preview import make_server
        with make_server(args.run, args.port) as server:
            print(f"Canada geography preview: http://127.0.0.1:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    summary = {key: value for key, value in report.items() if key not in {"points", "results"}}
    if args.command == "regions":
        summary = {"output": str(args.output), "state": report["state"],
                   **{key: report["regions"][key] for key in ("feature_count", "province_counts", "geometry_status_counts", "membership_count", "unassigned_member_count", "elapsed_seconds")}}
    elif args.command == "city-areas":
        summary = {"output": str(args.output), "state": report["state"],
                   **{key: report["city_areas"][key] for key in ("feature_count", "municipality_count", "kind_counts", "elapsed_seconds")}}
    elif args.command == "quebec-refresh":
        summary = {'output': str(args.output), 'state': report['state'],
                   'active_municipalities': report['quebec_refresh']['active_municipality_count'],
                   'city_areas': report['city_areas']['feature_count'],
                   'unresolved': report['quebec_refresh']['unresolved']}
    elif args.command == "ontario-refresh":
        summary = {'output': str(args.output), 'state': report['state'],
                   **{key: report['ontario_refresh'][key] for key in ('updated_municipality_count',
                      'updated_region_count', 'added_city_area_count', 'unresolved')}}
    elif args.command == 'jurisdiction-refresh':
        summary = {'output': str(args.output), 'state': report['state'], 'province': args.province,
                   **{key: report['jurisdiction_refreshes'][args.province][key] for key in (
                       'updated_municipality_count', 'deferred_municipality_count', 'added_city_area_count', 'unresolved')}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if report.get("status") == "failed" or report.get("state") == "review_required" else 0


def entrypoint():
    try:
        sys.exit(main())
    except (CatalogueError, FileExistsError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Totally Normal Maps: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    entrypoint()
