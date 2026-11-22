"""Regression coverage for public Quagsire timeout replays and shield-only matching."""
import unittest

from tools.evaluate_rl_quagsire_timeouts import (
    POLICIES, PRIOR_WINDOWS, RULESET_ID, WINDOWS, fresh_cases, historical_cases,
    azumarill_mirror, run_cases, summarize,
)


class QuagsireTimeoutTests(unittest.TestCase):
    def test_prespecified_grid_preserves_prior_rosters_and_uses_unused_seeds(self):
        seen = set()
        for window in PRIOR_WINDOWS:
            rows = historical_cases(window)
            self.assertEqual(len(rows), 48)
            seen.update(row["seed"] for row in rows)
        reference = historical_cases(PRIOR_WINDOWS[0])
        for window in WINDOWS:
            rows = fresh_cases(window)
            self.assertEqual(len(rows), 72)
            self.assertEqual({row["seed"] for row in rows}, set(range(window, window + 6)))
            self.assertFalse(seen & {row["seed"] for row in rows})
            seen.update(row["seed"] for row in rows)
            for roster in ("clodsire", "skarmory"):
                selected = [row for row in rows if row["roster"] == roster]
                self.assertEqual(len(selected), 36)
                self.assertEqual({row["opponent_shields"] for row in selected}, {0, 1, 2})
                self.assertEqual({row["handoff"]["ruleset_id"] for row in selected}, {RULESET_ID})
                expected = next(row["handoff"]["opponent_team"] for row in reference
                                if row["roster"] == roster)
                self.assertTrue(all(row["handoff"]["opponent_team"] == expected
                                    for row in selected))

    def test_historical_timeout_retains_public_clock_and_terminal_events(self):
        case = next(row for row in historical_cases(PRIOR_WINDOWS[0])
                    if row["seed"] == 1500014 and row["opponent_shields"] == 2
                    and row["handoff"]["own_team"][0]["species"] == "quagsire"
                    and row["handoff"]["own_team"][0]["charged2"] == "STONE_EDGE")
        historical, = run_cases([case], mode="historical")
        legacy, = run_cases([case])
        for name, arm in historical["by_policy"]["cpu_always"].items():
            self.assertEqual({key: value for key, value in arm.items() if key != "replay"},
                             legacy[name])
            self.assertEqual((arm["outcome"], arm["reward"]), ("timeout", None))
            replay = arm["replay"]
            self.assertEqual((replay["elapsed_ms"], replay["charged_ms"]), (240000, 170000))
            self.assertEqual(replay["clock_remainder_ms"], 70000)
            entry, ice_beams = azumarill_mirror(replay, "quagsire", "skarmory")
            self.assertIsNotNone(entry)
            self.assertGreaterEqual(ice_beams, 3)
            self.assertEqual(replay["terminal_step"]["end_ms"], 240000)
            self.assertLess(replay["terminal_step"]["start_ms"], 240000)
            self.assertTrue(any(e["kind"] == "switch" and e["forced"]
                                and e["start_ms"] == e["end_ms"] for e in replay["events"]))
            self.assertTrue(any(e["kind"] == "charged" and e["shielded"] for e in replay["events"]))
            for e in replay["events"]:
                expected = {"kind", "seq", "turn", "species", "side", "start_ms", "end_ms"}
                if e["kind"] == "switch":
                    expected |= {"previous_species", "forced"}
                if e["kind"] == "charged":
                    expected |= {"move_id", "shielded"}
                self.assertEqual(set(e), expected)
                self.assertLessEqual(e["start_ms"], e["end_ms"])
                self.assertIn(e["side"], ("self", "opponent"))

    def test_policy_changes_only_legal_shielding_and_preserves_zero_shield_replay(self):
        cases = [row for row in fresh_cases(WINDOWS[0])
                 if row["seed"] == 1600015 and row["opponent_shields"] in (0, 1)
                 and row["handoff"]["own_team"][0]["species"] == "quagsire_shadow"
                 and row["handoff"]["own_team"][0]["charged2"] == "STONE_EDGE"]
        zero, one = run_cases(cases, mode="shielding")
        self.assertEqual(zero["by_policy"]["cpu_always"], zero["by_policy"]["save_high_hp"])
        self.assertEqual(one["public_state"]["opponent_shields"], 1)
        for name in ("aqua_tail", "second_charge"):
            cpu = one["by_policy"]["cpu_always"][name]
            reserve = one["by_policy"]["save_high_hp"][name]
            self.assertTrue(cpu["move_resolved"])
            self.assertTrue(reserve["move_resolved"])
            self.assertTrue(cpu["shielded"])
            self.assertFalse(reserve["shielded"])
        winner = one["by_policy"]["save_high_hp"]["second_charge"]
        self.assertEqual(winner["reward"], 1)
        terminal_event = winner["replay"]["events"][-1]
        self.assertEqual((terminal_event["kind"], terminal_event["side"]), ("faint", "opponent"))
        self.assertEqual(terminal_event["end_ms"], winner["replay"]["elapsed_ms"])

    def test_common_complete_delta_does_not_impute_timeouts(self):
        def arm(reward):
            outcome = "timeout" if reward is None else "self_ko_win" if reward == 1 else "opponent_ko_win"
            return {"reward": reward, "outcome": outcome, "move_resolved": True, "shielded": False,
                    "replay": {"elapsed_ms": 240000, "charged_ms": 170000,
                               "clock_remainder_ms": 70000, "events": []}}

        def row(cpu, reserve):
            return {
                "public_state": {}, "species": "quagsire", "roster": "skarmory",
                "by_policy": {
                    name: {"aqua_tail": arm(a), "second_charge": arm(b)}
                    for name, (a, b) in zip(POLICIES, (cpu, reserve))
                },
            }

        report = summarize([row((1, None), (-1, 1)), row((1, 1), (1, -1))], POLICIES)
        self.assertEqual(report["by_policy"]["cpu_always"]["both_completed_rate"], 0.5)
        pair = report["matched_shield_policy_change"]
        self.assertEqual(pair["both_charge_arms_completed_only_with_reserve"], 1)
        self.assertEqual(pair["both_charge_arms_completed_under_both_policies"], 1)
        self.assertEqual(pair["mean_charge_reward_delta_shift_on_common_complete"], -2)
