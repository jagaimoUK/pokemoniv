"""Regression tests for the matched, shield-stratified charged-move trial."""
from collections import defaultdict
import json
import unittest
from unittest.mock import patch

from tools.evaluate_rl_skarmory import ROSTERS, WINDOWS, run_window, summarize, window_cases
from tools.evaluate_rl_wigglytuff import SWIFT_HOLDOUT


class SkarmoryChargeStudyTests(unittest.TestCase):
    def test_predeclared_rosters_and_shields_cross_each_seed(self):
        seeds_by_window = []
        for window in WINDOWS:
            matchups = defaultdict(set)
            opponent_teams = {}
            rows = window_cases(window)
            self.assertEqual(len(rows), 12)
            for row in rows:
                team = row["handoff"]["opponent_team"]
                species = tuple(member["species"] for member in team)
                self.assertEqual(species[0], row["roster"])
                self.assertEqual(row["handoff"]["own_team"][0]["species"], "skarmory")
                self.assertEqual(species, opponent_teams.setdefault(row["roster"], species))
                matchups[row["roster"], row["seed"]].add(row["opponent_shields"])
            self.assertEqual(len(set(opponent_teams.values())), len(ROSTERS))
            self.assertEqual(len(matchups), 6)
            self.assertTrue(all(shields == {1, 2} for shields in matchups.values()))
            seeds_by_window.append({row["seed"] for row in rows})
        self.assertFalse(seeds_by_window[0] & seeds_by_window[1])
        self.assertFalse((seeds_by_window[0] | seeds_by_window[1]) & set(SWIFT_HOLDOUT))

    def test_native_replay_resolves_and_shields_both_moves_at_the_shared_fork(self):
        conditions = [row for row in window_cases(WINDOWS[0]) if row["seed"] == 1100016]
        with patch("tools.evaluate_rl_skarmory.window_cases", return_value=conditions):
            one, two = run_window(WINDOWS[0])
        for row, shields in ((one, 1), (two, 2)):
            self.assertEqual(row["public_state"], {"turn": 24, "hp_bucket_5pct": 8,
                                                  "opponent_shields": shields, "elapsed_ms": 21000})
            self.assertEqual(row["sky_attack"]["requested_move"], "SKY_ATTACK")
            self.assertEqual(row["brave_bird"]["requested_move"], "BRAVE_BIRD")
            for key in ("sky_attack", "brave_bird"):
                self.assertTrue(row[key]["move_resolved"])
                self.assertTrue(row[key]["shielded"])
        self.assertEqual((one["sky_attack"]["reward"], one["brave_bird"]["reward"]), (1, 1))
        self.assertEqual((two["sky_attack"]["reward"], two["brave_bird"]["reward"]), (1, -1))
        for key in ("handoff", "audit", "randomness", "decisions"):
            self.assertNotIn(f'"{key}"', json.dumps([one, two]))

    def test_eligible_resolution_and_terminal_denominators_are_separate(self):
        base = {"roster": "quagsire", "planned_opponent_shields": 2}
        row = {**base, "public_state": {"hp_bucket_5pct": 5, "opponent_shields": 2, "elapsed_ms": 229000},
               "sky_attack": {"reward": 1, "outcome": "self_ko_win", "move_resolved": True, "shielded": True},
               "brave_bird": {"reward": None, "outcome": "timeout", "move_resolved": False, "shielded": None}}
        report = summarize([row, {**base, "excluded": "lead_fainted_before_fork"}])
        overall = report["overall"]
        self.assertEqual((overall["planned"], overall["attempted"], overall["both_completed"]), (2, 1, 0))
        self.assertEqual(overall["sky_attack"], {"resolved": 1, "shielded": 1})
        self.assertEqual(overall["brave_bird"], {"resolved": 0, "shielded": 0})
        self.assertEqual(overall["alternative_censored"], {"timeout": 1})
        self.assertIsNone(overall["mean_reward_delta"])
        self.assertIn("0–25% / 2 shield / ≤30s", report["strata"])
