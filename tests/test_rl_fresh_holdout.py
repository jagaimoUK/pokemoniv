"""Fresh held-out fixture experiment: pairing, bounds and no eval updates."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from tools.evaluate_rl_fresh_holdout import (
    FOLLOWUP_SELECTIONS, HELDOUT_OFFSET, compare_followup,
)
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from tools.evaluate_rl_mc import evaluate_one
from tools.rl_supported_tactics import SupportedTacticsPolicy, compare_tactical_actions
from test_rl_mc_train import FakeMatch, preview, public_tactics


def learned_fast_and_wait():
    policy = GeneralizedMonteCarloPolicy(seed=8)
    skind, skey, selection = policy.encode_state(preview())
    kind, key, _ = policy.encode_state(public_tactics())
    for action, reward in (("fast", -1), ("wait", 1)):
        for _ in range(2):
            policy.learn([(skind, skey, selection[0]), (kind, key, action)],
                         reward=reward, selection_reward=reward)
    return policy


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

    def test_supported_tactics_need_two_returns_on_each_side(self):
        legal = ("wait", "fast")
        for table, expected in (
            ({"fast": (2, -1)}, ("fast", "fast", False)),
            ({"fast": (2, -1), "wait": (1, 1)}, ("fast", "fast", False)),
            ({"fast": (1, -1), "wait": (2, 1)}, ("fast", "fast", False)),
            ({"fast": (2, -1), "wait": (2, -1)}, ("fast", "fast", True)),
            ({"fast": (2, -1), "wait": (2, 0)}, ("fast", "wait", True)),
        ):
            with self.subTest(table=table):
                self.assertEqual(compare_tactical_actions(legal, table), expected)
        self.assertEqual(compare_tactical_actions(("fast",), {"wait": (2, 1)}),
                         ("fast", "fast", False))

    def test_ablation_reuses_checkpoint_and_ignores_non_public_fields(self):
        source = learned_fast_and_wait()
        view = public_tactics()
        kind, key, _ = source.encode_state(view)
        checkpoint = deepcopy(source.snapshot())
        supported = SupportedTacticsPolicy.restore(checkpoint, seed=8)
        view["opponent"]["unseen_ivs"] = [0, 15, 15]
        view["private_replay"] = {"opponent_team": ["hidden"]}
        self.assertEqual(supported.choose(view, epsilon=0), ("wait", (kind, key, "wait")))
        self.assertEqual(supported.snapshot(), checkpoint)

        restored = GeneralizedMonteCarloPolicy.restore(checkpoint, seed=8)
        restored.choose(public_tactics(), epsilon=0)
        for _ in range(12):
            self.assertEqual(supported.choose(view, epsilon=0.25),
                             restored.choose(public_tactics(), epsilon=0.25))

    def test_supported_evaluation_keeps_verified_terminal_and_decision_counts(self):
        class StubEnvironment(FakeMatch):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        source = learned_fast_and_wait()
        supported = SupportedTacticsPolicy.restore(source.snapshot(), seed=8)
        with patch("tools.evaluate_rl_mc.SixToThreeEnvironment",
                   return_value=StubEnvironment(final="boolean_selection")):
            row = evaluate_one(supported, "supported", (12, (0, 1, 2), 0))
        self.assertEqual(row["status"], "discarded")
        self.assertIsNone(row["reward"])
        self.assertEqual(row["supported_deviations"], 1)
        self.assertEqual(row["comparable_tactical_decisions"], 1)
        self.assertEqual(supported.snapshot(), source.snapshot())


if __name__ == "__main__":
    unittest.main()
