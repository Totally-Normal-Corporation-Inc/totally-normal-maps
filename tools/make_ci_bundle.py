"""Build a tiny offline deployment fixture for container CI; no source downloads."""
import argparse
from pathlib import Path
import tempfile

from tests.api_fixture import make_release
from totally_normal_maps.deployment import assemble_deployment
from totally_normal_maps.distribution import package_dataset, read_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='maps-ci-') as scratch:
        root = Path(scratch)
        _, release, digest = make_release(root)
        notice = root / 'NOTICE.md'
        notice.write_text('Synthetic geography fixture. No external datasets.\n')
        package = root / 'package'
        package_dataset(release, package, manifest_sha256=digest, repository='example/maps',
                        tag='dataset-ci', notice=notice)
        lock = read_lock(package / 'dataset.lock.json')
        assemble_deployment(package / 'dataset.lock.json', args.output, archive=package / lock['asset'])
    print('Offline synthetic deployment bundle verified.')


if __name__ == '__main__': main()
