"""Content identity of the data and code that actually produce battle matrices."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SCHEMA = 1
CALCULATION_FILES = (
    "pvpoke_batch_v2.py", "pvpoke_24_workflow.py", "pvpoke_iv_modes.py",
    "pvpoke_form_rules.py", "pvpoke_direct_backend.py", "pvpoke_node_matrix.js",
    "pvpoke_minior_strategy.js", "pvpoke_calculation_version.py", "pvpoke_matchup_cache.py",
)


def content_hash(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def calculation_version(data_dir: Path, *, root: Path | None = None) -> str | None:
    """Unknown/missing inputs disable reuse; timestamps are never used as identity.

    Browser engines load mutable remote code, so reuse needs an explicit operator
    revision. Direct engines hash every installed JS dependency on each request.
    Report/UI code is deliberately excluded: recommendations are rebuilt fresh.
    """
    root = Path(root or Path(__file__).resolve().parent)
    selected = os.environ.get("PVP_ENGINE", "browser").strip().lower()
    selected = "direct" if selected == "node" else selected
    browser_revision = os.environ.get("PVP_BROWSER_CACHE_EPOCH", "").strip()
    if selected not in ("direct", "browser") or selected == "browser" and not browser_revision:
        return None
    try:
        files = [(name, content_hash(root / name)) for name in CALCULATION_FILES]
        files += [("data/" + name, content_hash(Path(data_dir) / name))
                  for name in ("gamemaster.json", "Pokemon.js")]
        if selected == "direct":
            source = Path(os.environ.get("PVP_PVPOKE_SOURCE") or root / "vendor/pvpoke")
            js = source / "src/js"
            for required in ("battle/Battle.js", "battle/DamageCalculator.js", "pokemon/Pokemon.js"):
                if not (js / required).is_file():
                    return None
            files += [("engine/" + p.relative_to(js).as_posix(), content_hash(p))
                      for p in sorted(js.rglob("*.js")) if p.is_file()]
        body = [SCHEMA, selected, browser_revision, os.environ.get("PVP_CACHE_EPOCH", ""), files]
        return hashlib.sha256(json.dumps(body, separators=(",", ":")).encode()).hexdigest()
    except (OSError, ValueError):
        return None


def force_recalculate() -> bool:
    return os.environ.get("PVP_FORCE_RECALCULATE", "").lower() in ("1", "true", "on")
