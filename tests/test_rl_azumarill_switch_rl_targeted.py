"""Regression tests for targeted mid-battle HP/shield RL pretraining at 150s."""
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_switch_150s import WINDOWS as CPU_150S_WINDOWS
from tools.evaluate_rl_azumarill_switch_clock import WINDOWS as CLOCK_WINDOWS
from tools.evaluate_rl_azumarill_switch_rl_150s import (
    TRAIN_EPISODES as RL_150S_EPISODES,
    TRAIN_SEED as RL_150S_TRAIN_SEED,
    WINDOWS as RL_150S_WINDOWS,
)
from tools.evaluate_rl_azumarill_switch_rl_targeted import (
    GENERIC_TRAIN_SEED, OWN_CONTINUATIONS, TARGETED_TRAIN_SEED, TRAIN_EPISODES,
    WINDOWS, evaluate_rl_switch_targeted, window_cases,
)
from tools.evaluate_rl_azumarill_switch_strata import WINDOWS as NATURAL_WINDOWS
from tools.evaluate_rl_azumarill_switch_synthetic import WINDOWS as SYNTHETIC_WINDOWS
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility,
)
from tools.run_rl_mc import GAME_DATA


class AzumarillSwitchRlTargetedTests(unittest.TestCase):
    def test_predeclared_windows_disjoint_training_seeds_and_ruleset_distinction(self):
        self.assertEqual(WINDOWS, (2500012, 2501012))
        self.assertEqual(GENERIC_TRAIN_SEED, 2500)
        self.assertEqual(TARGETED_TRAIN_SEED, 2600)

        prior = {window + offset for window in NATURAL_WINDOWS for offset in range(9)}
        for group in (SYNTHETIC_WINDOWS, CLOCK_WINDOWS, CPU_150S_WINDOWS, RL_150S_WINDOWS):
            prior.update(window + offset for window in group for offset in range(6))
        prior.update(range(RL_150S_TRAIN_SEED, RL_150S_TRAIN_SEED + RL_150S_EPISODES))

        gen_seeds = set(range(GENERIC_TRAIN_SEED, GENERIC_TRAIN_SEED + TRAIN_EPISODES))
        tgt_seeds = set(range(TARGETED_TRAIN_SEED, TARGETED_TRAIN_SEED + TRAIN_EPISODES))
        self.assertTrue(gen_seeds.isdisjoint(tgt_seeds))
        self.assertTrue(gen_seeds.isdisjoint(prior))
        self.assertTrue(tgt_seeds.isdisjoint(prior))

        with self.assertRaises(ValueError):
            window_cases(RL_150S_WINDOWS[0])

        seen = set(prior) | gen_seeds | tgt_seeds
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 72)
            self.assertTrue(all(row["remaining_seconds"] == 150 for row in cases))
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

    def test_targeted_vs_generic_frozen_eval_tracks_seen_low_hp_overrides_and_privacy(self):
        slice_cases = [
            row for row in window_cases(WINDOWS[0])
            if row["roster"] == "azumarill_fearow_wigglytuff"
            and row["seed"] == WINDOWS[0] + 3
            and row["handoff"]["own_team"][1]["species"] == "quagsire"
            and row["condition"] in ("base", "shield_1")
        ]
        self.assertEqual(len(slice_cases), 2)

        with patch("tools.evaluate_rl_azumarill_switch_rl_targeted.window_cases", return_value=slice_cases):
            report = evaluate_rl_switch_targeted(
                windows=(WINDOWS[0],),
                own_continuations=OWN_CONTINUATIONS,
                train_episodes=6,
            )

        self.assertEqual(report["policy_snapshots_unchanged"], {"generic": True, "targeted": True})
        self.assertEqual(report["training"]["generic"]["episodes"], 6)
        self.assertEqual(report["training"]["targeted"]["episodes"], 6)

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

        for cont in ("rl_generic_cpu_fallback", "rl_targeted_cpu_fallback"):
            overall = by_cont[cont]["overall"]
            self.assertEqual(overall["rl_diagnostics"]["diverged_on_unseen_states"], 0)
            self.assertEqual(overall["low_hp_shield_decisions"]["unseen_overrides_to_yes"], 0)

        shift = report["summary"]["training_shift_comparison"]
        self.assertIn("overall", shift)
        self.assertIn("by_condition", shift)
        self.assertEqual(set(shift["by_condition"]), {"base", "hp_40", "hp_60", "hp_85", "shield_1", "shield_2"})

        for row in report["cases"]:
            self.assertEqual(row["public_state"]["elapsed_ms"], 90000)

        serialized = json.dumps(report)
        for forbidden in (
            "handoff", "audit", "randomness", "decisions",
            "opponent_team", "energy_points", "hp_points",
        ):
            self.assertNotIn(f'"{forbidden}"', serialized)
