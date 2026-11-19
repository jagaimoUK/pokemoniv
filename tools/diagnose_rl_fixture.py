#!/usr/bin/env python3
"""Small, predeclared native 6v3 fixture-sensitivity check.

All choices use the same PUBLIC CPU tactics and identical hidden-opponent
scenario list. This checks the outcome censoring and lineup sensitivity of
the synthetic benchmark, not a policy's competitive strength.

No real user data, no model updates, no private replay or PvPoke MCP.
"""
from __future__ import annotations

import argparse
from itertools import combinations
import json

from tools.evaluate_rl_mc import evaluate_one, heldout_scenarios, _metrics
from tools.run_rl_mc import GAME_DATA, fixture_teams
from pvpoke_rl_team_preview import SixToThreeSelection

# Declared before observing results. Do not select a "winner" from this probe.
OWN_SELECTIONS = ("0,1,2|0", "0,1,4|4", "2,3,5|2", "0,4,5|4")


def diagnose_fixture(*, seed=12, episodes=6, evaluator=evaluate_one):
    if type(episodes) is not int or not 1 <= episodes <= 12:
        raise ValueError("Expected 1..12 scenarios")
    scenarios = heldout_scenarios(count=episodes, seed=seed + 100000)
    own, public, opponent = fixture_teams()
    public_preview = SixToThreeSelection(
        own, public, opponent, scenarios[0][1], scenarios[0][2],
        ruleset_id="great-league-v1").observe()
    legal = set(public_preview["legal_actions"])
    if len(OWN_SELECTIONS) != len(set(OWN_SELECTIONS)) or any(
            choice not in legal for choice in OWN_SELECTIONS):
        raise ValueError("Unexpected fixed selection")
    results = {}
    for own_selection in OWN_SELECTIONS:
        results[own_selection] = [
            evaluator(None, "fixed", scenario, fixed_selection=own_selection)
            for scenario in scenarios
        ]
    summaries = {}
    for own_selection, trials in results.items():
        stats = _metrics(trials)
        summaries[own_selection] = {
            "complete": stats["complete"],
            "discarded": stats["discarded"],
            "discard_reasons": stats["discard_reasons"],
            "wins_among_completed": stats["wins"],
            "losses_among_completed": stats["losses"],
            "draws_among_completed": stats["draws"],
            "timeout_public_clocks": stats["timeout_public_clocks"],
        }
    pairs = {}
    for one, two in combinations(OWN_SELECTIONS, 2):
        pairs[one + "__vs__" + two] = sum(
            a["status"] == b["status"] == "complete"
            for a, b in zip(results[one], results[two])
        )
    return {
        "phase": "synthetic_fixture_selection_sensitivity_v1",
        "scenarios_per_selection": episodes,
        "predeclared_own_selections": list(OWN_SELECTIONS),
        "fixed_public_tactics": True,
        "summary_by_own_selection": summaries,
        "both_completed_denominators": pairs,
        "conclusion": "diagnostic_only_no_competitive_strength_claim",
        "scope": "synthetic_native_3v3_no_policy_learning",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evaluate", type=int, default=6)
    p.add_argument("--seed", type=int, default=12)
    a = p.parse_args()
    if not 1 <= a.evaluate <= 12 or not 0 <= a.seed <= 2**32 - 100100:
        p.error("Invalid bounded fixture experiment")
    print(json.dumps(diagnose_fixture(seed=a.seed, episodes=a.evaluate),
                     sort_keys=True))


if __name__ == "__main__":
    main()
