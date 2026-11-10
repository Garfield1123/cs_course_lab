#!/usr/bin/env python3
"""Install only new optimization files. Existing files and unsafe archives are rejected."""
import argparse
import tarfile
from pathlib import Path, PurePosixPath


def install(archive, root):
    root = Path(root).resolve(strict=True)
    if not (root/'adapters/gateann_adapter.py').is_file():
        raise ValueError('root must be the existing course repository')
    with tarfile.open(archive, 'r:gz') as tar:
        pending = []
        seen = set()
        for member in tar.getmembers():
            rel = PurePosixPath(member.name)
            if (not member.isfile() or rel.is_absolute() or '..' in rel.parts or '\\' in member.name
                    or not (rel.parts[:1] == ('optimization',) or rel.parts[:2] == ('scripts', 'optimization'))):
                raise ValueError(f'unsafe or out-of-scope archive member: {member.name}')
            target = (root / Path(*rel.parts)).resolve()
            if not target.is_relative_to(root) or target in seen:
                raise ValueError(f'escaping or duplicate member: {member.name}')
            seen.add(target)
            if target.exists():
                raise FileExistsError(f'no files installed: target exists: {target}')
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError(f'unreadable member: {member.name}')
            pending.append((target, stream.read()))
        if not pending:
            raise ValueError('empty bundle')
        for target, data in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as f:
                f.write(data)
    print(f'Installed {len(pending)} new files in {root}; original files unchanged.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    a = p.parse_args()
    try:
        install(a.archive, a.root)
    except (ValueError, OSError, tarfile.TarError) as e:
        p.exit(2, f'ERROR: {e}\n')
