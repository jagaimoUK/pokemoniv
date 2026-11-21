"""Check paired timing reachability and strict mixture reversals."""
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_lead_timing import (
    WINDOWS, evaluate_lead_timing, evaluate_timing, strict_reversals,
)


class LeadTimingTests(unittest.TestCase):
    def test_unreached_and_ineligible_forks_are_counted_without_rollouts(self):
        report = evaluate_timing(None, [{}, {}], [
            {}, {"first_charge": ((), {"legal_actions": ["charge_0", "switch_1"]})},
        ], "first_charge")
        self.assertEqual(report, {"planned": 2, "reached": 1, "eligible": 0})

    def test_different_unique_leaders_are_required_for_reversal(self):
        points = [
            {"first": "a", "second": "b", "best_actions": {
                "self_ko_win": winners, "verified_non_loss": ["fast"],
            }}
            for winners in (["fast"], ["fast", "switch_1"], ["switch_1"])
        ]
        report = strict_reversals({"pairs": points})
        self.assertEqual(report["self_ko_win"], [
            {"first": "a", "second": "b", "leaders": ["fast", "switch_1"]},
        ])
        self.assertEqual(report["verified_non_loss"], [])

    def test_native_timing_cohorts_share_seeds_and_public_observations(self):
        with patch("tools.evaluate_rl_azumarill_lead_timing.SEEDS_PER_WINDOW", 1):
            report = evaluate_lead_timing(windows=WINDOWS[:1])
        self.assertEqual(set(report["cohorts"]), {"clodsire", "skarmory"})
        for timings in report["cohorts"].values():
            damage, charge = timings["first_damage"], timings["first_charge"]
            self.assertEqual(damage["reached"], 10)
            self.assertEqual(damage["eligible"], 10)
            self.assertEqual({row["seed"] for row in damage["cases"]}, {WINDOWS[0]})
            self.assertLessEqual(charge["eligible"], charge["reached"])
            if "turn" in charge:
                self.assertGreater(charge["turn"], damage["turn"])
                self.assertEqual({row["seed"] for row in charge["cases"]}, {WINDOWS[0]})
