"""Read publication bytes from either the working tree or the exact Git index."""
from dataclasses import dataclass
from pathlib import Path
import subprocess

MAX_PUBLIC_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PublicationFile:
    name: str
    data: bytes | None = None
    problem: str | None = None


def publication_files(root, *, staged=False):
    root = Path(root).resolve()

    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])

    if staged:
        # Inspect the whole proposed commit, including unchanged tracked files.
        entries = git('ls-files', '--stage', '-z').split(b'\0')
        for entry in filter(None, entries):
            meta, raw_name = entry.split(b'\t', 1)
            mode, oid, stage = meta.decode().split()
            name = raw_name.decode()
            if stage != '0' or mode not in {'100644', '100755'}:
                yield PublicationFile(name, problem='unmerged file, symlink or submodule in index')
            elif int(git('cat-file', '-s', oid)) > MAX_PUBLIC_BYTES:
                yield PublicationFile(name, problem='oversized publication artifact')
            else:
                yield PublicationFile(name, data=git('cat-file', 'blob', oid))
        return

    names = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    for name in sorted(set(filter(None, names))):
        path = root / name
        if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
            yield PublicationFile(name, problem='symlinks are not publication artifacts')
        elif not path.is_file():
            yield PublicationFile(name, problem='tracked file missing from working tree')
        elif path.stat().st_size > MAX_PUBLIC_BYTES:
            yield PublicationFile(name, problem='oversized publication artifact')
        else:
            yield PublicationFile(name, data=path.read_bytes())
