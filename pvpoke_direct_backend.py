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


def linux_process_rss_mb(pid: int) -> dict | None:
    """Read Node RSS and the process-lifetime Linux VmHWM peak, in MiB.

    Railway's coarse service sampling can miss short Matrix calculations.
    Reading /proc after each calculation captures their real high water mark.
    """
    try:
        values = {}
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith(('VmRSS:', 'VmHWM:')):
                name, raw = line.split(':', 1)
                values[name] = round(int(raw.strip().split()[0]) / 1024, 2)
        if 'VmRSS' in values and 'VmHWM' in values:
            return {'rss_mb': values['VmRSS'], 'peak_rss_mb': values['VmHWM']}
    except (OSError, ValueError, IndexError):
        return None
    return None


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


def validate_minior_strategies(payload: dict, candidate_count: int, opponent_count: int):
    """Fail closed if the strategy evidence disagrees with the ratings in the Matrix."""
    result = payload.get('result') or {}
    model = result.get('minior_policy_model')
    if model is None:
        return None
    if model != 'experimental-max-per-matchup-v1':
        raise DirectMatrixError('Unsupported Minior strategy version')
    rows = result.get('candidates')
    if not isinstance(rows, list) or len(rows) != candidate_count:
        raise DirectMatrixError('Missing Minior candidate evidence')
    valid_policies = ('instant', 'hold', 'adaptive')
    for row in rows:
        chosen, by_policy, ratings = row.get('policies'), row.get('strategy_ratings'), row.get('ratings')
        if (not isinstance(chosen, list) or len(chosen) != opponent_count or
            not isinstance(by_policy, dict) or set(by_policy) != set(valid_policies)):
            raise DirectMatrixError('Incomplete Minior strategy evidence')
        for policy in valid_policies:
            values = by_policy[policy]
            if (not isinstance(values, list) or len(values) != opponent_count or
                any(type(value) is not int or not 0 <= value <= 1000 for value in values)):
                raise DirectMatrixError('Invalid Minior policy ratings')
        for i, policy in enumerate(chosen):
            if policy not in valid_policies or ratings[i] != by_policy[policy][i] or (
                ratings[i] != max(by_policy[name][i] for name in valid_policies)
            ):
                raise DirectMatrixError('Minior policy and chosen Rating disagree')
    return rows


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
        self.memory_samples = []
        self.last_minior_data = None
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
            before = linux_process_rss_mb(self.proc.pid)
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            ready, _, _ = select.select([self.proc.stdout], [], [], self.timeout_seconds)
            if not ready:
                raise DirectMatrixError("PvPoke Node response timed out")
            line = self.proc.stdout.readline()
            if not line:
                raise DirectMatrixError("PvPoke Node exited without a Matrix response")
            response = json.loads(line)
            matrix = matrix_from_response(response, candidates, opponents)
            self.last_minior_data = validate_minior_strategies(
                response, len(candidates), len(opponents))
            after = linux_process_rss_mb(self.proc.pid)
            if before is not None and after is not None:
                self.memory_samples.append({
                    'candidates': len(candidates), 'opponents': len(opponents),
                    'rss_before_mb': before['rss_mb'],
                    'rss_after_mb': after['rss_mb'],
                    'peak_rss_mb': after['peak_rss_mb'],
                })
            return matrix
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
