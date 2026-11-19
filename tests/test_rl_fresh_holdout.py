"""Fresh held-out fixture experiment: pairing, bounds and no eval updates."""
import unittest
from unittest.mock import patch

from tools.evaluate_rl_fresh_holdout import (
    FOLLOWUP_SELECTIONS, HELDOUT_OFFSET, compare_followup,
)
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy


class FreshHoldoutTests(unittest.TestCase):
    def test_same_fresh_scenarios_are_reused_across_both_lineups(self):
        invocations = []
        trainings = []
        def fake_train(model, *, count, seed, selection):
            self.assertEqual(type(model), GeneralizedMonteCarloPolicy)
            trainings.append((model, count, seed, selection))
            return {"complete": 0, "discarded": count, "updates": 0}
        def fake_paired(*, trained, untrained, scenarios, fixed_selection):
            self.assertIsNot(trained.policy, untrained.policy)
            self.assertEqual(trained.selection, fixed_selection)
            self.assertEqual(untrained.selection, fixed_selection)
            self.assertEqual(trained.snapshot(), untrained.snapshot())
            invocations.append((fixed_selection, tuple(scenarios)))
            return {"evaluation_policy_updated": False,
                    "metrics": {"trained": {"complete": 0}},
                    "paired": {}}
        with (patch("tools.evaluate_rl_fresh_holdout.train_fixed_own",
                    side_effect=fake_train),
              patch("tools.evaluate_rl_fresh_holdout.evaluate_paired",
                    side_effect=fake_paired)):
            result = compare_followup(train=2, evaluate=3, seed=200)
        self.assertEqual([x[0] for x in invocations],
                         list(FOLLOWUP_SELECTIONS))
        self.assertEqual(invocations[0][1], invocations[1][1])
        self.assertEqual(invocations[0][1][0][0], 200 + HELDOUT_OFFSET)
        self.assertNotEqual(invocations[0][1][0][0], 200 + 100000)
        self.assertEqual({x[3] for x in trainings}, set(FOLLOWUP_SELECTIONS))
        self.assertEqual(len({id(x[0]) for x in trainings}), 2)
        self.assertEqual(result["evaluation_scenarios_per_selection"], 3)
        self.assertEqual(result["training_episodes_per_selection"], 2)

    def test_invalid_parameter_bounds_rejected(self):
        invalid = [
            {"policy_variant": "v3"}, {"seed": True}, {"seed": -1},
            {"seed": 2**32}, {"train": 17}, {"train": 1.5},
            {"evaluate": 0}, {"evaluate": 13}, {"evaluate": True},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                compare_followup(**kwargs)


if __name__ == "__main__":
    unittest.main()
