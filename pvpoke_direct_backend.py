"""Experimental PvPoke Node.js matrix client using pinned upstream source.

Only instantiate when explicitly selected. Reconstructs the exact established
PvPoke Matrix CSV shape and always validates row/column counts, IV labels and
Battle Ratings before returning. Adapter errors stop the calculation; callers
must not silently switch to a less isolated browser engine.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import threading
import time

from pvpoke_child_env import child_environment

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 600.0


def _reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


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
        raise DirectMatrixError("PvPoke Node result failed")
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
                 timeout_seconds: int | float = 120,
                 max_response_bytes: int = MAX_RESPONSE_BYTES):
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not (0 < float(timeout_seconds) <= MAX_TIMEOUT_SECONDS):
            raise ValueError("Invalid timeout_seconds")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or not (1024 <= max_response_bytes <= 64 * 1024 * 1024):
            raise ValueError("Invalid max_response_bytes")

        self.gamemaster = Path(gamemaster).resolve()
        self.source = Path(source or os.environ.get("PVP_PVPOKE_SOURCE") or
                           (Path(__file__).resolve().parent / "vendor/pvpoke")).resolve()
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = max_response_bytes
        self._closed = False
        self._poisoned = False
        self._io_lock = threading.Lock()

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
                stderr=self._log_file, bufsize=0,
                start_new_session=(os.name == "posix"),
                env=child_environment({"PVP_PVPOKE_SOURCE": str(self.source)})
            )
            if self.proc.stdin is not None:
                os.set_blocking(self.proc.stdin.fileno(), False)
            if self.proc.stdout is not None:
                os.set_blocking(self.proc.stdout.fileno(), False)
        except Exception:
            self.close()
            raise

    def _fail_close(self, message: str) -> None:
        self._poisoned = True
        self.close()
        raise DirectMatrixError(message)

    def _exchange_frame(self, request: dict, *, timeout_message: str) -> dict:
        with self._io_lock:
            if self._closed or self._poisoned or self.proc is None or self.proc.poll() is not None:
                raise DirectMatrixError("PvPoke Node process is not running")

            try:
                frame = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            except Exception:
                self._fail_close("Failed to serialize request")

            if len(frame) > MAX_REQUEST_BYTES:
                self._fail_close("PvPoke Node request exceeded frame limit")

            deadline = time.monotonic() + self.timeout_seconds
            stdin_fd = self.proc.stdin.fileno()
            stdout_fd = self.proc.stdout.fileno()
            sent = 0
            view = memoryview(frame)
            rx_buf = bytearray()
            nl_index = -1

            with selectors.DefaultSelector() as sel:
                sel.register(stdout_fd, selectors.EVENT_READ)
                if len(view) > 0:
                    sel.register(stdin_fd, selectors.EVENT_WRITE)

                while nl_index == -1:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._fail_close(timeout_message)

                    events = sel.select(timeout=remaining)
                    if not events:
                        self._fail_close(timeout_message)

                    for key, _ in events:
                        if key.fd == stdin_fd:
                            try:
                                n = os.write(stdin_fd, view[sent:])
                                sent += n
                                if sent >= len(view):
                                    sel.unregister(stdin_fd)
                            except (BrokenPipeError, OSError):
                                self._fail_close("PvPoke Node write failed")
                        elif key.fd == stdout_fd:
                            while True:
                                try:
                                    chunk = os.read(stdout_fd, 65536)
                                except BlockingIOError:
                                    break
                                except (OSError, BrokenPipeError):
                                    self._fail_close("PvPoke Node read failed")

                                if chunk == b"":
                                    if not rx_buf:
                                        self._fail_close("PvPoke Node exited without a response")
                                    self._fail_close("PvPoke Node exited with incomplete response")

                                if len(rx_buf) + len(chunk) > self.max_response_bytes:
                                    self._fail_close("PvPoke Node response exceeded frame limit")

                                rx_buf.extend(chunk)
                                pos = rx_buf.find(b"\n")
                                if pos != -1:
                                    trailing = rx_buf[pos + 1:]
                                    if trailing:
                                        self._fail_close("Unexpected trailing bytes in PvPoke Node response")
                                    nl_index = pos
                                    break

            if sent < len(view):
                self._fail_close("PvPoke Node responded before request completed")

            line_bytes = bytes(rx_buf[:nl_index]).rstrip(b"\r")
            try:
                line_text = line_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                self._fail_close("PvPoke Node response decoding failed")

            try:
                response = json.loads(line_text, parse_constant=_reject_constant)
            except Exception as exc:
                self._fail_close("PvPoke Node response parsing failed")

            if not isinstance(response, dict):
                self._fail_close("Invalid PvPoke Node response")

            return response

    def simulate(self, candidates: list, opponents: list, shields: tuple[int, int], *,
                 cp_cap: int | None = None) -> list[list]:
        if self._closed or self._poisoned or self.proc is None or self.proc.poll() is not None:
            raise DirectMatrixError("PvPoke Node process is not running")
        payload = {
            "gamemaster_path": str(self.gamemaster),
            "candidates": candidates,
            "opponents": opponents,
            "shields": list(shields),
        }
        if cp_cap is not None:
            payload["cp_cap"] = int(cp_cap)
        try:
            before = linux_process_rss_mb(self.proc.pid)
            response = self._exchange_frame(payload, timeout_message="PvPoke Node response timed out")
            matrix = matrix_from_response(response, candidates, opponents)
            self.last_minior_data = validate_minior_strategies(
                response, len(candidates), len(opponents))
            if self.proc is not None:
                after = linux_process_rss_mb(self.proc.pid)
                if before is not None and after is not None:
                    self.memory_samples.append({
                        'candidates': len(candidates), 'opponents': len(opponents),
                        'rss_before_mb': before['rss_mb'],
                        'rss_after_mb': after['rss_mb'],
                        'peak_rss_mb': after['peak_rss_mb'],
                    })
            return matrix
        except DirectMatrixError:
            self._poisoned = True
            self.close()
            raise
        except Exception as exc:
            self._poisoned = True
            self.close()
            raise DirectMatrixError("PvPoke Node protocol failed") from exc

    def strategy(self, action: str, payload: dict, *, include_engine_sources: bool = False) -> dict:
        """Explicit detail protocol; never infer resources from a Rating."""
        if action not in ("detail", "switch_branch", "switch_prefix", "engine_identity"):
            raise DirectMatrixError("Unknown strategy action")
        if self._closed or self._poisoned or self.proc is None or self.proc.poll() is not None:
            raise DirectMatrixError("PvPoke Node process is not running")
        request = {"action": action, "gamemaster_path": str(self.gamemaster),
                   "battle" if action == "detail" else "branch": payload}
        if include_engine_sources:
            request["include_engine_sources"] = True

        try:
            response = self._exchange_frame(request, timeout_message="Strategy response timed out")
            if response.get("ok") is not True:
                raise DirectMatrixError("PvPoke strategy calculation failed")
            result = response.get("result")
            if not isinstance(result, dict) or result.get("status") not in ("calculated", "unknown"):
                raise DirectMatrixError("Invalid strategy response")
            if action == "detail":
                if result.get("schema") != "strategy-detail-v1" or len(result.get("terminal", [])) != 2:
                    raise DirectMatrixError("Missing detailed terminal states")
                for i, state in enumerate(result["terminal"]):
                    if not (0 <= state["hp"] <= state["max_hp"] and
                            0 <= state["energy_points"] <= 100 and
                            0 <= state["shields"] <= payload["shields"][i]):
                        raise DirectMatrixError("Invalid detailed resources")
            if self.proc is not None:
                sample = result.pop("node_memory", None) or linux_process_rss_mb(self.proc.pid)
                if sample:
                    self.memory_samples.append(sample)
            return result
        except DirectMatrixError:
            self._poisoned = True
            self.close()
            raise
        except Exception as exc:
            self._poisoned = True
            self.close()
            raise DirectMatrixError("PvPoke strategy protocol failed") from exc

    def close(self):
        self._closed = True
        self._poisoned = True
        proc = self.proc
        self.proc = None
        log_file = self._log_file
        self._log_file = None

        if proc is not None:
            try:
                pgid = None
                pid = getattr(proc, "pid", None)
                if os.name == "posix" and isinstance(pid, int) and pid > 0:
                    try:
                        if pid != os.getpgrp():
                            pgid = pid
                    except OSError:
                        pgid = None
                if proc.poll() is None:
                    if pgid is not None:
                        try:
                            os.killpg(pgid, signal.SIGTERM)
                        except (ProcessLookupError, PermissionError):
                            pass
                    try:
                        proc.terminate()
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        if pgid is not None:
                            try:
                                os.killpg(pgid, signal.SIGKILL)
                            except (ProcessLookupError, PermissionError):
                                pass
                        try:
                            proc.kill()
                        except (ProcessLookupError, PermissionError, OSError):
                            pass
                        try:
                            proc.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            pass
                if pgid is not None:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=0.5)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
            except Exception:
                pass
            finally:
                for stream in (proc.stdin, proc.stdout):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, BrokenPipeError):
                            pass

        if log_file is not None:
            try:
                log_file.close()
            except (OSError, BrokenPipeError):
                pass
            self._log_file = None
