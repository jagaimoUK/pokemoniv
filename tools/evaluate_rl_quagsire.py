"""Paired Quagsire charge decisions with a separate, offline shadow fixture."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from pvpoke_child_env import child_environment
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_branches import PRIMEAPE
from tools.rl_charge_metrics import charge_stratum, paired_charge_rewards
from tools.rl_tournament_rules import RULESETS, validate_team_for_ruleset
from tools.run_rl_mc import fixture_teams

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/fixtures"
BASE_GAMEMASTER = FIXTURES / "strategy_gamemaster.json"
SHADOW_OVERLAY = FIXTURES / "strategy_quagsire_shadow.json"
RULESET_IDS = ("play-pokemon-worlds-2026-gl", "play-pokemon-cs-2026-11-16-gl")
WINDOWS = (1500012, 1501012)
SEEDS_PER_ROSTER = 2
SPECIES = ("quagsire", "quagsire_shadow")
SECOND_MOVES = ("MUD_BOMB", "STONE_EDGE")
OWN_SELECTION = "0,2,4|0"
STARTING_OPPONENT_SHIELDS = (0, 1, 2)
# Name, slot replaced by Primeape (if any), selected trio, lead.
ROSTERS = (
    ("clodsire", None, (1, 3, 5), 1),
    ("skarmory", 1, (1, 2, 4), 4),
    ("wigglytuff", 2, (1, 2, 5), 5),
)
WORLDS_BUILDS = (
    {"competitor": "MEweedle", "species": "quagsire_shadow",
     "charged": ["AQUA_TAIL", "MUD_BOMB"]},
    {"competitor": "PvpDavid07", "species": "quagsire",
     "charged": ["AQUA_TAIL", "STONE_EDGE"]},
)


def shadow_gamemaster():
    """Materialize the additional species in memory for this study only."""
    data = json.loads(BASE_GAMEMASTER.read_text(encoding="utf-8"))
    overlay = json.loads(SHADOW_OVERLAY.read_text(encoding="utf-8"))
    by_species = {entry["speciesId"]: entry for entry in data["pokemon"]}
    entry = overlay["shadow_entry"]
    if entry["speciesId"] in by_species:
        raise ValueError("Shadow study overlay would overwrite a base species")
    data["pokemon"].append({**by_species[overlay["base_species_id"]], **entry})
    return data


def window_cases(window):
    """Precommit rosters, selection, seed, shields, forms and moves before replay."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared Quagsire seed window")
    return build_window_cases(window, RULESET_IDS, ROSTERS, SEEDS_PER_ROSTER)


def build_window_cases(window, rulesets, rosters, seeds_per_roster, *, own_selection=OWN_SELECTION):
    """Build prepared inputs for a predeclared study condition grid."""
    own_base, _, enemy_base = fixture_teams()
    cases = []
    for ruleset in rulesets:
        for index, (name, replaced, trio, lead) in enumerate(rosters):
            enemy = [dict(row) for row in enemy_base]
            if replaced is not None:
                enemy[replaced].update(PRIMEAPE)
            validate_team_for_ruleset(enemy, ruleset)
            public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
            seed_start = window + index * seeds_per_roster
            for species in SPECIES:
                for move in SECOND_MOVES:
                    own = [{**own_base[0], "species": species, "charged2": move}, *own_base[1:]]
                    validate_team_for_ruleset(own, ruleset)
                    preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=ruleset)
                    preview.choose(own_selection)
                    handoff = preview._private_engine_input()
                    for seed in range(seed_start, seed_start + seeds_per_roster):
                        for shields in STARTING_OPPONENT_SHIELDS:
                            cases.append({"handoff": handoff, "roster": name, "seed": seed,
                                          "opponent_shields": shields})
    return cases


