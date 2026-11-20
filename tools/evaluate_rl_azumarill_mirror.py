"""Compare Ice Beam and switching at the first Azumarill mirror turn offering both."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from statistics import mean

from tools.evaluate_rl_quagsire_timeouts import ROSTERS, RULESET_ID
from tools.evaluate_rl_quagsire import build_window_cases, run_cases
from tools.rl_charge_metrics import BATTLE_CLOCK_MS, charge_stratum, paired_charge_rewards

WINDOWS = (1700012, 1701012)


def window_cases(window):
    """The two fixed opponent rosters each receive three fresh seeds per window."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared Azumarill mirror window")
    return build_window_cases(window, (RULESET_ID,), ROSTERS, 3)


def run_window(window):
    return run_mirror_cases(window_cases(window))


def run_mirror_cases(battle_specs):
    cases = []
    for row in run_cases(battle_specs, mode="mirror"):
        forks = row.pop("mirror_forks")
        cases.extend({**row, **fork} for fork in forks)
    return cases


def summarize(rows):
    pairs = [(row["ice_beam"], row["switch"]) for row in rows if "public_state" in row]
    clock = [(ice["mirror_charge_ms_after_fork"], switch["mirror_charge_ms_after_fork"])
             for ice, switch in pairs]
    return {
        "planned_histories": len(rows),
        "legal_opportunities": len(pairs),
        "excluded": dict(Counter(row["excluded"] for row in rows if "excluded" in row)),
        "switch_destinations": dict(Counter(
            row["switch_to"] for row in rows if "public_state" in row
        )),
        "action_resolved": {
            "ice_beam": sum(ice["action_resolved"] for ice, _ in pairs),
            "switch": sum(switch["action_resolved"] for _, switch in pairs),
        },
        "mirror_charge_clock_ms": {
            "ice_beam_mean": mean(ice for ice, _ in clock) if clock else None,
            "switch_mean": mean(switch for _, switch in clock) if clock else None,
            "mean_paired_difference": mean(switch - ice for ice, switch in clock) if clock else None,
            "reduced": sum(switch < ice for ice, switch in clock),
            "unchanged": sum(switch == ice for ice, switch in clock),
            "increased": sum(switch > ice for ice, switch in clock),
        },
        "completion": {
            "ice_beam_only": sum(ice["reward"] is not None and switch["reward"] is None
                                 for ice, switch in pairs),
            "switch_only": sum(switch["reward"] is not None and ice["reward"] is None
                               for ice, switch in pairs),
            "neither": sum(ice["reward"] is None and switch["reward"] is None
                           for ice, switch in pairs),
        },
        **paired_charge_rewards(pairs),
    }


def summarize_conditions(rows, rosters=ROSTERS):
    return {
        "overall": summarize(rows),
        "by_roster": {
            name: summarize([row for row in rows if row["roster"] == name])
            for name, *_ in rosters
        },
        "by_switch_destination": {
            species: summarize([row for row in rows if row.get("switch_to") == species])
            for species in sorted({row["switch_to"] for row in rows if "switch_to" in row})
        },
        "by_fork_state": {
            key: summarize([row for row in rows if "public_state" in row
                            and charge_stratum(row["public_state"]) == key])
            for key in sorted({charge_stratum(row["public_state"]) for row in rows
                               if "public_state" in row})
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="マリルリ同士で、れいとうビームと交代がどちらも選択肢にある最初の場面を比較します。"
    )
    parser.add_argument("--window", type=int, choices=WINDOWS, help="指定したシード窓だけを実行")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    results = {window: run_window(window) for window in windows}
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "difference_direction": "switch minus Ice Beam",
        "pooled": summarize_conditions([row for batch in results.values() for row in batch]),
        "windows": {window: {"summary": summarize_conditions(rows), "cases": rows}
                    for window, rows in results.items()},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
