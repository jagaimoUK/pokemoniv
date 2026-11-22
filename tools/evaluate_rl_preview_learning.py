"""Fit one legal synthetic 6→3 selection under fixed public tactics."""
from __future__ import annotations

import argparse
import json

from tools.diagnose_rl_fixture import OWN_SELECTIONS
from tools.evaluate_rl_mc import BASELINE_SELECTION, evaluate_one, heldout_scenarios

HOLDOUT_OFFSET = 300000
MIN_PAIRED_COMPLETIONS = 2


def compare_results(candidate, baseline):
    pairs = [(a["reward"], b["reward"]) for a, b in zip(candidate, baseline, strict=True)
             if a["status"] == b["status"] == "complete"]
    return {
        "candidate_completed": sum(row["status"] == "complete" for row in candidate),
        "baseline_completed": sum(row["status"] == "complete" for row in baseline),
        "both_completed": len(pairs),
        "better": sum(a > b for a, b in pairs),
        "equal": sum(a == b for a, b in pairs),
        "worse": sum(a < b for a, b in pairs),
        "mean_reward_difference": sum(a - b for a, b in pairs) / len(pairs) if pairs else None,
    }


def compare_preview_learning(*, seed=12, train=8, evaluate=8):
    if (type(train) is not int or not 2 <= train <= 12 or
            type(evaluate) is not int or not 1 <= evaluate <= 12 or
            type(seed) is not int or not 0 <= seed <= 2**32 - HOLDOUT_OFFSET - 12):
        raise ValueError("Use 2..12 training cases and 1..12 held-out cases")
    training = heldout_scenarios(count=train, seed=seed)
    heldout = heldout_scenarios(count=evaluate, seed=seed + HOLDOUT_OFFSET)

    def results(scenarios, selection):
        return [evaluate_one(None, "fixed", scenario, fixed_selection=selection)
                for scenario in scenarios]

    baseline = results(training, BASELINE_SELECTION)
    candidates = {selection: compare_results(results(training, selection), baseline)
                  for selection in OWN_SELECTIONS if selection != BASELINE_SELECTION}
    eligible = [selection for selection, score in candidates.items()
                if score["candidate_completed"] >= score["baseline_completed"]
                and score["both_completed"] >= MIN_PAIRED_COMPLETIONS
                and score["mean_reward_difference"] > 0]
    selected = max(eligible, default=BASELINE_SELECTION, key=lambda selection: (
        candidates[selection]["mean_reward_difference"], candidates[selection]["both_completed"]))

    baseline_test = results(heldout, BASELINE_SELECTION)
    selected_test = baseline_test if selected == BASELINE_SELECTION else results(heldout, selected)
    return {
        "phase": "synthetic_preview_learning_with_fixed_tactics",
        "baseline_selection": BASELINE_SELECTION,
        "learned_selection": selected,
        "training_cases_per_selection": train,
        "training_comparisons": candidates,
        "heldout_cases_per_selection": evaluate,
        "heldout_comparison": compare_results(selected_test, baseline_test),
        "heldout_seed_offset": HOLDOUT_OFFSET,
        "scope": "one public preview, predeclared subset of legal actions, censored timeouts",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=12)
    parser.add_argument("--train", type=int, default=8)
    parser.add_argument("--evaluate", type=int, default=8)
    args = parser.parse_args()
    try:
        result = compare_preview_learning(seed=args.seed, train=args.train, evaluate=args.evaluate)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