def run_cases(cases, *, mode=None, worker="evaluate_rl_quagsire.cjs"):
    """Run one fixed window (or a smoke-test slice) against an ephemeral fixture."""
    with TemporaryDirectory(prefix="quagsire-study-") as temp:
        fixture = Path(temp) / "strategy_gamemaster_shadow.json"
        fixture.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        command = ["node", str(ROOT / "tools" / worker), str(fixture)]
        if mode is not None:
            command.append(mode)
        result = subprocess.run(
            command,
            input=json.dumps(cases), capture_output=True, encoding="utf-8", cwd=ROOT, timeout=180,
            env=child_environment({"PVP_PVPOKE_SOURCE": str(ROOT / "vendor/pvpoke")}),
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)


def summarize_forks(rows):
    pairs = [(r["aqua_tail"], r["second_charge"]) for r in rows if "public_state" in r]
    return {
        "planned": len(rows),
        **paired_charge_rewards(pairs),
        "excluded": dict(Counter(r["excluded"] for r in rows if "excluded" in r)),
        **{
            action: {"resolved": sum(pair[index]["move_resolved"] for pair in pairs),
                     "shielded": sum(pair[index]["shielded"] is True for pair in pairs)}
            for index, action in enumerate(("aqua_tail", "second_charge"))
        },
    }


def compare_worlds_builds(rows):
    """Match input conditions across builds; the individual fork histories can differ."""
    builds = defaultdict(dict)
    worlds_keys = {(build["species"], build["charged"][1]) for build in WORLDS_BUILDS}
    for row in rows:
        build = row["species"], row["second_move"]
        if build in worlds_keys:
            condition = row["roster"], row["seed"], row["starting_opponent_shields"]
            builds[condition][row["species"]] = row
    matched = [(b["quagsire"], b["quagsire_shadow"]) for b in builds.values()]
    legal = [(normal, shadow) for normal, shadow in matched
             if "public_state" in normal and "public_state" in shadow]
    return {
        "planned": len(matched),
        "delta_direction": "MEweedle (shadow) minus PvpDavid07 (normal)",
        **{action: paired_charge_rewards([(normal[action], shadow[action]) for normal, shadow in legal])
           for action in ("aqua_tail", "second_charge")},
    }


def summarize(rows):
    """Keep ruleset labels separate; report by assigned roster and public fork state."""
    report = {}
    for ruleset in RULESET_IDS:
        ruleset_rows = [row for row in rows if row["ruleset_id"] == ruleset]
        builds = {}
        for species in SPECIES:
            for move in SECOND_MOVES:
                selected = [row for row in ruleset_rows
                            if row["species"] == species and row["second_move"] == move]
                strata = defaultdict(list)
                for row in selected:
                    if "public_state" in row:
                        strata[charge_stratum(row["public_state"])].append(row)
                builds[f"{species}/{move}"] = {
                    **summarize_forks(selected),
                    "by_roster": {
                        name: summarize_forks([row for row in selected if row["roster"] == name])
                        for name, _, _, _ in ROSTERS
                    },
                    "by_public_state": {key: summarize_forks(group) for key, group in strata.items()},
                }
        report[ruleset] = {"within_builds": builds,
                           "worlds_builds_matched_inputs": compare_worlds_builds(ruleset_rows)}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both seed windows")
    args = parser.parse_args()
    windows = WINDOWS if args.window is None else (args.window,)
    reports = {}
    for window in windows:
        rows = run_cases(window_cases(window))
        reports[window] = {"summary": summarize(rows), "cases": rows}
    print(json.dumps({
        "worlds_builds": WORLDS_BUILDS,
        "worlds_results_url": RULESETS[RULESET_IDS[0]]["results_url"],
        "fixture_scope": "Charge pairs from the prior PR handoff; synthetic IVs, rosters and CPU policies.",
        "ruleset_distinction": {
            ruleset: {
                "tournament_name": RULESETS[ruleset]["tournament_name"],
                "banned_species_subset": sorted(RULESETS[ruleset]["banned_species"]),
            }
            for ruleset in RULESET_IDS
        },
        "windows": reports,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
