"""Protect the three-action frontier, public trace and matched outcome accounting."""
import json
import unittest

from tools.evaluate_rl_azumarill_mirror import run_mirror_cases
from tools.evaluate_rl_azumarill_mirror_followup import WINDOWS as PREVIOUS_WINDOWS
from tools.evaluate_rl_azumarill_three_way import ACTIONS, WINDOWS, summarize, window_cases, with_traces


class AzumarillThreeWayTests(unittest.TestCase):
    def test_fixed_opponent_selections_and_new_seeds(self):
        seen = {w + offset for w in PREVIOUS_WINDOWS for offset in range(6)}
        names = {
            "skarmory_fearow": ["skarmory", "azumarill", "fearow"],
            "clodsire_skarmory": ["clodsire", "azumarill", "skarmory"],
            "skarmory": ["skarmory", "primeape", "azumarill"],
        }
        for window in WINDOWS:
            cases = window_cases(window)
            seeds = {case["seed"] for case in cases}
            self.assertTrue(seeds.isdisjoint(seen))
            seen.update(seeds)
            self.assertEqual(seeds, set(range(window, window + 9)))
            self.assertEqual(len(cases), 108)
            for name, team in names.items():
                selected = [row for row in cases if row["roster"] == name]
                self.assertEqual(len(selected), 36)
                self.assertTrue(all([p["species"] for p in c["handoff"]["opponent_team"]] == team
                                    for c in selected))

    def test_three_way_public_trace_matches_a_native_case(self):
        cases = [
            row for row in window_cases(WINDOWS[0])
            if row["seed"] == 1900012 and row["opponent_shields"] == 1
            and row["handoff"]["own_team"][0]["species"] == "quagsire"
            and row["handoff"]["own_team"][0]["charged2"] == "STONE_EDGE"
        ]
        rows = with_traces(run_mirror_cases(cases, mode="mirror_three_way"))
        row, = [r for r in rows if r["opening_move"] == "STONE_EDGE"]
        self.assertEqual(row["public_state"]["turn"], 112)
        self.assertEqual(row["switch_targets"], {"switch_skarmory": "skarmory",
                                                 "switch_quagsire": "quagsire"})
        for action, target in zip(ACTIONS, ("azumarill", "skarmory", "quagsire")):
            self.assertTrue(row[action]["action_resolved"])
            trace = row["traces"][action]
            self.assertEqual(trace["first_opponent_charge"]["target"], target)
            self.assertEqual(trace["first_opponent_charge"]["move"], "ICE_BEAM")
        self.assertEqual(row["traces"]["switch_quagsire"]["next_kos"][0]["species"], "quagsire")
        self.assertEqual(row["traces"]["switch_skarmory"]["remaining_at_battle_end_ms"], 1000)
        self.assertEqual([row[a]["reward"] for a in ACTIONS], [None, 1, None])
        for field in ("opponent_team", "audit", "decisions", "energy_points"):
            self.assertNotIn(f'"{field}"', json.dumps(row))

    def test_missing_second_switch_is_excluded(self):
        cases = [row for row in window_cases(WINDOWS[0])
                 if row["seed"] == 1900012 and row["opponent_shields"] == 0]
        old = run_mirror_cases(cases)
        new = run_mirror_cases(cases, mode="mirror_three_way")
        missing = [(before, after) for before, after in zip(old, new)
                   if after.get("excluded") == "only_one_switch_available"]
        self.assertTrue(missing)
        for before, after in missing:
            self.assertIn("switch", before)
            self.assertNotIn("public_state", after)

    def test_completion_and_pairwise_score_denominators_are_distinct(self):
        def row(rewards):
            record = {"public_state": {}, "traces": {}}
            for action, reward in zip(ACTIONS, rewards):
                record[action] = {"action_resolved": True, "reward": reward,
                                  "outcome": "timeout" if reward is None else "self_ko_win",
                                  "mirror_charge_ms_after_fork": 0}
                record["traces"][action] = {"first_opponent_charge": None, "next_kos": []}
            return record

        result = summarize([row((None, 1, 1)), row((1, 1, 1)), row((None, 1, None)),
                            {"excluded": "only_one_switch_available"}])
        self.assertEqual((result["planned_histories"], result["three_choices_available"]), (4, 3))
        self.assertEqual(result["all_three_ko_completed"], 1)
        self.assertEqual(result["actions"]["switch_skarmory"]["ko_completion_rate"], 1)
        pair = result["paired_outcomes"]["switch_quagsire_minus_switch_skarmory"]
        self.assertEqual((pair["both_completed"], pair["only_reference_completed"]), (2, 1))
        self.assertEqual(pair["mean_reward_delta"], 0)
