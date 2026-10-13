#!/usr/bin/env python3
"""Keep verified final 24-condition ZIPs; purge intermediate files on success.

The default archive folder is ephemeral. Attach a Railway volume at /data,
or set PVP_ARCHIVE_DIR to a persistent path, to retain files across redeploys.
"""
from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MODES = ("default", "rank1", "attack", "defense")
SHIELDS = ("s0", "s1", "s2", "i0y1", "i0y2", "i1y2")
REQUIRED = {f"{mode}_{shield}.csv" for mode in MODES for shield in SHIELDS}
REQUIRED |= {"ranking_summary.csv", "manifest.json"}


def archive_dir(work: Path) -> Path:
    # Railway automatically exports the mount path when a volume is attached.
    persistent = os.environ.get("PVP_ARCHIVE_DIR") or os.environ.get(
        "RAILWAY_VOLUME_MOUNT_PATH"
    )
    return (Path(persistent) / "pvpoke_archives") if persistent else work / "archives"


def archived_latest(work: Path) -> Path | None:
    result = archive_dir(work) / "latest.zip"
    return result if result.is_file() else None


def verify_zip(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Final ZIP missing or empty: {path}")
    with zipfile.ZipFile(path, "r") as bundle:
        names = set(bundle.namelist())
        missing = sorted(REQUIRED - names)
        if missing:
            raise ValueError(f"Final ZIP missing required files: {missing}")
        damaged = bundle.testzip()
        if damaged:
            raise ValueError(f"Final ZIP checksum failed for: {damaged}")


def _atomic_copy(source: Path, dest: Path) -> None:
    temporary = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".partial")
    try:
        with source.open("rb") as read_stream, temporary.open("xb") as write_stream:
            shutil.copyfileobj(read_stream, write_stream)
            write_stream.flush()
            os.fsync(write_stream.fileno())
        verify_zip(temporary)
        os.replace(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)


def preserve_and_cleanup(batch_dir: Path, work: Path) -> Path:
    """Only erase the disposable batch directory once the archives verify.

    A failed/corrupt archive or an unwritable persistent volume leaves all
    intermediates in place for retry/debugging. All saved archives are kept.
    """
    batch_dir, work = batch_dir.resolve(), work.resolve()
    if batch_dir != work / "batch24_results":
        raise ValueError("Refusing to delete an unexpected directory")
    final_zip = batch_dir / "pvpoke_24_conditions.zip"
    verify_zip(final_zip)
    storage = archive_dir(work).resolve()
    if storage == batch_dir or batch_dir in storage.parents:
        raise ValueError("Archive directory must not be inside the temporary output")
    storage.mkdir(parents=True, exist_ok=True)
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archived = storage / f"pvpoke_{label}_{uuid.uuid4().hex[:8]}.zip"
    _atomic_copy(final_zip, archived)
    # A latest pointer is useful after server restart; write atomically.
    _atomic_copy(archived, storage / "latest.zip")
    verify_zip(archived_latest(work))
    # No delete before both historical archive and latest pointer are valid.
    shutil.rmtree(batch_dir)
    return archived
