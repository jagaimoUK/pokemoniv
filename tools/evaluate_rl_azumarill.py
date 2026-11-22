"""Paired Play Rough and Hydro Pump trial sourced from 2026 Worlds teamsheets."""
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
from tools.rl_tournament_rules import RULESETS, validate_team_for_ruleset
from tools.run_rl_mc import fixture_teams

ROOT = Path(__file__).resolve().parent.parent
RULESET_ID = "play-pokemon-worlds-2026-gl"
WINDOWS = (1200012, 1201012)
ROLES = ("lead", "closer")
SEEDS_PER_ROSTER = 2
AZUMARILL_WORLDS_MOVES = {
    "fast": "BUBBLE",
    "charged1": "PLAY_ROUGH",
    "charged2": "HYDRO_PUMP",
}
LEAD_SELECTION = "2,3,5|5"
LEAD_OPPONENT_SHIELDS = (0, 1, 2)
# Name, slot replaced by Primeape, swap enemy slots 3/4, selected trio, lead.
LEAD_ROSTERS = (
    ("clodsire", None, False, (1, 3, 5), 1),
    ("skarmory", None, False, (3, 4, 5), 4),
    ("primeape", 1, False, (1, 2, 4), 1),
)
CLOSER_SELECTION = "0,2,5|0"
CLOSER_STARTING_SHIELDS = (2,)
CLOSER_ROSTERS = (
    ("clodsire_skarmory", None, True, (1, 3, 4), 1),
    ("clodsire_primeape", 3, False, (1, 3, 4), 1),
    ("skarmory_fearow", None, False, (3, 4, 5), 4),
)

_WORLDS_RULESET = RULESETS[RULESET_ID]
TOURNAMENT_EVIDENCE = {
    "ruleset_id": RULESET_ID,
    "tournament_name": _WORLDS_RULESET["tournament_name"],
    "event_dates": _WORLDS_RULESET["event_dates"],
    "location": _WORLDS_RULESET["location"],
    "format": "Great League (CP <= 1500), Bring-6-Pick-3",
    "rules_url": _WORLDS_RULESET["rules_url"],
    "handbook_url": _WORLDS_RULESET["handbook_url"],
    "banned_list_url": _WORLDS_RULESET["banned_list_url"],
    "results_url": _WORLDS_RULESET["results_url"],
    "banned_species_subset": sorted(_WORLDS_RULESET["banned_species"]),
    "competitor": "David 'PvpDavid07' Bustos Nordgren (Sweden, 5th-6th Place / Top 8)",
    "pokemon": "azumarill",
    "reported_entry": {
        "cp": 1499,
        "hp": 194,
        "fast": "BUBBLE",
        "charged": ["HYDRO_PUMP", "PLAY_ROUGH"],
        "shadow": False,
    },
    "fixture_caveat": (
        "Official Worlds team sheets omit exact IVs; offline native evaluation uses "
        "pinned fixture IVs (0/15/15, Lv45.5, CP1499, HP196) and eligible fixture "
        "opponent rosters from tests/fixtures/strategy_gamemaster.json."
    ),
}


def _build_own_six():
    own_base, _, base_enemy = fixture_teams()
    own = [dict(row) for row in own_base]
    own[2], own[5] = own[5], own[2]
    own[5] = {**own[5], **AZUMARILL_WORLDS_MOVES}
    validate_team_for_ruleset(own, RULESET_ID)
    return own, base_enemy


def _build_enemy_six(base_enemy, replaced, swap_3_4):
    enemy = [dict(row) for row in base_enemy]
    if replaced is not None:
        enemy[replaced] = {**enemy[replaced], **PRIMEAPE}
    if swap_3_4:
        enemy[3], enemy[4] = enemy[4], enemy[3]
    validate_team_for_ruleset(enemy, RULESET_ID)
    return enemy


