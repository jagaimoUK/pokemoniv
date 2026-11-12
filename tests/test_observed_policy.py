"""Offline safety contract for observation-only tactical proposals.

No HTTP route, no PvPoke native engine, no user's real data.
"""
import copy
import unittest

from pvpoke_observed_policy import propose, SCHEMA


def snapshot():
    return {
        "turn": 3, "phase": "choose_action", "own_energy": 45,
        "own_shields": 1, "opponent_shields_visible": 1,
        "own_can_act": True, "events": [
            {"turn": 1, "kind": "opponent_fast"},
        ],
    }


def policy():
    return {
        "own_charged_moves": [
            {"move_id": "AQUA_TAIL", "energy_cost": 35},
            {"move_id": "STONE_EDGE", "energy_cost": 55},
        ],
        "energy_reserve": 0,
        "shield_rule": "first_announcement",
    }


class VisiblePolicyTests(unittest.TestCase):
    def test_affordable_charge_and_no_native_or_live_promotion(self):
        result = propose(snapshot(), policy())
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["action"], {"kind": "charged", "move_id": "AQUA_TAIL"})
        self.assertEqual(result["information_model"], "visible_input_contract_only")
        self.assertFalse(result["observation_provenance_verified"])
        self.assertFalse(result["native_execution_verified"])
        self.assertFalse(result["practical_role_covered"])
        self.assertEqual(result["live_reproducibility"], "not_verified")

    def test_wait_and_energy_reserve_are_deterministic(self):
        visible = snapshot()
        visible["own_can_act"] = False
        self.assertEqual(propose(visible, policy())["action"], {"kind": "wait"})
        visible["own_can_act"] = True
        chosen = policy()
        chosen["energy_reserve"] = 11
        self.assertEqual(propose(visible, chosen)["action"], {"kind": "fast"})
        visible["own_energy"] = 46
        self.assertEqual(propose(visible, chosen)["action"]["kind"], "charged")

    def test_shield_prompt_before_move_identity_is_observed(self):
        visible = snapshot()
        visible["phase"] = "shield_prompt"
        visible["events"].append({"turn": 3, "kind": "opponent_charge_announced"})
        self.assertEqual(propose(visible, policy())["action"], {"kind": "shield", "use_shield": True})
        visible["own_shields"] = 0
        self.assertEqual(propose(visible, policy())["action"], {"kind": "shield", "use_shield": False})
        visible["own_shields"] = 1
        chosen = policy()
        chosen["shield_rule"] = "never"
        self.assertFalse(propose(visible, chosen)["action"]["use_shield"])
        chosen["shield_rule"] = "always"
        self.assertTrue(propose(visible, chosen)["action"]["use_shield"])

    def test_first_announced_shield_rule_counts_only_public_events(self):
        visible = snapshot()
        visible["phase"] = "shield_prompt"
        visible["events"] += [
            {"turn": 2, "kind": "opponent_charge_announced"},
            {"turn": 2, "kind": "opponent_charge_resolved", "move_id": "ICE_BEAM"},
            {"turn": 3, "kind": "opponent_charge_announced"},
        ]
        self.assertEqual(propose(visible, policy())["action"],
                         {"kind": "shield", "use_shield": False})

    def test_hidden_opponent_worlds_cannot_affect_same_observation(self):
        visible = snapshot()
        baseline = propose(visible, policy())
        for hidden_world in (
            {"opponent_ivs": (0, 15, 15), "opponent_energy": 0},
            {"opponent_ivs": (15, 0, 0), "opponent_energy": 100},
            {"opponent_move": "ICE_BEAM", "opponent_intends_to_shield": True},
        ):
            world = {**copy.deepcopy(visible), **hidden_world}
            with self.subTest(hidden=hidden_world):
                self.assertEqual(propose(copy.deepcopy(visible), policy()), baseline)
                with self.assertRaises(ValueError):
                    propose(world, policy())

    def test_unknown_or_future_knowledge_rejected(self):
        for key, value in (
            ("opponent_energy", 44), ("opponent_ivs", {"attack": 15}),
            ("opponent_next_move", "STONE_EDGE"),
            ("opponent_shield_intent", True), ("owner_scope", "other"),
        ):
            with self.subTest(key=key):
                visible = snapshot()
                visible[key] = value
                with self.assertRaises(ValueError):
                    propose(visible, policy())
        visible = snapshot()
        visible["phase"] = "shield_prompt"
        visible["events"].append({"turn": 3, "kind": "opponent_charge_announced",
                                  "move_id": "ICE_BEAM"})
        with self.assertRaises(ValueError):
            propose(visible, policy())
        visible["events"][-1].pop("move_id")
        visible["events"].append({"turn": 4, "kind": "opponent_charge_resolved",
                                  "move_id": "ICE_BEAM"})
        with self.assertRaises(ValueError):
            propose(visible, policy())

    def test_shield_requires_current_public_announcement(self):
        visible = snapshot()
        visible["phase"] = "shield_prompt"
        with self.assertRaises(ValueError):
            propose(visible, policy())
        visible["events"].append({"turn": 3, "kind": "opponent_charge_resolved",
                                  "move_id": "ICE_BEAM"})
        with self.assertRaises(ValueError):
            propose(visible, policy())

    def test_validate_policy_and_event_types(self):
        for change in (
            {"energy_reserve": True}, {"energy_reserve": 31},
            {"shield_rule": "if_hidden_move_is_strong"},
            {"own_charged_moves": []},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    propose(snapshot(), {**policy(), **change})
        for field, value in (("turn", 501), ("own_energy", 101),
                             ("own_shields", -1), ("own_can_act", 1),
                             ("events", [1])):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    propose({**snapshot(), field: value}, policy())

    def test_resolved_reveal_cannot_change_past_shield_choice(self):
        early = snapshot()
        early["phase"] = "shield_prompt"
        early["events"].append({"turn": 3, "kind": "opponent_charge_announced"})
        decision = propose(early, policy())
        self.assertTrue(decision["action"]["use_shield"])
        # A later move reveal is not retroactively available at this prompt.
        later = copy.deepcopy(early)
        later["turn"] = 4
        later["phase"] = "choose_action"
        later["events"].append({"turn": 4, "kind": "opponent_charge_resolved",
                                "move_id": "ICE_BEAM"})
        self.assertEqual(propose(later, policy())["action"]["kind"], "charged")
        self.assertEqual(propose(early, policy()), decision)


if __name__ == "__main__":
    unittest.main()
