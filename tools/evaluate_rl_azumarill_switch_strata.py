"""Compare both reserve switches by predeclared HP, shield, and clock bands."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json

from tools import evaluate_rl_azumarill_three_way as previous
from tools.evaluate_rl_azumarill_mirror import run_mirror_cases
from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_quagsire import build_window_cases
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS, paired_charge_rewards

WINDOWS = (2000012, 2001012)
ROSTERS = (
    ("skarmory_wigglytuff", None, (2, 4, 5), 4),
    ("clodsire_fearow", None, (1, 2, 3), 1),
    ("primeape_wigglytuff", 1, (1, 2, 5), 1),
)
HP_BANDS = ("<25%", "25–<50%", "50–<75%", "75–100%")
CLOCK_BANDS = ("0–30s", ">30–60s", ">60s")
ARMS = ("switch_skarmory", "switch_quagsire")


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared switch comparison window")
    return build_window_cases(window, (RULESET_ID,), ROSTERS, 3)


def state_bands(row):
    view = row["public_state"]
    remaining = BATTLE_CLOCK_MS - view["elapsed_ms"]
    time_index = (remaining > 30000) + (remaining > 60000)
    return {
        "skarmory_hp": HP_BANDS[row["reserve_hp_bands"]["skarmory"]],
        "quagsire_hp": HP_BANDS[row["reserve_hp_bands"]["quagsire"]],
        "own_shields": row["own_shields"],
        "opponent_shields": view["opponent_shields"],
        "remaining_clock": CLOCK_BANDS[time_index],
    }


def only_winning_switch(row):
    for arm, other in (ARMS, tuple(reversed(ARMS))):
        if row[arm]["outcome"] == "self_ko_win" and row[other]["outcome"] == "timeout":
            return arm
    return None


def summarize(rows):
    pairs = [(row[ARMS[0]], row[ARMS[1]]) for row in rows if "public_state" in row]
    return {
        "planned_histories": len(rows),
        "two_switches_in_choice_set": len(pairs),
        "excluded": dict(Counter(row["excluded"] for row in rows if "excluded" in row)),
        "switches_executed": {arm: sum(pair[i]["action_resolved"] for pair in pairs)
                              for i, arm in enumerate(ARMS)},
        "joint_endings": [
            {ARMS[0]: skarmory, ARMS[1]: quagsire, "count": count}
            for (skarmory, quagsire), count in sorted(Counter(
                (a["outcome"], b["outcome"]) for a, b in pairs
            ).items())
        ],
        "timeouts": {
            ARMS[0]: sum(a["outcome"] == "timeout" for a, _ in pairs),
            ARMS[1]: sum(b["outcome"] == "timeout" for _, b in pairs),
            "both": sum(a["outcome"] == b["outcome"] == "timeout" for a, b in pairs),
        },
        "ko_reward_comparison": paired_charge_rewards(pairs),
    }


def report(rows):
    roster_groups, strata = defaultdict(list), defaultdict(list)
    traces = []
    for row in rows:
        roster_groups[row["roster"]].append(row)
        if "public_state" not in row:
            continue
        bands = state_bands(row)
        strata[tuple(bands.items())].append(row)
        winner = only_winning_switch(row)
        if winner is None:
            continue
        traces.append({
            **{k: row[k] for k in ("roster", "seed", "species", "second_move", "opening_move",
                                  "starting_opponent_shields", "switch_targets", "public_state")},
            "bands": bands,
            "only_winning_switch": winner,
            "arms": {arm: trace_arm(row, arm) for arm in ARMS},
        })
    return {
        "overall": summarize(rows),
        "by_roster": {roster: summarize(group) for roster, group in roster_groups.items()},
        "by_state": [{"bands": dict(bands), "summary": summarize(group)}
                     for bands, group in sorted(strata.items())],
        "one_sided_ko_wins": dict(Counter(trace["only_winning_switch"] for trace in traces)),
        "one_sided_ko_win_traces": traces,
    }


def replay_windows(windows, make_cases):
    pooled = []
    batches = {}
    for window in windows:
        rows = run_mirror_cases(make_cases(window), mode="mirror_three_way")
        pooled.extend(rows)
        batches[window] = report(rows)
    return {"pooled": report(pooled), "windows": batches}


def main():
    parser = argparse.ArgumentParser(
        description="同じ場面からエアームドとヌオーへの交代を試し、HP・シールド・残り時間ごとに比較します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定した未使用シード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "predeclared_bands": {"reserve_hp": HP_BANDS, "each_side_shields": (0, 1, 2),
                              "clock": CLOCK_BANDS},
        "historical": replay_windows(previous.WINDOWS, previous.window_cases),
        "fresh": replay_windows(windows, window_cases),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
