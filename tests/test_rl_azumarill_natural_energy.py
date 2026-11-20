"""Check matched natural forks and the control for energy misses."""
import json
import unittest
from unittest.mock import patch

from test_rl_mc_train import preview, public_tactics
from tools.evaluate_rl_azumarill_natural_energy import (
    CONTINUATIONS, HYBRID, POLICY_CLASSES, WINDOWS, _continue, evaluate_natural_energy,
    summarize, window_cases,
)
from tools.evaluate_rl_azumarill_switch_rl_wait_energy import WINDOWS as SYNTHETIC_WINDOWS
from tools.evaluate_rl_azumarill_switch_strata import WINDOWS as NATURAL_WINDOWS


class OneDecisionWorker:
    def __init__(self, view):
        self.view = view

    def reset(self, handoff, *, seed, shields):
        return {"observation": self.view}

    def step(self, action):
        completion = action == "fast"
        return {
            "observation": None, "reward": 1 if completion else None,
            "terminated": completion, "truncated": not completion,
            "info": {"outcome": "self_ko_win" if completion else "timeout",
                     "training_eligible": completion, "elapsed_ms": 235000 if completion else 240000},
        }


class NaturalEnergyTests(unittest.TestCase):
    def test_control_attributes_first_difference_and_cpu_ko_recall(self):
        view = public_tactics()
        view.update(turn=31, elapsed_ms=45000)
        cases = (
            ({"v2": "wait"}, HYBRID, "energy", "v2_hit_energy_miss"),
            ({"energy": "wait"}, "v2", HYBRID, "energy_only_hit"),
            ({"v2": "wait", "energy": "fast"}, "v2", HYBRID, "both_hit"),
        )
        for trained, source, other, expected in cases:
            with self.subTest(trained=trained):
                models = {name: cls(seed=12) for name, cls in POLICY_CLASSES.items()}
                for name, action in trained.items():
                    model = models[name]
                    selection, selection_key, available = model.encode_state(preview())
                    kind, key, _ = model.encode_state(view)
                    model.learn([(selection, selection_key, available[0]), (kind, key, action)],
                                reward=1, selection_reward=1)
                tables = {name: model.snapshot()["values"]["tactics"] for name, model in models.items()}
                worker = OneDecisionWorker(view)
                case = {"handoff": {}, "seed": 12, "opponent_shields": 2}
                rows = {name: _continue(worker, case, ((), view), name, models, tables)
                        for name in CONTINUATIONS}
                first = rows[source]["first_differences"][other]
                self.assertEqual(first["source"], expected)
                self.assertNotEqual(first["action"], first["other_action"])
                self.assertNotEqual(rows[source]["outcome"], rows[other]["outcome"])
                report = summarize([rows])
                self.assertEqual(report["cpu_ko_forks"], 1)
                self.assertEqual(report["comparisons"][f"{source}->{other}"]["first_action_difference"],
                                 {expected: 1})
                for name in CONTINUATIONS:
                    self.assertEqual(report["policies"][name]["cpu_ko_outcome_recall"],
                                     int(rows[name]["reward"] is not None))
                self.assertEqual(rows[HYBRID]["stats"]["v2_backup_hits"], int(expected == "v2_hit_energy_miss"))
        self.assertIsNone(summarize([])["policies"]["energy"]["cpu_ko_outcome_recall"])

    def test_fixed_windows_and_native_public_replay(self):
        self.assertEqual(WINDOWS, (2800012, 2801012))
        prior = {seed for window in NATURAL_WINDOWS + SYNTHETIC_WINDOWS for seed in range(window, window + 15)}
        with self.assertRaises(ValueError):
            window_cases(NATURAL_WINDOWS[0])
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 90)
            seeds = {case["seed"] for case in cases}
            self.assertEqual(seeds, set(range(window, window + 15)))
            self.assertTrue(seeds.isdisjoint(prior))
            prior.update(seeds)

        candidates = window_cases(WINDOWS[0])
        per_roster = {}
        for case in candidates:
            if case["opponent_shields"] == 2:
                per_roster.setdefault(case["roster"], case)
        with patch("tools.evaluate_rl_azumarill_natural_energy.window_cases",
                   return_value=list(per_roster.values())):
            result = evaluate_natural_energy(windows=WINDOWS[:1], train_episodes=4)

        self.assertTrue(result["policy_snapshots_unchanged"])
        self.assertEqual(result["ruleset_id"], "play-pokemon-worlds-2026-gl")
        rulesets = result["ruleset_distinction"]
        self.assertFalse(rulesets["worlds_2026_mimikyu"]["tournament_eligible"])
        self.assertTrue(rulesets["cs_2026_11_16_mimikyu"]["tournament_eligible"])
        self.assertEqual(result["planned_standard_histories"], len(per_roster))
        self.assertEqual(result["reduced_opponent_shields"]["first_charge"]["matched_forks"], 0)
        self.assertGreater(result["summary"]["hp_60"]["matched_forks"], 0)
        for row in result["cases"]:
            self.assertGreater(row["fork"]["elapsed_ms"], 0)
            self.assertGreater(row["fork"]["turn"], 1)
            if row["cohort"] == "hp_60":
                self.assertIn(row["fork"]["species"], ("quagsire", "quagsire_shadow"))
                self.assertTrue(50 <= row["fork"]["active_hp_pct"] < 75)
            for result_row in row["continuations"].values():
                if result_row["outcome"] == "timeout":
                    self.assertIsNone(result_row["reward"])
                metrics = result_row["stats"]
                if metrics:
                    self.assertEqual(metrics["choices"], metrics["hits"] + metrics["v2_backup_hits"]
                                     + metrics["cpu_fallbacks"])
        output = json.dumps(result)
        for field in ("handoff", "opponent_team", "private_replay", "randomness", "energy_points"):
            self.assertNotIn(f'"{field}"', output)
