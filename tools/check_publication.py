"""Check the exact tracked/nonignored publication surface without printing secrets.

This focused guard complements detect-secrets and human review. It is not proof
that a repository contains no sensitive information or vulnerabilities.
"""
import argparse
from pathlib import Path
import re
import sys

if __package__:
    from .publication_files import publication_files
else:
    from publication_files import publication_files

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'embedded credentials': re.compile(r'https?://[^\s/:]+:[^\s/@]+@'),
    'personal workspace': re.compile(r'/home/[^/\s]+/(?:Work|\.aws|\.ssh)/'),
    'deployed AWS identity': re.compile(r'arn:aws[^:]*:[^\s:]+:[^\s:]*:[0-9]{12}:'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Scan exact index bytes that would be committed, not working files')
    args = parser.parse_args()
    findings, count = [], 0
    for entry in publication_files(ROOT, staged=args.staged):
        name, path = entry.name, Path(entry.name)
        if entry.problem:
            findings.append((name, entry.problem))
            continue
        count += 1
        parts = Path(name).parts
        if (any(p.startswith(('.local', '.venv', 'secrets', 'credentials')) or p in {'.aws', '.ssh'} for p in parts)
                or (path.name.startswith('.env') and path.name != '.env.example')
                or path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx', '.sqlite3', '.sqlite', '.db', '.gpkg', '.zip', '.gz', '.tar', '.sql', '.dump', '.log'}
                or path.name in {'id_rsa', 'id_ed25519', 'id_ecdsa'} or '.tfstate' in path.name):
            findings.append((name, 'private/generated/oversized publication artifact'))
        try:
            text = entry.data.decode('utf-8')
        except UnicodeDecodeError:
            if not name.startswith('totally_normal_maps/vendor/leaflet/images/'):
                findings.append((name, 'unexpected binary file'))
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append((name, label))
    for name, reason in findings:
        print(f'{name}: {reason}', file=sys.stderr)
    if findings:
        return 1
    surface = 'Git index' if args.staged else 'working tree'
    print(f'Publication surface checked ({surface}): {count} files; no guard matches. Manual and secret-scanner review still apply.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
