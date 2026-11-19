"""Trace Swift and compare legal decisions on synthetic native replays."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import subprocess
from pathlib import Path

from pvpoke_child_env import child_environment
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_branches import PRIMEAPE
from tools.evaluate_rl_mc import heldout_scenarios
from tools.evaluate_rl_switch_traces import LEGACY_SELECTION
from tools.rl_charge_metrics import charge_stratum, paired_charge_rewards
from tools.run_rl_mc import fixture_teams

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL = (500014, 500015, 501015, 701014)
HOLDOUT = tuple(range(800012, 800018)) + tuple(range(801012, 801018))
TIMING_HOLDOUT = tuple(range(900012, 900018)) + tuple(range(901012, 901018))
SWIFT_HOLDOUT = tuple(range(1000012, 1000018)) + tuple(range(1001012, 1001018))
# Each alternate matchup actually selects Primeape (slot 3); its original
# pool does not contain Primeape. Each lead gets two predeclared seeds.
ALTERNATE_MATCHUPS = tuple(((1, 3, 5), lead) for lead in (1, 3, 5) for _ in range(2)) + tuple(
    ((0, 2, 3), lead) for lead in (0, 2, 3) for _ in range(2))
# Primeape replaces Clodsire in slot 1 and is included in every selected trio.
SWIFT_ALTERNATE_MATCHUPS = tuple(((1, 3, 4), lead) for lead in (1, 3, 4) for _ in range(2)) + tuple(
    ((0, 1, 2), lead) for lead in (0, 1, 2) for _ in range(2))
CHARGE_ALTERNATIVES = ("fast", "charge_0", "wait")


def run_cases(seeds, *, timing_pool=None, charge_pool=None):
    if not 1 <= len(seeds) <= 12:
        raise ValueError("Expected 1–12 synthetic cases")
    own, public, enemy = fixture_teams()
    own[0] = {**own[0], **PRIMEAPE}
    if (timing_pool and charge_pool or
            any(pool not in (None, "legacy", "alternate") for pool in (timing_pool, charge_pool))):
        raise ValueError("Select one study and opponent pool")
    alternate = timing_pool == "alternate" or charge_pool == "alternate"
    if alternate:
        slot, lineup_seeds, matchups = ((1, SWIFT_HOLDOUT, SWIFT_ALTERNATE_MATCHUPS) if charge_pool else
                                        (3, TIMING_HOLDOUT, ALTERNATE_MATCHUPS))
        enemy[slot] = {**enemy[slot], **PRIMEAPE}
        public[slot] = {key: enemy[slot][key] for key in ("species", "roster_clause_id")}
    cases = []
    for seed in seeds:
        if alternate:
            trio, lead = matchups[lineup_seeds.index(seed)]
        else:
            _, trio, lead = heldout_scenarios(count=1, seed=seed)[0]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id="great-league-v1")
        preview.choose(LEGACY_SELECTION)
        cases.append({"seed": seed, "handoff": preview._private_engine_input()})
    command = ["node", str(ROOT / "tools/evaluate_rl_wigglytuff.cjs")]
    if timing_pool:
        command.append("--switch-timing")
    if charge_pool:
        command.append("--second-swift")
    result = subprocess.run(
        command, input=json.dumps(cases),
        capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60, check=True,
        env=child_environment({"PVP_PVPOKE_SOURCE": str(ROOT / "vendor/pvpoke")}),
    )
    return json.loads(result.stdout)


def _unshielded(row):
    return sum(not move["shielded"] for move in row["swift"])


def summarize(cases):
    report = {}
    for bonus in ("8", "16"):
        pairs = [(case["switch"], case["interventions"][bonus])
                 for case in cases if bonus in case["interventions"]]
        completed = [(old, new) for old, new in pairs
                     if old["reward"] is not None and new["reward"] is not None]
        deltas = [new["reward"] - old["reward"] for old, new in completed]
        study = {"planned_cases": len(cases), "matched_entries": len(pairs),
                 "both_completed": len(completed), "new_second_unshielded_swift": 0,
                 "removed_second_unshielded_swift": 0, "better": sum(d > 0 for d in deltas),
                 "mean_reward_delta": sum(deltas) / len(deltas) if deltas else None,
                 "worse": sum(d < 0 for d in deltas), "equal": sum(d == 0 for d in deltas)}
        for old, new in completed:
            study["new_second_unshielded_swift"] += _unshielded(old) < 2 <= _unshielded(new)
            study["removed_second_unshielded_swift"] += _unshielded(new) < 2 <= _unshielded(old)
        report[bonus] = study
    return report


def _summarize_delay(pairs):
    completed = [(a, b) for a, b in pairs if a["reward"] is not None and b["reward"] is not None]
    deltas = [b["reward"] - a["reward"] for a, b in completed]
    executed = [(a, b) for a, b in pairs if a["timing"]["status"] == b["timing"]["status"] ==
                "voluntary_switch_resolved"]
    hp_deltas = [b["entry_hp_lost"] - a["entry_hp_lost"] for a, b in executed
                 if a["entry_hp_lost"] is not None and b["entry_hp_lost"] is not None]
    arms = {}
    for index, label in enumerate(("immediate", "delayed")):
        rows = [pair[index] for pair in pairs]
        arms[label] = {
            "timing_status": dict(Counter(row["timing"]["status"] for row in rows)),
            "second_swift_legal": sum(row["second_resolved_swift_ready"] is not None for row in rows),
            "second_swift_resolved": sum(len(row["swift"]) >= 2 for row in rows),
            "second_unshielded_swift_resolved": sum(_unshielded(row) >= 2 for row in rows),
            "censored_outcomes": dict(Counter(row["outcome"] for row in rows if row["reward"] is None)),
        }
    return {
        "attempted": len(pairs), "both_completed": len(completed),
        "both_completed_rate": len(completed) / len(pairs) if pairs else None,
        "reward_better": sum(d > 0 for d in deltas), "reward_equal": sum(d == 0 for d in deltas),
        "reward_worse": sum(d < 0 for d in deltas),
        "mean_reward_delta": sum(deltas) / len(deltas) if deltas else None,
        "arms": arms, "both_voluntary_switches_resolved": len(executed),
        "both_entry_hp_observed_after_voluntary_switches": len(hp_deltas),
        "entry_hp_loss_smaller": sum(d < 0 for d in hp_deltas),
        "entry_hp_loss_same": sum(d == 0 for d in hp_deltas),
        "entry_hp_loss_larger": sum(d > 0 for d in hp_deltas),
        "mean_entry_hp_loss_delta": sum(hp_deltas) / len(hp_deltas) if hp_deltas else None,
    }


def summarize_timing(cases):
    eligible = [case for case in cases if "delayed" in case]
    return {
        "planned": len(cases), "eligible": len(eligible),
        "excluded": dict(Counter(case["excluded"] for case in cases if "excluded" in case)),
        **{action: _summarize_delay([(case["immediate"], case["delayed"][action])
                                    for case in eligible if action in case["delayed"]])
           for action in ("wait", "fast")},
    }


def _charge_pair_summary(histories, action):
    pairs = [(row["immediate"], row["alternatives"][action])
             for row in histories if action in row["alternatives"]]
    return {
        **paired_charge_rewards(pairs),
        "immediate_swift_resolved_at_fork": sum(any(m["move"] == "SWIFT" for m in a["charge_resolved_at_fork"])
                                                for a, _ in pairs),
        "immediate_second_swift_resolved": sum(a["second_swift_resolved"] for a, _ in pairs),
        "alternative_second_swift_resolved": sum(b["second_swift_resolved"] for _, b in pairs),
        "alternative_first_charge_from_fork": dict(Counter(
            (b["first_charge_from_fork"] or {}).get("move", "none") for _, b in pairs)),
    }


def summarize_charge(cases):
    histories = [row for case in cases for row in case["histories"].values()]
    eligible = [row for row in histories if "public_state" in row]
    grouped = {}
    for row in eligible:
        grouped.setdefault(charge_stratum(row["public_state"]), []).append(row)
    return {
        "planned_histories": len(histories), "eligible_histories": len(eligible),
        "excluded": dict(Counter(row["excluded"] for row in histories if "excluded" in row)),
        "overall": {action: _charge_pair_summary(eligible, action) for action in CHARGE_ALTERNATIVES},
        "strata": {key: {"eligible_histories": len(rows), **{
            action: _charge_pair_summary(rows, action) for action in CHARGE_ALTERNATIVES}}
            for key, rows in grouped.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("historical", "holdout"), required=True)
    study = parser.add_mutually_exclusive_group()
    study.add_argument("--timing-pool", choices=("legacy", "alternate"),
                       help="Compare legal switch timing instead of synthetic energy bonuses")
    study.add_argument("--charge-pool", choices=("legacy", "alternate"),
                       help="Compare one legal action at the second-Swift fork")
    args = parser.parse_args()
    if (args.timing_pool == "alternate" or args.charge_pool == "alternate") and args.cohort == "historical":
        parser.error("The alternate pool is predeclared for holdout only")
    holdout = SWIFT_HOLDOUT if args.charge_pool else TIMING_HOLDOUT if args.timing_pool else HOLDOUT
    rows = run_cases(HISTORICAL if args.cohort == "historical" else holdout,
                     timing_pool=args.timing_pool, charge_pool=args.charge_pool)
    stats = summarize_charge(rows) if args.charge_pool else summarize_timing(rows) if args.timing_pool else summarize(rows)
    report = {"cohort": args.cohort, "summary": stats, "cases": rows}
    if args.timing_pool:
        report["timing_pool"] = args.timing_pool
    if args.charge_pool:
        report["charge_pool"] = args.charge_pool
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
