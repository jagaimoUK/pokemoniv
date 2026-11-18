"""Bounded exploratory RL step benchmark with *synthetic* PvPoke fixtures.

Run:
  PYTHONPATH=.:tests python tools/benchmark_rl_step.py --episodes 2 --windows 4

Measures wall clock for N public decision windows:
- replay: start a new native Node worker and replay history at each decision.
- stateful: keep one native Node process and battle object between decisions.

These are NOT proven gameplay-equivalent policies; the observed replay also
requires explicit shield decisions. Do not infer a speedup for 3v3/6v3 or
full RL training. Native per-episode result parity is tested separately.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from pvpoke_observed_observation import Context, digest
from pvpoke_observed_search import native_replay
from pvpoke_rl_replay_env import ReplayStepEnv
from pvpoke_rl_step_client import NativeStepClient
from test_observed_native_runner import NativeObservedMultiTurnTests


def measure(episodes=2, windows=4):
    if type(episodes) is not int or not 1 <= episodes <= 5:
        raise ValueError("episodes must be 1..5")
    if type(windows) is not int or not 1 <= windows <= 6:
        raise ValueError("windows must be 1..6")
    fixture = NativeObservedMultiTurnTests()
    fixture.setUp()
    try:
        prepared = fixture.request(
            energy=0, enemy_energy=0, shields=(0, 0),
            opponent_attack_rule="standard", enemy_shield_rule="standard")
        context = Context(
            digest(prepared["self"]),
            tuple(x["energy_cost"] for x in prepared["policy"]["own_charged_moves"]),
            0, tuple(prepared["shields"]), 8, prepared["opponent"]["species"])
        replay_rss = []
        replay_calls = []

        def replay_native(payload):
            receipt, rss = native_replay(fixture.sandbox, payload, timeout=20)
            if rss:
                replay_rss.append(rss)
            if receipt.get("status") == "unknown" and "schema" not in receipt:
                return {"schema": "observed-native-v2", **receipt}
            return receipt

        def replay_episode():
            env = ReplayStepEnv(prepared, context, replay_native, horizon=8, seed=0)
            start_calls = len(replay_calls)
            view, _ = env.reset()
            accepted = 0
            extra_shields = 0
            attempts = 0
            while accepted < windows and attempts < 16:
                attempts += 1
                if view["phase"] == "charge_announced":
                    action = "shield_no"
                    extra_shields += 1
                else:
                    action = "fast" if "fast" in view["legal_actions"] else "wait_one_window"
                    accepted += 1
                view, _, done, truncated, info = env.step(action)
                if done or truncated:
                    break
            if attempts >= 16:
                raise RuntimeError("Replay did not finish the bounded decision loop")
            replay_calls.append(attempts + 1)  # reset + submitted actions
            return accepted, extra_shields

        def stateful_episode(client):
            view, _ = client.reset(prepared, horizon=8)
            accepted = 0
            while accepted < windows:
                action = "fast" if "fast" in view["legal_actions"] else "wait"
                view, _, done, truncated, info = client.step(action)
                accepted += 1
                if done or truncated:
                    break
            return accepted

        replay_times = []
        stateful_times = []
        extras = []
        with NativeStepClient(fixture.client.source, timeout=20) as client:
            # One warmup cycle per mode, followed by bounded measured episodes.
            for trial in range(episodes + 1):
                start = perf_counter()
                replay_windows, shield_prompts = replay_episode()
                elapsed_replay = (perf_counter() - start) * 1000

                start = perf_counter()
                stateful_windows = stateful_episode(client)
                elapsed_stateful = (perf_counter() - start) * 1000
                if trial > 0:
                    replay_times.append(elapsed_replay)
                    stateful_times.append(elapsed_stateful)
                    extras.append(shield_prompts)
            stateful_peak = client.stats()["peak_rss_kib"]
        return {
            "label": "exploratory_fixed_fixture_not_equivalent_full_battles",
            "episodes_measured": episodes,
            "window_budget_per_episode": windows,
            "replay_median_ms": round(statistics.median(replay_times), 3),
            "stateful_median_ms": round(statistics.median(stateful_times), 3),
            "replay_worker_invocations_per_episode":
                replay_calls[-episodes:],
            "extra_replay_shield_prompts_per_episode": extras,
            "replay_native_peak_rss_kib_observed": max(replay_rss, default=None),
            "stateful_worker_peak_rss_kib": stateful_peak,
            "results_equivalence": "not_established",
            "other_formats": "not_measured",
        }
    finally:
        fixture.doCleanups()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--windows", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(measure(args.episodes, args.windows),
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
