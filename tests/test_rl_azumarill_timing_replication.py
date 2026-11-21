"""Verify held-out public forks and disagreements between objectives."""
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_timing_replication import (
    BENCHES, EXPECTED_FORKS, WINDOWS, evaluate_replication, objective_splits,
)


class TimingReplicationTests(unittest.TestCase):
    def test_shared_optimum_is_not_an_objective_split(self):
        overlap = {"best_actions": {"self_ko_win": ["fast"], "verified_non_loss": ["fast", "switch_1"]}}
        split = {"best_actions": {"self_ko_win": ["fast"], "verified_non_loss": ["switch_1"]}}
        self.assertEqual(objective_splits({"pairs": [overlap, split]}), [split])

    def test_native_replication_reaches_both_pinned_forks(self):
        with patch("tools.evaluate_rl_azumarill_timing_replication.SEEDS_PER_WINDOW", 1):
            report = evaluate_replication()
        self.assertEqual(report["common_seeds"], list(WINDOWS))
        for timing, result in report["timings"].items():
            self.assertEqual(result["sha256"], EXPECTED_FORKS[timing])
            self.assertEqual(result["reached"], len(BENCHES) * len(WINDOWS))
            self.assertEqual(set(result["by_roster"]), set(BENCHES))
            self.assertEqual(len(result["mixtures"]["pairs"]), 33)
            self.assertTrue(all(arm["switch_resolved"] for row in result["cases"]
                                for name, arm in row["actions"].items() if name.startswith("switch_")))
