"""Regression tests for the matched, offline Swift study."""
import json
import unittest

from tools.evaluate_rl_wigglytuff import HISTORICAL, HOLDOUT, run_cases, summarize


class WigglytuffStudyTests(unittest.TestCase):
    def test_replays_old_results_and_detects_damage_after_exact_entry(self):
        a, b = run_cases((500014, 701014))
        for row in (a, b):
            self.assertEqual((row["stay"]["reward"], row["switch"]["reward"]), (1, -1))
            self.assertEqual((len(row["stay"]["swift"]), len(row["switch"]["swift"])), (2, 1))
            self.assertEqual(row["switch"]["switch_at_fork"], "primeape")
            switched = row["switch"]["entry"]
            self.assertEqual((switched["hp"], switched["energy_points"]), (224, 0))
            self.assertEqual((switched["self_shields"], switched["opponent_shields"]), (0, 0))
            for grant, intervention in row["interventions"].items():
                self.assertEqual(intervention["entry"], {**switched, "energy_added": int(grant)})
                self.assertEqual(intervention["reward"], -1)
            self.assertIsNone(row["switch"]["second_swift_ready"])
            self.assertEqual(len(row["interventions"]["16"]["swift"]), 2)
        self.assertEqual(a["switch"]["first_active"]["hp"], 160)
        self.assertEqual([m["move"] for m in a["switch"]["moves_before_first_active"]], ["SWIFT"])
        self.assertTrue(b["switch"]["entry"]["forced"])
        self.assertEqual(b["switch"]["entry"]["switch_timer_ms"], 15500)
        for name in ("handoff", "randomness", "state", "decisions", "studied_entry"):
            self.assertNotIn(f'"{name}"', json.dumps((a, b)))

    def test_cohorts_are_fixed_and_disjoint(self):
        self.assertEqual(HISTORICAL, (500014, 500015, 501015, 701014))
        self.assertEqual(len(set(HOLDOUT)), 12)
        self.assertFalse(set(HOLDOUT) & set(HISTORICAL))

    def test_second_swift_and_rewards_are_compared_only_when_both_complete(self):
        short = {"reward": -1, "swift": [{"shielded": False}]}
        second = {"reward": -1, "swift": [{"shielded": False}] * 2}
        rows = [
            {"switch": short, "interventions": {"8": second, "16": second}},
            {"switch": short, "interventions": {"8": {**second, "reward": None}}},
            {"switch": short, "interventions": {}},
        ]
        report = summarize(rows)
        self.assertEqual(report["8"]["matched_entries"], 2)
        self.assertEqual(report["8"]["both_completed"], 1)
        self.assertEqual(report["8"]["new_second_unshielded_swift"], 1)
        self.assertEqual(report["8"]["mean_reward_delta"], 0)
        self.assertEqual(report["16"]["matched_entries"], 1)
