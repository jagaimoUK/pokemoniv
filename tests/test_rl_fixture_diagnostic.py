"""Fixture diagnostic contracts: predeclared lineups, bounded, no invented wins."""
import unittest

from tools.diagnose_rl_fixture import OWN_SELECTIONS, diagnose_fixture


class FixtureSensitivityTests(unittest.TestCase):
    def test_same_scenarios_all_selections_and_explicit_paired_denominators(self):
        seen = []
        def fake_evaluator(policy, label, scenario, *, fixed_selection):
            self.assertIsNone(policy)
            self.assertEqual(label, "fixed")
            seen.append((fixed_selection, scenario))
            # Deliberately different eligibility between selections, to
            # ensure censored matches never become losses.
            eligible = (scenario[0] % 2 == 0 or fixed_selection == OWN_SELECTIONS[0])
            return {
                "status": "complete" if eligible else "discarded",
                "reward": 1 if eligible else None,
                "outcome": "self_ko_win" if eligible else "timeout",
                "decisions": 2,
                "action_counts": {"selection": 1, "fast": 1, "wait": 0,
                                  "charged": 0, "switch": 0, "shield": 0},
            }
        result = diagnose_fixture(seed=12, episodes=4, evaluator=fake_evaluator)
        self.assertEqual(result["scenarios_per_selection"], 4)
        self.assertEqual(len(seen), 16)
        self.assertEqual(
            [x[1] for x in seen[:4]],
            [x[1] for x in seen[4:8]])
        self.assertEqual(result["summary_by_own_selection"][OWN_SELECTIONS[0]]["complete"], 4)
        for selection in OWN_SELECTIONS[1:]:
            stat = result["summary_by_own_selection"][selection]
            self.assertEqual(stat["complete"], 2)
            self.assertEqual(stat["discarded"], 2)
            self.assertEqual(stat["losses_among_completed"], 0)
            self.assertEqual(stat["discard_reasons"], {"timeout": 2})
        self.assertEqual(len(result["both_completed_denominators"]), 6)
        self.assertEqual(set(result["predeclared_own_selections"]), set(OWN_SELECTIONS))

    def test_invalid_episode_count_is_rejected_before_native_work(self):
        for bad in (-1, 0, 13, True, 1.5):
            with self.assertRaises(ValueError):
                diagnose_fixture(episodes=bad, evaluator=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
