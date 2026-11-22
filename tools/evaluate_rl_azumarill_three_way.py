"""Compare three available actions on the same Azumarill mirror turn."""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
import json
from statistics import mean

from tools.evaluate_rl_azumarill_mirror import run_mirror_cases
from tools.evaluate_rl_azumarill_mirror_followup import ROSTERS as FOLLOWUP_ROSTERS, trace_arm
from tools.evaluate_rl_quagsire import ROSTERS as ORIGINAL_ROSTERS, build_window_cases
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS, paired_charge_rewards

WINDOWS = (1900012, 1901012)
ROSTERS = (*FOLLOWUP_ROSTERS, next(row for row in ORIGINAL_ROSTERS if row[0] == "skarmory"))
ACTIONS = ("ice_beam", "switch_skarmory", "switch_quagsire")
LABELS = {"ice_beam": "れいとうビームを撃つ", "switch_skarmory": "エアームドに交代",
          "switch_quagsire": "ヌオーに交代"}


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared three-way comparison window")
    return build_window_cases(window, (RULESET_ID,), ROSTERS, 3)


def with_traces(rows):
    return [
        {**row, "traces": {action: trace_arm(row, action) for action in ACTIONS}}
        if "public_state" in row else row for row in rows
    ]


def summarize(rows):
    compared = [row for row in rows if "public_state" in row]
    all_complete = [row for row in compared
                    if all(row[action]["reward"] is not None for action in ACTIONS)]
    actions = {}
    for action in ACTIONS:
        results = [row[action] for row in compared]
        traces = [row["traces"][action] for row in compared]
        completed = sum(result["reward"] is not None for result in results)
        actions[action] = {
            "resolved": sum(result["action_resolved"] for result in results),
            "ko_completed": completed,
            "ko_completion_rate": completed / len(compared) if compared else None,
            "outcomes": dict(Counter(result["outcome"] for result in results)),
            "mean_mirror_charge_ms": mean(r["mirror_charge_ms_after_fork"] for r in results)
            if results else None,
            "next_opponent_charge_targets": dict(Counter(
                trace["first_opponent_charge"]["target"] if trace["first_opponent_charge"]
                else "no_opponent_charge" for trace in traces
            )),
            "next_ko": dict(Counter(
                "+".join(f'{faint["side"]}:{faint["species"]}' for faint in trace["next_kos"])
                or "no_ko" for trace in traces
            )),
        }

    pairs = {}
    for before, after in combinations(ACTIONS, 2):
        paired = [(row[before], row[after]) for row in compared]
        pairs[f"{after}_minus_{before}"] = {
            **paired_charge_rewards(paired),
            "only_reference_completed": sum(a["reward"] is not None and b["reward"] is None
                                            for a, b in paired),
            "only_alternative_completed": sum(a["reward"] is None and b["reward"] is not None
                                              for a, b in paired),
        }

    return {
        "planned_histories": len(rows),
        "three_choices_available": len(compared),
        "excluded": dict(Counter(row["excluded"] for row in rows if "excluded" in row)),
        "all_three_ko_completed": len(all_complete),
        "all_three_ko_completion_rate": len(all_complete) / len(compared) if compared else None,
        "ko_completion_patterns": dict(Counter(
            "+".join(action for action in ACTIONS if row[action]["reward"] is not None) or "none"
            for row in compared
        )),
        "actions": actions,
        "paired_outcomes": pairs,
    }


def summarize_conditions(rows):
    return {
        "overall": summarize(rows),
        "by_roster": {name: summarize([row for row in rows if row["roster"] == name])
                      for name, *_ in ROSTERS},
    }


def main():
    parser = argparse.ArgumentParser(
        description="れいとうビーム・エアームドへの交代・ヌオーへの交代がそろう場面を比較します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定したシード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    batches = {
        window: with_traces(run_mirror_cases(window_cases(window), mode="mirror_three_way"))
        for window in windows
    }
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "labels_ja": LABELS,
        "pooled": summarize_conditions([row for rows in batches.values() for row in rows]),
        "windows": {
            window: {"summary": summarize_conditions(rows), "cases": rows}
            for window, rows in batches.items()
        },
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
