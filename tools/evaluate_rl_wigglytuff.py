"""Trace Swift and run energy-only interventions on synthetic native replays."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from pvpoke_child_env import child_environment
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_branches import PRIMEAPE
from tools.evaluate_rl_mc import heldout_scenarios
from tools.evaluate_rl_switch_traces import LEGACY_SELECTION
from tools.run_rl_mc import fixture_teams

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL = (500014, 500015, 501015, 701014)
HOLDOUT = tuple(range(800012, 800018)) + tuple(range(801012, 801018))


def run_cases(seeds):
    if not 1 <= len(seeds) <= 12:
        raise ValueError("Expected 1–12 synthetic cases")
    own, public, enemy = fixture_teams()
    own[0] = {**own[0], **PRIMEAPE}
    cases = []
    for seed in seeds:
        _, trio, lead = heldout_scenarios(count=1, seed=seed)[0]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id="great-league-v1")
        preview.choose(LEGACY_SELECTION)
        cases.append({"seed": seed, "handoff": preview._private_engine_input()})
    result = subprocess.run(
        ["node", str(ROOT / "tools/evaluate_rl_wigglytuff.cjs")], input=json.dumps(cases),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("historical", "holdout"), required=True)
    args = parser.parse_args()
    rows = run_cases(HISTORICAL if args.cohort == "historical" else HOLDOUT)
    print(json.dumps({"cohort": args.cohort, "summary": summarize(rows), "cases": rows}, sort_keys=True))


if __name__ == "__main__":
    main()
