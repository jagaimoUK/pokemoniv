"""Single-factor Quagsire HP or own-shield changes from the 150s remaining-clock synthetic state."""
from __future__ import annotations

import argparse
import json

from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_switch_clock import summarize_clock_group
from tools.evaluate_rl_azumarill_switch_strata import ARMS
from tools.evaluate_rl_azumarill_switch_synthetic import BUILDS, CONDITIONS, ROSTERS
from tools.evaluate_rl_quagsire import build_window_cases, run_cases
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS

WINDOWS = (2300012, 2301012)
REMAINING_SECONDS = 150
WORKER = "rl_azumarill_switch_synthetic.cjs"
WORKER_MODE = "clock_150s"


def window_cases(window):
    """Build single-factor HP/shield batches at fixed 150s remaining clock."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared 150s synthetic switch window")
    base_cases = build_window_cases(window, (RULESET_ID,), ROSTERS, 3, own_selection="0,2,4|2")
    cases = []
    for row in base_cases:
        quagsire = row["handoff"]["own_team"][1]
        if row["opponent_shields"] == 0 and quagsire["charged2"] == BUILDS[quagsire["species"]]:
            cases.extend(
                {
                    **row,
                    "condition": condition,
                    "hp_percent": hp_percent,
                    "own_shields": own_shields,
                    "remaining_seconds": REMAINING_SECONDS,
                }
                for condition, hp_percent, own_shields in CONDITIONS
            )
    return cases


def run_window(window):
    """Replay all fixed-150s cases for one window and attach public event traces."""
    cases = window_cases(window)
    rows = run_cases(cases, mode=WORKER_MODE, worker=WORKER)
    for case, row in zip(cases, rows, strict=True):
        row["condition"] = case["condition"]
        row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
    return rows


def summarize_conditions(rows):
    """Group summary metrics by HP/shield condition, roster, build, and roster+build."""
    summaries = {}
    for condition, hp_percent, own_shields in CONDITIONS:
        selected = [row for row in rows if row["condition"] == condition]
        summaries[condition] = {
            "hp_percent": hp_percent,
            "own_shields": own_shields,
            "remaining_seconds": REMAINING_SECONDS,
            "fork_elapsed_ms": BATTLE_CLOCK_MS - REMAINING_SECONDS * 1000,
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
            "by_roster_and_build": {
                f"{name}:{species}/{move}": summarize_clock_group([
                    row for row in selected
                    if row["roster"] == name and row["species"] == species and row["second_move"] == move
                ])
                for name, *_ in ROSTERS
                for species, move in BUILDS.items()
            },
        }
    return summaries


def main():
    parser = argparse.ArgumentParser(
        description="残り時間150秒固定の同じ合成開始状態から、ヌオーHPまたは自軍残りシールドだけを1要因ずつ変えて比較します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定した未使用シード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    batches = {window: run_window(window) for window in windows}
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "study": "synthetic_150s_hp_or_shield_only",
        "fixed_start_state": {
            "lead": "azumarill (hp=120, energy=55) vs azumarill (hp=120, energy=55)",
            "remaining_seconds": REMAINING_SECONDS,
            "fork_elapsed_ms": BATTLE_CLOCK_MS - REMAINING_SECONDS * 1000,
            "opponent_shields": 0,
            "rosters": [name for name, *_ in ROSTERS],
            "builds": BUILDS,
        },
        "previous_90s_reference": "https://github.com/jagaimoUK/pokemoniv/pull/123#issuecomment-7028436054",
        "previous_clock_reference": "https://github.com/jagaimoUK/pokemoniv/pull/123#issuecomment-7028796518",
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "pooled_by_condition": summarize_conditions([row for rows in batches.values() for row in rows]),
        "windows": {
            window: {"summary": summarize_conditions(rows), "cases": rows}
            for window, rows in batches.items()
        },
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
