"""Exercise the pinned natural fork and the complete action comparison."""
import json
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_bench_choices import (
    EXPECTED_PUBLIC_FORK, ROSTERS, WINDOWS, compare_case, evaluate_bench_choices, summarize, window_cases,
)
from tools.evaluate_rl_azumarill_shared_history import ROSTERS as TRAIN_ROSTERS
from tools.evaluate_rl_azumarill_switch_intervention import ROSTERS as PRIOR_ROSTERS
from tools.evaluate_rl_azumarill_switch_intervention import WINDOWS as PRIOR_WINDOWS

MODULE = "tools.evaluate_rl_azumarill_bench_choices"


class BenchChoiceTests(unittest.TestCase):
    def test_all_fixed_benches_reproduce_the_prior_native_fork(self):
        self.assertEqual(WINDOWS, (3100012, 3101012))
        prior_trios = {(lead, trio) for _, own, lead, trio in PRIOR_ROSTERS if own == "0,3,5|0"}
        prior_trios.update((lead, train) for _, own, lead, train, _ in TRAIN_ROSTERS if own == "0,3,5|0")
        self.assertTrue(prior_trios.isdisjoint({(lead, trio) for _, _, lead, trio in ROSTERS}))
        prior_seeds = {seed for window in PRIOR_WINDOWS for seed in range(window, window + 18)}
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 15)
            seeds = {case["seed"] for case in cases}
            self.assertEqual(seeds, set(range(window, window + 15)))
            self.assertTrue(seeds.isdisjoint(prior_seeds))
            prior_seeds.update(seeds)
            for case in cases:
                self.assertEqual(case["opponent_shields"], 2)
                self.assertEqual(case["handoff"]["own_team"][0]["species"], "quagsire_shadow")
                self.assertEqual(case["handoff"]["opponent_team"][0]["species"], "fearow")

        sample = {}
        for case in window_cases(WINDOWS[0]):
            sample.setdefault(case["roster"], case)
        with patch(f"{MODULE}.window_cases", return_value=list(sample.values())):
            report = evaluate_bench_choices(windows=WINDOWS[:1])

        self.assertEqual(report["public_view_sha256"], EXPECTED_PUBLIC_FORK)
        self.assertEqual(report["starting_shields"], [2, 2])
        self.assertEqual((report["cpu_action"], report["cpu_move_id"]), ("fast", "MUD_SHOT"))
        self.assertFalse(report["ruleset_distinction"]["worlds_2026_mimikyu"]["tournament_eligible"])
        self.assertTrue(report["ruleset_distinction"]["cs_2026_11_16_mimikyu"]["tournament_eligible"])
        self.assertEqual(len(report["cases"]), 5)
        self.assertEqual(len({tuple(row["opponent_bench"]) for row in report["cases"]}), 5)
        for row in report["cases"]:
            arms = row["actions"]
            self.assertEqual(set(arms), {"fast", "switch_1", "switch_2"})
            self.assertIsNone(arms["fast"]["switch_resolved"])
            self.assertEqual(arms["switch_1"]["target_species"], "fearow")
            self.assertEqual(arms["switch_2"]["target_species"], "wigglytuff")
            self.assertTrue(arms["switch_1"]["switch_resolved"])
            self.assertTrue(arms["switch_2"]["switch_resolved"])
        for field in ("handoff", "private_replay", "opponent_team", "energy_points"):
            self.assertNotIn(f'"{field}"', json.dumps(report))

    def test_different_public_view_is_rejected_before_running_any_arm(self):
        with (patch(f"{MODULE}._forks", return_value={"hp_60": ((), {"phase": "turn"})}),
              patch(f"{MODULE}.play_one_action") as play):
            with self.assertRaisesRegex(RuntimeError, "prior public fork"):
                compare_case(None, {})
        play.assert_not_called()

    def test_summary_counts_simultaneous_ko_and_timeout_separately(self):
        cpu = {"target_species": None, "outcome": "opponent_ko_win", "reward": -1}
        switched = {"target_species": "fearow", "switch_resolved": True}
        rows = [
            {"cpu_action": "fast", "actions": {"fast": cpu, "switch_1": {**switched, "outcome": outcome, "reward": reward}}}
            for outcome, reward in (("timeout", None), ("simultaneous_ko", 0))
        ]
        report = summarize(rows)
        switch = report["actions"]["switch_1"]
        self.assertEqual(switch["outcomes"]["timeout"], 1)
        self.assertEqual(switch["outcomes"]["simultaneous_ko"], 1)
        self.assertEqual(switch["ko_reward_vs_cpu"]["both_completed"], 1)
        self.assertEqual(switch["ko_reward_vs_cpu"]["alternative_better"], 1)
        self.assertEqual(switch["ko_reward_vs_cpu"]["alternative_censored"], {"timeout": 1})
