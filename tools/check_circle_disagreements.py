"""Offline acceptance of the Casselman/Nation reach regression.

Uses public, synthetic sample centres, never consumer/venue coordinates. Reads a
pinned local release; no networking, publication, geometry edits or deployment.
"""
import argparse
import copy
from contextlib import closing
import json
import sqlite3
import time

import shapely

from totally_normal_maps.catalogue import CatalogueError
from totally_normal_maps.circle import (Budget, CircleIndex, CircleInput, CircleIncomplete,
                                       CircleResult, CirclePredicate, polygon_parts)
from totally_normal_maps.dataset import Dataset


IDS = {'ca-csd-3502025', 'ca-csd-3502044'}


def check(data):
    # Removing the recognised provenance only disables revision 2's inclusion
    # proof, reproducing revision 1's conservative uncertainty policy.
    legacy = copy.copy(data)
    legacy.areas = {uid: {k: v for k, v in row.items() if k != 'uncertainty_basis'}
                    for uid, row in data.areas.items()}
    before, after = CircleIndex(legacy), CircleIndex(data)
    evidence = []
    for name, lon, lat, radius in [('ottawa_80km', -75.7, 45.4, 80000),
                                   ('ottawa_30km', -75.8, 45.4, 30000),
                                   ('outside_canada', 0., 0., 1000)]:
        query = CircleInput(longitude=lon, latitude=lat, radius_m=radius, limit=7)
        old, new = before.lookup(query), after.lookup(query)
        if name == 'ottawa_80km':
            if not (isinstance(old, CircleIncomplete) and old.sample_is_complete
                    and set(old.sample_area_ids) == IDS
                    and len(old.reasons) == 1 and old.reasons[0].code == 'boundary_disagreement'):
                raise CatalogueError('The pinned release did not reproduce the reported two-area disagreement.')
        elif old != new:
            raise CatalogueError('Unaffected circle changed.')
        if not isinstance(new, CircleResult):
            raise CatalogueError('Public sample still has incomplete coverage.')
        collected, page, pages = [], new, 0
        while True:
            collected.extend(item.id for item in page.items); pages += 1
            if page.total != new.total or page.dataset_version != data.version:
                raise CatalogueError('Circle pagination changed version or total.')
            if page.next_offset is None:
                break
            page = after.lookup(query.model_copy(update={'offset': page.next_offset}))
            if not isinstance(page, CircleResult):
                raise CatalogueError('Continuation became incomplete.')
        if collected != sorted(set(collected)) or len(collected) != new.total:
            raise CatalogueError('Circle pagination omitted or duplicated members.')
        if name == 'ottawa_80km' and not IDS <= set(collected):
            raise CatalogueError('Affected municipalities missing from the complete result.')
        evidence.append({'sample': name, 'legacy_status': old.status, 'status': new.status,
                         'total': new.total, 'pages': pages})
    # The actual source disagreement remains; discovery has not approved it.
    for uid in IDS:
        if uid not in data.pending_ids:
            raise CatalogueError('Municipal source disagreement was removed.')
    with closing(sqlite3.connect((data.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        for uid in sorted(IDS):
            raw = db.execute('SELECT geometry FROM csd WHERE id=?', (uid.removeprefix('ca-csd-'),)).fetchone()
            if raw is None or raw[0] is None:
                raise CatalogueError('Missing original municipal source geometry.')
            for geometry in (shapely.from_wkb(raw[0]), data.geometries[uid]):
                predicate = CirclePredicate(-75.7, 45.4, 80000, Budget())
                if not any(predicate.intersects(part) for part in polygon_parts(geometry)):
                    raise CatalogueError('Original and current source do not both reach the 80 km sample.')
    return {'dataset_version': data.version, 'representation_revision': 2,
            'samples': evidence, 'source_disagreements_preserved': sorted(IDS),
            'independent_original_and_current_inclusion': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    start = time.monotonic()
    data = Dataset(args.dataset, args.manifest_sha256)
    result = check(data)
    result['elapsed_seconds_including_load'] = round(time.monotonic() - start, 3)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
