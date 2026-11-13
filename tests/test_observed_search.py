import unittest

from pvpoke_observed_observation import Context, history_key
from pvpoke_observed_search import Search, initial_state


class ObservedSearchTests(unittest.TestCase):
    def test_individually_winning_worlds_cannot_be_combined(self):
        context = Context("a" * 64, (35, 55), 100, (0, 0))
        events = [{"seq": 1, "observed_time_range": [1, 1], "kind": "window"}]
        key = history_key(context, events)
        search = Search(context, ["left", "right"])
        state = initial_state()
        while state["frontier"]:
            item = state["frontier"][-1]
            scenario = search.scenarios[item["index"]]
            action = item["table"].get(key)
            if action is None:
                receipt = {"status": "frontier", "key": key, "events": events,
                           "legal": ["fast", "charge_0", "charge_1", "wait_one_window"]}
            else:
                win = action == ("charge_0" if scenario == "left" else "charge_1")
                receipt = {"status": "complete", "outcome": "self_ko_win" if win else "opponent_ko_win",
                           "terminal": [[1, 0, 0], [0, 0, 0]] if win else [[0, 0, 0], [1, 0, 0]]}
            search.advance(state, receipt)
        self.assertEqual(state["stop_reason"], "no_policy_in_declared_class")
        self.assertEqual(len(state["evaluations"]), 4)
        self.assertTrue(all(e["role"] is False for e in state["evaluations"]))

    def test_unknown_is_not_a_loss_and_no_worst_is_claimed(self):
        search = Search(Context("a" * 64, (35, 55), 0, (0, 0)), ["one"])
        state = initial_state()
        search.advance(state, {"status": "unknown", "reason": "wall_limit"})
        self.assertIsNone(state["evaluations"][0]["role"])
        self.assertIsNone(state["evaluations"][0]["worst_outcome"])

    def test_checkpoint_resume_and_owner_boundary(self):
        from copy import deepcopy
        from pvpoke_battle_store import BattleStore
        from pvpoke_observed_search import ObservedSearch
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        world = scripted_spec(energy=0, shield=1)
        world.update(actions=[], shield_decisions=[])
        other = deepcopy(world)
        other["combatants"][1]["initial"]["energy"] = 30
        controllers = [{"attack": "charge_if_ready", "shield": "never"}]
        branches = [{"fast_delay": 1, "miss_first_fast": True, "reverse_fast_batch": False}]
        service = ObservedSearch(fixture.sandbox)
        search_id = service.start([world, other], controllers, branches, 1)["search_id"]
        first = service.step(search_id, 0, 1)
        self.assertEqual(first["work"], 1)
        self.assertEqual(service.step(search_id, 0, 8)["work"], 1)
        self.assertTrue(service.pause(search_id)["paused"])
        self.assertEqual(service.step(search_id, 1, 8)["work"], 1)
        service = ObservedSearch(fixture.sandbox)
        service.pause(search_id, paused=False)
        resumed = service.step(search_id, 1, 8)
        other_store = BattleStore(service.store.path, owner_scope="second-owner")
        service.store = other_store
        self.assertIsNone(service.get(search_id))
        service.start([other, world], controllers, branches, 1)
        continuous = service.step(search_id, 0, 8)
        for key in ("work", "stop_reason", "evaluations"):
            self.assertEqual(resumed[key], continuous[key])

    def test_receipt_validation_and_rollback(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        from pvpoke_battle_store import BattleStoreError
        from pvpoke_observed_search import ObservedSearch, digest
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        world = scripted_spec(energy=0, shield=1)
        world.update(actions=[], shield_decisions=[])
        service = ObservedSearch(fixture.sandbox)
        search_id = service.start([world], [{"attack": "standard", "shield": "never"}],
                                  [{"fast_delay": 0, "miss_first_fast": False,
                                    "reverse_fast_batch": False}], 1)["search_id"]
        writer = service.store._writer

        @contextmanager
        def failing_write():
            with writer() as db:
                yield db
                raise BattleStoreError("injected write failure")

        with patch.object(service.store, "_writer", failing_write), self.assertRaises(BattleStoreError):
            service.step(search_id, 0, 1)
        self.assertEqual(service.get(search_id)["work"], 0)
        service.step(search_id, 0, 1)
        with patch("pvpoke_observed_search.versions", return_value={}):
            self.assertEqual(service.get(search_id)["status"], "stale")
        with writer() as db:
            work_id, rss = db.execute("SELECT work_id,rss FROM observed_work_v2").fetchone()
            receipt = {"status": "frontier", "key": "a" * 64, "events": [], "legal": []}
            import json
            db.execute("UPDATE observed_work_v2 SET receipt=?,digest=?",
                       (json.dumps(receipt), digest([work_id, receipt, rss])))
        with self.assertRaises(ValueError):
            service.get(search_id)

    def test_native_win_requires_resolved_damage_in_saved_receipt(self):
        import json
        from pvpoke_observed_search import ObservedSearch, digest
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        world = scripted_spec(energy=100, shield=0)
        world.update(actions=[], shield_decisions=[])
        world["combatants"][1]["initial"]["hp"] = 1
        service = ObservedSearch(fixture.sandbox)
        job = service.start([world], [{"attack": "standard", "shield": "never"}],
                            [{"fast_delay": 0, "miss_first_fast": False,
                              "reverse_fast_batch": False}], 1)
        search_id = job["search_id"]
        done = service.step(search_id, 0, 8)
        self.assertTrue(done["role"])
        self.assertTrue(any(e["worst_outcome"] == "self_ko_win" for e in done["evaluations"]))
        with service.store._writer() as db:
            for position, work_id, body, rss in db.execute(
                    "SELECT position,work_id,receipt,rss FROM observed_work_v2"):
                value = json.loads(body)
                if value.get("outcome") == "self_ko_win":
                    value["moves"] = []
                    db.execute("UPDATE observed_work_v2 SET receipt=?,digest=? WHERE position=?",
                               (json.dumps(value), digest([work_id, value, rss]), position))
                    break
        with self.assertRaisesRegex(ValueError, "differs from native move ledger"):
            service.get(search_id)
