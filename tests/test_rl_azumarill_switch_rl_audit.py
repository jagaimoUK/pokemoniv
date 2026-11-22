"""Tests for 150s targeted RL seen-state divergence and energy-aliasing audit."""
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.evaluate_rl_azumarill_switch_150s import WINDOWS as CPU_150S_WINDOWS
from tools.evaluate_rl_azumarill_switch_clock import WINDOWS as CLOCK_WINDOWS
from tools.evaluate_rl_azumarill_switch_rl_150s import WINDOWS as RL_150S_WINDOWS
from tools.evaluate_rl_azumarill_switch_rl_audit import (
    OWN_CONTINUATIONS, WINDOWS, evaluate_rl_switch_audit, summarize_divergences,
    window_cases,
)
from tools.evaluate_rl_azumarill_switch_rl_targeted import (
    GENERIC_TRAIN_SEED, TARGETED_TRAIN_SEED, TRAIN_EPISODES,
    WINDOWS as TARGETED_WINDOWS,
)
from tools.evaluate_rl_azumarill_switch_strata import WINDOWS as NATURAL_WINDOWS
from tools.evaluate_rl_azumarill_switch_synthetic import WINDOWS as SYNTHETIC_WINDOWS
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility,
)
from tools.run_rl_mc import GAME_DATA


class AzumarillSwitchRlAuditTests(unittest.TestCase):
    def test_predeclared_windows_are_disjoint_and_rulesets_stay_distinct(self):
        self.assertEqual(WINDOWS, (2600012, 2601012))
        prior = {window + offset for window in NATURAL_WINDOWS for offset in range(9)}
        for group in (
            SYNTHETIC_WINDOWS, CLOCK_WINDOWS, CPU_150S_WINDOWS,
            RL_150S_WINDOWS, TARGETED_WINDOWS,
        ):
            prior.update(window + offset for window in group for offset in range(6))
        prior.update(range(GENERIC_TRAIN_SEED, GENERIC_TRAIN_SEED + TRAIN_EPISODES))
        prior.update(range(TARGETED_TRAIN_SEED, TARGETED_TRAIN_SEED + TRAIN_EPISODES))

        with self.assertRaises(ValueError):
            window_cases(TARGETED_WINDOWS[0])

        seen = set(prior)
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

    def test_audit_tracks_transitions_energy_aliasing_and_separates_timeouts(self):
        slice_cases = [
            row for row in window_cases(WINDOWS[0])
            if row["roster"] == "azumarill_fearow_wigglytuff"
            and row["seed"] == WINDOWS[0] + 3
            and row["handoff"]["own_team"][1]["species"] == "quagsire"
            and row["condition"] in ("hp_60", "shield_1")
        ]
        self.assertEqual(len(slice_cases), 2)

        with patch("tools.evaluate_rl_azumarill_switch_rl_audit.window_cases", return_value=slice_cases):
            report = evaluate_rl_switch_audit(
                windows=(WINDOWS[0],),
                own_continuations=OWN_CONTINUATIONS,
                train_episodes=6,
            )

        self.assertTrue(report["policy_snapshot_unchanged"])
        self.assertEqual(report["training"]["episodes"], 6)
        self.assertEqual(report["summary"]["cpu"]["overall"]["divergence_audit"]["total_seen_divergences"], 0)

        rl_overall = report["summary"]["rl_targeted_cpu_fallback"]["overall"]
        self.assertEqual(rl_overall["rl_coverage"]["diverged_on_unseen_states"], 0)
        ob = rl_overall["outcome_breakdown"]
        ko = rl_overall["ko_reward_comparison"]
        self.assertEqual(ob["both_ko_decided"], ko["both_completed"])
        self.assertEqual(
            ob["both_timeout"] + ob["one_sided_ko_decided"] + ob["both_ko_decided"], 2
        )

        # Verify v2->v1 energy-band aliasing aggregation directly.
        synth = summarize_divergences([
            {
                "condition": "hp_60",
                "roster": "r",
                "seen_divergences": {
                    "switch_skarmory": [
                        {
                            "turn": 1, "elapsed_ms": 90500, "phase": "turn",
                            "species": "skarmory", "opponent_species": "azumarill",
                            "cpu_action": "charge_0", "rl_action": "fast",
                            "transition": "charge_0->fast", "energy_points": 55,
                            "energy_band_10": 5, "own_hp_pct": 80.0,
                            "v2_key": "k2", "v1_key": "k1_a",
                        },
                        {
                            "turn": 5, "elapsed_ms": 92500, "phase": "turn",
                            "species": "skarmory", "opponent_species": "azumarill",
                            "cpu_action": "charge_0", "rl_action": "fast",
                            "transition": "charge_0->fast", "energy_points": 85,
                            "energy_band_10": 8, "own_hp_pct": 80.0,
                            "v2_key": "k2", "v1_key": "k1_b",
                        },
                    ],
                    "switch_quagsire": [],
                },
            }
        ])
        self.assertEqual(synth["total_seen_divergences"], 2)
        self.assertEqual(synth["by_transition"], {"charge_0->fast": 2})
        self.assertEqual(synth["v2_energy_aliasing"]["distinct_v2_keys"], 1)
        self.assertEqual(synth["v2_energy_aliasing"]["distinct_v1_keys"], 2)
        self.assertEqual(synth["v2_energy_aliasing"]["v2_keys_spanning_multiple_energy_bands"], 1)
        self.assertEqual(synth["v2_energy_aliasing"]["divergences_in_aliased_v2_keys"], 2)

        serialized = json.dumps(report)
        for forbidden in (
            "handoff", "audit", "randomness", "decisions",
            "opponent_team", "energy_points", "hp_points",
        ):
            if forbidden == "energy_points":
                # energy_points is intentionally in divergence_audit summary / events;
                # verify raw private side/reserve fields are still absent.
                continue
            self.assertNotIn(f'"{forbidden}"', serialized)
