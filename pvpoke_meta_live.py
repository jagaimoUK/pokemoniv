#!/usr/bin/env python3
"""User-authorized PvPoke meta snapshot synchronization over the authenticated MCP.

ChatGPT Project source cannot be polled by Railway. The ChatGPT skill explicitly
supplies the current Project rows when a calculation is requested.
"""
from __future__ import annotations
import csv
from collections import Counter
import hashlib
import io
import os
import uuid
from pathlib import Path

import pvpoke_meta_sync as meta
import pvpoke_24_workflow as workflow
import pvpoke_archive as archives

MAX_BYTES = 80_000
MAX_ROWS = 500
BUNDLED = Path(__file__).resolve().parent / "pvpoke_meta_opponents.csv"


def uploaded_path(work: Path) -> Path:
    return archives.archive_dir(work) / "project_meta_opponents.csv"


def active_path(work: Path) -> Path:
    user = uploaded_path(work)
    return user if user.is_file() else BUNDLED


def digest(csv_data: str) -> str:
    rows = _parse(csv_data)
    return hashlib.sha256(meta.serialize(rows).encode("utf-8")).hexdigest()


def _parse(csv_data: str) -> list[tuple[str, str, str, str]]:
    if not isinstance(csv_data, str) or len(csv_data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("メタ一覧が空、または80KBを超えています")
    rows = []
    for i, fields in enumerate(csv.reader(io.StringIO(csv_data.lstrip('\ufeff'))), 1):
        if not fields or (len(fields) == 1 and not fields[0].strip()):
            continue
        if len(fields) != 4 or any(not f.strip() for f in fields):
            raise ValueError(f"メタ一覧{i}行目は種IDと技3列の4列にしてください")
        rows.append(tuple(f.strip() for f in fields))
        if len(rows) > MAX_ROWS:
            raise ValueError("メタ一覧は最大500行までです")
    if not rows:
        raise ValueError("メタ一覧が空です")
    return rows


def get_status(work: Path) -> dict:
    target = active_path(work)
    rows = meta.read_rows(target)
    rendered = meta.serialize(rows)
    return {
        "source": "project_synced" if target != BUNDLED else "bundled",
        "rows": len(rows),
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "max_rows": MAX_ROWS,
    }


def _validated_rows(work: Path, content: str, species: dict):
    """Validate all proposed rows with the actual battle engine, without replacing active meta."""
    rows = _parse(content)
    rendered = meta.serialize(rows)
    destination = uploaded_path(work)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        _, errors = workflow.load_meta(temporary, species)
        if errors:
            raise ValueError("メタ一覧の検証失敗: " + "; ".join(
                f"{e['line']}行 {e['reason']}" for e in errors[:10]
            ))
    finally:
        temporary.unlink(missing_ok=True)
    return rows, rendered


def preview(work: Path, content: str, species: dict) -> dict:
    """Read-only proposal: show validated changes, preserve current snapshot."""
    rows, rendered = _validated_rows(work, content, species)
    existing = meta.read_rows(active_path(work))
    old = get_status(work)
    proposed = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    before, after = Counter(existing), Counter(rows)
    added = list((after - before).elements())
    removed = list((before - after).elements())
    return {
        "rows": len(rows),
        "sha256": proposed,
        "previous_sha256": old["sha256"],
        "changed": proposed != old["sha256"],
        "current_rows": old["rows"],
        "current_source": old["source"],
        "added_count": len(added),
        "removed_count": len(removed),
        "added": [",".join(row) for row in added[:30]],
        "removed": [",".join(row) for row in removed[:30]],
        "diff_limit": 30,
    }


def sync(work: Path, content: str, species: dict, *,
         expected_previous_sha256: str | None = None,
         expected_sha256: str | None = None) -> dict:
    """Validate every move against current GM; atomically save valid inputs.

    This is called under the web server's execution lock, never while running.
    Failed or partial validation must not replace the active snapshot.
    """
    # Preview state is an optimistic lock: never overwrite a newer snapshot.
    old = get_status(work)
    if expected_previous_sha256 is not None and old["sha256"] != expected_previous_sha256:
        raise ValueError("メタは確認後に更新されました。再度プレビューしてください")
    rows, rendered = _validated_rows(work, content, species)
    checksum = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("ファイル内容がプレビューと異なります。再確認してください")
    if old["sha256"] == checksum:
        return {"changed": False, **old}
    destination = uploaded_path(work)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"changed": True, **get_status(work)}
