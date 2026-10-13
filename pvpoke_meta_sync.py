#!/usr/bin/env python3
"""Compare or update the bundled PvPoke opponent move-list snapshot.

The ChatGPT Project source is NOT available to Railway directly. Supply an
exported local copy of pvpokeメタポケモン.txt with --source. This tool does
not fetch Project files, commit to GitHub, or deploy anything automatically.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import io
from pathlib import Path

DEFAULT_TARGET = Path(__file__).resolve().parent / "pvpoke_meta_opponents.csv"


def read_rows(path: Path) -> list[tuple[str, str, str, str]]:
    """Preserve ordering, repeated move sets, forms and shadow spelling."""
    if not path.is_file():
        raise ValueError(f"File does not exist: {path}")
    rows = []
    text = path.read_text(encoding="utf-8-sig")
    for number, fields in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not fields or (len(fields) == 1 and not fields[0].strip()):
            continue
        if len(fields) != 4 or any(not value.strip() for value in fields):
            raise ValueError(
                f"{path}:{number}: expected four nonempty "
                "species,fast,charged1,charged2 fields; source IVs must "
                "be handled separately"
            )
        rows.append(tuple(value.strip() for value in fields))
    if not rows:
        raise ValueError(f"Source has no usable move sets: {path}")
    return rows


def serialize(rows: list[tuple[str, str, str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def sync(source: Path, target: Path, *, apply: bool = False) -> bool:
    original = read_rows(source)
    existing = read_rows(target) if target.is_file() else []
    rendered = serialize(original)
    checksum = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
    if original == existing:
        print(f"MATCH: {len(original)} rows; sha256 prefix {checksum}; no changes")
        return True
    print(f"DIFFER: source {len(original)} rows, target {len(existing)} rows")
    for line in list(difflib.unified_diff(
        serialize(existing).splitlines(), rendered.splitlines(),
        fromfile=str(target), tofile=str(source), lineterm=""
    ))[:120]:
        print(line)
    if not apply:
        print("No files changed. To update the target explicitly, use --apply.")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    assert read_rows(target) == original
    print(f"UPDATED: {target}; {len(original)} rows; sha256 prefix {checksum}")
    print("Git commit and Railway deployment remain separate explicit steps.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="Exported/current ChatGPT Project move-list file")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--apply", action="store_true",
                        help="Write a changed snapshot; default is read-only check")
    args = parser.parse_args()
    try:
        return 0 if sync(args.source, args.target, apply=args.apply) else 1
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(2, f"SYNC ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
