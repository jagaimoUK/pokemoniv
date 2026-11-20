"""Repeat the Azumarill mirror comparison with two different opposing selections."""
from __future__ import annotations

import argparse
import json

from tools import evaluate_rl_azumarill_mirror as previous
from tools.evaluate_rl_quagsire import build_window_cases
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS

WINDOWS = (1800012, 1801012)
# Selected trio, with a fresh back line for Skarmory and Azumarill added to Clodsire's.
ROSTERS = (
    ("skarmory_fearow", None, (2, 3, 4), 4),
    ("clodsire_skarmory", None, (1, 2, 4), 1),
)


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared follow-up seed window")
    return build_window_cases(window, (RULESET_ID,), ROSTERS, 3)


def event_marker(event):
    return {
        "seq": event["seq"], "turn": event["turn"],
        "step_start_ms": event["start_ms"], "step_end_ms": event["end_ms"],
        "remaining_at_step_end_ms": BATTLE_CLOCK_MS - event["end_ms"],
    }


def trace_arm(row, arm):
    """Read the actual target of a resolved foe charge from public event order."""
    result = row[arm]
    own_active = "azumarill"
    opening_switch = None
    first_charge = None
    charge_after_switch = None
    next_kos = []
    for event in result["replay"]["events"]:
        if event["seq"] <= row["after_event_seq"]:
            continue
        side = event["side"]
        if event["kind"] == "switch" and side == "self":
            own_active = event["species"]
            if (arm == "switch" and event["turn"] == row["public_state"]["turn"]
                    and not event["forced"] and event["species"] == row["switch_to"]):
                opening_switch = {**event_marker(event), "species": own_active}
        elif event["kind"] == "charged" and side == "opponent":
            received = {
                **event_marker(event), "attacker": event["species"], "move": event["move_id"],
                "target": own_active, "shielded": event["shielded"],
            }
            if first_charge is None:
                first_charge = received
            if opening_switch is not None and charge_after_switch is None:
                charge_after_switch = received
        elif event["kind"] == "faint" and (not next_kos or event["turn"] == next_kos[0]["turn"]):
            next_kos.append({**event_marker(event), "species": event["species"], "side": side})

    return {
        "outcome": result["outcome"],
        "battle_end_ms": result["elapsed_ms"],
        "remaining_at_battle_end_ms": BATTLE_CLOCK_MS - result["elapsed_ms"],
        "resolved_switch": opening_switch,
        "first_opponent_charge": first_charge,
        "first_opponent_charge_after_switch": charge_after_switch,
        "charge_landed_on_switch_turn": (
            charge_after_switch is not None and charge_after_switch["turn"] == opening_switch["turn"]
        ),
        "next_kos": next_kos,
    }


def same_clock_results(rows):
    """Trace one-sided completions with equal mirror charge time in both branches."""
    traces = []
    for row in rows:
        if "public_state" not in row:
            continue
        ice, switch = row["ice_beam"], row["switch"]
        if ice["outcome"] != "timeout" or switch["reward"] is None:
            continue
        if ice["mirror_charge_ms_after_fork"] != switch["mirror_charge_ms_after_fork"]:
            continue
        traces.append({
            **{key: row[key] for key in ("seed", "roster", "species", "second_move", "opening_move",
                                        "starting_opponent_shields", "switch_to")},
            "fork_remaining_ms": BATTLE_CLOCK_MS - row["public_state"]["elapsed_ms"],
            "mirror_charge_ms": ice["mirror_charge_ms_after_fork"],
            "ice_beam": trace_arm(row, "ice_beam"),
            "switch": trace_arm(row, "switch"),
        })
    return traces


def reference_traces():
    """Replay the prior case group where the eight equal-clock wins occurred."""
    traces = []
    for window in previous.WINDOWS:
        specs = [
            row for row in previous.window_cases(window)
            if row["roster"] == "skarmory" and row["opponent_shields"] == 2
            and row["handoff"]["own_team"][0]["species"] == "quagsire_shadow"
        ]
        traces.extend(same_clock_results(previous.run_mirror_cases(specs)))
    return traces


def main():
    parser = argparse.ArgumentParser(
        description="別の相手編成で、れいとうビームとその場で選べる交代を比較します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定したシード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    data = {window: previous.run_mirror_cases(window_cases(window)) for window in windows}
    pooled = [row for rows in data.values() for row in rows]
    print(json.dumps({
        "labels_ja": {
            "legal_opportunities": "れいとうビームと交代がどちらも選択肢にあった場面",
            "both_completed_rate": "両分岐がKOで決着した割合",
            "mean_reward_delta": "両方が決着した組の平均報酬差（交代 − 発射）",
        },
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "pooled": previous.summarize_conditions(pooled, ROSTERS),
        "new_same_clock_switch_only": same_clock_results(pooled),
        "previous_same_clock_switch_only": reference_traces(),
        "windows": {
            window: {"summary": previous.summarize_conditions(rows, ROSTERS), "cases": rows}
            for window, rows in data.items()
        },
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
