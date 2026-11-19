"""Regression checks for resolved move, shield and KO diagnostics."""
import json
import unittest
from unittest.mock import patch

from pvpoke_rl_team_env import InvalidNativeTeamResult
from tools.evaluate_rl_branches import PRIMEAPE, _Rollout
from tools.evaluate_rl_mc import heldout_scenarios
from tools.run_rl_mc import fixture_teams
from tools import evaluate_rl_switch_traces as traces


def summarize(events, shields):
    audit = {"battle": {"events": events, "starting_shields": [2, 2],
                       "state": {"sides": [{"shields": shields[0]}, {"shields": shields[1]}]},
                       "handoff": {"private": "hidden"}}}
    transition = (None, None, False, True, {"outcome": "timeout", "training_eligible": False,
                                            "elapsed_ms": 240000})
    fork = ((), ({"turn": 3},), {"battle": {"events": []}})
    return traces._summarize_rollout(_Rollout(transition, audit), fork, "switch_1")


class SwitchTraceTests(unittest.TestCase):
    def test_uses_resolved_moves_and_defender_shields_and_groups_simultaneous_ko(self):
        events = [
            {"kind": "switch", "actor": 0, "species": "primeape", "turn": 3, "forced": False},
            {"kind": "charge_announced", "actor": 0, "species": "primeape", "turn": 5},
            {"kind": "charged", "actor": 0, "species": "primeape", "move_id": "NIGHT_SLASH",
             "shielded": True, "turn": 6},
            {"kind": "fast", "actor": 1, "species": "fearow", "move_id": "PECK",
             "shielded": False, "turn": 7},
            {"kind": "faint", "actor": 0, "species": "primeape", "turn": 8},
            {"kind": "faint", "actor": 1, "species": "fearow", "turn": 8},
            {"kind": "switch", "actor": 1, "species": "quagsire", "turn": 8, "forced": True},
            {"kind": "charged", "actor": 1, "species": "quagsire", "move_id": "AQUA_TAIL",
             "shielded": True, "turn": 10},
        ]
        result = summarize(events, (1, 1))
        self.assertEqual(result["switch_at_fork"], "primeape")
        self.assertEqual(result["first_ko"]["action_turn"], 7)
        self.assertEqual(result["first_ko"]["native_event_turn"], 8)
        self.assertEqual(result["first_ko"]["fainted"], [
            {"side": "self", "species": "primeape"}, {"side": "opponent", "species": "fearow"},
        ])
        self.assertEqual(result["last_resolved_move_before_ko"]["move"], "PECK")
        self.assertEqual([m["move"] for m in result["charged_before_first_ko"]], ["NIGHT_SLASH"])
        self.assertEqual(result["moves_after_first_ko"], [{
            "side": "opponent", "species": "quagsire", "move": "AQUA_TAIL",
            "shielded": True, "count": 1,
        }])
        self.assertEqual(result["shields_before_first_ko"], {"self": 0, "opponent": 1})
        self.assertEqual(result["shields_total"], {"self": 1, "opponent": 1})
        self.assertIsNone(result["reward"])
        self.assertEqual(result["censor"], "timeout")
        self.assertNotIn("handoff", json.dumps(result))
        with self.assertRaises(InvalidNativeTeamResult):
            summarize(events, (2, 1))

    def test_no_ko_before_censor_leaves_first_ko_null(self):
        result = summarize([], (2, 2))
        self.assertIsNone(result["first_ko"])
        self.assertIsNone(result["switch_at_fork"])
        self.assertIsNone(result["last_resolved_move_before_ko"])
        self.assertEqual(result["moves_after_first_ko"], [])

    def test_native_replays_one_historical_loss_and_crosses_legal_targets(self):
        own, public, enemy = fixture_teams()
        own[0] = {**own[0], **PRIMEAPE}
        case = heldout_scenarios(count=1, seed=501015)
        legacy, = traces._run_cases(case, (own, public, enemy), crossed=False)
        crossed, = traces._run_cases(case, (own, public, enemy), crossed=True)
        self.assertEqual(legacy["opponent_lead"], "wigglytuff")
        self.assertEqual((legacy["fork_turn"], crossed["fork_turn"]), (3, 3))
        self.assertEqual([x["reward"] for x in legacy["arms"].values()], [1, -1])
        self.assertEqual([x["reward"] for x in crossed["arms"].values()], [-1, -1, 1])
        primeape = legacy["arms"]["primeape"]
        self.assertEqual(primeape["first_ko"]["action_turn"], 24)
        self.assertEqual(primeape["first_ko"]["fainted"], [{"side": "self", "species": "primeape"}])
        self.assertEqual(crossed["arms"]["primeape"]["switch_at_fork"], "primeape")
        self.assertEqual(crossed["arms"]["fearow"]["switch_at_fork"], "fearow")
        for key in ("handoff", "state", "randomness", "decisions", "combatant_id"):
            self.assertNotIn(f'"{key}"', json.dumps(crossed))

    def test_holdout_keeps_nonworsened_and_censored_cases(self):
        def fake(cases, teams, *, crossed):
            results = []
            for seed, _, _ in cases:
                arms = {"stay": {"reward": 1}, "primeape": {"reward": 1}}
                if crossed:
                    arms["fearow"] = {"reward": None}
                results.append({"seed": seed, "arms": arms})
            return results

        with patch.object(traces, "_run_cases", side_effect=fake):
            result = traces.evaluate_switch_traces(cohort="holdout")
        self.assertEqual(result["legacy_worse_seeds"], [])
        self.assertEqual(len(result["crossed"]), 12)
        self.assertEqual(result["crossed_fearow_vs_stay"], {
            "attempted": 12, "both_completed": 0, "both_completed_rate": 0,
            "better": 0, "equal": 0, "worse": 0, "mean_reward_delta": None,
        })
