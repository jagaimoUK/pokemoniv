"""Regression tests for the matched, offline Swift study."""
import json
import unittest

from tools.evaluate_rl_wigglytuff import (
    ALTERNATE_MATCHUPS, HISTORICAL, HOLDOUT, TIMING_HOLDOUT,
    run_cases, summarize, summarize_timing,
)


class WigglytuffStudyTests(unittest.TestCase):
    def test_replays_old_results_and_detects_damage_after_exact_entry(self):
        a, b = run_cases((500014, 701014))
        for row in (a, b):
            self.assertEqual((row["stay"]["reward"], row["switch"]["reward"]), (1, -1))
            self.assertEqual((len(row["stay"]["swift"]), len(row["switch"]["swift"])), (2, 1))
            self.assertEqual(row["switch"]["switch_at_fork"], "primeape")
            switched = row["switch"]["entry"]
            self.assertEqual((switched["hp"], switched["energy_points"]), (224, 0))
            self.assertEqual((switched["self_shields"], switched["opponent_shields"]), (0, 0))
            for grant, intervention in row["interventions"].items():
                self.assertEqual(intervention["entry"], {**switched, "energy_added": int(grant)})
                self.assertEqual(intervention["reward"], -1)
            self.assertIsNone(row["switch"]["second_swift_ready"])
            self.assertEqual(len(row["interventions"]["16"]["swift"]), 2)
        self.assertEqual(a["switch"]["first_active"]["hp"], 160)
        self.assertEqual([m["move"] for m in a["switch"]["moves_before_first_active"]], ["SWIFT"])
        self.assertTrue(b["switch"]["entry"]["forced"])
        self.assertEqual(b["switch"]["entry"]["switch_timer_ms"], 15500)
        for name in ("handoff", "randomness", "state", "decisions", "studied_entry"):
            self.assertNotIn(f'"{name}"', json.dumps((a, b)))

    def test_cohorts_are_fixed_and_disjoint(self):
        self.assertEqual(HISTORICAL, (500014, 500015, 501015, 701014))
        self.assertEqual(len(set(HOLDOUT)), 12)
        self.assertFalse(set(HOLDOUT) & set(HISTORICAL))
        self.assertEqual(len(set(TIMING_HOLDOUT)), 12)
        self.assertFalse(set(TIMING_HOLDOUT) & (set(HISTORICAL) | set(HOLDOUT)))
        self.assertEqual(len(ALTERNATE_MATCHUPS), len(TIMING_HOLDOUT))
        self.assertTrue(all(3 in trio and lead in trio for trio, lead in ALTERNATE_MATCHUPS))

    def test_second_swift_and_rewards_are_compared_only_when_both_complete(self):
        short = {"reward": -1, "swift": [{"shielded": False}]}
        second = {"reward": -1, "swift": [{"shielded": False}] * 2}
        rows = [
            {"switch": short, "interventions": {"8": second, "16": second}},
            {"switch": short, "interventions": {"8": {**second, "reward": None}}},
            {"switch": short, "interventions": {}},
        ]
        report = summarize(rows)
        self.assertEqual(report["8"]["matched_entries"], 2)
        self.assertEqual(report["8"]["both_completed"], 1)
        self.assertEqual(report["8"]["new_second_unshielded_swift"], 1)
        self.assertEqual(report["8"]["mean_reward_delta"], 0)
        self.assertEqual(report["16"]["matched_entries"], 1)

    def test_native_timing_delay_retries_once_and_tracks_fallback(self):
        good, cooldown, replacement, forced = run_cases(
            (500014, 500015, 900017, 701014), timing_pool="legacy")
        self.assertEqual(good["fork_turn"], 73)
        self.assertEqual(good["immediate"]["opening_fork_turn"], 3)
        self.assertEqual(good["immediate"]["entry_hp_lost"], 64)
        self.assertIsNone(good["immediate"]["second_resolved_swift_ready"])
        self.assertEqual(good["immediate"]["swift"], [{"turn": 90, "shielded": False}])
        for action in ("wait", "fast"):
            arm = good["delayed"][action]
            self.assertEqual(arm["timing"], {"status": "voluntary_switch_resolved",
                                              "attempted_turn": 74, "blocked_at": None})
            self.assertEqual(arm["entry_hp_lost"], 0)
            self.assertEqual(arm["second_resolved_swift_ready"]["turn"], 103)
            self.assertEqual([move["turn"] for move in arm["swift"]], [90, 103])
            self.assertEqual(arm["reward"], good["immediate"]["reward"])
        fast = cooldown["delayed"]["fast"]
        self.assertEqual(fast["timing"]["status"], "next_switch_illegal")
        self.assertIsNone(fast["timing"]["attempted_turn"])
        self.assertEqual(fast["timing"]["blocked_at"]["cooldown_ms"], 1000)
        self.assertEqual(fast["entry"]["turn"], 73)  # Later entry by the fallback policy.
        for arm in replacement["delayed"].values():
            self.assertEqual(arm["timing"]["status"], "next_switch_illegal")
            self.assertEqual(arm["timing"]["blocked_at"]["phase"], "replace")
            self.assertTrue(arm["entry"]["forced"])
        self.assertEqual(forced, {"seed": 701014, "excluded": "forced_entry"})
        report = summarize_timing((good, cooldown, replacement, forced))
        self.assertEqual(report["eligible"], 3)
        self.assertEqual(report["fast"]["both_completed"], 3)
        self.assertEqual(report["fast"]["both_voluntary_switches_resolved"], 1)
        self.assertEqual(report["fast"]["both_entry_hp_observed_after_voluntary_switches"], 1)

    def test_alternate_native_case_skips_unavailable_fast_delay(self):
        row, = run_cases((900014,), timing_pool="alternate")
        self.assertEqual(set(row["delayed"]), {"wait"})
        self.assertEqual(row["delayed"]["wait"]["timing"]["status"], "voluntary_switch_resolved")
        report = summarize_timing((row,))
        self.assertEqual(report["fast"]["attempted"], 0)
        self.assertIsNone(report["fast"]["both_completed_rate"])

    def test_timing_summary_separates_censored_reward_and_observed_swift(self):
        immediate = {"timing": {"status": "voluntary_switch_resolved"}, "entry_hp_lost": 64,
                     "reward": 1, "outcome": "self_ko_win", "swift": [],
                     "second_resolved_swift_ready": None}
        delayed = {**immediate, "reward": None, "outcome": "timeout", "entry_hp_lost": 0,
                   "swift": [{"shielded": True}, {"shielded": False}],
                   "second_resolved_swift_ready": {"turn": 99}}
        report = summarize_timing([{"immediate": immediate, "delayed": {"wait": delayed}}])["wait"]
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["both_completed"], 0)
        self.assertIsNone(report["mean_reward_delta"])
        self.assertEqual(report["mean_entry_hp_loss_delta"], -64)
        self.assertEqual(report["arms"]["delayed"]["second_swift_legal"], 1)
        self.assertEqual(report["arms"]["delayed"]["second_swift_resolved"], 1)
        self.assertEqual(report["arms"]["delayed"]["second_unshielded_swift_resolved"], 0)
