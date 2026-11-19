"""Offline contract tests: hidden 6v3 selection and 3v3 state snapshots."""
import unittest
from pvpoke_rl_team_preview import SixToThreeSelection
from pvpoke_rl_team_state import ThreeVThreeSnapshot


def combatant(i, side="own"):
    return {
        "species": f"species{i}", "fast": "FAST_MOVE",
        "charged1": "CHARGE_1", "charged2": "CHARGE_2",
        "atk": 0, "def": 15, "hp": 15, "level": 20,
        "cp": 1100, "combatant_id": f"{side}{i}",
        "roster_clause_id": f"clause{i}",
    }


def preview(secret=(0, 1, 2), lead=0):
    own = [combatant(i) for i in range(6)]
    enemy = [combatant(i, "opponent") for i in range(6)]
    public = [{"species": p["species"],
               "roster_clause_id": p["roster_clause_id"]} for p in enemy]
    return SixToThreeSelection(own, public, enemy, secret, lead,
                               ruleset_id="custom_6v3_v1")


def native_snapshot():
    def member(i):
        return {"species": f"s{i}", "hp": 110, "max_hp": 120,
                "energy_points": i * 15, "buffs": [0, 0],
                "cooldown_ms": 0}
    return {"turn": 6, "sides": [
        {"active_slot": 0, "shields": 1, "switch_timer_ms": 25000,
         "team": [member(i) for i in range(3)]},
        {"active_slot": 1, "shields": 2, "switch_timer_ms": 10000,
         "team": [member(i + 3) for i in range(3)]},
    ]}


class SelectionTests(unittest.TestCase):
    def test_exact_sixty_actions_and_no_bench_order_duplicates(self):
        actions = preview().observe()["legal_actions"]
        self.assertEqual(len(actions), 60)
        self.assertEqual(len(set(actions)), 60)
        self.assertEqual(sum(a.startswith("0,1,2|") for a in actions), 3)

    def test_hidden_team_and_lead_have_identical_public_selection(self):
        first = preview((0, 1, 2), 0)
        second = preview((3, 4, 5), 5)
        self.assertEqual(first.observe(), second.observe())
        a = first.choose("0,1,2|1")
        b = second.choose("0,1,2|1")
        self.assertEqual(a, b)
        self.assertNotIn("opponent_team", a)
        self.assertIsNone(a["reward"])
        self.assertFalse(a["battle_verified"])

    def test_private_handoff_follows_chosen_leads_and_is_never_public(self):
        game = preview((0, 2, 4), 2)
        with self.assertRaises(RuntimeError):
            game._private_engine_input()
        result = game.choose("1,3,5|3")
        self.assertEqual(result["selected_slots"], [1, 3, 5])
        handoff = game._private_engine_input()
        self.assertEqual([r["combatant_id"] for r in handoff["own_team"]],
                         ["own3", "own1", "own5"])
        self.assertEqual([r["combatant_id"] for r in handoff["opponent_team"]],
                         ["opponent2", "opponent0", "opponent4"])
        handoff["opponent_team"][0]["atk"] = 99
        self.assertEqual(game._private_engine_input()["opponent_team"][0]["atk"], 0)
        with self.assertRaises(RuntimeError):
            game.observe()
        with self.assertRaises(RuntimeError):
            game.choose("0,1,2|0")

    def test_illegal_and_duplicate_selections_rejected(self):
        game = preview()
        for action in ("0,1,2|3", "0,0,2|0", "1,2,3|0", None):
            with self.subTest(action=action), self.assertRaises(ValueError):
                game.choose(action)

    def test_duplicate_roster_clause_or_preview_mismatch_rejected(self):
        own = [combatant(i) for i in range(6)]
        own[-1]["roster_clause_id"] = own[0]["roster_clause_id"]
        enemy = [combatant(i, "opponent") for i in range(6)]
        public = [{"species": p["species"],
                   "roster_clause_id": p["roster_clause_id"]} for p in enemy]
        with self.assertRaises(ValueError):
            SixToThreeSelection(own, public, enemy, (0, 1, 2), 0, ruleset_id="v1")
        own[-1]["roster_clause_id"] = "clause5"
        own[-1]["species"] = own[0]["species"]
        with self.assertRaises(ValueError):
            SixToThreeSelection(own, public, enemy, (0, 1, 2), 0, ruleset_id="v1")
        own[-1]["species"] = "species5"
        public[0]["species"] = "wrong"
        with self.assertRaises(ValueError):
            SixToThreeSelection(own, public, enemy, (0, 1, 2), 0, ruleset_id="v1")

    def test_enemy_private_iv_does_not_change_preselection_observation(self):
        own = [combatant(i) for i in range(6)]
        enemy = [combatant(i, "opponent") for i in range(6)]
        public = [{"species": p["species"],
                   "roster_clause_id": p["roster_clause_id"]} for p in enemy]
        first = SixToThreeSelection(own, public, enemy, (0, 1, 2), 0, ruleset_id="v1")
        enemy[0]["atk"] = 15
        second = SixToThreeSelection(own, public, enemy, (0, 1, 2), 0, ruleset_id="v1")
        own[0]["species"] = "mutated_after_init"
        self.assertEqual(first.observe(), second.observe())
        self.assertEqual(first._opponent[0]["atk"], 0)
        self.assertEqual(second._opponent[0]["atk"], 15)

    def test_private_selections_require_distinct_valid_slots_and_lead(self):
        own = [combatant(i) for i in range(6)]
        enemy = [combatant(i, "opponent") for i in range(6)]
        public = [{"species": p["species"],
                   "roster_clause_id": p["roster_clause_id"]} for p in enemy]
        for hidden, lead in [((0, 0, 2), 0), ((0, 1, 6), 0),
                             ((0, 1, 2), 4), ((True, 1, 2), 1)]:
            with self.subTest(hidden=hidden), self.assertRaises(ValueError):
                SixToThreeSelection(own, public, enemy, hidden, lead,
                                    ruleset_id="v1")


