"""Trace Quagsire timeouts and rerun the charge fork with opponent shield policies."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from statistics import median

from tools.evaluate_rl_quagsire import (
    ROSTERS as PRIOR_ROSTERS, RULESET_IDS, WINDOWS as PRIOR_WINDOWS, build_window_cases,
    run_cases, summarize_forks, window_cases,
)
from tools.rl_charge_metrics import BATTLE_CLOCK_MS, paired_charge_rewards

WINDOWS = (1600012, 1601012)
RULESET_ID = RULESET_IDS[0]
ROSTERS = tuple(row for row in PRIOR_ROSTERS if row[0] in ("clodsire", "skarmory"))
POLICIES = ("cpu_always", "save_high_hp")
BRANCHES = ("aqua_tail", "second_charge")


def fresh_cases(window):
    """Three seeds per roster in each fixed six-seed window."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared timeout study window")
    return build_window_cases(window, (RULESET_ID,), ROSTERS, 3)


def historical_cases(window):
    """Replay the two preceding opponent rosters under their original CPU policy."""
    return [row for row in window_cases(window)
            if row["roster"] in ("clodsire", "skarmory")
            and row["handoff"]["ruleset_id"] == RULESET_ID]


def azumarill_mirror(replay, own_lead, opponent_lead):
    """Reconstruct the active matchup from the public leads and resolved switches."""
    active = {"self": own_lead, "opponent": opponent_lead}
    first_entry_ms = None
    ice_beams = 0
    for event in replay["events"]:
        if event["kind"] == "switch":
            active[event["side"]] = event["species"]
            if first_entry_ms is None and set(active.values()) == {"azumarill"}:
                first_entry_ms = event["end_ms"]
        elif (event["kind"] == "charged" and event["move_id"] == "ICE_BEAM"
              and set(active.values()) == {"azumarill"}):
            ice_beams += 1
    return first_entry_ms, ice_beams


def replay_summary(rows, policy):
    """Describe public events for individual arms, grouped by KO/timeout outcome."""
    groups = defaultdict(list)
    for row in rows:
        if "public_state" not in row:
            continue
        for branch in BRANCHES:
            arm = row["by_policy"][policy][branch]
            replay = arm["replay"]
            mirror = azumarill_mirror(replay, row["species"], row["roster"])
            groups[arm["outcome"] if arm["reward"] is None else "ko"].append((replay, mirror))
    report = {}
    for outcome, records in groups.items():
        replays = [replay for replay, _ in records]
        mirrors = [(entry, ice_beams) for _, (entry, ice_beams) in records if entry is not None]
        counts = [Counter(event["kind"] for event in r["events"]) for r in replays]
        report[outcome] = {
            "arms": len(replays),
            "median_elapsed_ms": median(r["elapsed_ms"] for r in replays),
            "median_charged_ms": median(r["charged_ms"] for r in replays),
            "median_clock_remainder_ms": median(r["clock_remainder_ms"] for r in replays),
            "median_resolved_charges": median(c["charged"] for c in counts),
            "median_switches": median(c["switch"] for c in counts),
            "median_faints": median(c["faint"] for c in counts),
            "azumarill_mirror": {
                "arms": len(mirrors),
                "entry_step_end_ms_range": [min(entry for entry, _ in mirrors),
                                            max(entry for entry, _ in mirrors)] if mirrors else None,
                "ice_beam_count_range": [min(count for _, count in mirrors),
                                         max(count for _, count in mirrors)] if mirrors else None,
            },
            "median_opponent_shields_spent": median(
                sum(e["kind"] == "charged" and e["side"] == "self" and e["shielded"]
                    for e in r["events"]) for r in replays
            ),
        }
    return report


def summarize(rows, policies):
    valid = [r for r in rows if "public_state" in r]
    result = {
        "by_policy": {
            policy: {
                **summarize_forks([{
                    "public_state": r["public_state"], **r["by_policy"][policy],
                } if "public_state" in r else r for r in rows]),
                "public_replay": replay_summary(rows, policy),
            }
            for policy in policies
        }
    }
    if len(policies) == 2:
        baseline, reserve = policies
        comparisons = {action: [] for action in BRANCHES}
        completion = Counter()
        shifts = []
        for row in valid:
            before, after = (row["by_policy"][policy] for policy in policies)
            for action in BRANCHES:
                comparisons[action].append((before[action], after[action]))
            before_completed, after_completed = (
                all(arm["reward"] is not None for arm in pair.values()) for pair in (before, after)
            )
            completion[(before_completed, after_completed)] += 1
            if before_completed and after_completed:
                baseline_delta = before["second_charge"]["reward"] - before["aqua_tail"]["reward"]
                reserve_delta = after["second_charge"]["reward"] - after["aqua_tail"]["reward"]
                shifts.append(reserve_delta - baseline_delta)
        result["matched_shield_policy_change"] = {
            "delta_direction": f"{reserve} minus {baseline}",
            "both_charge_arms_completed_under_both_policies": len(shifts),
            "both_charge_arms_completed_only_with_reserve": completion[False, True],
            "both_charge_arms_completed_only_with_cpu": completion[True, False],
            "both_charge_arms_not_jointly_completed_under_either_policy": completion[False, False],
            "mean_charge_reward_delta_shift_on_common_complete": (
                sum(shifts) / len(shifts) if shifts else None
            ),
            **{action: paired_charge_rewards(pairs) for action, pairs in comparisons.items()},
        }
    return result


def by_roster(rows, policies):
    return {
        name: {
            **summarize([row for row in rows if row["roster"] == name], policies),
            "by_starting_opponent_shields": {
                shields: summarize([row for row in rows if row["roster"] == name
                                    and row["starting_opponent_shields"] == shields], policies)
                for shields in (0, 1, 2)
            },
        }
        for name, *_ in ROSTERS
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Run just one fresh window")
    parser.add_argument("--skip-historical", action="store_true")
    args = parser.parse_args()
    historical = {}
    if not args.skip_historical:
        for window in PRIOR_WINDOWS:
            rows = run_cases(historical_cases(window), mode="historical")
            historical[window] = {"summary": by_roster(rows, POLICIES[:1]), "cases": rows}
    fresh = {}
    windows = WINDOWS if args.window is None else (args.window,)
    for window in windows:
        rows = run_cases(fresh_cases(window), mode="shielding")
        fresh[window] = {"summary": by_roster(rows, POLICIES), "cases": rows}
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "fresh": fresh,
        "fresh_pooled": by_roster([row for data in fresh.values() for row in data["cases"]], POLICIES),
        "historical": historical,
        "historical_pooled": by_roster(
            [row for data in historical.values() for row in data["cases"]], POLICIES[:1],
        ) if historical else {},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
