"""Isolate remaining clock (90s, 120s, 150s) from a fixed synthetic mirror start state."""
from __future__ import annotations

import argparse
from collections import Counter
import json

from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_switch_strata import ARMS
from tools.evaluate_rl_azumarill_switch_synthetic import summarize_traces
from tools.evaluate_rl_quagsire import build_window_cases, run_cases
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS

WINDOWS = (2200012, 2201012)
ROSTERS = (
    ("azumarill_clodsire_skarmory", None, (1, 2, 4), 2),
    ("azumarill_fearow_wigglytuff", None, (2, 3, 5), 2),
)
BUILDS = {"quagsire": "STONE_EDGE", "quagsire_shadow": "MUD_BOMB"}
HP_PERCENT = 20
OWN_SHIELDS = 0
CONDITIONS = (
    ("remaining_90s", 90),
    ("remaining_120s", 120),
    ("remaining_150s", 150),
)


def window_cases(window):
    """Build matched triples differing only in remaining_seconds for one predeclared window."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared synthetic clock window")
    base_cases = build_window_cases(window, (RULESET_ID,), ROSTERS, 3, own_selection="0,2,4|2")
    cases = []
    for row in base_cases:
        quagsire = row["handoff"]["own_team"][1]
        if row["opponent_shields"] == 0 and quagsire["charged2"] == BUILDS[quagsire["species"]]:
            cases.extend(
                {
                    **row,
                    "condition": condition,
                    "hp_percent": HP_PERCENT,
                    "own_shields": OWN_SHIELDS,
                    "remaining_seconds": remaining_seconds,
                }
                for condition, remaining_seconds in CONDITIONS
            )
    return cases


def run_window(window):
    """Replay all cases for a predeclared window and attach public event traces."""
    cases = window_cases(window)
    rows = run_cases(cases, worker="rl_azumarill_switch_synthetic.cjs")
    for case, row in zip(cases, rows, strict=True):
        row["condition"] = case["condition"]
        row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
    return rows


def summarize_clock_group(rows):
    """Separate timeout censorship from joint KO-decided win/loss reward deltas."""
    report = summarize_traces(rows)
    report["outcome_breakdown"] = {
        "both_ko_decided": sum(
            row[ARMS[0]]["reward"] is not None and row[ARMS[1]]["reward"] is not None
            for row in rows
        ),
        "one_sided_ko_decided": sum(
            (row[ARMS[0]]["reward"] is not None) != (row[ARMS[1]]["reward"] is not None)
            for row in rows
        ),
        "both_timeout": sum(
            row[ARMS[0]]["outcome"] == row[ARMS[1]]["outcome"] == "timeout"
            for row in rows
        ),
        "by_arm_outcomes": {
            arm: dict(Counter(row[arm]["outcome"] for row in rows))
            for arm in ARMS
        },
    }
    return report


def summarize_conditions(rows):
    """Group summary metrics by remaining-clock condition, roster, and Quagsire build."""
    summaries = {}
    for condition, remaining_seconds in CONDITIONS:
        selected = [row for row in rows if row["condition"] == condition]
        summaries[condition] = {
            "remaining_seconds": remaining_seconds,
            "fork_elapsed_ms": BATTLE_CLOCK_MS - remaining_seconds * 1000,
            **summarize_clock_group(selected),
            "by_roster": {
                name: summarize_clock_group([row for row in selected if row["roster"] == name])
                for name, *_ in ROSTERS
            },
            "by_build": {
                f"{species}/{move}": summarize_clock_group([
                    row for row in selected
                    if row["species"] == species and row["second_move"] == move
                ])
                for species, move in BUILDS.items()
            },
        }
    return summaries


def main():
    parser = argparse.ArgumentParser(
        description="ヌオーHP20%・双方シールド0枚の同じ合成開始状態から残り時間だけを変え、2つの交代を比較します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定した未使用シード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    batches = {window: run_window(window) for window in windows}
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "study": "synthetic_remaining_clock_only",
        "fixed_start_state": {
            "lead": "azumarill (hp=120, energy=55) vs azumarill (hp=120, energy=55)",
            "quagsire_hp_percent": HP_PERCENT,
            "own_shields": OWN_SHIELDS,
            "opponent_shields": 0,
            "rosters": [name for name, *_ in ROSTERS],
            "builds": BUILDS,
        },
        "previous_synthetic_reference": "https://github.com/jagaimoUK/pokemoniv/pull/123#issuecomment-7028436054",
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "pooled_by_condition": summarize_conditions([row for rows in batches.values() for row in rows]),
        "windows": {
            window: {"summary": summarize_conditions(rows), "cases": rows}
            for window, rows in batches.items()
        },
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
