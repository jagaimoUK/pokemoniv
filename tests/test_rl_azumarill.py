"""Regression tests for tournament ruleset separation and Azumarill charge forks."""
from collections import defaultdict
import inspect
import json
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill import (
    WINDOWS, run_window, summarize, window_cases,
)
from tools.evaluate_rl_skarmory import WINDOWS as SKARMORY_WINDOWS, window_cases as skarmory_cases
from tools.evaluate_rl_wigglytuff import HISTORICAL, HOLDOUT, SWIFT_HOLDOUT, TIMING_HOLDOUT
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability,
    evaluate_tournament_eligibility,
    validate_team_for_ruleset,
)


def _sample_row(species="azumarill", cp=1499):
    return {
        "species": species, "roster_clause_id": species, "combatant_id": f"c_{species}",
        "fast": "BUBBLE", "charged1": "PLAY_ROUGH", "charged2": "HYDRO_PUMP",
        "atk": 0, "def": 15, "hp": 15, "level": 45.5, "cp": cp,
    }


class AzumarillTournamentStudyTests(unittest.TestCase):
    def test_tournament_ruleset_separates_event_bans_from_simulator_analyzability(self):
        self.assertNotIn(
            "ruleset_id", inspect.signature(evaluate_simulator_analyzability).parameters
        )
        worlds = evaluate_tournament_eligibility("mimikyu", "play-pokemon-worlds-2026-gl")
        nov_cs = evaluate_tournament_eligibility("mimikyu", "play-pokemon-cs-2026-11-16-gl")
        open_gl = evaluate_tournament_eligibility("mimikyu", "great-league-v1")
        self.assertFalse(worlds["tournament_eligible"])
        self.assertEqual(worlds["reason"], "banned_in_ruleset")
        self.assertTrue(nov_cs["tournament_eligible"])
        self.assertTrue(open_gl["tournament_eligible"])

        pokemon_by_id = {
            "mimikyu": {"speciesId": "mimikyu", "tags": []},
            "altaria_mega": {"speciesId": "altaria_mega", "tags": ["mega"]},
            "morpeko_full_belly": {"speciesId": "morpeko_full_belly", "formChange": {"moveId": "AURA_WHEEL"}},
            "minior_core": {"speciesId": "minior_core", "tags": []},
        }
        self.assertEqual(
            evaluate_simulator_analyzability("mimikyu", pokemon_by_id),
            {"species": "mimikyu", "simulator_analyzable": True, "reason": "supported"},
        )
        for sp in ("altaria_mega", "morpeko_full_belly", "minior_core"):
            res = evaluate_simulator_analyzability(sp, pokemon_by_id)
            self.assertFalse(res["simulator_analyzable"])
            self.assertEqual(res["reason"], "unsupported_engine_mechanic")
        self.assertEqual(
            evaluate_simulator_analyzability("unknown_mon", pokemon_by_id),
            {"species": "unknown_mon", "simulator_analyzable": False, "reason": "missing_from_gamemaster"},
        )

        valid_team = [_sample_row("azumarill"), _sample_row("clodsire"), _sample_row("mimikyu")]
        with self.assertRaises(ValueError):
            validate_team_for_ruleset(valid_team, "play-pokemon-worlds-2026-gl")
        validate_team_for_ruleset(valid_team, "play-pokemon-cs-2026-11-16-gl")
        with self.assertRaises(ValueError):
            validate_team_for_ruleset([_sample_row("azumarill", cp=1501)], "great-league-v1")
        with self.assertRaises(ValueError):
            validate_team_for_ruleset(
                [_sample_row("azumarill"), _sample_row("azumarill")], "great-league-v1"
            )

    def test_predeclared_windows_rosters_and_shields_are_disjoint_from_prior_studies(self):
        prior_seeds = (
            set(HISTORICAL) | set(HOLDOUT) | set(TIMING_HOLDOUT) | set(SWIFT_HOLDOUT)
            | {row["seed"] for win in SKARMORY_WINDOWS for row in skarmory_cases(win)}
        )
        seen_windows = []
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 24)
            lead_cases = [c for c in cases if c["role"] == "lead"]
            closer_cases = [c for c in cases if c["role"] == "closer"]
            self.assertEqual((len(lead_cases), len(closer_cases)), (18, 6))

            lead_shields = defaultdict(set)
            lead_teams = {}
            for row in lead_cases:
                handoff = row["handoff"]
                self.assertEqual(handoff["ruleset_id"], "play-pokemon-worlds-2026-gl")
                azu = handoff["own_team"][row["target_slot"]]
                self.assertEqual(row["target_slot"], 0)
                self.assertEqual((azu["species"], azu["fast"], azu["charged1"], azu["charged2"]),
                                 ("azumarill", "BUBBLE", "PLAY_ROUGH", "HYDRO_PUMP"))
                enemy_species = tuple(m["species"] for m in handoff["opponent_team"])
                self.assertEqual(enemy_species, lead_teams.setdefault(row["roster"], enemy_species))
                lead_shields[(row["roster"], row["seed"])].add(row["opponent_shields"])
            self.assertEqual(len(set(lead_teams.values())), 3)
            self.assertEqual(len(lead_shields), 6)
            self.assertTrue(all(shields == {0, 1, 2} for shields in lead_shields.values()))

            closer_teams = {}
            for row in closer_cases:
                handoff = row["handoff"]
                self.assertEqual(handoff["ruleset_id"], "play-pokemon-worlds-2026-gl")
                self.assertEqual(row["target_slot"], 2)
                self.assertEqual(row["opponent_shields"], 2)
                self.assertIsNone(row["expected_opponent_shields"])
                azu = handoff["own_team"][2]
                self.assertEqual((azu["species"], azu["fast"], azu["charged1"], azu["charged2"]),
                                 ("azumarill", "BUBBLE", "PLAY_ROUGH", "HYDRO_PUMP"))
                enemy_species = tuple(m["species"] for m in handoff["opponent_team"])
                self.assertEqual(enemy_species, closer_teams.setdefault(row["roster"], enemy_species))
            self.assertEqual(len(set(closer_teams.values())), 3)

            window_seeds = {row["seed"] for row in cases}
            self.assertFalse(window_seeds & prior_seeds)
            seen_windows.append(window_seeds)
        self.assertFalse(seen_windows[0] & seen_windows[1])

    def test_native_replay_slice_preserves_public_boundary_and_matches_conditions(self):
        slice_cases = [row for row in window_cases(WINDOWS[0]) if row["seed"] == 1200012]
        self.assertEqual(len(slice_cases), 4)
        with patch("tools.evaluate_rl_azumarill.window_cases", return_value=slice_cases):
            results = run_window(WINDOWS[0])
        self.assertEqual(len(results), 4)
        lead_rows = [r for r in results if r["role"] == "lead"]
        closer_rows = [r for r in results if r["role"] == "closer"]
        self.assertEqual([r["public_state"]["opponent_shields"] for r in lead_rows], [0, 1, 2])
        self.assertEqual(len(closer_rows), 1)
        for row in results:
            self.assertIn("public_state", row)
            for key in ("play_rough", "hydro_pump"):
                self.assertIn("move_resolved", row[key])
                self.assertIn("shielded", row[key])
                self.assertIn("reward", row[key])
        serialized = json.dumps(results)
        for forbidden in ("handoff", "audit", "randomness", "decisions"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_summarize_separates_resolution_shielding_timeouts_and_clock_strata(self):
        rows = [
            {
                "seed": 1, "role": "lead", "roster": "r0", "planned_starting_opponent_shields": 0,
                "public_state": {"hp_bucket_5pct": 15, "opponent_shields": 0, "elapsed_ms": 20000},
                "play_rough": {"reward": -1, "outcome": "opponent_ko_win", "move_resolved": True, "shielded": False},
                "hydro_pump": {"reward": 1, "outcome": "self_ko_win", "move_resolved": True, "shielded": False},
            },
            {
                "seed": 2, "role": "closer", "roster": "r1", "planned_starting_opponent_shields": 2,
                "public_state": {"hp_bucket_5pct": 6, "opponent_shields": 1, "elapsed_ms": 190000},
                "play_rough": {"reward": 1, "outcome": "self_ko_win", "move_resolved": True, "shielded": True},
                "hydro_pump": {"reward": None, "outcome": "timeout", "move_resolved": True, "shielded": True},
            },
            {
                "seed": 3, "role": "closer", "roster": "r1", "planned_starting_opponent_shields": 2,
                "public_state": {"hp_bucket_5pct": 4, "opponent_shields": 2, "elapsed_ms": 215000},
                "play_rough": {"reward": 1, "outcome": "self_ko_win", "move_resolved": True, "shielded": True},
                "hydro_pump": {"reward": -1, "outcome": "opponent_ko_win", "move_resolved": False, "shielded": None},
            },
            {
                "seed": 4, "role": "closer", "roster": "r2", "planned_starting_opponent_shields": 2,
                "excluded": "target_fainted_before_fork",
            },
        ]
        report = summarize(rows)
        overall = report["overall"]
        self.assertEqual((overall["planned"], overall["attempted"], overall["both_completed"]), (4, 3, 2))
        self.assertEqual(overall["both_completed_rate"], 2 / 3)
        self.assertEqual(overall["play_rough"], {"resolved": 3, "shielded": 2})
        self.assertEqual(overall["hydro_pump"], {"resolved": 2, "shielded": 1})
        self.assertEqual(overall["alternative_censored"], {"timeout": 1})
        self.assertEqual(overall["excluded"], {"target_fainted_before_fork": 1})
        self.assertEqual(overall["mean_reward_delta"], 0.0)
        self.assertIn("0 shield / >60s", report["by_shield_and_time"])
        self.assertIn("1 shield / >30–60s", report["by_shield_and_time"])
        self.assertIn("2 shield / ≤30s", report["by_shield_and_time"])
        self.assertIn("0–25% / 2 shield / ≤30s", report["strata"])
