"""Regression tests for the first legal Azumarill mirror fork and accounting."""
import json
import unittest

from tools.evaluate_rl_azumarill_mirror import WINDOWS, summarize, window_cases
from tools.evaluate_rl_quagsire_timeouts import WINDOWS as PRIOR_WINDOWS, historical_cases, run_cases


class AzumarillMirrorTests(unittest.TestCase):
    def test_fixed_rosters_and_seed_windows(self):
        prior = set(range(PRIOR_WINDOWS[0], PRIOR_WINDOWS[0] + 6))
        prior.update(range(PRIOR_WINDOWS[1], PRIOR_WINDOWS[1] + 6))
        for window in WINDOWS:
            cases = window_cases(window)
            seeds = {case["seed"] for case in cases}
            self.assertEqual(seeds, set(range(window, window + 6)))
            self.assertTrue(prior.isdisjoint(seeds))
            prior.update(seeds)
            self.assertEqual(len(cases), 72)
            for roster in ("skarmory", "clodsire"):
                matching = [c for c in cases if c["roster"] == roster]
                self.assertEqual(len(matching), 36)
                self.assertEqual({c["opponent_shields"] for c in matching}, {0, 1, 2})
                team = matching[0]["handoff"]["opponent_team"]
                self.assertTrue(all(c["handoff"]["opponent_team"] == team for c in matching))
                self.assertEqual("azumarill" in {m["species"] for m in team}, roster == "skarmory")

    def test_native_fork_has_first_expected_turn_and_only_public_results(self):
        cases = [row for row in historical_cases(1500012)
                 if row["seed"] in (1500012, 1500014) and row["opponent_shields"] == 2
                 and row["handoff"]["own_team"][0]["species"] == "quagsire"
                 and row["handoff"]["own_team"][0]["charged2"] == "STONE_EDGE"]
        control, study = run_cases(cases, mode="mirror")
        self.assertEqual([x["excluded"] for x in control["mirror_forks"]],
                         ["mirror_not_reached", "mirror_not_reached"])
        self.assertEqual([x["opening_move"] for x in study["mirror_forks"]],
                         ["AQUA_TAIL", "STONE_EDGE"])
        for fork, turn in zip(study["mirror_forks"], (111, 115)):
            self.assertEqual(fork["public_state"]["turn"], turn)
            self.assertEqual(fork["switch_to"], "quagsire")
            for action, expected_kind, expected_clock in (
                    ("ice_beam", "charged", 40000), ("switch", "switch", 30000)):
                result = fork[action]
                self.assertTrue(result["action_resolved"])
                self.assertEqual(result["mirror_charge_ms_after_fork"], expected_clock)
                self.assertEqual((result["outcome"], result["reward"]), ("timeout", None))
                changed = [e for e in result["replay"]["events"] if e["seq"] > fork["after_event_seq"]
                           and e["turn"] == turn and e["side"] == "self"]
                self.assertTrue(any(e["kind"] == expected_kind and
                                    (e.get("move_id") == "ICE_BEAM" if action == "ice_beam"
                                     else not e["forced"] and e["species"] == fork["switch_to"])
                                    for e in changed))
        serialized = json.dumps(study)
        for field in ("opponent_team", "audit", "randomness", "decisions", "energy_points"):
            self.assertNotIn(f'"{field}"', serialized)

    def test_clock_uses_all_legal_pairs_and_reward_uses_joint_completion(self):
        def arm(reward, clock):
            return {"action_resolved": True, "reward": reward,
                    "outcome": "timeout" if reward is None else "self_ko_win",
                    "mirror_charge_ms_after_fork": clock}

        def case(ice, switch):
            return {"public_state": {}, "switch_to": "quagsire", "ice_beam": ice, "switch": switch}

        report = summarize([case(arm(None, 30000), arm(1, 30000)),
                            case(arm(1, 40000), arm(1, 20000)),
                            {"excluded": "mirror_not_reached"}])
        self.assertEqual((report["planned_histories"], report["legal_opportunities"]), (3, 2))
        self.assertEqual(report["both_completed"], 1)
        self.assertEqual(report["both_completed_rate"], 0.5)
        self.assertEqual(report["mean_reward_delta"], 0)
        self.assertEqual(report["completion"]["switch_only"], 1)
        self.assertEqual(report["mirror_charge_clock_ms"]["mean_paired_difference"], -10000)
