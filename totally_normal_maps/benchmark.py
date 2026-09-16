"""Reproducible geometry-only comparisons; these are not production load tests."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import time

import shapely
from shapely.geometry import Point
from shapely.strtree import STRtree

from .catalogue import CatalogueError, ROOT, open_catalogue, read_json


def load_shapes(run, include_repair_candidates=False):
    with open_catalogue(run) as db:
        rows = db.execute("SELECT id, geometry, repair_candidate FROM csd ORDER BY id").fetchall()
    geometries = [row["geometry"] if row["geometry"] is not None else row["repair_candidate"] if include_repair_candidates else None for row in rows]
    if any(geometry is None for geometry in geometries):
        raise CatalogueError("Resolve missing or invalid assignment geometries first, or explicitly use --include-repair-candidates for an unqualified experiment.")
    return [row["id"] for row in rows], [shapely.from_wkb(geometry) for geometry in geometries]


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(samples):
    return {"queries": len(samples), "median_ms": round(statistics.median(samples), 4),
            "p95_ms": round(percentile(samples, .95), 4), "max_ms": round(max(samples), 4),
            "total_seconds": round(sum(samples) / 1000, 4)}


def peak_memory_mib():
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024 * 1024 if platform.system() == "Darwin" else 1024), 2)


def make_points(ids, shapes, count, seed, fixtures):
    points = [{**fixture, "kind": "known_locality"} for fixture in fixtures]
    rng = random.Random(seed)
    while len(points) < count:
        index = rng.randrange(len(shapes))
        geometry = shapes[index]
        if len(points) % 3 == 0:
            # Exact source vertex tests covers() inclusion, including shared edges.
            part = max(geometry.geoms, key=lambda p: p.area) if geometry.geom_type == "MultiPolygon" else geometry
            xy = part.exterior.coords[rng.randrange(len(part.exterior.coords))]
            point = Point(xy)
            kind = "source_vertex"
        else:
            point = geometry.representative_point()
            kind = "generated_interior"
        points.append({"label": f"{kind}:{ids[index]}:{len(points)}", "lon": point.x, "lat": point.y,
                       "must_include": [ids[index]], "kind": kind})
    return points


def validate_points(points):
    if not isinstance(points, list) or not points:
        raise CatalogueError("Point fixtures must be a nonempty JSON list.")
    for row in points:
        if not isinstance(row, dict) or not isinstance(row.get("label"), str):
            raise CatalogueError("Each point needs a label and numeric lon/lat.")
        for key, limit in (("lon", 180), ("lat", 90)):
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
                raise CatalogueError(f"Invalid point {key}.")
        expected = row.get("expected_ids")
        if not isinstance(expected, list) or any(not isinstance(uid, str) for uid in expected):
            raise CatalogueError("Each input point needs an explicit expected_ids list (empty for outside Canada).")


def postgis_options(dsn):
    """The optional comparison can only use an explicitly named local lab DB."""
    from psycopg2.extensions import parse_dsn
    import psycopg2
    try:
        options = parse_dsn(dsn)
    except psycopg2.ProgrammingError:
        raise CatalogueError("Invalid PostGIS connection configuration.") from None
    allowed = {"host", "port", "dbname", "user", "password", "sslmode", "connect_timeout"}
    if set(options) - allowed or options.get("host") not in {"127.0.0.1", "::1"} or options.get("dbname") != "maps_lab":
        raise CatalogueError("PostGIS requires an explicit loopback host and database maps_lab; service files and remote hosts are not accepted.")
    return options


def compare_postgis(ids, shapes, points, rounds, dsn):
    import psycopg2
    from psycopg2.extras import execute_values
    options = postgis_options(dsn)
    options["connect_timeout"] = "5"
    # Explicit hostaddr prevents an inherited PGHOSTADDR from overriding loopback.
    options["hostaddr"] = options["host"]
    options["options"] = "-c search_path=public,pg_temp"
    started = time.perf_counter()
    with closing(psycopg2.connect(**options)) as db:
        try:
            with db.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '60s'")
                cursor.execute("SELECT PostGIS_Full_Version()")
                version = cursor.fetchone()[0]
                cursor.execute("CREATE TEMP TABLE canada_shapes (id text PRIMARY KEY, geom geometry(Geometry, 4326) NOT NULL) ON COMMIT DROP")
                execute_values(cursor, "INSERT INTO pg_temp.canada_shapes VALUES %s",
                               [(uid, psycopg2.Binary(shape.wkb)) for uid, shape in zip(ids, shapes)],
                               template="(%s, ST_GeomFromWKB(%s, 4326))", page_size=100)
                cursor.execute("CREATE INDEX ON pg_temp.canada_shapes USING gist (geom)")
                cursor.execute("ANALYZE pg_temp.canada_shapes")
                setup_seconds = time.perf_counter() - started
                timings, first, result = [], [], []
                for turn in range(rounds):
                    for point in points:
                        if time.perf_counter() - started > 900:
                            raise CatalogueError("PostGIS comparison exceeded its 15-minute budget.")
                        before = time.perf_counter()
                        cursor.execute("SELECT id FROM pg_temp.canada_shapes WHERE ST_Covers(geom, ST_SetSRID(ST_Point(%s, %s), 4326)) ORDER BY id", (point["lon"], point["lat"]))
                        matches = [row[0] for row in cursor.fetchall()]
                        elapsed = (time.perf_counter() - before) * 1000
                        (first if turn == 0 else timings).append(elapsed)
                        if turn == 0:
                            result.append(matches)
                return {"version": version, "setup_seconds": round(setup_seconds, 4),
                        "first_pass": summarize(first), "repeat_passes": summarize(timings), "matches": result}
        finally:
            # Even a successful comparison leaves no persistent table or data.
            db.rollback()


def benchmark(run, *, count=500, rounds=3, seed=2025, fixtures_path=None, postgis_env=None, include_repair_candidates=False):
    if not 20 <= count <= 10_000 or not 2 <= rounds <= 5:
        raise CatalogueError("Use 20–10,000 points and 2–5 rounds.")
    fixtures = read_json(fixtures_path or ROOT / "points.json")
    validate_points(fixtures)
    if len(fixtures) > count:
        raise CatalogueError("Point count must include every supplied fixture.")
    started = time.perf_counter()
    ids, shapes = load_shapes(run, include_repair_candidates)
    load_seconds = time.perf_counter() - started
    points = make_points(ids, shapes, count, seed, fixtures)
    point_shapes = [Point(p["lon"], p["lat"]) for p in points]
    bounds = [geometry.bounds for geometry in shapes]
    results, engines = {}, {}

    def linear(point):
        x, y = point.x, point.y
        return [ids[i] for i, (west, south, east, north) in enumerate(bounds)
                if west <= x <= east and south <= y <= north and shapes[i].covers(point)]

    tree_started = time.perf_counter()
    tree = STRtree(shapes)
    tree_seconds = time.perf_counter() - tree_started

    def indexed(point):
        return sorted(ids[int(i)] for i in tree.query(point, predicate="covered_by"))

    # Compare a linear bbox/covers baseline against an index, without application
    # queries or consumer-specific limits. This is not a runtime capacity test.
    for name, classifier in (("bbox_loop", linear), ("strtree", indexed)):
        first, repeat, matches = [], [], []
        for turn in range(rounds):
            for point in point_shapes:
                if time.perf_counter() - started > 900:
                    raise CatalogueError("Comparison exceeded its 15-minute budget.")
                before = time.perf_counter()
                found = classifier(point)
                elapsed = (time.perf_counter() - before) * 1000
                (first if turn == 0 else repeat).append(elapsed)
                if turn == 0:
                    matches.append(found)
        results[name] = matches
        engines[name] = {"first_pass": summarize(first), "repeat_passes": summarize(repeat)}
    engines["strtree"]["index_build_seconds"] = round(tree_seconds, 4)
    if postgis_env:
        dsn = os.environ.get(postgis_env)
        if not dsn:
            raise CatalogueError("The named PostGIS environment variable is empty.")
        comparison = compare_postgis(ids, shapes, points, rounds, dsn)
        results["postgis"] = comparison.pop("matches")
        engines["postgis"] = comparison
    failures = []
    for index, point in enumerate(points):
        reference = results["bbox_loop"][index]
        for engine, matches in results.items():
            actual = matches[index]
            if actual != reference:
                failures.append({"point": point["label"], "engine": engine, "reason": "engine_disagreement", "expected": reference, "actual": actual})
            if "expected_ids" in point and actual != sorted(point["expected_ids"]):
                failures.append({"point": point["label"], "engine": engine, "reason": "fixture_mismatch", "expected": point["expected_ids"], "actual": actual})
            elif not set(point.get("must_include", [])) <= set(actual):
                failures.append({"point": point["label"], "engine": engine, "reason": "own_boundary_missing", "actual": actual})
    report = read_json(Path(run) / "report.json")
    return {"schema_version": 1, "status": "failed" if failures else "passed",
            "dataset_sha256": report["source"]["sha256"], "feature_count": len(ids),
            "catalogue_sha256": report["catalogue_sha256"],
            "point_count": len(points), "rounds": rounds, "seed": seed,
            "point_sha256": hashlib.sha256(json.dumps(points, sort_keys=True).encode()).hexdigest(),
            "load_seconds": round(load_seconds, 4), "engines": engines, "failures": failures,
            "peak_process_rss_mib": peak_memory_mib(),
            "environment": {"python": platform.python_version(), "platform": platform.platform(), "shapely": shapely.__version__, "geos": shapely.geos_version_string},
            "postgis": "evaluated" if postgis_env else "not_evaluated",
            "geography_qualified": False,
            "geometry_validation_passed": report["qualification"]["geometry_validation"] == "passed",
            "unreviewed_repair_candidates_used": report["repair_candidate_count"] if include_repair_candidates else 0,
            "limits": ["Geometry-only local experiment; excludes application queries, worker concurrency and production capacity.",
                       "First pass is not a controlled cold operating-system or database cache test.",
                       "Generated interiors/vertices test consistency, not independent source accuracy.",
                       "CSD layer only; ancestor expansion and manual memberships remain untested."],
            "points": [{**point, "matches": {engine: values[i] for engine, values in results.items()}} for i, point in enumerate(points)]}
