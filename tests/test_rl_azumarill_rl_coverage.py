"""Regression tests for Azumarill CPU-fallback overlay and 100-episode RL coverage."""
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill import WINDOWS as AZU_WINDOWS, window_cases as azu_cases
from tools.evaluate_rl_azumarill_rl_coverage import (
    LARGE_EPISODES, OWN_CONTINUATIONS, TRAIN_SEED, WINDOWS,
    CpuFallbackMonteCarloPolicy, evaluate_rl_coverage, window_cases,
)
from tools.evaluate_rl_azumarill_sensitivity import (
    TRAIN_EPISODES as SENS_TRAIN_EPISODES,
    TRAIN_SEED as SENS_TRAIN_SEED,
    WINDOWS as SENS_WINDOWS,
    window_cases as sens_cases,
)
from tools.evaluate_rl_skarmory import WINDOWS as SKARMORY_WINDOWS, window_cases as skarmory_cases
from tools.evaluate_rl_wigglytuff import HISTORICAL, HOLDOUT, SWIFT_HOLDOUT, TIMING_HOLDOUT
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability,
    evaluate_tournament_eligibility,
)
from tools.rl_wait_guard import GuardedWaitMonteCarloPolicy
from tools.run_rl_mc import GAME_DATA


def _sample_tactics_view(*, phase="turn", legal=("wait", "fast", "charge_0", "charge_1"), hp=100, max_hp=196):
    return {
        "schema": "rl-native-3v3-v1",
        "ruleset_id": "play-pokemon-worlds-2026-gl",
        "phase": phase,
        "turn": 24,
        "elapsed_ms": 20500,
        "own": {
            "active_slot": 0,
            "shields": 1,
            "switch_timer_ms": 0,
            "team": [
                {
                    "species": "azumarill", "hp": hp, "max_hp": max_hp,
                    "energy_points": 80, "buffs": [0, 0], "cooldown_ms": 0,
                    "fast_move": "BUBBLE",
                    "charged_moves": [
                        {"move_id": "PLAY_ROUGH", "energy_cost": 60},
                        {"move_id": "HYDRO_PUMP", "energy_cost": 75},
                    ],
                },
                {
                    "species": "wigglytuff", "hp": 224, "max_hp": 224,
                    "energy_points": 0, "buffs": [0, 0], "cooldown_ms": 0,
                    "fast_move": "CHARM",
                    "charged_moves": [
                        {"move_id": "ICY_WIND", "energy_cost": 45},
                        {"move_id": "SWIFT", "energy_cost": 35},
                    ],
                },
                {
                    "species": "fearow", "hp": 140, "max_hp": 140,
                    "energy_points": 0, "buffs": [0, 0], "cooldown_ms": 0,
                    "fast_move": "PECK",
                    "charged_moves": [
                        {"move_id": "DRILL_PECK", "energy_cost": 40},
                        {"move_id": "DRILL_RUN", "energy_cost": 45},
                    ],
                },
            ],
        },
        "opponent": {
            "active_species": "clodsire",
            "shields": 1,
            "revealed": [
                {"species": "clodsire", "fainted": False, "hp_bucket_5pct": 15, "seen_moves": []},
            ],
        },
        "legal_actions": list(legal),
    }


