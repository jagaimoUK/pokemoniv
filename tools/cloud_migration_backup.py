#!/usr/bin/env python3
"""Private, offline migration bundles. Never uploads, deletes or overwrites sources.

Run on the Railway container with --root volume=/data and additional work/auth
roots. A final cutover snapshot requires application writes to be quiesced.
SQLite backup() gives database-level consistency, not cross-file consistency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile

SCHEMA = "pokemoniv-private-backup-v1"
SQLITE_MAGIC = b"SQLite format 3\x00"


def digest(path):
    with Path(path).open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _cell(value):
    # Explicit types preserve BLOBs, floats, large integers and NULL distinctly.
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if value is None:
        return ["null", None]
    if isinstance(value, float):
        return ["float", value.hex()]
    return ["integer" if isinstance(value, int) else "text", value]


def sqlite_inventory(path):
    """Call on an offline snapshot; returns no data values, only counts/hashes."""
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        check = [x[0] for x in db.execute("PRAGMA integrity_check")]
        if check != ["ok"]:
            raise ValueError("SQLite integrity check failed")
        schema = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        tables = {}
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            row_hashes = []
            for row in db.execute("SELECT * FROM " + quoted(name)):
                encoded = json.dumps([_cell(x) for x in row], ensure_ascii=True,
                                     separators=(",", ":")).encode()
                row_hashes.append(hashlib.sha256(encoded).digest())
            # Multiset hash: independent of row order, but preserves duplicate rows.
            tables[name] = {"rows": len(row_hashes),
                            "sha256": hashlib.sha256(b"".join(sorted(row_hashes))).hexdigest()}
        return {"user_version": db.execute("PRAGMA user_version").fetchone()[0],
                "schema_sha256": hashlib.sha256(json.dumps(schema).encode()).hexdigest(),
                "tables": tables}


def sqlite_snapshot(source, target, timeout=120):
    deadline = time.monotonic() + timeout

    def progress(*_):
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup exceeded time limit; retry after quiescing writes")

    with sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
    return sqlite_inventory(target)


def is_sqlite(path):
    with Path(path).open("rb") as fp:
        return fp.read(16) == SQLITE_MAGIC


def zip_inventory(path):
    with zipfile.ZipFile(path) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        return {"entries": len(bundle.infolist()),
                "uncompressed_bytes": sum(x.file_size for x in bundle.infolist())}


def _scan(root):
    """No symlinks/devices, even for unknown files. Account for SQLite sidecars."""
    files = []
    for path in sorted(Path(root).rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Symlink in source; resolve and review it before backup")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Special file in source; cannot safely back it up")
        if any(path.name.endswith(suffix) and path.with_name(path.name[:-len(suffix)]).is_file()
               and is_sqlite(path.with_name(path.name[:-len(suffix)]))
               for suffix in ("-wal", "-shm", "-journal")):
            continue  # Included through SQLite's consistent backup API.
        files.append(path)
    return files


def _roots(roots):
    checked = {}
    for label, raw in roots.items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", label):
            raise ValueError("Root labels must use 1..40 letters, digits, _ or -")
        path = Path(raw)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Every root must be an existing, non-symlink directory")
        checked[label] = path.resolve()
    if not checked:
        raise ValueError("At least one explicit source root is required")
    values = list(checked.values())
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate(values) for b in values[i+1:]):
        raise ValueError("Source roots must not overlap")
    return checked


def _safe_child(root, relative):
    part = PurePosixPath(relative)
    if (not relative or part.is_absolute() or ".." in part.parts or "\\" in relative
            or part.as_posix() != relative):
        raise ValueError("Unsafe manifest path")
    path = Path(root).joinpath(*part.parts)
    if Path(root).resolve() not in path.resolve().parents:
        raise ValueError("Path escapes bundle")
    if any(x.is_symlink() for x in (path, *path.parents)):
        raise ValueError("Symlink in bundle path")
    return path


def _private_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x", encoding="utf-8") as fp:
        os.chmod(path, 0o600)
        fp.write(body)
        fp.flush()
        os.fsync(fp.fileno())


def _publish_new_directory(staging, destination):
    # rename(directory, destination) can replace an existing empty directory on
    # POSIX. Reserve the destination with an exclusive mkdir instead. If the
    # process is interrupted while publishing, keep the private partial copy;
    # it cannot pass verification until the manifest is moved last.
    destination.mkdir(mode=0o700)
    for path in sorted(staging.iterdir(), key=lambda p: p.name == 'manifest.json'):
        path.rename(destination / path.name)
    staging.rmdir()


def backup(roots, destination):
    roots = _roots(roots)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Backup destination must not exist")
    if any(r == destination.resolve() or r in destination.resolve().parents for r in roots.values()):
        raise ValueError("Backup destination must be outside all source roots")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    inventories = {name: _scan(path) for name, path in roots.items()}
    size = sum(p.stat().st_size for paths in inventories.values() for p in paths)
    if shutil.disk_usage(destination.parent).free < size * 2 + 16 * 1024 * 1024:
        raise OSError("Insufficient free space for backup and restore verification")
    staging = Path(tempfile.mkdtemp(prefix=".pokemoniv-backup-", dir=destination.parent))
    manifest = {"schema": SCHEMA, "created_unix": int(time.time()),
                "consistency": "per-database; quiesce writes for a final cross-file snapshot",
                "roots": list(roots), "files": [], "directories": []}
    try:
        for label, root in roots.items():
            # Empty directories can be semantically important; preserve them too.
            for directory in [root, *sorted(p for p in root.rglob("*") if p.is_dir())]:
                rel = (Path(label) / directory.relative_to(root)).as_posix()
                (staging / "files" / rel).mkdir(parents=True, exist_ok=True, mode=0o700)
                manifest["directories"].append(rel)
            for source in inventories[label]:
                rel = (Path(label) / source.relative_to(root)).as_posix()
                target = staging / "files" / rel
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                before = source.stat()
                entry = {"path": rel, "source_mode": stat.S_IMODE(before.st_mode),
                         "source_uid": before.st_uid, "source_gid": before.st_gid,
                         "source_bytes": before.st_size, "source_mtime_ns": before.st_mtime_ns}
                if is_sqlite(source):
                    entry["sqlite"] = sqlite_snapshot(source, target)
                else:
                    with source.open("rb") as src, target.open("xb") as dst:
                        os.chmod(target, 0o600)
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                        dst.flush()
                        os.fsync(dst.fileno())
                    after = source.stat()
                    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                            after.st_ino, after.st_size, after.st_mtime_ns):
                        raise ValueError("Source changed during copy; quiesce writes and retry")
                os.chmod(target, 0o600)
                if source.suffix.lower() == ".zip":
                    entry["zip"] = zip_inventory(target)
                entry.update(bytes=target.stat().st_size, sha256=digest(target))
                manifest["files"].append(entry)
            # New/deleted files must not silently disappear from the snapshot.
            if [p.relative_to(root) for p in _scan(root)] != [p.relative_to(root) for p in inventories[label]]:
                raise ValueError("Source file set changed; quiesce writes and retry")
        _private_write(staging / "manifest.json", json.dumps(manifest, ensure_ascii=True, indent=2) + "\n")
        _private_write(staging / "manifest.sha256", digest(staging / "manifest.json") + "\n")
        verify(staging)
        # A successful backup includes a separate restore and full verification.
        with tempfile.TemporaryDirectory(prefix=".pokemoniv-restore-check-", dir=destination.parent) as tmp:
            restore(staging, Path(tmp) / "restored")
        _publish_new_directory(staging, destination)
        return summary(manifest, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify(bundle):
    bundle = Path(bundle).absolute()
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Backup must be a non-symlink directory")
    manifest_path = _safe_child(bundle, "manifest.json")
    if digest(manifest_path) != _safe_child(bundle, "manifest.sha256").read_text().strip():
        raise ValueError("Manifest checksum mismatch")
    obj = json.loads(manifest_path.read_text())
    if obj.get("schema") != SCHEMA or not isinstance(obj.get("files"), list):
        raise ValueError("Unsupported backup manifest")
    if len(obj.get("roots", [])) != len(set(obj.get("roots", []))) or not obj.get("roots"):
        raise ValueError("Invalid backup roots")
    paths = [item["path"] for item in obj["files"]]
    dirs = obj.get("directories", [])
    if len(set(paths)) != len(paths) or len(set(dirs)) != len(dirs) or set(paths) & set(dirs):
        raise ValueError("Duplicate manifest path")
    for rel in dirs + paths:
        if PurePosixPath(rel).parts[0] not in obj["roots"]:
            raise ValueError("Unknown manifest root")
        _safe_child(bundle / "files", rel)
    for rel in dirs:
        if not _safe_child(bundle / "files", rel).is_dir():
            raise ValueError("Missing backup directory")
    actual = {p.relative_to(bundle / "files").as_posix() for p in _scan(bundle / "files")}
    if actual != set(paths):
        raise ValueError("Missing or unexpected backup files")
    for entry in obj["files"]:
        path = _safe_child(bundle / "files", entry["path"])
        if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ValueError("Backup file checksum mismatch")
        if "sqlite" in entry and sqlite_inventory(path) != entry["sqlite"]:
            raise ValueError("SQLite schema/count/content mismatch")
        if "zip" in entry and zip_inventory(path) != entry["zip"]:
            raise ValueError("ZIP inventory mismatch")
    return obj


def restore(bundle, destination):
    manifest = verify(bundle)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Restore only into a NEW directory; overwriting live data is forbidden")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".pokemoniv-restore-", dir=destination.parent))
    try:
        for rel in manifest["directories"]:
            _safe_child(staging, rel).mkdir(parents=True, exist_ok=True, mode=0o700)
        for entry in manifest["files"]:
            src = _safe_child(Path(bundle) / "files", entry["path"])
            target = _safe_child(staging, entry["path"])
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with src.open("rb") as source, target.open("xb") as output:
                os.chmod(target, 0o600)
                shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            if digest(target) != entry["sha256"]:
                raise ValueError("Restored file checksum mismatch")
            if "sqlite" in entry and sqlite_inventory(target) != entry["sqlite"]:
                raise ValueError("Restored database differs")
            if "zip" in entry:
                zip_inventory(target)
        _publish_new_directory(staging, destination)
        return summary(manifest, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def summary(manifest, destination):
    return {"destination": str(destination), "files": len(manifest["files"]),
            "bytes": sum(x["bytes"] for x in manifest["files"]),
            "sqlite_databases": sum("sqlite" in x for x in manifest["files"]),
            "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("backup")
    create.add_argument("--root", action="append", required=True, help="label=/absolute/source-directory")
    create.add_argument("--destination", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("bundle", type=Path)
    recover = sub.add_parser("restore")
    recover.add_argument("bundle", type=Path)
    recover.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "backup":
        roots = [x.split("=", 1) for x in args.root]
        if any(len(x) != 2 for x in roots) or len({x[0] for x in roots}) != len(roots):
            parser.error("Use distinct labels in --root label=/path")
        result = backup(dict(roots), args.destination)
    elif args.action == "restore":
        result = restore(args.bundle, args.destination)
    else:
        result = summary(verify(args.bundle), args.bundle)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
