"""Regression tests for fixed-150s CPU vs frozen public-RL continuation study."""
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_switch_150s import WINDOWS as CPU_150S_WINDOWS
from tools.evaluate_rl_azumarill_switch_clock import WINDOWS as CLOCK_WINDOWS
from tools.evaluate_rl_azumarill_switch_rl_150s import (
    OWN_CONTINUATIONS, TRAIN_EPISODES, TRAIN_SEED, WINDOWS,
    evaluate_rl_switch_150s, window_cases,
)
from tools.evaluate_rl_azumarill_switch_strata import WINDOWS as NATURAL_WINDOWS
from tools.evaluate_rl_azumarill_switch_synthetic import WINDOWS as SYNTHETIC_WINDOWS
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility,
)
from tools.run_rl_mc import GAME_DATA


class AzumarillSwitchRl150sTests(unittest.TestCase):
    def test_predeclared_windows_training_seeds_and_ruleset_separation(self):
        self.assertEqual(WINDOWS, (2400012, 2401012))
        prior = {window + offset for window in NATURAL_WINDOWS for offset in range(9)}
        for group in (SYNTHETIC_WINDOWS, CLOCK_WINDOWS, CPU_150S_WINDOWS):
            prior.update(window + offset for window in group for offset in range(6))

        train_seeds = set(range(TRAIN_SEED, TRAIN_SEED + TRAIN_EPISODES))
        self.assertTrue(train_seeds.isdisjoint(prior))

        with self.assertRaises(ValueError):
            window_cases(CPU_150S_WINDOWS[0])

        seen = set(prior) | train_seeds
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 72)
            seeds = {row["seed"] for row in cases}
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertTrue(seeds.isdisjoint(seen))
            seen.update(seeds)

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

    def test_frozen_rl_continuations_preserve_snapshot_and_separate_timeouts_from_ko(self):
        slice_cases = [
            row for row in window_cases(WINDOWS[0])
            if row["roster"] == "azumarill_fearow_wigglytuff"
            and row["seed"] == WINDOWS[0] + 3
            and row["handoff"]["own_team"][1]["species"] == "quagsire"
            and row["condition"] in ("base", "shield_1")
        ]
        self.assertEqual(len(slice_cases), 2)

        with patch("tools.evaluate_rl_azumarill_switch_rl_150s.window_cases", return_value=slice_cases):
            report = evaluate_rl_switch_150s(
                windows=(WINDOWS[0],),
                own_continuations=OWN_CONTINUATIONS,
                train_episodes=4,
            )

        self.assertTrue(report["policy_snapshot_unchanged"])
        self.assertEqual(report["training"]["episodes"], 4)
        self.assertEqual(report["remaining_seconds"], 150)

        by_cont = report["summary"]["by_continuation"]
        for cont in OWN_CONTINUATIONS:
            overall = by_cont[cont]["overall"]
            ob = overall["outcome_breakdown"]
            ko = overall["ko_reward_comparison"]
            self.assertEqual(ob["both_ko_decided"], ko["both_completed"])
            self.assertEqual(
                ob["both_timeout"] + ob["one_sided_ko_decided"] + ob["both_ko_decided"],
                2,
            )

        # In base & shield_1 with HP=20%, rl_v2_cpu_fallback matches CPU's <25% shield_no on unseen states,
        # whereas rl_v2_priority prioritizes shield_yes on unseen shield_1 states.
        self.assertEqual(by_cont["cpu"]["by_condition"]["shield_1"]["low_hp_shield_decisions"]["shield_yes"], 0)
        self.assertGreaterEqual(
            by_cont["rl_v2_priority"]["by_condition"]["shield_1"]["low_hp_shield_decisions"]["shield_yes"], 1
        )
        self.assertEqual(
            by_cont["rl_v2_cpu_fallback"]["overall"]["rl_diagnostics"]["diverged_on_unseen_states"], 0
        )

        for row in report["cases"]:
            self.assertEqual(row["public_state"]["elapsed_ms"], 90000)

        serialized = json.dumps(report)
        for forbidden in ("handoff", "audit", "randomness", "decisions", "opponent_team", "energy_points", "hp_points"):
            self.assertNotIn(f'"{forbidden}"', serialized)
