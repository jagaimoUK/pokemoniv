"""Tests for roster precommitment and public event tracing across mirror branches."""
import unittest

from tools import evaluate_rl_azumarill_mirror as previous
from tools.evaluate_rl_azumarill_mirror_followup import (
    WINDOWS, same_clock_results, trace_arm, window_cases,
)


class AzumarillMirrorFollowupTests(unittest.TestCase):
    def test_both_new_selections_include_azumarill_and_seeds_are_new(self):
        old = {
            case["seed"] for window in previous.WINDOWS for case in previous.window_cases(window)
        }
        expected = {
            "skarmory_fearow": ["skarmory", "azumarill", "fearow"],
            "clodsire_skarmory": ["clodsire", "azumarill", "skarmory"],
        }
        for window in WINDOWS:
            cases = window_cases(window)
            seeds = {case["seed"] for case in cases}
            self.assertTrue(old.isdisjoint(seeds))
            old.update(seeds)
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertEqual(len(cases), 72)
            for roster, trio in expected.items():
                matches = [case for case in cases if case["roster"] == roster]
                self.assertEqual(len(matches), 36)
                self.assertTrue(all([p["species"] for p in c["handoff"]["opponent_team"]] == trio
                                    for c in matches))

    def test_trace_distinguishes_hits_before_and_after_a_pivot_in_same_turn(self):
        def event(seq, kind, side, species, **fields):
            return {"seq": seq, "kind": kind, "side": side, "species": species,
                    "turn": 95, "start_ms": 152000, "end_ms": 172000, **fields}

        events = [
            event(8, "charged", "opponent", "azumarill", move_id="PLAY_ROUGH", shielded=False),
            event(9, "charged", "opponent", "azumarill", move_id="ICE_BEAM", shielded=True),
            event(10, "switch", "self", "skarmory", forced=False),
            event(11, "charged", "opponent", "azumarill", move_id="ICE_BEAM", shielded=False),
            event(12, "faint", "self", "skarmory"),
            event(13, "faint", "opponent", "azumarill"),
        ]
        row = {"after_event_seq": 8, "public_state": {"turn": 95}, "switch_to": "skarmory",
               "switch": {"outcome": "simultaneous_ko", "elapsed_ms": 172000,
                          "replay": {"events": events}}}
        trace = trace_arm(row, "switch")
        self.assertEqual(trace["first_opponent_charge"]["seq"], 9)
        self.assertEqual(trace["first_opponent_charge"]["target"], "azumarill")
        self.assertEqual(trace["first_opponent_charge_after_switch"]["target"], "skarmory")
        self.assertTrue(trace["charge_landed_on_switch_turn"])
        self.assertEqual([item["species"] for item in trace["next_kos"]], ["skarmory", "azumarill"])
        self.assertEqual(trace["next_kos"][0]["remaining_at_step_end_ms"], 68000)

    def test_known_equal_clock_case_preserves_actual_target_and_next_ko(self):
        specs = [
            row for row in previous.window_cases(1700012)
            if row["roster"] == "skarmory" and row["seed"] == 1700015
            and row["opponent_shields"] == 2
            and row["handoff"]["own_team"][0]["species"] == "quagsire_shadow"
            and row["handoff"]["own_team"][0]["charged2"] == "MUD_BOMB"
        ]
        rows = previous.run_mirror_cases(specs)
        matched = [trace for trace in same_clock_results(rows) if trace["opening_move"] == "AQUA_TAIL"]
        reference, = matched
        self.assertEqual((reference["mirror_charge_ms"], reference["fork_remaining_ms"]), (30000, 88000))
        ice, switch = reference["ice_beam"], reference["switch"]
        self.assertEqual(ice["first_opponent_charge"]["target"], "azumarill")
        self.assertEqual(ice["next_kos"], [])
        self.assertEqual(ice["outcome"], "timeout")
        hit = switch["first_opponent_charge_after_switch"]
        self.assertEqual((hit["move"], hit["target"], hit["step_end_ms"]), ("ICE_BEAM", "skarmory", 165000))
        self.assertFalse(switch["charge_landed_on_switch_turn"])
        faint, = switch["next_kos"]
        self.assertEqual((faint["side"], faint["species"], faint["remaining_at_step_end_ms"]),
                         ("opponent", "azumarill", 3000))
        self.assertEqual(switch["outcome"], "self_ko_win")
