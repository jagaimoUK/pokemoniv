"""Synthetic switch comparison with one change to Quagsire HP or own shields."""
from __future__ import annotations

import argparse
from collections import Counter
import json

from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_switch_strata import ARMS, summarize
from tools.evaluate_rl_quagsire import build_window_cases, run_cases
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS

WINDOWS = (2100012, 2101012)
ROSTERS = (
    ("azumarill_clodsire_skarmory", None, (1, 2, 4), 2),
    ("azumarill_fearow_wigglytuff", None, (2, 3, 5), 2),
)
BUILDS = {"quagsire": "STONE_EDGE", "quagsire_shadow": "MUD_BOMB"}
CONDITIONS = (
    ("base", 20, 0),
    ("hp_40", 40, 0),
    ("hp_60", 60, 0),
    ("hp_85", 85, 0),
    ("shield_1", 20, 1),
    ("shield_2", 20, 2),
)


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared synthetic switch window")
    base_cases = build_window_cases(window, (RULESET_ID,), ROSTERS, 3, own_selection="0,2,4|2")
    cases = []
    for row in base_cases:
        quagsire = row["handoff"]["own_team"][1]
        if row["opponent_shields"] == 0 and quagsire["charged2"] == BUILDS[quagsire["species"]]:
            cases.extend({**row, "condition": condition, "hp_percent": hp, "own_shields": shields}
                         for condition, hp, shields in CONDITIONS)
    return cases


def run_window(window):
    cases = window_cases(window)
    rows = run_cases(cases, worker="rl_azumarill_switch_synthetic.cjs")
    for case, row in zip(cases, rows, strict=True):
        row["condition"] = case["condition"]
        row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
    return rows


def summarize_traces(rows):
    report = summarize(rows)
    report["next_events"] = {}
    for arm in ARMS:
        traces = [row["traces"][arm] for row in rows]
        hits = Counter((hit["move"], hit["target"], hit["shielded"])
                       for trace in traces if (hit := trace["first_opponent_charge"]))
        report["next_events"][arm] = {
            "first_opponent_charge": [
                {"move": move, "target": target, "shielded": shielded, "count": count}
                for (move, target, shielded), count in sorted(hits.items())
            ],
            "no_opponent_charge": len(traces) - sum(hits.values()),
            "first_ko_in_same_step_as_first_charge": sum(
                any(faint["step_end_ms"] == hit["step_end_ms"]
                    and faint["step_start_ms"] == hit["step_start_ms"] for faint in trace["next_kos"])
                for trace in traces if (hit := trace["first_opponent_charge"])
            ),
            "next_ko": dict(Counter(
                "+".join(f'{event["side"]}:{event["species"]}' for event in trace["next_kos"])
                or "no_ko" for trace in traces
            )),
        }
    return report


def summarize_conditions(rows):
    summaries = {}
    for condition, _, _ in CONDITIONS:
        selected = [row for row in rows if row["condition"] == condition]
        summaries[condition] = {
            **summarize_traces(selected),
            "by_roster": {name: summarize_traces([row for row in selected if row["roster"] == name])
                          for name, *_ in ROSTERS},
        }
    return summaries


def main():
    parser = argparse.ArgumentParser(
        description="ヌオーのHPまたは自軍の残りシールドだけを変え、同じ合成場面から2つの交代を試します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定した未使用シード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    batches = {window: run_window(window) for window in windows}
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "study": "synthetic_start_only",
        "natural_reference": "https://github.com/jagaimoUK/pokemoniv/pull/123#issuecomment-7028195235",
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "pooled_by_condition": summarize_conditions([row for rows in batches.values() for row in rows]),
        "windows": {
            window: {"summary": summarize_conditions(rows), "cases": rows}
            for window, rows in batches.items()
        },
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
