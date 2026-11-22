"""Test that switch strata use pre-fork information and keep draws and timeouts distinct."""
import unittest

from tools import evaluate_rl_azumarill_three_way as previous
from tools.evaluate_rl_azumarill_mirror import run_mirror_cases
from tools.evaluate_rl_azumarill_switch_strata import (
    ARMS, WINDOWS, only_winning_switch, report, state_bands, summarize, window_cases,
)


def result(outcome, reward):
    return {"outcome": outcome, "reward": reward, "action_resolved": True}


class AzumarillSwitchStrataTests(unittest.TestCase):
    def test_new_rosters_and_seed_windows_are_fixed(self):
        old = {row["seed"] for w in previous.WINDOWS for row in previous.window_cases(w)}
        expected = {
            "skarmory_wigglytuff": ["skarmory", "azumarill", "wigglytuff"],
            "clodsire_fearow": ["clodsire", "azumarill", "fearow"],
            "primeape_wigglytuff": ["primeape", "azumarill", "wigglytuff"],
        }
        for window in WINDOWS:
            cases = window_cases(window)
            seeds = {row["seed"] for row in cases}
            self.assertTrue(seeds.isdisjoint(old))
            old.update(seeds)
            self.assertEqual(seeds, set(range(window, window + 9)))
            self.assertEqual(len(cases), 108)
            for name, trio in expected.items():
                matching = [row for row in cases if row["roster"] == name]
                self.assertEqual(len(matching), 36)
                self.assertTrue(all([p["species"] for p in r["handoff"]["opponent_team"]] == trio
                                    for r in matching))

    def test_clock_cutoffs_and_both_shield_counts(self):
        row = {
            "reserve_hp_bands": {"skarmory": 3, "quagsire": 0},
            "own_shields": 2, "public_state": {"opponent_shields": 1},
        }
        for elapsed, band in ((210000, "0–30s"), (209500, ">30–60s"),
                              (180000, ">30–60s"), (179500, ">60s")):
            row["public_state"]["elapsed_ms"] = elapsed
            self.assertEqual(state_bands(row), {
                "skarmory_hp": "75–100%", "quagsire_hp": "<25%",
                "own_shields": 2, "opponent_shields": 1, "remaining_clock": band,
            })

    def test_draw_and_timeout_are_not_a_one_sided_win_or_paired_reward(self):
        timeout = result("timeout", None)
        draw = result("simultaneous_ko", 0)
        win = result("self_ko_win", 1)
        draw_timeout = {"public_state": {}, ARMS[0]: draw, ARMS[1]: timeout}
        both = {"public_state": {}, ARMS[0]: draw, ARMS[1]: win}
        self.assertIsNone(only_winning_switch(draw_timeout))
        summary = summarize([draw_timeout, both, {"excluded": "only_one_switch_available"}])
        self.assertEqual(summary["timeouts"], {ARMS[0]: 0, ARMS[1]: 1, "both": 0})
        self.assertEqual(summary["two_switches_in_choice_set"], 2)
        self.assertEqual(summary["ko_reward_comparison"]["both_completed"], 1)
        self.assertEqual(summary["ko_reward_comparison"]["mean_reward_delta"], 1)

    def test_known_quagsire_only_win_exports_only_prefork_bands_and_public_trace(self):
        specs = [row for row in previous.window_cases(1900012)
                 if row["seed"] == 1900015 and row["opponent_shields"] == 0
                 and row["handoff"]["own_team"][0]["species"] == "quagsire_shadow"
                 and row["handoff"]["own_team"][0]["charged2"] == "STONE_EDGE"]
        rows = run_mirror_cases(specs, mode="mirror_three_way")
        fork, = [row for row in rows if row["opening_move"] == "STONE_EDGE"]
        self.assertEqual(fork["reserve_hp_bands"], {"skarmory": 3, "quagsire": 0})
        trace, = report([fork])["one_sided_ko_win_traces"]
        self.assertEqual(trace["bands"]["own_shields"], 0)
        self.assertEqual(trace["bands"]["opponent_shields"], 0)
        self.assertEqual(trace["only_winning_switch"], ARMS[1])
        quag = trace["arms"][ARMS[1]]
        self.assertEqual(quag["first_opponent_charge"]["target"], "quagsire_shadow")
        self.assertEqual(quag["next_kos"][0]["species"], "quagsire_shadow")
        self.assertEqual(quag["remaining_at_battle_end_ms"], 500)
