"""Bounded persistent reuse of verified battle ZIPs, never of stale recommendations."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
import uuid
import zipfile
from pathlib import Path

import pvpoke_archive as archives
from pvpoke_calculation_version import content_hash

SCHEMA = 1
KEY = re.compile(r"[0-9a-f]{64}")


def context(candidate: dict, ivs: list, batch_mode: str, meta_sha256: str,
            calculation_version: str, cp_cap: int, max_level: int) -> dict:
    request = dict(candidate=candidate, ivs=ivs, batch_mode=batch_mode,
                   meta_sha256=meta_sha256, calculation_version=calculation_version,
                   cp_cap=cp_cap, max_level=max_level, schema=SCHEMA)
    key = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"key": key, "request": request}


def _validate(path: Path, request: dict) -> None:
    archives.verify_zip(path)
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        if any(manifest.get(k) != request[k] for k in (
                "batch_mode", "meta_sha256", "calculation_version", "cp_cap", "max_level")):
            raise ValueError("Saved battle conditions differ")
        if manifest.get("engine", {}).get("browser_fallbacks", 0):
            raise ValueError("A browser fallback has no pinned engine identity")
        if manifest.get("minior_strategy"):
            evidence = manifest["minior_strategy"].get("evidence_file")
            if not evidence or evidence not in bundle.namelist():
                raise ValueError("Missing strategy evidence")
        modes = ("default",) if request["batch_mode"] == "simple" else ("default", "rank1", "attack", "defense")
        expected = {tuple(iv) for iv in request["ivs"]}
        rows = list(csv.DictReader(io.StringIO(bundle.read("ranking_summary.csv").decode("utf-8-sig"))))
        if len(rows) != len(expected) * len(modes) or manifest.get("candidates") != len(expected):
            raise ValueError("Saved candidate count differs")
        for mode in modes:
            selected = [row for row in rows if row.get("opponent_iv_mode") == mode]
            if len(selected) != len(expected) or {tuple(int(r[k]) for k in ("atk", "def", "hp")) for r in selected} != expected:
                raise ValueError("Saved candidate IVs differ")
            if any(any(r.get(k, "").lower() != v.lower() for k, v in request["candidate"].items()) for r in selected):
                raise ValueError("Saved Pokemon or moves differ")


class ResultCache:
    def __init__(self, work: Path, *, ttl_seconds: int = 7 * 86400,
                 max_bytes: int = 200 * 1024 * 1024, max_entries: int = 20):
        self.root = archives.archive_dir(work) / "result_cache"
        self.ttl_seconds, self.max_bytes, self.max_entries = ttl_seconds, max_bytes, max_entries

    @classmethod
    def configured(cls, work: Path):
        if os.environ.get("PVP_RESULT_CACHE", "1").lower() in ("0", "false", "off"):
            return None
        ttl = int(os.environ.get("PVP_RESULT_CACHE_TTL_SECONDS", str(7 * 86400)))
        budget = int(os.environ.get("PVP_RESULT_CACHE_MAX_MB", "200"))
        if not 0 <= ttl <= 30 * 86400 or not 1 <= budget <= 1024:
            raise ValueError("Invalid result cache retention limits")
        return cls(work, ttl_seconds=ttl, max_bytes=budget * 1024 * 1024) if ttl else None

    def restore(self, ctx: dict, destination: Path) -> dict | None:
        key = ctx["key"]
        if not KEY.fullmatch(key):
            return None
        path, metadata = self.root / (key + ".zip"), self.root / (key + ".json")
        try:
            if path.is_symlink() or metadata.is_symlink():
                return None
            info = json.loads(metadata.read_text())
            age = time.time() - info["created_at"]
            if info.get("schema") != SCHEMA or info.get("key") != key or not 0 <= age < self.ttl_seconds:
                return None
            if path.stat().st_size > self.max_bytes or content_hash(path) != info["sha256"]:
                return None
            _validate(path, ctx["request"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            archives._atomic_copy(path, destination)
            return {"reused": True, "age_seconds": int(age), "calculation_version": ctx["request"]["calculation_version"]}
        except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
            return None

    def store(self, ctx: dict, source: Path) -> bool:
        key = ctx["key"]
        if not KEY.fullmatch(key) or source.stat().st_size > self.max_bytes:
            return False
        _validate(source, ctx["request"])
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (key + ".zip")
        archives._atomic_copy(source, path)
        metadata = self.root / (key + ".json")
        temp = self.root / (key + "." + uuid.uuid4().hex + ".partial")
        try:
            with temp.open("x") as stream:
                json.dump(dict(schema=SCHEMA, key=key, created_at=time.time(), sha256=content_hash(path)), stream)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, metadata)
        finally:
            temp.unlink(missing_ok=True)
        self.prune()
        return True

    def prune(self) -> None:
        # Only our hash-named files; never delete history ZIPs or latest.zip.
        files = sorted((p for p in self.root.glob("*.zip") if KEY.fullmatch(p.stem) and not p.is_symlink()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        used = kept = 0
        for path in files:
            size = path.stat().st_size
            metadata = path.with_suffix(".json")
            try:
                age = time.time() - json.loads(metadata.read_text())["created_at"]
                valid = 0 <= age < self.ttl_seconds
            except (OSError, ValueError, KeyError, TypeError):
                valid = False
            if valid and kept < self.max_entries and used + size <= self.max_bytes:
                used += size; kept += 1
            else:
                path.unlink(missing_ok=True)
                if not metadata.is_symlink():
                    metadata.unlink(missing_ok=True)
