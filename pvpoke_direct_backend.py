"""Experimental PvPoke Node.js matrix client using pinned upstream source.

Only instantiate when explicitly selected. Reconstructs the exact established
PvPoke Matrix CSV shape and always validates row/column counts, IV labels and
Battle Ratings before returning. A caller should switch to the browser engine
if this adapter raises any error.
"""
from __future__ import annotations

import json
import math
import os
import select
import shutil
import subprocess
from pathlib import Path


class DirectMatrixError(RuntimeError):
    pass


def matrix_from_response(payload: dict, candidates: list, opponents: list) -> list[list]:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise DirectMatrixError("PvPoke Node result failed: " +
                                str(payload.get("error") if isinstance(payload, dict) else payload)[:800])
    result = payload.get("result")
    rows = result.get("candidates") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise DirectMatrixError("PvPoke Node returned the wrong candidate count")
    count = len(opponents)
    headers = None
    output = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DirectMatrixError("PvPoke Node candidate is not an object")
        names, ratings, label = row.get("opponents"), row.get("ratings"), row.get("label")
        if not isinstance(names, list) or not isinstance(ratings, list):
            raise DirectMatrixError("Missing Matrix columns or ratings")
        if len(names) != count or len(ratings) != count or not all(
            isinstance(name, str) and name for name in names
        ):
            raise DirectMatrixError("Incomplete PvPoke Node Matrix")
        expected_iv = "/".join(str(candidates[i][k]) for k in ("atk", "def", "hp"))
        if not isinstance(label, str) or expected_iv not in label:
            raise DirectMatrixError("Candidate IV label mismatch")
        if headers is None:
            headers = names
        elif headers != names:
            raise DirectMatrixError("Opponent order/labels disagree across candidate rows")
        if not all(isinstance(rate, int) and 0 <= rate <= 1000 for rate in ratings):
            raise DirectMatrixError("PvPoke Node returned an out-of-range Battle Rating")
        wins = sum(rate > 500 for rate in ratings)
        losses = sum(rate < 500 for rate in ratings)
        draws = count - wins - losses
        # PvPoke Interface.js uses JavaScript Math.round(average * 100)/100.
        mean = math.floor(sum(ratings) * 100 / count + 0.5) / 100
        output.append([label, *ratings, wins, losses, draws, mean])
    return [["", *headers, "Wins", "Losses", "Draws", "Average"], *output]


class DirectMatrixClient:
    def __init__(self, *, gamemaster: Path, log_dir: Path, source: Path | None = None,
                 timeout_seconds: int = 120):
        self.gamemaster = Path(gamemaster).resolve()
        self.source = Path(source or os.environ.get("PVP_PVPOKE_SOURCE") or
                           (Path(__file__).resolve().parent / "vendor/pvpoke")).resolve()
        self.timeout_seconds = timeout_seconds
        if not self.gamemaster.is_file():
            raise DirectMatrixError("GameMaster JSON is missing")
        if not (self.source / "src/js/battle/Battle.js").is_file():
            raise DirectMatrixError("Pinned PvPoke engine sources are missing")
        node = shutil.which("node")
        if not node:
            raise DirectMatrixError("Node.js binary is not installed")
        self._log_file = None
        self.proc = None
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._log_file = (log_dir / "pvpoke_direct.log").open("ab")
            self.proc = subprocess.Popen(
                [node, str(Path(__file__).resolve().parent / "pvpoke_node_matrix.js")],
                cwd=str(Path(__file__).resolve().parent),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._log_file, bufsize=1, text=True, encoding="utf-8",
                env={**os.environ, "PVP_PVPOKE_SOURCE": str(self.source)}
            )
        except Exception:
            self.close()
            raise

    def simulate(self, candidates: list, opponents: list, shields: tuple[int, int]) -> list[list]:
        if self.proc is None or self.proc.poll() is not None:
            raise DirectMatrixError("PvPoke Node process is not running")
        payload = {
            "gamemaster_path": str(self.gamemaster),
            "candidates": candidates,
            "opponents": opponents,
            "shields": list(shields),
        }
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            ready, _, _ = select.select([self.proc.stdout], [], [], self.timeout_seconds)
            if not ready:
                raise DirectMatrixError("PvPoke Node response timed out")
            line = self.proc.stdout.readline()
            if not line:
                raise DirectMatrixError("PvPoke Node exited without a Matrix response")
            return matrix_from_response(json.loads(line), candidates, opponents)
        except (ValueError, OSError, BrokenPipeError) as exc:
            raise DirectMatrixError(f"PvPoke Node protocol failed: {exc}") from exc

    def close(self):
        if self.proc is not None:
            try:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=4)
            finally:
                for stream in (self.proc.stdin, self.proc.stdout):
                    if stream:
                        stream.close()
            self.proc = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
