"""Checks for the public energy representation and the 150s wait ablation."""
import copy
import json
import unittest
from unittest.mock import patch

from pvpoke_rl_mc_train import LearningError
from test_rl_mc_train import preview, public_tactics
from tools.evaluate_rl_azumarill_rl_coverage import CpuFallbackMonteCarloPolicy
from tools.evaluate_rl_azumarill_switch_rl_audit import WINDOWS as AUDIT_WINDOWS
from tools.evaluate_rl_azumarill_switch_rl_targeted import (
    TARGETED_TRAIN_SEED, TRAIN_EPISODES, WINDOWS as TARGETED_WINDOWS,
)
from tools.evaluate_rl_azumarill_switch_rl_wait_energy import (
    CONTINUATION_SPECS, WINDOWS, EnergyBandNoVoluntaryWaitPolicy, EnergyBandPolicy,
    NoVoluntaryWaitPolicy, evaluate_rl_switch_wait_energy, summarize_matched, window_cases,
)
from tools.evaluate_rl_azumarill_switch_strata import ARMS


class WaitEnergyTests(unittest.TestCase):
    def test_positive_wait_is_removed_only_at_evaluation_with_a_legal_attack(self):
        baseline = CpuFallbackMonteCarloPolicy(seed=12)
        selection_kind, selection_key, selections = baseline.encode_state(preview())
        view = public_tactics()
        decisions = [(selection_kind, selection_key, selections[0])]
        for attacks in (["fast"], ["charge_0"], ["charge_1"]):
            view["legal_actions"] = ["wait", *attacks]
            kind, key, _ = baseline.encode_state(view)
            decisions.append((kind, key, "wait"))
        baseline.learn(decisions, reward=1, selection_reward=1)
        snapshot = copy.deepcopy(baseline.snapshot())
        strict = NoVoluntaryWaitPolicy.restore(snapshot, seed=12)

        for attacks in (["fast"], ["charge_0"], ["charge_1"]):
            view["legal_actions"] = ["wait", *attacks]
            self.assertEqual(baseline.choose(view, epsilon=0)[0], "wait")
            self.assertEqual(strict.choose(view, epsilon=0), (
                attacks[0], ("tactics", baseline.encode_state(view)[1], attacks[0]),
            ))
            for _ in range(8):
                self.assertEqual(strict.choose(view, epsilon=0.3), baseline.choose(view, epsilon=0.3))

        view["legal_actions"] = ["wait"]
        self.assertEqual(strict.choose(view, epsilon=0)[0], "wait")
        view["phase"] = "shield"
        view["legal_actions"] = ["shield_yes", "shield_no"]
        self.assertEqual(strict.choose(view, epsilon=0), baseline.choose(view, epsilon=0))
        view["phase"] = "replace"
        view["legal_actions"] = ["switch_1", "switch_2"]
        self.assertEqual(strict.choose(view, epsilon=0), baseline.choose(view, epsilon=0))
        self.assertEqual(strict.snapshot(), snapshot)

    def test_energy_key_splits_only_active_public_energy_bands(self):
        v2, energy = CpuFallbackMonteCarloPolicy(), EnergyBandPolicy()
        view = public_tactics()
        view["own"]["team"][0]["energy_points"] = 50
        kind, key, legal = energy.encode_state(view)
        self.assertEqual((kind, legal), ("tactics", ("wait", "fast")))
        altered = copy.deepcopy(view)
        altered["own"]["team"][0]["energy_points"] = 59
        altered["own"]["team"][1]["energy_points"] = 99
        altered["opponent"]["revealed"][0]["energy_points"] = 100
        altered["opponent"]["secret_ivs"] = [15, 15, 15]
        altered["private_replay"] = {"opponent_private_team": ["redacted"]}
        self.assertEqual(energy.encode_state(altered), (kind, key, legal))
        self.assertEqual(energy.choose(altered, epsilon=0), energy.choose(view, epsilon=0))
        altered["own"]["team"][0]["energy_points"] = 60
        self.assertEqual(v2.encode_state(altered), v2.encode_state(view))
        self.assertNotEqual(energy.encode_state(altered)[1], key)
        self.assertEqual(energy.encode_state(preview()), v2.encode_state(preview()))
        self.assertEqual(energy.encode_state(view), EnergyBandNoVoluntaryWaitPolicy().encode_state(view))
        with self.assertRaises(LearningError):
            EnergyBandPolicy.restore(v2.snapshot())
        with self.assertRaises(LearningError):
            CpuFallbackMonteCarloPolicy.restore(energy.snapshot())
        altered["own"]["team"][0]["energy_points"] = 101
        with self.assertRaises(LearningError):
            energy.encode_state(altered)

    def test_ko_recall_counts_only_matched_native_outcomes(self):
        def row(outcome_a, reward_a, outcome_b, reward_b):
            return dict(zip(ARMS, (
                {"outcome": outcome_a, "reward": reward_a},
                {"outcome": outcome_b, "reward": reward_b},
            ), strict=True))

        matches = [
            (row("self_ko_win", 1, "self_ko_win", 1), row("self_ko_win", 1, "opponent_ko_win", -1)),
            (row("timeout", None, "opponent_ko_win", -1), row("self_ko_win", 1, "timeout", None)),
            (row("timeout", None, "unsupported", None), row("unsupported", None, "timeout", None)),
        ]
        self.assertEqual(summarize_matched(matches), {
            "cpu_ko_arms": 3,
            "cpu_ko_arms_with_candidate_ko": 2,
            "cpu_ko_outcomes_reproduced": 1,
            "cpu_ko_outcome_recall": 1 / 3,
            "timeout_to_ko": 1,
            "ko_to_timeout": 1,
        })
        self.assertIsNone(summarize_matched([])["cpu_ko_outcome_recall"])

    def test_predeclared_windows_and_frozen_native_branches(self):
        self.assertEqual(WINDOWS, (2700012, 2701012))
        prior = {seed for window in AUDIT_WINDOWS + TARGETED_WINDOWS for seed in range(window, window + 6)}
        prior.update(range(TARGETED_TRAIN_SEED, TARGETED_TRAIN_SEED + TRAIN_EPISODES))
        with self.assertRaises(ValueError):
            window_cases(AUDIT_WINDOWS[0])
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 72)
            seeds = {case["seed"] for case in cases}
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertTrue(seeds.isdisjoint(prior))
            prior.update(seeds)

        selected = next(case for case in window_cases(WINDOWS[0]) if case["condition"] == "hp_60")
        module = "tools.evaluate_rl_azumarill_switch_rl_wait_energy"
        with patch(f"{module}.window_cases", return_value=[selected]):
            report = evaluate_rl_switch_wait_energy(windows=WINDOWS[:1], train_episodes=4)

        self.assertEqual(report["remaining_seconds"], 150)
        self.assertEqual(report["ruleset_id"], "play-pokemon-worlds-2026-gl")
        rulesets = report["ruleset_distinction"]
        self.assertFalse(rulesets["worlds_2026_mimikyu"]["tournament_eligible"])
        self.assertTrue(rulesets["cs_2026_11_16_mimikyu"]["tournament_eligible"])
        self.assertTrue(rulesets["simulator_analyzability_azumarill"]["simulator_analyzable"])
        self.assertTrue(report["policy_snapshots_unchanged"])
        self.assertEqual({run["seed"] for run in report["training"].values()}, {TARGETED_TRAIN_SEED})
        self.assertEqual(len({run["policy_schema"] for run in report["training"].values()}), 2)

        rows = report["cases"]
        self.assertEqual(set(rows), set(CONTINUATION_SPECS))
        for name, (row,) in rows.items():
            self.assertEqual(row["public_state"], rows["cpu"][0]["public_state"])
            self.assertEqual(row["public_state"]["elapsed_ms"], 90000)
            for arm in ARMS:
                self.assertTrue(row[arm]["action_resolved"])
                if row[arm]["outcome"] == "timeout":
                    self.assertIsNone(row[arm]["reward"])
            hp_60 = report["summary"][name]["by_condition"]["hp_60"]
            self.assertEqual(hp_60["rl_diagnostics"]["diverged_on_unseen_states"], 0)
            if name.endswith("_no_wait"):
                self.assertEqual(hp_60["rl_diagnostics"]["waits_with_legal_attack"], 0)

        serialized = json.dumps(report)
        for field in ("handoff", "private_replay", "randomness", "opponent_team", "energy_points"):
            self.assertNotIn(f'"{field}"', serialized)
