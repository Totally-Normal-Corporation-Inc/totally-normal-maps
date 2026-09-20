"""Create an immutable metadata-only release from evidenced source-licence reviews.

Previous import plans must match the source pins in the input release. Changes to
acquisition, parsing, identities, editions, coverage or geometry are rejected.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import shutil

from totally_normal_maps.catalogue import CatalogueError, new_directory, read_json, sha256, write_json
from totally_normal_maps.electoral import electoral_source_metadata
from totally_normal_maps.layers import public_url, valid_date
from totally_normal_maps.licensing import redistribution_approved
from totally_normal_maps.releases import checked_release, validate_manifest

LICENCE_FIELDS = {'licence', 'licence_review', 'redistribution_status', 'attribution_statement',
                  'licence_evidence', 'publication_decision', 'publication_disclaimer', 'attribution_display'}


def review_source_licences(dataset, output, *, plans, expected_sha256, label):
    root, manifest, digest = checked_release(dataset, expected_sha256)
    if Path(output).resolve().is_relative_to(root):
        raise CatalogueError('Licence review output must be outside the immutable source release.')
    if not plans or set(plans) - {'electoral', 'municipal_elections'}:
        raise CatalogueError('Expected electoral or municipal source review plans.')
    report = deepcopy(read_json(root / 'report.json'))
    reviewed = {}
    plan_hashes = {Path(path): sha256(Path(path)) for pair in plans.values() for path in pair}
    for section, (previous_path, current_path) in plans.items():
        previous, current = read_json(previous_path), read_json(current_path)
        if (not valid_date(current.get('reviewed_on'))
                or {k:v for k,v in previous.items() if k not in {'sources', 'reviewed_on', 'release_label'}}
                != {k:v for k,v in current.items() if k not in {'sources', 'reviewed_on', 'release_label'}}
                or previous['sources'].keys() != current['sources'].keys()):
            raise CatalogueError('Licence review may only change source licence metadata.')
        part = report[section]
        reviewed[section] = []
        for key, source in current['sources'].items():
            old = previous['sources'][key]
            if electoral_source_metadata(old) != part['sources'].get(key):
                raise CatalogueError(f'Previous source plan does not match the release pin: {section}/{key}.')
            if old == source:
                continue
            if ({k:v for k,v in old.items() if k not in LICENCE_FIELDS}
                    != {k:v for k,v in source.items() if k not in LICENCE_FIELDS}):
                raise CatalogueError('Licence review cannot change source acquisition or parsing.')
            if (not public_url(source.get('licence')) or not redistribution_approved(source)
                    or not source.get('licence_evidence') or not source.get('licence_review')
                    or not source.get('attribution_statement')
                    or source.get('attribution_display', 'always') not in {'always', 'details'}):
                raise CatalogueError('Licence review requires evidence, attribution and a publication basis.')
            metadata = electoral_source_metadata(source)
            part['sources'][key] = metadata
            reviewed[section].append(key)
        part['reviewed_on'] = current['reviewed_on']
        part.setdefault('licence_reviews', []).append({
            'reviewed_on': current['reviewed_on'], 'previous_manifest_sha256': digest,
            'previous_plan_sha256': plan_hashes[Path(previous_path)], 'plan_sha256': plan_hashes[Path(current_path)],
            'source_keys': reviewed[section], 'geometry_changed': False})
    if not any(reviewed.values()):
        raise CatalogueError('No source licence changes to publish in a new release.')
    if any(sha256(path) != digest for path, digest in plan_hashes.items()):
        raise CatalogueError('Licence review plan changed during the review.')
    with new_directory(output) as staging:
        for name in manifest['files']:
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, path)
        write_json(staging / 'report.json', report)
        updated = deepcopy(manifest)
        updated['label'] = label
        updated['files']['report.json'] = {'bytes': (staging / 'report.json').stat().st_size,
                                          'sha256': sha256(staging / 'report.json')}
        validate_manifest(updated)
        write_json(staging / 'manifest.json', updated)
        checked_release(staging)
    return {'manifest_sha256': sha256(Path(output) / 'manifest.json'), 'reviewed_sources': reviewed,
            'geometry_changed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--label', required=True)
    for name in ('electoral', 'municipal'):
        parser.add_argument(f'--previous-{name}-plan', type=Path)
        parser.add_argument(f'--{name}-plan', type=Path)
    args = parser.parse_args()
    plans = {}
    for name, section in (('electoral', 'electoral'), ('municipal', 'municipal_elections')):
        old, new = getattr(args, f'previous_{name}_plan'), getattr(args, f'{name}_plan')
        if bool(old) != bool(new):
            parser.error(f'Both previous and current {name} plans are required.')
        if old:
            plans[section] = (old, new)
    import json
    print(json.dumps(review_source_licences(args.dataset, args.output, plans=plans,
                     expected_sha256=args.expected_sha256, label=args.label), indent=2))


if __name__ == '__main__':
    main()