class AzumarillRlCoverageTests(unittest.TestCase):
    def test_predeclared_windows_and_training_seeds_are_disjoint_from_all_prior_studies(self):
        prior_seeds = (
            set(HISTORICAL) | set(HOLDOUT) | set(TIMING_HOLDOUT) | set(SWIFT_HOLDOUT)
            | {row["seed"] for win in SKARMORY_WINDOWS for row in skarmory_cases(win)}
            | {row["seed"] for win in AZU_WINDOWS for row in azu_cases(win)}
            | set(range(SENS_TRAIN_SEED, SENS_TRAIN_SEED + SENS_TRAIN_EPISODES))
            | {row["seed"] for win in SENS_WINDOWS for row in sens_cases(win)}
        )
        train_seeds = set(range(TRAIN_SEED, TRAIN_SEED + LARGE_EPISODES))
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

    def test_cpu_fallback_policy_eliminates_unseen_divergence_and_preserves_learned_overrides(self):
        base = CpuFallbackMonteCarloPolicy(seed=1)
        low_shield = _sample_tactics_view(phase="shield", legal=("shield_yes", "shield_no"), hp=40, max_hp=196)
        priority_shield = GuardedWaitMonteCarloPolicy.restore(base.snapshot(), seed=1)
        self.assertEqual(priority_shield.choose(low_shield, epsilon=0.0)[0], "shield_yes")
        self.assertEqual(base.choose(low_shield, epsilon=0.0)[0], "shield_no")

        low_switch = _sample_tactics_view(phase="turn", legal=("wait", "fast", "switch_1"), hp=40, max_hp=196)
        self.assertEqual(base.choose(low_switch, epsilon=0.0)[0], "switch_1")

        # Seen state where charge_1 strictly beats charge_0 must override choose_team_cpu.
        charge_view = _sample_tactics_view(phase="turn", legal=("wait", "fast", "charge_0", "charge_1"), hp=150)
        _, key, _ = base.encode_state(charge_view)
        snap = base.snapshot()
        snap["values"]["tactics"][key] = {"charge_0": [2, -1.0], "charge_1": [2, 1.0]}
        learned = CpuFallbackMonteCarloPolicy.restore(snap, seed=2)
        before = json.dumps(learned.snapshot(), sort_keys=True)
        self.assertEqual(learned.choose(charge_view, epsilon=0.0)[0], "charge_1")
        self.assertEqual(before, json.dumps(learned.snapshot(), sort_keys=True))

        # Unproven voluntary wait remains guarded even if fast has a negative mean.
        wait_view = _sample_tactics_view(phase="turn", legal=("wait", "fast"), hp=150)
        _, wkey, _ = learned.encode_state(wait_view)
        snap2 = json.loads(before)
        snap2["values"]["tactics"][wkey] = {"fast": [1, -1.0]}
        guarded = CpuFallbackMonteCarloPolicy.restore(snap2, seed=2)
        before_guarded = json.dumps(guarded.snapshot(), sort_keys=True)
        self.assertEqual(guarded.choose(wait_view, epsilon=0.0)[0], "fast")
        self.assertEqual(before_guarded, json.dumps(guarded.snapshot(), sort_keys=True))

    def test_paired_checkpoints_and_frozen_evaluation_zero_unseen_divergence(self):
        slice_cases = [
            c for c in window_cases(WINDOWS[0])
            if c["seed"] == 1400012 and (
                (c["role"] == "lead" and c["roster"] == "clodsire" and c["opponent_shields"] == 1)
                or (c["role"] == "closer" and c["roster"] == "clodsire_skarmory")
            )
        ]
        self.assertEqual(len(slice_cases), 2)
        with patch("tools.evaluate_rl_azumarill_rl_coverage.window_cases", return_value=slice_cases):
            report = evaluate_rl_coverage(
                windows=(WINDOWS[0],),
                opponent_policies=("cpu_always",),
                own_continuations=OWN_CONTINUATIONS,
                small_episodes=2,
                large_episodes=6,
            )
        self.assertEqual(report["policy_snapshots_unchanged"], {"small": True, "large": True})
        self.assertEqual((report["training"]["small"]["episodes"], report["training"]["large"]["episodes"]), (2, 6))
        by_reg = report["summary"]["by_regime"]
        self.assertEqual(
            by_reg["cpu_always / rl_v2_cpu_fallback_small"]["rl_diagnostics"]["diverged_on_unseen_states"], 0
        )
        self.assertEqual(
            by_reg["cpu_always / rl_v2_cpu_fallback_large"]["rl_diagnostics"]["diverged_on_unseen_states"], 0
        )
        self.assertIn("cpu_always", report["summary"]["decomposition"])
        serialized = json.dumps(report)
        for forbidden in ("handoff", "audit", "randomness", "decisions"):
            self.assertNotIn(f'"{forbidden}"', serialized)
