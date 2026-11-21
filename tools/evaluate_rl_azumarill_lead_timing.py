"""Compare first damage and first legal charged attack on a common CPU history."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evaluate_rl_azumarill_bench_choices import compare_fork, summarize
from tools.evaluate_rl_azumarill_natural_energy import _reset
from tools.evaluate_rl_azumarill_new_lead_choices import LEADS, build_lead_cases, mixture_scores
from tools.evaluate_rl_azumarill_sensitivity import choose_team_cpu
from tools.evaluate_rl_azumarill_switch_intervention import public_view_sha256
from tools.evaluate_rl_azumarill_switch_rl_150s import MAX_STEPS, _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import ROOT, ruleset_distinction
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID

WINDOWS = (3400012, 3401012)
SEEDS_PER_WINDOW = 3
TIMINGS = ("first_damage", "first_charge")
OBJECTIVES = ("self_ko_win", "verified_non_loss")


def find_timing_forks(worker, case, lead):
    result = _reset(worker, case)
    history, forks = [], {}
    for _ in range(MAX_STEPS):
        view = result["observation"]
        if view is None:
            return forks
        own, opponent = view["own"], view["opponent"]
        if own["active_slot"] != 0 or opponent["active_species"] != lead or len(opponent["revealed"]) != 1:
            return forks
        if view["phase"] == "turn":
            legal = set(view["legal_actions"])
            active = own["team"][0]
            if active["hp"] < active["max_hp"] and {"switch_1", "switch_2"} <= legal:
                forks.setdefault("first_damage", (tuple(history), view))
            if legal & {"charge_0", "charge_1"}:
                forks.setdefault("first_charge", (tuple(history), view))
            if len(forks) == len(TIMINGS):
                return forks
        action = choose_team_cpu(view)
        history.append(action)
        result = worker.step(action)
    raise RuntimeError("Timing prefix exceeded its step budget")


def strict_reversals(mixtures):
    """Find bench pairs whose unique leader differs somewhere on the same grid."""
    leaders = {metric: defaultdict(set) for metric in OBJECTIVES}
    for point in mixtures["pairs"]:
        for metric in OBJECTIVES:
            best = point["best_actions"][metric]
            if len(best) == 1:
                leaders[metric][(point["first"], point["second"])].add(best[0])
    return {metric: [{"first": pair[0], "second": pair[1], "leaders": sorted(actions)}
                     for pair, actions in pairs.items() if len(actions) > 1]
            for metric, pairs in leaders.items()}


def evaluate_timing(worker, cases, forks_by_case, timing):
    reached = [(case, forks[timing]) for case, forks in zip(cases, forks_by_case, strict=True)
               if timing in forks]
    eligible = [(case, fork) for case, fork in reached
                if {"switch_1", "switch_2"} <= set(fork[1]["legal_actions"])]
    report = {"planned": len(cases), "reached": len(reached), "eligible": len(eligible)}
    # A partial bench/seed grid cannot establish a controlled mixture.
    if len(eligible) != len(cases):
        return report
    _, reference = eligible[0][1]
    if any(view != reference for _, (_, view) in eligible):
        raise RuntimeError("Timing fork differs across benches or seeds")
    rows = [compare_fork(worker, case, fork) for case, fork in eligible]
    if any(arm["switch_resolved"] is False for row in rows for arm in row["actions"].values()):
        raise RuntimeError("A requested switch did not resolve")
    groups = defaultdict(list)
    for row in rows:
        groups[row["roster"]].append(row)
    by_roster = {name: {"opponent_bench": group[0]["opponent_bench"], **summarize(group)}
                 for name, group in groups.items()}
    mixtures = mixture_scores(by_roster)
    return {**report, "turn": reference["turn"], "elapsed_ms": reference["elapsed_ms"],
            "sha256": public_view_sha256(reference),
            "cpu_action": rows[0]["cpu_action"], "cpu_move_id": rows[0]["cpu_move_id"],
            "summary": summarize(rows), "by_roster": by_roster,
            "mixtures": mixtures, "strict_reversals": strict_reversals(mixtures), "cases": rows}


def evaluate_lead_timing(*, windows=WINDOWS):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)) or not set(windows) <= set(WINDOWS):
        raise ValueError("Use one or both predeclared seed windows")
    cohorts = {}
    with TemporaryDirectory(prefix="quagsire-lead-timing-") as temp:
        path = Path(temp) / "shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            for lead, name in LEADS.items():
                cases = [case for window in windows for case in build_lead_cases(window, lead, SEEDS_PER_WINDOW)]
                forks = [find_timing_forks(worker, case, name) for case in cases]
                cohorts[name] = {timing: evaluate_timing(worker, cases, forks, timing) for timing in TIMINGS}
    return {"ruleset_id": RULESET_ID, "ruleset_distinction": ruleset_distinction(),
            "starting_shields": [2, 2], "windows": list(windows), "cohorts": cohorts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS)
    args = parser.parse_args()
    print(json.dumps(evaluate_lead_timing(windows=WINDOWS if args.window is None else (args.window,)),
                     sort_keys=True))


if __name__ == "__main__":
    main()
