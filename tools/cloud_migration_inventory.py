#!/usr/bin/env python3
"""Read-only inventory for use INSIDE the running Railway container.

Only names, sizes, modes and database counts/hashes are emitted, never rows or
secret values. Save the output privately; it is not a backup of the data.
"""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.cloud_migration_backup import is_sqlite, sqlite_snapshot


def inventory():
    from pvpoke_web import WORK
    from pvpoke_auth_store import CredentialStore
    import pvpoke_archive
    archive = pvpoke_archive.archive_dir(WORK)
    auth = CredentialStore().path
    roots = {'archives': archive, 'work': WORK}
    result = {'format': 'pokemoniv-storage-inventory-v1',
              'archive_path': str(archive), 'work_path': str(WORK), 'auth_path': str(auth),
              'variable_names': sorted(os.environ), 'roots': {},
              'notes': ['SQLite table metadata uses backup API snapshots',
                        'S3 object inventory and browser stores require separate export',
                        'Allocated Railway volume size is not measured data size']}
    if not any(auth.is_relative_to(p) for p in roots.values()):
        # Do not scan all of HOME when only one legacy auth database is needed.
        result['extra_auth_file'] = inspect(auth) if auth.exists() else {'exists': False}
    for label, root in roots.items():
        files = []
        if root.is_dir():
            for path in sorted(root.rglob('*')):
                if not path.is_dir() or path.is_symlink():
                    files.append({'path': str(path.relative_to(root)), **inspect(path)})
        result['roots'][label] = {'exists': root.is_dir(), 'files': files,
                                  'bytes': sum(x.get('bytes', 0) for x in files)}
    return result


def inspect(path):
    info = path.lstat()
    result = {'bytes': info.st_size, 'mode': oct(stat.S_IMODE(info.st_mode)),
              'uid': info.st_uid, 'gid': info.st_gid}
    if path.is_symlink():
        return {**result, 'unsupported': 'symlink; requires explicit review'}
    if stat.S_ISREG(info.st_mode) and is_sqlite(path):
        with tempfile.TemporaryDirectory(prefix='pokemoniv-db-inventory-') as tmp:
            result['sqlite'] = sqlite_snapshot(path, Path(tmp) / 'snapshot.sqlite3')
    return result


if __name__ == '__main__':
    print(json.dumps(inventory(), ensure_ascii=True, indent=2))
