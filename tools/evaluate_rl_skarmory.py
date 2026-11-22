"""Paired Sky Attack and Brave Bird trial with predeclared synthetic opponents."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from pvpoke_child_env import child_environment
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_branches import PRIMEAPE
from tools.rl_charge_metrics import charge_stratum, paired_charge_rewards
from tools.run_rl_mc import fixture_teams

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = (1100012, 1101012)
OWN_SELECTION = "3,4,5|4"
# Name, slot replaced by Primeape, selected trio, lead. Each roster gets two
# seeds per window crossed with both initial opponent shield counts.
ROSTERS = (("quagsire", None, (0, 3, 5), 0),
           ("primeape", 1, (1, 2, 4), 1),
           ("wigglytuff", 3, (2, 3, 5), 5))
OPPONENT_SHIELDS = (1, 2)
SEEDS_PER_ROSTER = 2


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared Skarmory window")
    own, _, base_enemy = fixture_teams()
    cases = []
    for index, (name, replaced, trio, lead) in enumerate(ROSTERS):
        enemy = base_enemy.copy()
        if replaced is not None:
            enemy[replaced] = {**enemy[replaced], **PRIMEAPE}
        public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id="great-league-v1")
        preview.choose(OWN_SELECTION)
        handoff = preview._private_engine_input()
        start = window + index * SEEDS_PER_ROSTER
        cases.extend({"seed": seed, "roster": name, "opponent_shields": shields, "handoff": handoff}
                     for seed in range(start, start + SEEDS_PER_ROSTER) for shields in OPPONENT_SHIELDS)
    return cases


def run_window(window):
    result = subprocess.run(
        ["node", str(ROOT / "tools/evaluate_rl_skarmory.cjs")], input=json.dumps(window_cases(window)),
        capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60, check=True,
        env=child_environment({"PVP_PVPOKE_SOURCE": str(ROOT / "vendor/pvpoke")}),
    )
    return json.loads(result.stdout)


def summarize_pairs(cases):
    pairs = [(row["sky_attack"], row["brave_bird"]) for row in cases if "public_state" in row]
    return {"planned": len(cases), **paired_charge_rewards(pairs),
            "excluded": dict(Counter(row["excluded"] for row in cases if "excluded" in row)),
            **{move: {
                "resolved": sum(pair[index]["move_resolved"] for pair in pairs),
                "shielded": sum(pair[index]["shielded"] is True for pair in pairs),
            } for index, move in enumerate(("sky_attack", "brave_bird"))}}


def summarize(cases):
    groups, strata = {}, {}
    for row in cases:
        name = f'{row["roster"]} / {row["planned_opponent_shields"]} shield'
        groups.setdefault(name, []).append(row)
        if "public_state" in row:
            strata.setdefault(charge_stratum(row["public_state"]), []).append(row)
    return {"overall": summarize_pairs(cases),
            "rosters": {key: summarize_pairs(rows) for key, rows in groups.items()},
            "strata": {key: summarize_pairs(rows) for key, rows in strata.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both predeclared windows")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    rows = [row for window in windows for row in run_window(window)]
    print(json.dumps({"windows": windows, "summary": summarize(rows), "cases": rows}, sort_keys=True))


if __name__ == "__main__":
    main()
