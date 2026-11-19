"""Local, bounded Python bridge to the persistent 1v1 native PvPoke worker.

Gymnasium-shaped calls, but no Gymnasium dependency and no learner yet.
This is a trusted, local runner for prepared synthetic/native scenarios.
Do not pass the private prepared request to a policy or train on info data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
from time import monotonic

from pvpoke_child_env import child_environment

ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "pvpoke_rl_step_worker.js"
MAX_INPUT = 128 * 1024
MAX_OUTPUT = 1024 * 1024
ACTIONS = frozenset(("wait", "fast", "charge_0", "charge_1"))


class NativeStepError(RuntimeError):
    """The local worker failed or the step protocol became untrustworthy."""


class _NativeWorkerTransport:
    """Bounded JSONL transport shared by the local native environments."""

    def __init__(self, source, *, timeout=10.0):
        source = Path(source).resolve()
        if not (source / "src/js/battle/Battle.js").is_file():
            raise ValueError("Pinned PvPoke source does not exist")
        if type(timeout) not in (int, float) or not 0 < timeout <= 120:
            raise ValueError("Timeout must be between 0 and 120 seconds")
        self._source = source
        self._timeout = timeout
        self._proc = None
        self._buffer = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _start(self):
        if self._proc is None:
            self._proc = subprocess.Popen(
                ["node", "--max-old-space-size=128", str(WORKER)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=child_environment({"PVP_PVPOKE_SOURCE": str(self._source)}),
            )
            # A blocking stdin write can hang before the response timeout starts.
            # Use partial, nonblocking writes within the same RPC deadline.
            os.set_blocking(self._proc.stdin.fileno(), False)

    def _rpc(self, payload):
        self._start()
        try:
            wire = (json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n").encode()
            if len(wire) > MAX_INPUT:
                raise NativeStepError("Worker request exceeds the input budget")
            if self._proc.poll() is not None:
                raise NativeStepError("Native worker exited")
            deadline = monotonic() + self._timeout
            written = 0
            while written < len(wire):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise NativeStepError("Native worker timed out during input")
                _, writable, _ = select.select([], [self._proc.stdin], [], remaining)
                if not writable:
                    raise NativeStepError("Native worker timed out during input")
                try:
                    n = os.write(self._proc.stdin.fileno(), wire[written:])
                except BlockingIOError:
                    continue
                if n <= 0:
                    raise NativeStepError("Native worker closed its input")
                written += n
            while b"\n" not in self._buffer:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise NativeStepError("Native worker timed out")
                readable, _, _ = select.select([self._proc.stdout], [], [], remaining)
                if not readable:
                    raise NativeStepError("Native worker timed out")
                chunk = os.read(self._proc.stdout.fileno(), 8192)
                if not chunk:
                    raise NativeStepError("Native worker closed its output")
                self._buffer.extend(chunk)
                if len(self._buffer) > MAX_OUTPUT:
                    raise NativeStepError("Worker response exceeds the output budget")
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            response = json.loads(line)
            if type(response) is not dict or response.get("ok") is not True:
                raise NativeStepError("Native worker rejected an operation")
            return response
        except (OSError, ValueError, TypeError, BrokenPipeError) as error:
            self.close()
            raise NativeStepError("Native worker I/O failed") from error
        except NativeStepError:
            self.close()
            raise

    def stats(self):
        response = self._rpc({"op": "stats"})
        rss, peak = response.get("rss_bytes"), response.get("peak_rss_kib")
        if type(rss) is not int or type(peak) is not int or rss < 0 or peak < 0:
            raise NativeStepError("Invalid worker memory measurement")
        return {"rss_bytes": rss, "peak_rss_kib": peak}

    def close(self):
        proc, self._proc = self._proc, None
        self._buffer.clear()
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()


class NativeStepClient(_NativeWorkerTransport):
    """One OS process for many native battle steps and episode resets.

    In this initial experiment, the action space excludes manual shielding,
    switching, stochastic effects, and team selection.
    """

    def __init__(self, source, *, timeout=10.0):
        super().__init__(source, timeout=timeout)
        self._legal = ()
        self._done = True

    def close(self):
        super().close()
        self._legal = ()
        self._done = True

    def reset(self, prepared, *, horizon=500):
        """Return public (observation, info); private prepared data stays in Node."""
        if type(horizon) is not int or not 1 <= horizon <= 500:
            raise ValueError("Invalid horizon")
        response = self._rpc({"op": "reset", "prepared": prepared, "horizon": horizon})
        observation = response.get("observation")
        if (type(observation) is not dict or
                type(observation.get("legal_actions")) is not list or
                not set(observation["legal_actions"]) <= ACTIONS):
            self.close()
            raise NativeStepError("Invalid native observation")
        self._legal = tuple(observation["legal_actions"])
        self._done = False
        return observation, response["info"]

    def step(self, action):
        """Return observation, reward, terminated, truncated, info."""
        if self._done:
            raise NativeStepError("Call reset() before step()")
        if type(action) is not str or action not in self._legal:
            raise ValueError("Illegal action for the current public state")
        response = self._rpc({"op": "step", "action": action})
        result = response.get("result")
        if type(result) is not dict:
            self.close()
            raise NativeStepError("Invalid native step response")
        observation = result.get("observation")
        terminated = result.get("terminated")
        truncated = result.get("truncated")
        reward = result.get("reward")
        if (type(terminated) is not bool or type(truncated) is not bool or
                type(reward) not in (int, float) or reward not in (-1, 0, 1) or
                (terminated and truncated) or
                (observation is None) != (terminated or truncated)):
            self.close()
            raise NativeStepError("Invalid native episode result")
        if observation is not None:
            if (type(observation) is not dict or
                    type(observation.get("legal_actions")) is not list or
                    not set(observation["legal_actions"]) <= ACTIONS):
                self.close()
                raise NativeStepError("Invalid native observation")
            self._legal = tuple(observation["legal_actions"])
        else:
            self._legal = ()
        self._done = terminated or truncated
        return observation, float(reward), terminated, truncated, result.get("info", {})
