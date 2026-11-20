"""Check shared seed coverage and objective-specific action reversals."""
from itertools import combinations
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_bench_choices import EXPECTED_PUBLIC_FORK, OUTCOMES
from tools.evaluate_rl_azumarill_new_lead_choices import (
    LEADS, WINDOWS, evaluate_new_leads, mixture_scores, window_cases,
)


class NewLeadChoiceTests(unittest.TestCase):
    def test_all_benches_share_the_same_seed_set_and_native_fork(self):
        self.assertEqual(WINDOWS, (3302012, 3303012))
        for window in WINDOWS:
            for slot in LEADS:
                cases = window_cases(window, slot)
                self.assertEqual(len(cases), 30)
                for seed in range(window, window + 3):
                    self.assertEqual(len({row["roster"] for row in cases if row["seed"] == seed}), 10)

        with patch("tools.evaluate_rl_azumarill_new_lead_choices.SEEDS_PER_WINDOW", 1):
            report = evaluate_new_leads(windows=WINDOWS[:1])
        forks = set()
        for name, cohort in report["cohorts"].items():
            self.assertEqual(cohort["summary"]["matched_forks"], 10)
            self.assertEqual({row["seed"] for row in cohort["cases"]}, {WINDOWS[0]})
            benches = {tuple(sorted(row["opponent_bench"])) for row in cohort["cases"]}
            species = {"quagsire", "clodsire", "azumarill", "fearow", "skarmory", "wigglytuff"} - {name}
            self.assertEqual(benches, set(combinations(sorted(species), 2)))
            self.assertTrue(all(row["actions"][arm]["switch_resolved"]
                                for row in cohort["cases"] for arm in ("switch_1", "switch_2")))
            self.assertNotEqual(cohort["fork"]["sha256"], EXPECTED_PUBLIC_FORK)
            forks.add(cohort["fork"]["sha256"])
        self.assertEqual(len(forks), 2)

    def test_grid_preserves_ties_and_exposes_rank_changes(self):
        def bench(fast, switch):
            return {"matched_forks": 1, "actions": {
                name: {"outcomes": {outcome: int(outcome == result) for outcome in OUTCOMES}}
                for name, result in (("fast", fast), ("switch_1", switch))
            }}

        scores = mixture_scores({
            "left": bench("self_ko_win", "opponent_ko_win"),
            "right": bench("timeout", "simultaneous_ko"),
        })
        self.assertEqual(scores["uniform"]["best_actions"]["self_ko_win"], ["fast"])
        self.assertEqual(scores["uniform"]["best_actions"]["verified_non_loss"], ["fast", "switch_1"])
        self.assertEqual(scores["pairs"][2]["best_actions"]["verified_non_loss"], ["switch_1"])
        self.assertEqual(scores["pairs"][8]["best_actions"]["verified_non_loss"], ["fast"])
