import copy
import unittest

from pvpoke_observed_audit import audit_traces
from test_observed_policy import snapshot, policy


def row(action=None):
    return {"visible": snapshot(), "action": action or {"kind": "fast"}}


class ObservedAuditTests(unittest.TestCase):
    def test_same_history_different_hidden_worlds_share_one_decision(self):
        trace = [row()]
        result = audit_traces([trace, copy.deepcopy(trace)], policy())
        self.assertEqual(result["repeated_histories"], 1)
        self.assertEqual(result["information_fairness"], "not_established")
        self.assertFalse(result["practical_role_covered"])

    def test_world_specific_best_actions_are_not_a_policy(self):
        with self.assertRaisesRegex(ValueError, "Different actions"):
            audit_traces([[row()], [row({"kind": "charged", "move_id": "AQUA_TAIL"})]], policy())

    def test_later_public_reveal_can_split_shared_history(self):
        traces = []
        for move, action in (("ICE_BEAM", {"kind": "fast"}),
                             ("PLAY_ROUGH", {"kind": "charged", "move_id": "AQUA_TAIL"})):
            prompt = row({"kind": "shield", "use_shield": True})
            prompt["visible"]["phase"] = "shield_prompt"
            prompt["visible"]["events"].append({"turn": 3, "kind": "opponent_charge_announced"})
            revealed = copy.deepcopy(prompt)
            revealed["visible"].update(turn=4, phase="choose_action", own_shields=0)
            revealed["visible"]["events"].append(
                {"turn": 3, "kind": "opponent_charge_resolved", "move_id": move})
            revealed["action"] = action
            traces.append([prompt, revealed])
        self.assertEqual(audit_traces(traces, policy())["repeated_histories"], 1)
        traces[1][0]["action"]["use_shield"] = False
        with self.assertRaisesRegex(ValueError, "Different actions"):
            audit_traces(traces, policy())

    def test_full_prefix_not_just_latest_snapshot(self):
        early, other = row(), row()
        other["visible"]["own_energy"] = 40
        later = row()
        later["visible"]["turn"] = 4
        different = copy.deepcopy(later)
        different["action"] = {"kind": "wait"}
        result = audit_traces([[early, later], [other, different]], policy())
        self.assertEqual(result["distinct_histories"], 4)

    def test_rewound_events_hidden_fields_and_invalid_actions_rejected(self):
        first, later = row(), row()
        later["visible"]["events"] = []
        with self.assertRaises(ValueError):
            audit_traces([[first, later]], policy())
        hidden = row()
        hidden["visible"]["opponent_energy"] = 100
        bad_bool = row({"kind": "shield", "use_shield": 1})
        for trace in ([], [hidden], [bad_bool], [row()] * 513):
            with self.subTest(trace_size=len(trace)), self.assertRaises(ValueError):
                audit_traces([trace], policy())
        with self.assertRaises(ValueError):
            audit_traces([[row()]] * 65, policy())


if __name__ == "__main__":
    unittest.main()
