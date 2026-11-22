"""Verify common seed alignment and ranking with separate terminal outcomes."""
from fractions import Fraction
from itertools import combinations
import json
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_bench_choices import EXPECTED_PUBLIC_FORK, OUTCOMES
from tools.evaluate_rl_azumarill_bench_choices import WINDOWS as PRIOR_WINDOWS
from tools.evaluate_rl_azumarill_bench_mixture import (
    DRAW_BENCH, ROSTERS, SCENARIOS, SEEDS_PER_WINDOW, WINDOWS, WIN_BENCHES,
    bench_weights, evaluate_bench_mixture, score_mixture, window_cases,
)

MODULE = "tools.evaluate_rl_azumarill_bench_mixture"


class BenchMixtureTests(unittest.TestCase):
    def test_all_ten_benches_use_the_exact_same_unused_seed_set(self):
        self.assertEqual(WINDOWS, (3200012, 3201012))
        expected_benches = set(combinations((0, 1, 2, 4, 5), 2))
        benches = {tuple(slot for slot in trio if slot != 3) for _, _, _, trio in ROSTERS}
        self.assertEqual(len(ROSTERS), 10)
        self.assertEqual(benches, expected_benches)
        prior = {seed for window in PRIOR_WINDOWS for seed in range(window, window + 15)}
        for window in WINDOWS:
            seeds = set(range(window, window + SEEDS_PER_WINDOW))
            self.assertTrue(seeds.isdisjoint(prior))
            prior.update(seeds)
            cases = window_cases(window)
            self.assertEqual(len(cases), 10 * SEEDS_PER_WINDOW)
            for roster, *_ in ROSTERS:
                self.assertEqual({case["seed"] for case in cases if case["roster"] == roster}, seeds)
            self.assertTrue(all(case["opponent_shields"] == 2 for case in cases))

    def test_objectives_rank_with_exact_ties_and_keep_timeout_separate(self):
        actions = ("fast", "switch_1", "switch_2")
        by_roster = {}
        for name, *_ in ROSTERS:
            counts = {action: dict.fromkeys(OUTCOMES, 0) for action in actions}
            for result in counts.values():
                result["opponent_ko_win"] = 4
            if name == DRAW_BENCH:
                counts["switch_1"].update(opponent_ko_win=0, simultaneous_ko=4)
            if name in WIN_BENCHES:
                for action in ("fast", "switch_2"):
                    counts[action].update(self_ko_win=2, opponent_ko_win=1, timeout=1)
            by_roster[name] = {"matched_forks": 4, "actions": {
                action: {"outcomes": result} for action, result in counts.items()
            }}

        self.assertEqual(set(bench_weights(*SCENARIOS["uniform"]).values()), {Fraction(1, 10)})
        self.assertEqual(sum(bench_weights(40, 20).values()), 1)
        with self.assertRaises(ValueError):
            bench_weights(80, 30)
        uniform = score_mixture(by_roster, 10, 20)
        self.assertEqual(uniform["best_actions"]["self_ko_win"], ["fast", "switch_2"])
        self.assertEqual(uniform["best_actions"]["verified_non_loss"], list(actions))
        self.assertEqual(uniform["rates"]["fast"]["verified_non_loss"], 0.1)
        self.assertEqual(uniform["rates"]["fast"]["timeout"], 0.05)
        draw_heavy = score_mixture(by_roster, 40, 20)
        self.assertEqual(draw_heavy["best_actions"]["self_ko_win"], ["fast", "switch_2"])
        self.assertEqual(draw_heavy["best_actions"]["verified_non_loss"], ["switch_1"])

    def test_native_common_seed_smoke(self):
        with patch(f"{MODULE}.SEEDS_PER_WINDOW", 1):
            report = evaluate_bench_mixture(windows=WINDOWS[:1])

        self.assertEqual(report["common_seeds"], [WINDOWS[0]])
        self.assertEqual(report["public_view_sha256"], EXPECTED_PUBLIC_FORK)
        self.assertEqual(report["summary"]["matched_forks"], 10)
        self.assertEqual({row["seed"] for row in report["cases"]}, {WINDOWS[0]})
        for roster in report["by_roster"].values():
            self.assertEqual(roster["matched_forks"], 1)
            self.assertEqual(set(roster["actions"]), {"fast", "switch_1", "switch_2"})
        self.assertEqual(len(report["sweep"]), 66)
        self.assertFalse(report["ruleset_distinction"]["worlds_2026_mimikyu"]["tournament_eligible"])
        self.assertTrue(report["ruleset_distinction"]["cs_2026_11_16_mimikyu"]["tournament_eligible"])
        for field in ("handoff", "private_replay", "opponent_team", "energy_points"):
            self.assertNotIn(f'"{field}"', json.dumps(report))
