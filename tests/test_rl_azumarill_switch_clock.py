"""Verify the synthetic remaining-clock study design and timeout/KO separation."""
import json
import unittest

from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_switch_clock import (
    BUILDS,
    CONDITIONS,
    ROSTERS,
    WINDOWS,
    summarize_clock_group,
    window_cases,
)
from tools.evaluate_rl_azumarill_switch_strata import ARMS, WINDOWS as NATURAL_WINDOWS
from tools.evaluate_rl_azumarill_switch_synthetic import (
    BUILDS as SYNTHETIC_BUILDS,
    ROSTERS as SYNTHETIC_ROSTERS,
    WINDOWS as SYNTHETIC_WINDOWS,
)
from tools.evaluate_rl_quagsire import run_cases

WORKER = "rl_azumarill_switch_synthetic.cjs"


class AzumarillSyntheticClockSwitchTests(unittest.TestCase):
    def test_fixed_windows_rosters_and_clock_only_variation(self):
        self.assertEqual(WINDOWS, (2200012, 2201012))
        self.assertEqual(ROSTERS, SYNTHETIC_ROSTERS)
        self.assertEqual(BUILDS, SYNTHETIC_BUILDS)

        seen = {window + offset for window in NATURAL_WINDOWS for offset in range(9)}
        seen.update(window + offset for window in SYNTHETIC_WINDOWS for offset in range(6))
        teams = {
            "azumarill_clodsire_skarmory": ["azumarill", "clodsire", "skarmory"],
            "azumarill_fearow_wigglytuff": ["azumarill", "fearow", "wigglytuff"],
        }
        with self.assertRaises(ValueError):
            window_cases(SYNTHETIC_WINDOWS[0])

        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 36)
            seeds = {row["seed"] for row in cases}
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertTrue(seeds.isdisjoint(seen))
            seen.update(seeds)
            for start in range(0, len(cases), len(CONDITIONS)):
                batch = cases[start:start + len(CONDITIONS)]
                self.assertEqual(
                    [(row["condition"], row["remaining_seconds"]) for row in batch],
                    list(CONDITIONS),
                )
                fixed = [
                    {k: v for k, v in row.items() if k not in ("condition", "remaining_seconds")}
                    for row in batch
                ]
                self.assertTrue(all(row == fixed[0] for row in fixed))
                base = batch[0]
                self.assertEqual(base["hp_percent"], 20)
                self.assertEqual(base["own_shields"], 0)
                self.assertEqual(base["opponent_shields"], 0)
                self.assertEqual(
                    [p["species"] for p in base["handoff"]["opponent_team"]],
                    teams[base["roster"]],
                )

    def test_native_clock_fork_separates_timeouts_and_joint_ko_rewards(self):
        cases = window_cases(WINDOWS[0])
        fearow_triple = [row for row in cases if row["roster"] == "azumarill_fearow_wigglytuff"][:3]
        self.assertEqual([row["remaining_seconds"] for row in fearow_triple], [90, 120, 150])

        rows = run_cases(fearow_triple, worker=WORKER)
        expected_elapsed = [150000, 120000, 90000]
        self.assertEqual([row["public_state"]["elapsed_ms"] for row in rows], expected_elapsed)
        self.assertEqual([row["remaining_seconds"] for row in rows], [90, 120, 150])

        for row, fork_ms in zip(rows, expected_elapsed, strict=True):
            self.assertEqual(row["public_state"]["opponent_shields"], 0)
            self.assertEqual(row["own_shields"], 0)
            self.assertEqual(row["reserve_hp_bands"], {"skarmory": 3, "quagsire": 0})
            row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
            for arm in ARMS:
                self.assertTrue(row[arm]["action_resolved"])
                hit = row["traces"][arm]["first_opponent_charge"]
                self.assertEqual(
                    (hit["move"], hit["target"], hit["step_end_ms"]),
                    ("ICE_BEAM", row["switch_targets"][arm], fork_ms + 10000),
                )
            single = summarize_clock_group([row])
            self.assertEqual(
                single["next_events"][ARMS[0]]["first_ko_in_same_step_as_first_charge"], 0
            )
            self.assertEqual(
                single["next_events"][ARMS[1]]["first_ko_in_same_step_as_first_charge"], 1
            )
            both_ko = (
                row[ARMS[0]]["reward"] is not None and row[ARMS[1]]["reward"] is not None
            )
            self.assertEqual(single["ko_reward_comparison"]["both_completed"], int(both_ko))
            self.assertEqual(single["outcome_breakdown"]["both_ko_decided"], int(both_ko))
            for arm in ARMS:
                if row[arm]["outcome"] == "timeout":
                    self.assertIsNone(row[arm]["reward"])
                    self.assertEqual(single["timeouts"][arm], 1)
                else:
                    self.assertIsNotNone(row[arm]["reward"])
                    self.assertEqual(single["timeouts"][arm], 0)
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
        one_sided_rows = [
            row for row in rows
            if (row[ARMS[0]]["reward"] is not None) != (row[ARMS[1]]["reward"] is not None)
        ]
        both_timeout_rows = [
            row for row in rows
            if row[ARMS[0]]["outcome"] == row[ARMS[1]]["outcome"] == "timeout"
        ]
        self.assertEqual(pooled["outcome_breakdown"]["both_ko_decided"], len(both_ko_rows))
        self.assertEqual(pooled["outcome_breakdown"]["one_sided_ko_decided"], len(one_sided_rows))
        self.assertEqual(pooled["outcome_breakdown"]["both_timeout"], len(both_timeout_rows))
        self.assertEqual(pooled["ko_reward_comparison"]["both_completed"], len(both_ko_rows))
        self.assertEqual(pooled["timeouts"]["both"], len(both_timeout_rows))
        for arm in ARMS:
            self.assertEqual(
                pooled["timeouts"][arm],
                sum(row[arm]["outcome"] == "timeout" for row in rows),
            )
        if both_ko_rows:
            deltas = [row[ARMS[1]]["reward"] - row[ARMS[0]]["reward"] for row in both_ko_rows]
            self.assertAlmostEqual(
                pooled["ko_reward_comparison"]["mean_reward_delta"],
                sum(deltas) / len(deltas),
            )
        else:
            self.assertIsNone(pooled["ko_reward_comparison"]["mean_reward_delta"])

        synthetic_split = summarize_clock_group([
            {
                **rows[0],
                ARMS[0]: {**rows[0][ARMS[0]], "outcome": "timeout", "reward": None},
                ARMS[1]: {**rows[0][ARMS[1]], "outcome": "timeout", "reward": None},
            },
            {
                **rows[0],
                ARMS[0]: {**rows[0][ARMS[0]], "outcome": "opponent_ko_win", "reward": -1},
                ARMS[1]: {**rows[0][ARMS[1]], "outcome": "timeout", "reward": None},
            },
            {
                **rows[0],
                ARMS[0]: {**rows[0][ARMS[0]], "outcome": "opponent_ko_win", "reward": -1},
                ARMS[1]: {**rows[0][ARMS[1]], "outcome": "self_ko_win", "reward": 1},
            },
        ])
        self.assertEqual(synthetic_split["outcome_breakdown"]["both_timeout"], 1)
        self.assertEqual(synthetic_split["outcome_breakdown"]["one_sided_ko_decided"], 1)
        self.assertEqual(synthetic_split["outcome_breakdown"]["both_ko_decided"], 1)
        self.assertEqual(synthetic_split["timeouts"]["switch_skarmory"], 1)
        self.assertEqual(synthetic_split["timeouts"]["switch_quagsire"], 2)
        self.assertEqual(synthetic_split["timeouts"]["both"], 1)
        self.assertEqual(synthetic_split["ko_reward_comparison"]["both_completed"], 1)
        self.assertEqual(synthetic_split["ko_reward_comparison"]["alternative_better"], 1)
        self.assertEqual(synthetic_split["ko_reward_comparison"]["mean_reward_delta"], 2)

        for field in ("audit", "opponent_team", "energy_points", "hp_points", "decisions"):
            self.assertNotIn(f'"{field}"', json.dumps(rows))

    def test_worker_rejects_combining_clock_change_with_hp_or_shield_or_invalid_clock(self):
        base = window_cases(WINDOWS[0])[0]
        with self.assertRaisesRegex(RuntimeError, "Unexpected synthetic switch condition"):
            run_cases([{**base, "remaining_seconds": 120, "hp_percent": 40}], worker=WORKER)
        with self.assertRaisesRegex(RuntimeError, "Unexpected synthetic switch condition"):
            run_cases([{**base, "remaining_seconds": 150, "own_shields": 1}], worker=WORKER)
        with self.assertRaisesRegex(RuntimeError, "Unexpected synthetic switch condition"):
            run_cases([{**base, "remaining_seconds": 60}], worker=WORKER)