def _role_cases(window, role, own, base_enemy):
    if role == "lead":
        selection, target_slot, rosters, shields_list, expect_fixed = (
            LEAD_SELECTION, 0, LEAD_ROSTERS, LEAD_OPPONENT_SHIELDS, True
        )
    else:
        selection, target_slot, rosters, shields_list, expect_fixed = (
            CLOSER_SELECTION, 2, CLOSER_ROSTERS, CLOSER_STARTING_SHIELDS, False
        )
    cases = []
    for index, (name, replaced, swap_3_4, trio, lead) in enumerate(rosters):
        enemy = _build_enemy_six(base_enemy, replaced, swap_3_4)
        public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=RULESET_ID)
        preview.choose(selection)
        handoff = preview._private_engine_input()
        start = window + index * SEEDS_PER_ROSTER
        for seed in range(start, start + SEEDS_PER_ROSTER):
            for shields in shields_list:
                cases.append({
                    "seed": seed,
                    "role": role,
                    "target_slot": target_slot,
                    "roster": name,
                    "opponent_shields": shields,
                    "expected_opponent_shields": shields if expect_fixed else None,
                    "handoff": handoff,
                })
    return cases


def window_cases(window, role=None):
    """Build predeclared, ruleset-validated lead and closer evaluation cases."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared Azumarill window")
    if role is not None and role not in ROLES:
        raise ValueError("Use a predeclared Azumarill role")
    own, base_enemy = _build_own_six()
    selected_roles = ROLES if role is None else (role,)
    return [case for item in selected_roles for case in _role_cases(window, item, own, base_enemy)]


def run_window(window, role=None):
    """Execute a predeclared window through the native 3v3 charge-branch worker."""
    result = subprocess.run(
        ["node", str(ROOT / "tools/evaluate_rl_azumarill.cjs")],
        input=json.dumps(window_cases(window, role=role)),
        capture_output=True, encoding="utf-8", cwd=ROOT, timeout=90, check=True,
        env=child_environment({"PVP_PVPOKE_SOURCE": str(ROOT / "vendor/pvpoke")}),
    )
    return json.loads(result.stdout)


def _shield_and_time_stratum(public_state):
    return charge_stratum(public_state).split(" / ", 1)[1]


def summarize_pairs(cases):
    """Aggregate resolution, shielding, censoring, and paired terminal reward deltas."""
    pairs = [(row["play_rough"], row["hydro_pump"]) for row in cases if "public_state" in row]
    return {
        "planned": len(cases),
        **paired_charge_rewards(pairs),
        "excluded": dict(Counter(row["excluded"] for row in cases if "excluded" in row)),
        **{
            move: {
                "resolved": sum(pair[index]["move_resolved"] for pair in pairs),
                "shielded": sum(pair[index]["shielded"] is True for pair in pairs),
            }
            for index, move in enumerate(("play_rough", "hydro_pump"))
        },
    }


def summarize(cases):
    """Summarize paired results overall, by role, roster, HP/shield/clock, and shield/clock."""
    by_role, rosters, strata, shield_time = {}, {}, {}, {}
    for row in cases:
        by_role.setdefault(row["role"], []).append(row)
        roster_key = (
            f'{row["role"]} / {row["roster"]} / '
            f'{row["planned_starting_opponent_shields"]} start-shield'
        )
        rosters.setdefault(roster_key, []).append(row)
        if "public_state" in row:
            strata.setdefault(charge_stratum(row["public_state"]), []).append(row)
            shield_time.setdefault(_shield_and_time_stratum(row["public_state"]), []).append(row)
    return {
        "overall": summarize_pairs(cases),
        "by_role": {key: summarize_pairs(rows) for key, rows in by_role.items()},
        "rosters": {key: summarize_pairs(rows) for key, rows in rosters.items()},
        "strata": {key: summarize_pairs(rows) for key, rows in strata.items()},
        "by_shield_and_time": {key: summarize_pairs(rows) for key, rows in shield_time.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both predeclared windows")
    parser.add_argument("--role", choices=ROLES, help="Default runs both lead and closer roles")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    rows = [row for window in windows for row in run_window(window, role=args.role)]
    print(json.dumps({
        "ruleset_id": RULESET_ID,
        "tournament_evidence": TOURNAMENT_EVIDENCE,
        "windows": windows,
        "role": args.role,
        "summary": summarize(rows),
        "cases": rows,
    }, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
