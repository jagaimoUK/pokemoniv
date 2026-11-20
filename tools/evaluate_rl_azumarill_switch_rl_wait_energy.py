"""Compare evaluation-only wait suppression and public energy buckets at 150s."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pvpoke_rl_mc_generalized import bounded_integer
from tools.evaluate_rl_azumarill_rl_coverage import CpuFallbackMonteCarloPolicy
from tools.evaluate_rl_azumarill_switch_150s import BUILDS, CONDITIONS, REMAINING_SECONDS
from tools.evaluate_rl_azumarill_switch_rl_150s import _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import (
    ROOT, TRAIN_EPISODES, _compare_case, build_targeted_window_cases,
    ruleset_distinction, summarize_group, train_targeted_switch_policy,
)
from tools.evaluate_rl_azumarill_switch_strata import ARMS
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS

WINDOWS = (2700012, 2701012)


class NoVoluntaryWaitPolicy(CpuFallbackMonteCarloPolicy):
    """Exclude wait at evaluation whenever fast or charged attacks are legal."""

    suppress_voluntary_wait = True


class EnergyBandPolicy(CpuFallbackMonteCarloPolicy):
    """Augment the v2 tactical key with the active ally's public energy band."""

    MODEL_VERSION = "rl-public-mc-generalized-v2-energy-band-10"

    def encode_state(self, view):
        kind, key, legal = super().encode_state(view)
        if kind == "tactics":
            own = view["own"]
            energy = bounded_integer(
                own["team"][own["active_slot"]]["energy_points"], 0, 100, "active energy",
            )
            key = hashlib.sha256(f"{self.MODEL_VERSION}:{key}:{energy // 10}".encode()).hexdigest()
        return kind, key, legal


class EnergyBandNoVoluntaryWaitPolicy(EnergyBandPolicy):
    suppress_voluntary_wait = True


CONTINUATION_SPECS = {
    "cpu": (None, None),
    "rl_v2": ("v2", CpuFallbackMonteCarloPolicy),
    "rl_v2_no_wait": ("v2", NoVoluntaryWaitPolicy),
    "rl_energy": ("energy", EnergyBandPolicy),
    "rl_energy_no_wait": ("energy", EnergyBandNoVoluntaryWaitPolicy),
}


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared 150s wait/energy window")
    return build_targeted_window_cases(window)


def summarize_matched(matches):
    """Measure timeout changes and KO outcome recall on the same CPU-decisive arms."""
    metrics = {
        "cpu_ko_arms": 0,
        "cpu_ko_arms_with_candidate_ko": 0,
        "cpu_ko_outcomes_reproduced": 0,
        "timeout_to_ko": 0,
        "ko_to_timeout": 0,
    }
    for candidate, cpu in matches:
        for arm in ARMS:
            result, reference = candidate[arm], cpu[arm]
            if reference["reward"] is not None:
                metrics["cpu_ko_arms"] += 1
                metrics["cpu_ko_arms_with_candidate_ko"] += result["reward"] is not None
                metrics["cpu_ko_outcomes_reproduced"] += result["outcome"] == reference["outcome"]
                metrics["ko_to_timeout"] += result["outcome"] == "timeout"
            elif reference["outcome"] == "timeout":
                metrics["timeout_to_ko"] += result["reward"] is not None
    denominator = metrics["cpu_ko_arms"]
    return {
        **metrics,
        "cpu_ko_outcome_recall": metrics["cpu_ko_outcomes_reproduced"] / denominator if denominator else None,
    }


def _summarize_slice(matches):
    return {
        **summarize_group([candidate for candidate, _ in matches]),
        "matched_cpu": summarize_matched(matches),
    }


def evaluate_rl_switch_wait_energy(*, windows=WINDOWS, train_episodes=TRAIN_EPISODES):
    """Use the same training schedule for both representations and freeze both tables."""
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)):
        raise ValueError("Use one or both distinct wait/energy windows")
    cases = [case for window in windows for case in window_cases(window)]
    snapshots, training = {}, {}
    with TemporaryDirectory(prefix="quagsire-rl-wait-energy-") as temp:
        gm_path = Path(temp) / "strategy_gamemaster_shadow.json"
        gm_path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", gm_path) as worker:
            for regime, policy_class in (("v2", CpuFallbackMonteCarloPolicy), ("energy", EnergyBandPolicy)):
                snapshots[regime], training[regime] = train_targeted_switch_policy(
                    worker, episodes=train_episodes, policy_class=policy_class,
                )
            before = json.dumps(snapshots, sort_keys=True)
            rows = {
                name: [
                    _compare_case(worker, case, name, snapshots, continuation_specs=CONTINUATION_SPECS)
                    for case in cases
                ]
                for name in CONTINUATION_SPECS
            }
    if before != json.dumps(snapshots, sort_keys=True):
        raise RuntimeError("Frozen RL snapshots mutated after evaluation")

    summary = {}
    for name, policy_rows in rows.items():
        matched = list(zip(policy_rows, rows["cpu"], strict=True))
        summary[name] = {
            "overall": _summarize_slice(matched),
            "by_condition": {
                condition: _summarize_slice([pair for pair in matched if pair[0]["condition"] == condition])
                for condition, _, _ in CONDITIONS
            },
            "hp_60_by_species": {
                species: _summarize_slice([
                    pair for pair in matched
                    if pair[0]["condition"] == "hp_60" and pair[0]["species"] == species
                ])
                for species in BUILDS
            },
        }
    return {
        "study": "synthetic_150s_targeted_rl_wait_energy",
        "ruleset_id": RULESET_ID,
        "ruleset_distinction": ruleset_distinction(),
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "remaining_seconds": REMAINING_SECONDS,
        "windows": list(windows),
        "training": training,
        "policy_snapshots_unchanged": True,
        "summary": summary,
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both held-out windows")
    parser.add_argument("--train-episodes", type=int, default=TRAIN_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.train_episodes <= 120:
        parser.error("Require 0 <= --train-episodes <= 120")
    result = evaluate_rl_switch_wait_energy(
        windows=WINDOWS if args.window is None else (args.window,),
        train_episodes=args.train_episodes,
    )
    result.pop("cases")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
