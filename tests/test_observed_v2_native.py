import unittest

import test_observed_native_runner as fixtures
from pvpoke_observed_observation import Context, ObservationV2


class ObservedV2NativeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def replay(self, table, *, enemy_energy=0, energy=35, horizon=4, branch=None, seed=0, enemy_ivs=None, swap_moves=False):
        req = self.fixture.request(energy=energy, enemy_energy=enemy_energy, enemy_ivs=enemy_ivs,
                                   opponent_attack_rule="charge_if_ready")
        if swap_moves:
            enemy = req["opponent"]
            enemy["charged1"], enemy["charged2"] = enemy["charged2"], enemy["charged1"]
        context = Context("a" * 64, (35, 55), energy, tuple(req["shields"]), 8)
        req["observed_v2"] = {"context_hash": context.key, "table": table, "horizon": horizon,
                              "branch": branch or {"fast_delay": 0, "miss_first_fast": False,
                                                   "reverse_fast_batch": False}, "seed": seed}
        result = self.fixture.native(req)
        if result["status"] == "frontier":
            view = ObservationV2.read(context, result["events"])
            self.assertEqual(view.key, result["key"])
            self.assertEqual(list(view.legal), result["legal"])
        return result

    def test_shared_opening_and_wait_does_not_attack(self):
        left = self.replay({})
        right = self.replay({}, enemy_energy=100, seed=7)
        self.assertEqual(left, right)
        self.assertIn("charge_0", left["legal"])
        self.assertNotIn("charge_0", self.replay({}, energy=34)["legal"])
        done = self.replay({left["key"]: "wait_one_window"}, horizon=1)
        self.assertEqual(done["outcome"], "timeout")
        self.assertEqual(done["intents"][0]["status"], "no_input")
        self.assertFalse(any(m["actor"] == 0 for m in done["moves"]))

    def test_shield_choice_stays_equal_until_move_reveals(self):
        worlds = [{"enemy_energy": 100}, {"enemy_energy": 100, "swap_moves": True,
                   "enemy_ivs": {"attack": 0, "defense": 15, "hp": 15}, "seed": 13}]
        opening = self.replay({}, **worlds[0])
        table = {opening["key"]: "wait_one_window"}
        prompts = [self.replay(table, **world) for world in worlds]
        self.assertEqual(prompts[0], prompts[1])
        self.assertEqual(prompts[0]["events"][-1]["kind"], "charge_announced")
        table[prompts[0]["key"]] = "shield_yes"
        next_views = [self.replay(table, **world) for world in reversed(worlds)]
        self.assertNotEqual(next_views[0]["key"], next_views[1]["key"])
        for view in next_views:
            self.assertIn("charge_revealed", [event["kind"] for event in view["events"]])
            self.assertIn("own_shield_used", [event["kind"] for event in view["events"]])

    def test_charge_lock_distinguishes_intent_from_resolution(self):
        first = self.replay({}, energy=100)
        table = {first["key"]: "charge_0"}
        second = self.replay(table, energy=100)
        table[second["key"]] = "charge_0"
        result = self.replay(table, energy=100, horizon=2)
        self.assertEqual([row["status"] for row in result["intents"]], ["resolved", "not_accepted"])
        self.assertEqual(sum(move["actor"] == 0 for move in result["moves"]), 1)
