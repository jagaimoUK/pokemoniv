import unittest
from unittest.mock import patch

from tools.evaluate_rl_preview_learning import HOLDOUT_OFFSET, compare_preview_learning
from tools.diagnose_rl_fixture import OWN_SELECTIONS
from tools.evaluate_rl_mc import BASELINE_SELECTION


class PreviewLearningTests(unittest.TestCase):
    def test_same_tactics_and_train_cases_then_only_chosen_action_on_holdout(self):
        seed = 100
        _, candidate, censored, insufficient = OWN_SELECTIONS
        trials = {BASELINE_SELECTION: [-1, 1, -1], candidate: [1, 1, 1],
                  censored: [1, None, None], insufficient: [None, 1, None]}
        calls = []

        def run(policy, label, scenario, *, fixed_selection):
            self.assertIsNone(policy)
            self.assertEqual(label, "fixed")
            case = scenario[0] - seed
            calls.append((case, fixed_selection))
            reward = (None if fixed_selection == candidate else -1) if case >= HOLDOUT_OFFSET else (
                trials[fixed_selection][case])
            return {"status": "discarded" if reward is None else "complete", "reward": reward}

        with patch("tools.evaluate_rl_preview_learning.evaluate_one", side_effect=run):
            result = compare_preview_learning(seed=seed, train=3, evaluate=2)
        self.assertEqual(result["learned_selection"], candidate)
        self.assertCountEqual(calls, [(case, choice) for case in range(3) for choice in OWN_SELECTIONS] +
                              [(HOLDOUT_OFFSET + i, choice) for i in range(2)
                               for choice in (BASELINE_SELECTION, candidate)])
        self.assertEqual(result["training_comparisons"][censored]["both_completed"], 1)
        self.assertEqual(result["heldout_comparison"], {
            "candidate_completed": 0, "baseline_completed": 2, "both_completed": 0,
            "better": 0, "equal": 0, "worse": 0, "mean_reward_difference": None,
        })

    def test_no_paired_improvement_chooses_baseline_and_reuses_results(self):
        row = {"status": "complete", "reward": 0}
        with patch("tools.evaluate_rl_preview_learning.evaluate_one", return_value=row) as run:
            result = compare_preview_learning(train=2, evaluate=1)
        self.assertEqual(result["learned_selection"], BASELINE_SELECTION)
        self.assertEqual(result["heldout_comparison"]["equal"], 1)
        self.assertEqual(run.call_count, 2 * len(OWN_SELECTIONS) + 1)
