"""Regression tests for Azumarill non-fixed shielding and RL continuation sensitivity."""
import inspect
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from pvpoke_child_env import child_environment
from pvpoke_rl_step_client import NativeStepError
from tools.evaluate_rl_azumarill import WINDOWS as AZU_WINDOWS, window_cases as azu_cases
from tools.evaluate_rl_azumarill_sensitivity import (
    OPPONENT_POLICIES, ROOT, TRAIN_EPISODES, TRAIN_SEED, WINDOWS,
    _SensitivityWorkerTransport, choose_team_cpu, evaluate_sensitivity, window_cases,
)
from tools.evaluate_rl_skarmory import WINDOWS as SKARMORY_WINDOWS, window_cases as skarmory_cases
from tools.evaluate_rl_wigglytuff import HISTORICAL, HOLDOUT, SWIFT_HOLDOUT, TIMING_HOLDOUT
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability,
    evaluate_tournament_eligibility,
)
from tools.run_rl_mc import GAME_DATA


class AzumarillSensitivityTests(unittest.TestCase):
    def test_predeclared_windows_and_training_seeds_are_disjoint_from_all_prior_studies(self):
        prior_seeds = (
            set(HISTORICAL) | set(HOLDOUT) | set(TIMING_HOLDOUT) | set(SWIFT_HOLDOUT)
            | {row["seed"] for win in SKARMORY_WINDOWS for row in skarmory_cases(win)}
            | {row["seed"] for win in AZU_WINDOWS for row in azu_cases(win)}
        )
        train_seeds = set(range(TRAIN_SEED, TRAIN_SEED + TRAIN_EPISODES))
        self.assertFalse(train_seeds & prior_seeds)

        seen_windows = []
        for win in WINDOWS:
            cases = window_cases(win)
            self.assertEqual(len(cases), 18)
            self.assertEqual(sum(c["role"] == "lead" for c in cases), 12)
            self.assertEqual(sum(c["role"] == "closer" for c in cases), 6)
            win_seeds = {c["seed"] for c in cases}
            self.assertFalse(win_seeds & prior_seeds)
            self.assertFalse(win_seeds & train_seeds)
            seen_windows.append(win_seeds)
        self.assertFalse(seen_windows[0] & seen_windows[1])

        self.assertFalse(
            evaluate_tournament_eligibility("mimikyu", "play-pokemon-worlds-2026-gl")["tournament_eligible"]
        )
        self.assertTrue(
            evaluate_tournament_eligibility("mimikyu", "play-pokemon-cs-2026-11-16-gl")["tournament_eligible"]
        )
        self.assertNotIn("ruleset_id", inspect.signature(evaluate_simulator_analyzability).parameters)
        pokemon_by_id = {
            entry["speciesId"]: entry
            for entry in json.loads(Path(GAME_DATA).read_text(encoding="utf-8"))["pokemon"]
        }
        self.assertTrue(evaluate_simulator_analyzability("azumarill", pokemon_by_id)["simulator_analyzable"])

    def test_python_cpu_policy_matches_native_choose_team_cpu(self):
        views = [
            {"phase": "shield", "legal_actions": ["shield_yes", "shield_no"],
             "own": {"active_slot": 0, "team": [{"hp": 50, "max_hp": 196}]}},
            {"phase": "shield", "legal_actions": ["shield_yes", "shield_no"],
             "own": {"active_slot": 0, "team": [{"hp": 48, "max_hp": 196}]}},
            {"phase": "replace", "legal_actions": ["switch_1", "switch_2"],
             "own": {"active_slot": 0, "team": [{"hp": 0, "max_hp": 196}]}},
            {"phase": "replace", "legal_actions": ["wait"],
             "own": {"active_slot": 0, "team": [{"hp": 100, "max_hp": 196}]}},
            {"phase": "turn", "legal_actions": ["wait", "fast", "charge_0", "switch_1"],
             "own": {"active_slot": 0, "team": [{"hp": 100, "max_hp": 196}]}},
            {"phase": "turn", "legal_actions": ["wait", "fast", "switch_2"],
             "own": {"active_slot": 0, "team": [{"hp": 40, "max_hp": 196}]}},
            {"phase": "turn", "legal_actions": ["wait", "fast", "switch_2"],
             "own": {"active_slot": 0, "team": [{"hp": 120, "max_hp": 196}]}},
            {"phase": "turn", "legal_actions": ["wait"],
             "own": {"active_slot": 0, "team": [{"hp": 120, "max_hp": 196}]}},
        ]
        node_code = (
            'const {chooseTeamCpu} = require("./pvpoke_rl_team_native.js");'
            'const views = JSON.parse(require("node:fs").readFileSync(0, "utf8"));'
            'process.stdout.write(JSON.stringify(views.map(chooseTeamCpu)));'
        )
        proc = subprocess.run(
            ["node", "-e", node_code], input=json.dumps(views),
            capture_output=True, encoding="utf-8", cwd=ROOT, timeout=15, check=True,
            env=child_environment({"PVP_PVPOKE_SOURCE": str(ROOT / "vendor/pvpoke")}),
        )
        native_actions = json.loads(proc.stdout)
        self.assertEqual([choose_team_cpu(v) for v in views], native_actions)

    def test_opponent_shield_policies_reverse_shielding_on_matched_fork_and_preserve_aa_audit(self):
        target_case = [
            c for c in window_cases(WINDOWS[0])
            if c["seed"] == 1300012 and c["role"] == "lead"
            and c["roster"] == "clodsire" and c["opponent_shields"] == 1
        ]
        self.assertEqual(len(target_case), 1)
        with patch("tools.evaluate_rl_azumarill_sensitivity.window_cases", return_value=target_case):
            report = evaluate_sensitivity(
                windows=(WINDOWS[0],),
                opponent_policies=OPPONENT_POLICIES,
                own_continuations=("cpu",),
            )
        rows = {row["opponent_policy"]: row for row in report["cases"]}
        self.assertEqual(set(rows), set(OPPONENT_POLICIES))
        base_state = rows["cpu_always"]["public_state"]
        for pol in OPPONENT_POLICIES:
            self.assertEqual(rows[pol]["public_state"], base_state)
        self.assertTrue(rows["cpu_always"]["play_rough"]["shielded"])
        self.assertTrue(rows["cpu_always"]["hydro_pump"]["shielded"])
        self.assertFalse(rows["save_high_hp"]["play_rough"]["shielded"])
        self.assertFalse(rows["save_high_hp"]["hydro_pump"]["shielded"])
        self.assertEqual(
            (rows["save_high_hp"]["play_rough"]["reward"], rows["save_high_hp"]["hydro_pump"]["reward"]),
            (-1, 1),
        )
        self.assertEqual(
            rows["seeded_mixed_50"]["play_rough"]["shielded"],
            rows["seeded_mixed_50"]["hydro_pump"]["shielded"],
        )
        serialized = json.dumps(report)
        for forbidden in ("handoff", "audit", "randomness", "decisions"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_frozen_rl_continuation_does_not_update_weights_and_uses_only_public_views(self):
        slice_cases = [
            c for c in window_cases(WINDOWS[0])
            if c["seed"] == 1300012 and (
                (c["role"] == "lead" and c["roster"] == "clodsire" and c["opponent_shields"] == 1)
                or (c["role"] == "closer" and c["roster"] == "clodsire_skarmory")
            )
        ]
        self.assertEqual(len(slice_cases), 2)
        with patch("tools.evaluate_rl_azumarill_sensitivity.window_cases", return_value=slice_cases):
            report = evaluate_sensitivity(
                windows=(WINDOWS[0],),
                opponent_policies=("cpu_always",),
                own_continuations=("rl_v2_guarded",),
                train_episodes=4,
            )
        self.assertTrue(report["policy_snapshot_unchanged"])
        self.assertEqual(report["training"]["episodes"], 4)
        self.assertEqual(len(report["cases"]), 2)
        for row in report["cases"]:
            self.assertIn("rl_stats", row)
            self.assertIn("post_fork_nontrivial_decisions", row["rl_stats"]["play_rough"])
            self.assertIn("learned_state_hits", row["rl_stats"]["play_rough"])
        serialized = json.dumps(report)
        for forbidden in ("handoff", "audit", "randomness", "decisions"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_worker_rejects_invalid_opponent_policy_and_exits_cleanly(self):
        sample = window_cases(WINDOWS[0])[0]
        with _SensitivityWorkerTransport(ROOT / "vendor/pvpoke", timeout=5.0) as worker:
            with self.assertRaises(NativeStepError):
                worker.reset(
                    sample["handoff"], seed=sample["seed"],
                    shields=(2, 1), opponent_policy="cheating_policy",
                )
            self.assertIsNone(worker._proc)
