"""Bounded fixed-own-selection experiment with no nonpublic policy inputs."""
import unittest

from pvpoke_rl_mc_train import PublicMonteCarloPolicy, play_episode
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from test_rl_mc_train import FakeMatch, preview, public_tactics

from tools.evaluate_rl_fixed_selection import (
    DEFAULT_SELECTION, FixedOwnSelection, train_fixed_own,
)


class FixedSelectionDiagnosticTests(unittest.TestCase):
    def test_adapter_keeps_same_public_tactic_encoder_and_forces_legal_selection(self):
        for cls in (PublicMonteCarloPolicy, GeneralizedMonteCarloPolicy):
            underlying = cls(seed=17)
            adapter = FixedOwnSelection(underlying)
            selection, record = adapter.choose(preview(), epsilon=1.0)
            self.assertEqual(selection, DEFAULT_SELECTION)
            self.assertEqual(record, (*underlying.encode_state(preview())[:2],
                                      DEFAULT_SELECTION))
            tactic, record = adapter.choose(public_tactics(), epsilon=0.0)
            self.assertIn(tactic, public_tactics()["legal_actions"])
            self.assertEqual(record[1], underlying.encode_state(public_tactics())[1])
            self.assertEqual(adapter.snapshot(), underlying.snapshot())

    def test_invalid_own_selection_fails_closed(self):
        model = FixedOwnSelection(GeneralizedMonteCarloPolicy(seed=1),
                                  "0,1,2|3")
        with self.assertRaises(ValueError):
            model.choose(preview())

    def test_fake_episode_updates_both_selection_and_tactic_values(self):
        base = GeneralizedMonteCarloPolicy(seed=3)
        policy = FixedOwnSelection(base)
        result = play_episode(FakeMatch(), policy, seed=3, epsilon=0.0)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["updated"])
        self.assertEqual(base.completed_matches, 1)
        self.assertIn(DEFAULT_SELECTION,
                      next(iter(base.snapshot()["values"]["selection"].values())))

    def test_bounded_native_training_keeps_outcomes_and_update_count_honest(self):
        policy = GeneralizedMonteCarloPolicy(seed=7)
        stats = train_fixed_own(policy, count=2, seed=120)
        self.assertEqual(stats["complete"] + stats["discarded"], 2)
        self.assertEqual(stats["updates"], stats["complete"])
        self.assertEqual(stats["updates"], policy.completed_matches)
        self.assertEqual(stats["wins"] + stats["losses"] + stats["draws"],
                         stats["complete"])


if __name__ == "__main__":
    unittest.main()
