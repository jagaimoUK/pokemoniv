"""Guarded v2 tactical ablation must preserve public keys and model data."""
import copy
import unittest
from unittest.mock import patch

from pvpoke_rl_mc_generalized import (
    GeneralizedMonteCarloPolicy, coarse_public_state,
)
from tools.rl_wait_guard import GuardedWaitMonteCarloPolicy
from tools.evaluate_rl_mc import evaluate_paired
from tools.evaluate_rl_fresh_holdout import compare_followup, FOLLOWUP_SELECTIONS
from test_rl_mc_train import preview, public_tactics


def model_with_tactic(action, reward):
    selection = preview()
    tactic = public_tactics()
    sel_kind, sel_key, legal = coarse_public_state(selection)
    tac_kind, tac_key, _ = coarse_public_state(tactic)
    assert (sel_kind, tac_kind) == ("selection", "tactics")
    original = GeneralizedMonteCarloPolicy(seed=6)
    original.learn([(sel_kind, sel_key, legal[0]),
                    (tac_kind, tac_key, action)],
                   reward=reward, selection_reward=reward)
    return original.snapshot(), tactic


class GuardedWaitTests(unittest.TestCase):
    def test_negative_fast_does_not_make_unknown_wait_preferable(self):
        snapshot, tactic = model_with_tactic("fast", -1)
        original = GeneralizedMonteCarloPolicy.restore(snapshot, seed=8)
        guarded = GuardedWaitMonteCarloPolicy.restore(snapshot, seed=8)
        self.assertEqual(original.choose(tactic, epsilon=0.0)[0], "wait")
        action, record = guarded.choose(tactic, epsilon=0.0)
        self.assertEqual(action, "fast")
        self.assertEqual(record[1], coarse_public_state(tactic)[1])
        self.assertEqual(record[2], "fast")
        self.assertEqual(guarded.snapshot(), snapshot)

    def test_positive_observed_wait_is_still_legal(self):
        snapshot, tactic = model_with_tactic("wait", 1)
        guarded = GuardedWaitMonteCarloPolicy.restore(snapshot, seed=2)
        self.assertEqual(guarded.choose(tactic, epsilon=0.0)[0], "wait")

    def test_forced_wait_and_training_exploration_remain_unchanged(self):
        snapshot, tactic = model_with_tactic("fast", -1)
        original = GeneralizedMonteCarloPolicy.restore(snapshot, seed=8)
        guarded = GuardedWaitMonteCarloPolicy.restore(snapshot, seed=8)
        for _ in range(25):
            self.assertEqual(
                guarded.choose(tactic, epsilon=0.25),
                original.choose(tactic, epsilon=0.25))
        only_wait = copy.deepcopy(tactic)
        only_wait["legal_actions"] = ["wait"]
        self.assertEqual(guarded.choose(only_wait, epsilon=0.0)[0], "wait")
        self.assertEqual(guarded.snapshot(), original.snapshot())

    def test_hidden_fields_do_not_change_ablation_decisions(self):
        snapshot, tactic = model_with_tactic("fast", -1)
        altered = copy.deepcopy(tactic)
        altered["opponent"]["secret_ivs"] = [15, 15, 15]
        altered["private_replay"] = {"opponent_private_team": ["redacted"]}
        first = GuardedWaitMonteCarloPolicy.restore(snapshot, seed=4)
        second = GuardedWaitMonteCarloPolicy.restore(snapshot, seed=4)
        self.assertEqual(first.choose(tactic, epsilon=0.0),
                         second.choose(altered, epsilon=0.0))

    def test_ablation_is_restricted_to_v2_and_is_opt_in(self):
        with self.assertRaises(ValueError):
            compare_followup(policy_variant="v1", guarded_ablation=True)
        with self.assertRaises(ValueError):
            compare_followup(guarded_ablation=1)

        observed = []
        def fake_train(policy, *, count, seed, selection):
            return {"complete": 0, "discarded": count, "updates": 0}
        def fake_paired(*, trained, untrained, scenarios, fixed_selection,
                        guarded=None):
            self.assertIsNotNone(guarded)
            self.assertIsInstance(guarded.policy, GuardedWaitMonteCarloPolicy)
            self.assertEqual(guarded.snapshot(), trained.snapshot())
            self.assertIsNot(guarded.policy, trained.policy)
            self.assertEqual(guarded.selection, fixed_selection)
            observed.append(fixed_selection)
            return {"evaluation_policy_updated": False, "metrics": {}, "paired": {}}
        with (patch("tools.evaluate_rl_fresh_holdout.train_fixed_own",
                    side_effect=fake_train),
              patch("tools.evaluate_rl_fresh_holdout.evaluate_paired",
                    side_effect=fake_paired)):
            result = compare_followup(train=2, evaluate=2,
                                      guarded_ablation=True)
        self.assertEqual(observed, list(FOLLOWUP_SELECTIONS))
        self.assertIsNotNone(result["wait_guard_ablation"])

    def test_paired_evaluator_has_guarded_denominator_and_no_checkpoint_mutation(self):
        snapshot, _ = model_with_tactic("fast", -1)
        original = GeneralizedMonteCarloPolicy.restore(snapshot, seed=7)
        guarded = GuardedWaitMonteCarloPolicy.restore(snapshot, seed=7)
        untrained = GeneralizedMonteCarloPolicy(seed=7)
        before = (original.snapshot(), guarded.snapshot())

        def fake_eval(policy, label, scenario, **kwargs):
            self.assertIn(label, ("fixed", "trained", "untrained", "guarded"))
            returns = {"fixed": None, "trained": -1,
                       "untrained": 1, "guarded": 1}
            reward = returns[label]
            return {
                "status": "discarded" if reward is None else "complete",
                "reward": reward, "decisions": 1,
                "outcome": "timeout" if reward is None else (
                    "self_ko_win" if reward == 1 else "opponent_ko_win"),
                "selection_action": "0,1,4|4",
            }
        with patch("tools.evaluate_rl_mc.evaluate_one", side_effect=fake_eval):
            result = evaluate_paired(
                trained=original, untrained=untrained, guarded=guarded,
                scenarios=[(12, (0, 1, 2), 0)],
                fixed_selection="0,1,4|4")
        self.assertEqual(result["paired"]["guarded_vs_trained"]["guarded_better"], 1)
        self.assertEqual(result["paired"]["guarded_vs_trained"]["both_completed"], 1)
        self.assertEqual(result["paired"]["guarded_vs_untrained"]["equal_return"], 1)
        self.assertEqual(result["paired"]["trained_vs_fixed"]["both_completed"], 0)
        self.assertEqual((original.snapshot(), guarded.snapshot()), before)
        self.assertFalse(result["evaluation_policy_updated"])


if __name__ == "__main__":
    unittest.main()
