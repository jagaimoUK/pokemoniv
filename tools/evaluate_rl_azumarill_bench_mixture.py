"""Compare a fixed public action across every hidden Fearow-lead bench."""
from __future__ import annotations

import argparse
from fractions import Fraction
import json

from tools.evaluate_rl_azumarill_bench_choices import (
    EXPECTED_PUBLIC_FORK, OUTCOMES, ROSTERS as NEW_BENCHES, replay_bench_cases, summarize,
)
from tools.evaluate_rl_azumarill_shared_history import ROSTERS as SHARED_ROSTERS, build_history_cases
from tools.evaluate_rl_azumarill_switch_intervention import ROSTERS as PREVIOUS_ROSTERS
from tools.evaluate_rl_azumarill_switch_rl_targeted import ruleset_distinction
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID

WINDOWS = (3200012, 3201012)
SEEDS_PER_WINDOW = 6
OWN_SELECTION = "0,3,5|0"
FEAROW_LEAD = 3
ROSTERS = (
    *NEW_BENCHES,
    *(row for row in PREVIOUS_ROSTERS if row[1:3] == (OWN_SELECTION, FEAROW_LEAD)),
    *((name + "_shared_training", selection, lead, trio)
      for name, selection, lead, trio, _ in SHARED_ROSTERS
      if (selection, lead) == (OWN_SELECTION, FEAROW_LEAD)),
)
# The groups use evidence from the prior studies. Their shares are assumptions,
# and each group divides its mass equally among its fixed members.
DRAW_BENCH = "clodsire_azumarill"
WIN_BENCHES = ("quagsire_wigglytuff", "fearow_clodsire_wigglytuff")
SCENARIOS = {
    "uniform": (10, 20),
    "draw_bench_heavy": (40, 20),
    "win_benches_heavy": (5, 55),
    "draw_bench_absent": (0, 20),
}


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared bench-mixture window")
    return [
        case for roster in ROSTERS
        for case in build_history_cases(window, (roster,), SEEDS_PER_WINDOW)
        if case["handoff"]["own_team"][0]["species"] == "quagsire_shadow"
    ]


def bench_weights(draw_pct, win_pct):
    if not 0 <= draw_pct <= 100 or not 0 <= win_pct <= 100 - draw_pct:
        raise ValueError("Bench-group percentages must be nonnegative and sum to at most 100")
    other_share = Fraction(100 - draw_pct - win_pct, 100 * (len(ROSTERS) - 1 - len(WIN_BENCHES)))
    weights = dict.fromkeys((name for name, *_ in ROSTERS), other_share)
    weights[DRAW_BENCH] = Fraction(draw_pct, 100)
    weights.update({name: Fraction(win_pct, 100 * len(WIN_BENCHES)) for name in WIN_BENCHES})
    return weights


def score_mixture(by_roster, draw_pct, win_pct):
    """Apply the same hidden-bench distribution to every action before ranking."""
    weighted_benches = [(by_roster[name], weight) for name, weight in bench_weights(draw_pct, win_pct).items()
                        if weight]
    actions = by_roster[DRAW_BENCH]["actions"]
    scores = {}
    for action in actions:
        outcomes = {
            outcome: sum(
                weight * Fraction(bench["actions"][action]["outcomes"][outcome], bench["matched_forks"])
                for bench, weight in weighted_benches
            )
            for outcome in OUTCOMES
        }
        scores[action] = {
            **outcomes,
            "verified_non_loss": outcomes["self_ko_win"] + outcomes["simultaneous_ko"],
        }
    objectives = ("self_ko_win", "verified_non_loss")
    best = {metric: max(row[metric] for row in scores.values()) for metric in objectives}
    return {
        "draw_bench_pct": draw_pct,
        "win_benches_pct": win_pct,
        "best_actions": {
            metric: [action for action, row in scores.items() if row[metric] == best[metric]]
            for metric in objectives
        },
        "rates": {action: {metric: float(rate) for metric, rate in row.items()}
                  for action, row in scores.items()},
    }


def evaluate_bench_mixture(*, windows=WINDOWS):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)) or not set(windows) <= set(WINDOWS):
        raise ValueError("Use one or both distinct bench-mixture windows")
    rows = replay_bench_cases({window: window_cases(window) for window in windows})
    seeds = {seed for window in windows for seed in range(window, window + SEEDS_PER_WINDOW)}
    by_roster = {}
    for name, *_ in ROSTERS:
        matched = [row for row in rows if row["roster"] == name]
        if len(matched) != len(seeds) or {row["seed"] for row in matched} != seeds:
            raise RuntimeError("Each bench must be evaluated on the same seed set")
        by_roster[name] = {"opponent_bench": matched[0]["opponent_bench"], **summarize(matched)}
    if any(arm["switch_resolved"] is False for row in rows for arm in row["actions"].values()):
        raise RuntimeError("A requested switch did not resolve")

    return {
        "ruleset_id": RULESET_ID,
        "ruleset_distinction": ruleset_distinction(),
        "starting_shields": [2, 2],
        "windows": list(windows), "common_seeds": sorted(seeds),
        "public_view_sha256": EXPECTED_PUBLIC_FORK,
        "cpu_action": rows[0]["cpu_action"], "cpu_move_id": rows[0]["cpu_move_id"],
        "draw_bench": DRAW_BENCH, "win_benches": list(WIN_BENCHES),
        "summary": summarize(rows),
        "by_roster": by_roster,
        "scenarios": {name: score_mixture(by_roster, *shares) for name, shares in SCENARIOS.items()},
        "sweep": [score_mixture(by_roster, draw_pct, win_pct) for draw_pct in range(0, 101, 10)
                  for win_pct in range(0, 101 - draw_pct, 10)],
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS)
    args = parser.parse_args()
    print(json.dumps(evaluate_bench_mixture(
        windows=WINDOWS if args.window is None else (args.window,)
    ), sort_keys=True))


if __name__ == "__main__":
    main()
