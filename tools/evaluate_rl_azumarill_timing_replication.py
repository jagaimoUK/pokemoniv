"""Replicate objective-dependent choices on fixed Skarmory benches."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evaluate_rl_azumarill_lead_timing import TIMINGS, evaluate_timing, find_timing_forks
from tools.evaluate_rl_azumarill_new_lead_choices import build_lead_cases
from tools.evaluate_rl_azumarill_switch_intervention import public_view_sha256
from tools.evaluate_rl_azumarill_switch_rl_150s import _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import ROOT, ruleset_distinction
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID

WINDOWS = (3500012, 3501012)
SEEDS_PER_WINDOW = 6
BENCHES = ("quagsire_azumarill", "azumarill_fearow", "fearow_wigglytuff")
EXPECTED_FORKS = {
    "first_damage": "8cf5b3deb5a0f4f6c3be25c60512a3e66290c165723cc35431219a8b1af82333",
    "first_charge": "e34bdf79501a952d2d82def85466f05f20d2c94083398d217e1812257cc5465c",
}


def objective_splits(mixtures):
    """Select ratios where no action is optimal under both objectives."""
    return [
        point for point in mixtures["pairs"]
        if set(point["best_actions"]["self_ko_win"]).isdisjoint(point["best_actions"]["verified_non_loss"])
    ]


def evaluate_replication():
    cases = [case for window in WINDOWS for case in build_lead_cases(window, 4, SEEDS_PER_WINDOW)
             if case["roster"] in BENCHES]
    expected_seeds = {seed for window in WINDOWS for seed in range(window, window + SEEDS_PER_WINDOW)}
    for bench in BENCHES:
        seeds = [case["seed"] for case in cases if case["roster"] == bench]
        if len(seeds) != len(expected_seeds) or set(seeds) != expected_seeds:
            raise RuntimeError("Each fixed bench must use the same new seed set")
    with TemporaryDirectory(prefix="quagsire-timing-replication-") as temp:
        path = Path(temp) / "shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            forks = [find_timing_forks(worker, case, "skarmory") for case in cases]
            for timing in TIMINGS:
                # The full public view is checked within evaluate_timing.
                if any(timing not in pair or public_view_sha256(pair[timing][1]) != EXPECTED_FORKS[timing]
                       for pair in forks):
                    raise RuntimeError(f"The prior public fork did not reproduce for {timing}")
            timings = {timing: evaluate_timing(worker, cases, forks, timing) for timing in TIMINGS}
    for result in timings.values():
        result["objective_splits"] = objective_splits(result["mixtures"])
    return {"ruleset_id": RULESET_ID, "ruleset_distinction": ruleset_distinction(),
            "starting_shields": [2, 2], "windows": list(WINDOWS), "common_seeds": sorted(expected_seeds),
            "timings": timings}


if __name__ == "__main__":
    print(json.dumps(evaluate_replication(), sort_keys=True))