class TeamSnapshotTests(unittest.TestCase):
    def test_shared_shields_timers_and_benched_energy_persist(self):
        state = ThreeVThreeSnapshot(native_snapshot())
        saved = state.export_private()
        own = state.observe()["own"]
        self.assertEqual(own["team"][2]["energy_points"], 30)
        self.assertEqual(own["shields"], 1)
        self.assertEqual(own["switch_timer_ms"], 25000)
        self.assertEqual(state.export_private(), saved)

    def test_enemy_hidden_bench_and_private_energy_are_not_exposed(self):
        state = ThreeVThreeSnapshot(native_snapshot())
        view = state.observe()
        self.assertEqual(view["opponent"]["active_species"], "s4")
        self.assertEqual(view["opponent"]["known_species"], ["s4"])
        self.assertNotIn("team", view["opponent"])
        self.assertNotIn("active_slot", view["opponent"])
        after_reveal = state.observe(revealed_opponent_slots=(2,))
        self.assertEqual(after_reveal["opponent"]["known_species"], ["s4", "s5"])

    def test_native_switch_handoff_does_not_invent_resource_changes(self):
        original = native_snapshot()
        after = native_snapshot()
        after["turn"] += 1
        after["sides"][0]["active_slot"] = 1
        after["sides"][0]["switch_timer_ms"] = 45000
        state = ThreeVThreeSnapshot(after)
        self.assertEqual(state.export_private()["sides"][0]["team"],
                         original["sides"][0]["team"])
        self.assertEqual(state.observe()["own"]["active_slot"], 1)

    def test_invalid_active_faint_and_shared_shields_fail_closed(self):
        bad = native_snapshot()
        bad["sides"][0]["team"][0]["hp"] = 0
        with self.assertRaises(ValueError):
            ThreeVThreeSnapshot(bad)
        bad = native_snapshot()
        bad["sides"][0]["shields"] = 3
        with self.assertRaises(ValueError):
            ThreeVThreeSnapshot(bad)
        bad = native_snapshot()
        bad["sides"][0]["team"][2]["energy_points"] = 101
        with self.assertRaises(ValueError):
            ThreeVThreeSnapshot(bad)

    def test_private_snapshot_is_deeply_copied(self):
        state = ThreeVThreeSnapshot(native_snapshot())
        result = state.export_private()
        result["sides"][1]["team"][0]["energy_points"] = 99
        self.assertEqual(state.export_private()["sides"][1]["team"][0]
                         ["energy_points"], 45)


if __name__ == "__main__":
    unittest.main()
