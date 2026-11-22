"""Verify fixed-150s HP/shield single-factor study setup and timeout/KO separation."""
import json
import unittest

from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_switch_150s import (
    BUILDS,
    CONDITIONS,
    REMAINING_SECONDS,
    ROSTERS,
    WINDOWS,
    WORKER,
    WORKER_MODE,
    window_cases,
)
from tools.evaluate_rl_azumarill_switch_clock import (
    WINDOWS as CLOCK_WINDOWS,
    summarize_clock_group,
)
from tools.evaluate_rl_azumarill_switch_strata import ARMS, WINDOWS as NATURAL_WINDOWS
from tools.evaluate_rl_azumarill_switch_synthetic import (
    BUILDS as SYNTHETIC_BUILDS,
    CONDITIONS as SYNTHETIC_CONDITIONS,
    ROSTERS as SYNTHETIC_ROSTERS,
    WINDOWS as SYNTHETIC_WINDOWS,
)
from tools.evaluate_rl_quagsire import run_cases


class AzumarillSynthetic150sSwitchTests(unittest.TestCase):
    def test_fixed_windows_rosters_and_one_factor_at_150s(self):
        self.assertEqual(WINDOWS, (2300012, 2301012))
        self.assertEqual(ROSTERS, SYNTHETIC_ROSTERS)
        self.assertEqual(BUILDS, SYNTHETIC_BUILDS)
        self.assertEqual(CONDITIONS, SYNTHETIC_CONDITIONS)
        self.assertEqual(REMAINING_SECONDS, 150)

        seen = {window + offset for window in NATURAL_WINDOWS for offset in range(9)}
        seen.update(window + offset for window in SYNTHETIC_WINDOWS for offset in range(6))
        seen.update(window + offset for window in CLOCK_WINDOWS for offset in range(6))
        teams = {
            "azumarill_clodsire_skarmory": ["azumarill", "clodsire", "skarmory"],
            "azumarill_fearow_wigglytuff": ["azumarill", "fearow", "wigglytuff"],
        }
        with self.assertRaises(ValueError):
            window_cases(CLOCK_WINDOWS[0])

        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 72)
            seeds = {row["seed"] for row in cases}
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertTrue(seeds.isdisjoint(seen))
            seen.update(seeds)
            for start in range(0, len(cases), len(CONDITIONS)):
                batch = cases[start:start + len(CONDITIONS)]
                self.assertEqual(
                    [(row["condition"], row["hp_percent"], row["own_shields"]) for row in batch],
                    list(CONDITIONS),
                )
                fixed = [
                    {k: v for k, v in row.items() if k not in ("condition", "hp_percent", "own_shields")}
                    for row in batch
                ]
                self.assertTrue(all(row == fixed[0] for row in fixed))
                base = batch[0]
                self.assertEqual(base["remaining_seconds"], 150)
                self.assertEqual(base["opponent_shields"], 0)
                self.assertEqual(
                    [p["species"] for p in base["handoff"]["opponent_team"]],
                    teams[base["roster"]],
                )

    def test_native_150s_fork_and_timeout_vs_ko_separation(self):
        cases = window_cases(WINDOWS[0])
        fearow_batch = [row for row in cases if row["roster"] == "azumarill_fearow_wigglytuff"][:6]
        self.assertEqual(
            [(row["hp_percent"], row["own_shields"], row["remaining_seconds"]) for row in fearow_batch],
            [(20, 0, 150), (40, 0, 150), (60, 0, 150), (85, 0, 150), (20, 1, 150), (20, 2, 150)],
        )

        rows = run_cases(fearow_batch, mode=WORKER_MODE, worker=WORKER)
        self.assertEqual([row["reserve_hp_bands"]["quagsire"] for row in rows[:4]], [0, 1, 2, 3])
        for idx, row in enumerate(rows):
            self.assertEqual(row["public_state"]["elapsed_ms"], 90000)
            self.assertEqual(row["remaining_seconds"], 150)
            self.assertEqual(row["public_state"]["opponent_shields"], 0)
            row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
            for arm in ARMS:
                self.assertTrue(row[arm]["action_resolved"])
                hit = row["traces"][arm]["first_opponent_charge"]
                self.assertEqual(
                    (hit["move"], hit["target"], hit["step_end_ms"]),
                    ("ICE_BEAM", row["switch_targets"][arm], 100000),
                )
            single = summarize_clock_group([row])
            expected_quagsire_faint = 1 if idx in (0, 4, 5) else 0
            self.assertEqual(
                single["next_events"][ARMS[0]]["first_ko_in_same_step_as_first_charge"], 0
            )
            self.assertEqual(
                single["next_events"][ARMS[1]]["first_ko_in_same_step_as_first_charge"],
                expected_quagsire_faint,
            )
            if idx in (4, 5):
                self.assertTrue(row["traces"][ARMS[0]]["first_opponent_charge"]["shielded"])
                self.assertFalse(row["traces"][ARMS[1]]["first_opponent_charge"]["shielded"])

            both_ko = (
                row[ARMS[0]]["reward"] is not None and row[ARMS[1]]["reward"] is not None
            )
            for arm in ARMS:
                if row[arm]["outcome"] == "timeout":
                    self.assertIsNone(row[arm]["reward"])
                    self.assertEqual(single["timeouts"][arm], 1)
                else:
                    self.assertIn(row[arm]["reward"], (-1, 0, 1))
                    self.assertEqual(single["timeouts"][arm], 0)
            self.assertEqual(single["outcome_breakdown"]["both_ko_decided"], int(both_ko))
            self.assertEqual(single["ko_reward_comparison"]["both_completed"], int(both_ko))
            if both_ko:
                self.assertEqual(
                    single["ko_reward_comparison"]["mean_reward_delta"],
                    row[ARMS[1]]["reward"] - row[ARMS[0]]["reward"],
                )
            else:
                self.assertIsNone(single["ko_reward_comparison"]["mean_reward_delta"])

        pooled = summarize_clock_group(rows)
        both_ko_rows = [
            row for row in rows
            if row[ARMS[0]]["reward"] is not None and row[ARMS[1]]["reward"] is not None
        ]
        self.assertEqual(pooled["outcome_breakdown"]["both_ko_decided"], len(both_ko_rows))
        self.assertEqual(pooled["ko_reward_comparison"]["both_completed"], len(both_ko_rows))
        self.assertEqual(
            pooled["outcome_breakdown"]["both_timeout"]
            + pooled["outcome_breakdown"]["one_sided_ko_decided"]
            + pooled["outcome_breakdown"]["both_ko_decided"],
            len(rows),
        )
        if both_ko_rows:
            deltas = [row[ARMS[1]]["reward"] - row[ARMS[0]]["reward"] for row in both_ko_rows]
            self.assertAlmostEqual(
                pooled["ko_reward_comparison"]["mean_reward_delta"],
                sum(deltas) / len(deltas),
            )
        else:
            self.assertIsNone(pooled["ko_reward_comparison"]["mean_reward_delta"])

        for field in ("audit", "opponent_team", "energy_points", "hp_points", "decisions"):
            self.assertNotIn(f'"{field}"', json.dumps(rows))

    def test_worker_clock_150s_mode_guards(self):
        base = window_cases(WINDOWS[0])[0]
        with self.assertRaisesRegex(RuntimeError, "Unexpected synthetic switch condition"):
            run_cases(
                [{**base, "hp_percent": 40, "own_shields": 1, "remaining_seconds": 150}],
                mode=WORKER_MODE, worker=WORKER,
            )
        for bad_clock in (90, 120):
            with self.assertRaisesRegex(RuntimeError, "Unexpected synthetic switch condition"):
                run_cases(
                    [{**base, "remaining_seconds": bad_clock}],
                    mode=WORKER_MODE, worker=WORKER,
                )
        with self.assertRaisesRegex(RuntimeError, "Invalid synthetic study input"):
            run_cases([base], mode="invalid_mode", worker=WORKER)
