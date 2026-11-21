"""Make the synthetic comparison reproducible and keep censoring explicit."""
import json
import unittest

from tools.evaluate_rl_azumarill_switch_strata import ARMS, WINDOWS as NATURAL_WINDOWS
from tools.evaluate_rl_azumarill_switch_synthetic import CONDITIONS, WINDOWS, summarize_traces, window_cases
from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_quagsire import run_cases

WORKER = "rl_azumarill_switch_synthetic.cjs"


class AzumarillSyntheticSwitchTests(unittest.TestCase):
    def test_fixed_windows_and_one_factor_at_a_time(self):
        seen = {window + offset for window in NATURAL_WINDOWS for offset in range(9)}
        teams = {
            "azumarill_clodsire_skarmory": ["azumarill", "clodsire", "skarmory"],
            "azumarill_fearow_wigglytuff": ["azumarill", "fearow", "wigglytuff"],
        }
        for window in WINDOWS:
            cases = window_cases(window)
            self.assertEqual(len(cases), 72)
            seeds = {row["seed"] for row in cases}
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertTrue(seeds.isdisjoint(seen))
            seen.update(seeds)
            for start in range(0, len(cases), len(CONDITIONS)):
                batch = cases[start:start + len(CONDITIONS)]
                self.assertEqual([(r["condition"], r["hp_percent"], r["own_shields"])
                                  for r in batch], list(CONDITIONS))
                fixed = [{k: v for k, v in r.items() if k not in
                          ("condition", "hp_percent", "own_shields")} for r in batch]
                self.assertTrue(all(r == fixed[0] for r in fixed))
                base = batch[0]
                self.assertEqual(base["opponent_shields"], 0)
                self.assertEqual([p["species"] for p in base["handoff"]["opponent_team"]],
                                 teams[base["roster"]])

    def test_native_fork_and_first_hit_use_the_fixed_synthetic_state(self):
        cases = window_cases(WINDOWS[0])
        rows = run_cases([cases[0], cases[1], cases[4]], worker=WORKER)
        for row in rows:
            self.assertEqual(row["public_state"]["elapsed_ms"], 150000)
            self.assertEqual(row["public_state"]["opponent_shields"], 0)
            row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
            for arm in ARMS:
                self.assertTrue(row[arm]["action_resolved"])
                self.assertEqual((row[arm]["outcome"], row[arm]["reward"]), ("timeout", None))
                hit = row["traces"][arm]["first_opponent_charge"]
                self.assertEqual((hit["move"], hit["target"], hit["step_end_ms"]),
                                 ("ICE_BEAM", row["switch_targets"][arm], 160000))
        base, hp, shield = rows
        self.assertEqual(base["reserve_hp_bands"]["quagsire"], 0)
        self.assertEqual(hp["reserve_hp_bands"]["quagsire"], 1)
        self.assertEqual(base["traces"][ARMS[1]]["next_kos"][0]["step_end_ms"], 160000)
        self.assertGreater(hp["traces"][ARMS[1]]["next_kos"][0]["step_end_ms"], 160000)
        self.assertTrue(shield["traces"][ARMS[0]]["first_opponent_charge"]["shielded"])
        self.assertFalse(shield["traces"][ARMS[1]]["first_opponent_charge"]["shielded"])
        summary = summarize_traces([base])
        self.assertEqual(summary["timeouts"]["both"], 1)
        self.assertEqual(summary["ko_reward_comparison"]["both_completed"], 0)
        self.assertIsNone(summary["ko_reward_comparison"]["mean_reward_delta"])
        self.assertEqual(summary["next_events"][ARMS[1]]["first_ko_in_same_step_as_first_charge"], 1)
        for field in ("audit", "opponent_team", "energy_points", "hp_points", "decisions"):
            self.assertNotIn(f'"{field}"', json.dumps(rows))

    def test_worker_rejects_combining_an_hp_and_shield_change(self):
        base = window_cases(WINDOWS[0])[0]
        with self.assertRaisesRegex(RuntimeError, "Unexpected synthetic switch condition"):
            run_cases([{**base, "hp_percent": 40, "own_shields": 1}], worker=WORKER)
