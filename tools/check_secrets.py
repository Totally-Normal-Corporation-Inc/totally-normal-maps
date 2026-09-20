"""Scan the exact publication surface offline; print locations, never secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __package__:
    from .publication_files import publication_files
else:
    from publication_files import publication_files

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {f'totally_normal_maps/{name}' for name in (
    'municipal-elections-2026-09.json', 'electoral-2026-09.json', 'statcan-2025.json', 'topology-review-2026-09.json', 'province-display-2021.json', 'regions-2026-09.json',
    'city-areas-quebec-2026-09.json', 'quebec-refresh-2026-09.json', 'ontario-refresh-2026-09.json',
    'jurisdiction-bc-2026-09.json',
    'jurisdiction-ab-2026-09.json',
    'jurisdiction-mb-2026-09.json',
    'jurisdiction-sk-2026-09.json',
    'jurisdiction-nb-2026-09.json',
    'jurisdiction-ns-2026-09.json',
    'jurisdiction-pe-2026-09.json',
    'jurisdiction-nl-2026-09.json',
    'jurisdiction-yt-2026-09.json',
    'jurisdiction-nt-2026-09.json',
    'jurisdiction-nu-2026-09.json')}
CHECKSUM_LINE = re.compile(r'\s*"(?:sha256|inventory_sha256|shape_sha256|identity_sha256|base_source_sha256|base_identity_sha256|member_identity_sha256|parent_catalogue_sha256|parent_report_sha256)": "[0-9a-f]{64}",?\s*')
REPAIR_CHECKSUM_LINE = re.compile(r'\s*"(?:source_sha256|candidate_sha256)": "[0-9a-f]{64}",?\s*')
MUNICIPAL_COMMIT_LINE = re.compile(r'\s*"represent_repository_commit": "[0-9a-f]{40}",?\s*')
DATASET_CHECKSUM_LINE = re.compile(r'\s*"(?:archive_sha256|manifest_sha256)": "[0-9a-f]{64}",?\s*')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Scan exact index bytes that would be committed, not working files')
    args = parser.parse_args()
    entries = list(publication_files(ROOT, staged=args.staged))
    problems = [entry for entry in entries if entry.problem]
    if problems:
        for entry in problems:
            print(f'{entry.name}: {entry.problem}', file=sys.stderr)
        return 2
    files = {entry.name: entry.data for entry in entries}
    if not files:
        print('No publication files to scan.')
        return 0
    # A private snapshot makes the scanner independent of working-tree/index drift.
    # An explicit file list keeps ignored-but-staged secrets in scope.
    with tempfile.TemporaryDirectory(prefix='maps-secret-review-') as scratch:
        for name, data in files.items():
            path = Path(scratch) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = subprocess.run([sys.executable, '-m', 'detect_secrets', '-c', '1', 'scan',
                                 '--no-verify', '--all-files', *sorted(files)],
                                cwd=scratch, capture_output=True, text=True)
    if result.returncode:
        print('Secret scanner failed; publication check is incomplete.', file=sys.stderr)
        return 2
    payload = json.loads(result.stdout)
    findings, checksums = [], 0
    for name, rows in payload['results'].items():
        lines = files[name].decode().splitlines()
        for row in rows:
            if (name in {'dataset.lock.json', 'totally_normal_maps/topology-review-2026-09.json'} and row['type'] == 'Hex High Entropy String'
                    and DATASET_CHECKSUM_LINE.fullmatch(lines[row['line_number'] - 1])):
                checksums += 1
                continue
            if (name == 'totally_normal_maps/municipal-elections-2026-09.json' and row['type'] == 'Hex High Entropy String'
                    and MUNICIPAL_COMMIT_LINE.fullmatch(lines[row['line_number'] - 1])):
                checksums += 1
                continue
            # Reviewed public source/identity digests, not a blanket entropy exclusion.
            if (name in MANIFESTS and row['type'] == 'Hex High Entropy String'
                    and (CHECKSUM_LINE.fullmatch(lines[row['line_number'] - 1]) or
                         (name in {'totally_normal_maps/ontario-refresh-2026-09.json', 'totally_normal_maps/topology-review-2026-09.json'} or name.startswith('totally_normal_maps/jurisdiction-')) and
                         REPAIR_CHECKSUM_LINE.fullmatch(lines[row['line_number'] - 1]))):
                checksums += 1
                continue
            findings.append((name, row['line_number'], row['type']))
    for name, line, kind in findings:
        print(f'{name}:{line}: {kind}', file=sys.stderr)
    surface = 'Git index' if args.staged else 'working tree'
    print(f'Scanned {len(files)} publication files offline ({surface}); {checksums} reviewed source checksums; {len(findings)} unresolved findings.')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
