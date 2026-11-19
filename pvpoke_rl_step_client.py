"""Local, bounded Python bridge to the persistent 1v1 native PvPoke worker.

Gymnasium-shaped calls, but no Gymnasium dependency and no learner yet.
This is a trusted, local runner for prepared synthetic/native scenarios.
Do not pass the private prepared request to a policy or train on info data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Thread
from time import monotonic

from pvpoke_child_env import child_environment

ROOT = Path(__file__).resolve().parent
WORKER = ROOT / "pvpoke_rl_step_worker.js"
MAX_INPUT = 128 * 1024
MAX_OUTPUT = 1024 * 1024
ACTIONS = frozenset(("wait", "fast", "charge_0", "charge_1"))


class NativeStepError(RuntimeError):
    """The local worker failed or the step protocol became untrustworthy."""


def _pipe_exchange(proc, requests, replies):
    """Keep blocking pipe operations off the caller's deadline thread."""
    while (wire := requests.get()) is not None:
        try:
            pending = memoryview(wire)
            while pending:
                sent = os.write(proc.stdin.fileno(), pending)
                if sent <= 0:
                    raise NativeStepError("Native worker closed its input")
                pending = pending[sent:]
            replies.put(None)  # Input finished; the caller now awaits a line.
            line = proc.stdout.readline(MAX_OUTPUT + 1)
            if len(line) > MAX_OUTPUT:
                raise NativeStepError("Worker response exceeds the output budget")
            if not line.endswith(b"\n"):
                raise NativeStepError("Native worker closed its output")
            replies.put(line)
        except (OSError, NativeStepError) as error:
            replies.put(error)
            return


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
        self._pipe_thread = None

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
        if self._pipe_thread is None:
            self._requests = Queue()
            self._replies = Queue()
            thread = Thread(
                target=_pipe_exchange, args=(self._proc, self._requests, self._replies),
                name="pvpoke-native-pipe", daemon=True,
            )
            try:
                thread.start()
            except RuntimeError as error:
                raise NativeStepError("Could not start the native pipe worker") from error
            self._pipe_thread = thread

    def _receive(self, deadline, message):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise NativeStepError(message)
        try:
            reply = self._replies.get(timeout=remaining)
        except Empty as error:
            raise NativeStepError(message) from error
        if isinstance(reply, Exception):
            raise reply
        return reply

    def _rpc(self, payload):
        try:
            wire = (json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n").encode()
            if len(wire) > MAX_INPUT:
                raise NativeStepError("Worker request exceeds the input budget")
            self._start()
            if self._proc.poll() is not None:
                raise NativeStepError("Native worker exited")
            deadline = monotonic() + self._timeout
            self._requests.put(wire)
            self._receive(deadline, "Native worker timed out during input")
            line = self._receive(deadline, "Native worker timed out")
            response = json.loads(line)
            if type(response) is not dict or response.get("ok") is not True:
                raise NativeStepError("Native worker rejected an operation")
            return response
        except (OSError, ValueError, TypeError) as error:
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
        thread, self._pipe_thread = self._pipe_thread, None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            if thread is not None:
                # Closing the child first releases either blocked pipe operation.
                self._requests.put(None)
                thread.join()
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
