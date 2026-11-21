"""Regression tests for the matched, offline Swift study."""
import json
import unittest

from tools.evaluate_rl_wigglytuff import (
    ALTERNATE_MATCHUPS, HISTORICAL, HOLDOUT, SWIFT_ALTERNATE_MATCHUPS, SWIFT_HOLDOUT,
    TIMING_HOLDOUT, charge_stratum, run_cases, summarize, summarize_charge, summarize_timing,
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
        self.assertEqual(len(set(SWIFT_HOLDOUT)), 12)
        self.assertFalse(set(SWIFT_HOLDOUT) & (set(HISTORICAL) | set(HOLDOUT) | set(TIMING_HOLDOUT)))
        self.assertEqual(len(SWIFT_ALTERNATE_MATCHUPS), len(SWIFT_HOLDOUT))
        self.assertTrue(all(1 in trio and lead in trio for trio, lead in SWIFT_ALTERNATE_MATCHUPS))

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

    def test_native_second_swift_uses_same_prefix_and_only_admits_legal_actions(self):
        legacy, = run_cases((500014,), charge_pool="legacy")
        self.assertEqual(legacy["histories"]["switch"], {"excluded": "second_swift_not_legal"})
        stay = legacy["histories"]["stay"]
        self.assertEqual(stay["public_state"], {"turn": 102, "hp_bucket_5pct": 13,
                                               "opponent_shields": 0, "elapsed_ms": 156000})
        self.assertEqual(stay["immediate_action"], "charge_1")
        self.assertEqual(set(stay["alternatives"]), {"fast", "wait"})
        self.assertEqual(stay["immediate"]["charge_resolved_at_fork"][0]["move"], "SWIFT")
        self.assertTrue(all(not b["charge_resolved_at_fork"] for b in stay["alternatives"].values()))
        self.assertEqual([b["reward"] for b in stay["alternatives"].values()], [1, 1])

        alternate, = run_cases((1001016,), charge_pool="alternate")
        history = alternate["histories"]["switch"]
        self.assertEqual(charge_stratum(history["public_state"]), "0–25% / 0 shield / ≤30s")
        self.assertEqual((history["immediate"]["reward"], history["alternatives"]["fast"]["reward"],
                          history["alternatives"]["wait"]["reward"]), (1, -1, 1))
        for key in ("handoff", "randomness", "audit", "state", "decisions"):
            self.assertNotIn(f'"{key}"', json.dumps((legacy, alternate)))

    def test_charge_strata_use_public_bucket_and_closed_upper_bounds(self):
        for hp, shields, remaining, expected in (
            (0, 0, 10000, "0–25% / 0 shield / ≤30s"),
            (5, 1, 30000, "0–25% / 1 shield / ≤30s"),
            (6, 2, 30001, "30–50% / 2 shield / >30–60s"),
            (10, 2, 60000, "30–50% / 2 shield / >30–60s"),
            (15, 1, 60001, "55–75% / 1 shield / >60s"),
            (16, 0, 120000, "80–100% / 0 shield / >60s"),
        ):
            self.assertEqual(charge_stratum({"hp_bucket_5pct": hp, "opponent_shields": shields,
                                             "elapsed_ms": 240000 - remaining}), expected)

    def test_charge_summary_pairs_by_action_and_keeps_timeouts_out_of_reward(self):
        base = {"reward": 1, "outcome": "self_ko_win", "second_swift_resolved": True,
                "charge_resolved_at_fork": [{"move": "SWIFT"}], "first_charge_from_fork": {"move": "SWIFT"}}
        cold = {**base, "reward": None, "outcome": "timeout", "second_swift_resolved": False,
                "charge_resolved_at_fork": [], "first_charge_from_fork": None}
        cases = [{"histories": {
            "stay": {"public_state": {"hp_bucket_5pct": 5, "opponent_shields": 1, "elapsed_ms": 230001},
                     "immediate": base, "alternatives": {"fast": cold, "wait": base}},
            "switch": {"excluded": "no_first_swift"},
        }}]
        report = summarize_charge(cases)
        self.assertEqual((report["planned_histories"], report["eligible_histories"]), (2, 1))
        stratum = report["strata"]["0–25% / 1 shield / ≤30s"]
        self.assertEqual(stratum["fast"]["attempted"], 1)
        self.assertEqual(stratum["fast"]["both_completed"], 0)
        self.assertEqual(stratum["fast"]["alternative_censored"], {"timeout": 1})
        self.assertIsNone(stratum["fast"]["mean_reward_delta"])
        self.assertEqual(stratum["wait"]["mean_reward_delta"], 0)
        self.assertEqual(stratum["charge_0"]["attempted"], 0)
        self.assertIsNone(stratum["charge_0"]["both_completed_rate"])
