import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

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

    def test_extended_job_survives_backup_restore_and_sqlite_full(self):
        from contextlib import contextmanager
        import sqlite3
        from unittest.mock import patch
        from pvpoke_battle_store import BattleStore
        from pvpoke_observed_search import ObservedSearch
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec
        from tools.cloud_migration_backup import backup, restore

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.sandbox.store.path.parent
        volume = root / "observed-volume"
        service = ObservedSearch(fixture.sandbox)
        service.store = BattleStore(volume / "battle_analysis.sqlite3")
        spec = scripted_spec(energy=100, shield=0)
        spec.update(actions=[], shield_decisions=[])
        spec["combatants"][1]["initial"]["hp"] = 1
        controllers = [{"attack": "charge_if_ready", "shield": "never"}]
        branches = [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}]
        roles = [{"id": "win_with_reserve", "priority": 1,
                  "outcomes": ["self_ko_win"], "minimum": {"energy": 60}}]
        legacy = service.start([spec], controllers, branches, 1)
        self.assertEqual(service.start([spec], controllers, branches, 1)["search_id"], legacy["search_id"])
        job = service.start([spec], controllers, branches, 1, roles)
        self.assertNotEqual(job["search_id"], legacy["search_id"])
        before = service.step(job["search_id"], 0, 3)
        self.assertGreater(before["evaluation_count"], 0)
        bundle, restored = root / "observed-backup", root / "observed-restored"
        backup({"volume": volume}, bundle)
        restore(bundle, restored)
        service.store = BattleStore(restored / "volume" / service.store.path.name)
        self.assertEqual(service.get(job["search_id"]), before)
        writer = service.store._writer

        @contextmanager
        def full_writer():
            with writer() as db:
                db.execute("PRAGMA max_page_count = " + str(db.execute("PRAGMA page_count").fetchone()[0]))
                db.execute("""CREATE TEMP TRIGGER force_full AFTER INSERT ON observed_work_v2
                              BEGIN UPDATE observed_jobs_v2 SET plan=randomblob(1048576); END""")
                yield db

        with patch.object(service.store, "_writer", full_writer):
            with self.assertRaises(sqlite3.OperationalError) as error:
                service.step(job["search_id"], before["work"], 1)
        self.assertEqual(error.exception.sqlite_errorcode, sqlite3.SQLITE_FULL)
        self.assertEqual(service.get(job["search_id"]), before)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: service.step(job["search_id"], before["work"], 1), range(2)))
        self.assertEqual([r["work"] for r in results], [before["work"] + 1] * 2)
        with patch("pvpoke_observed_search.native_replay",
                   return_value=({"status": "unknown", "reason": "runner_unavailable"}, 0)):
            failed = service.step(job["search_id"], before["work"] + 1, 1)
        self.assertIs(failed["role"], True)
        self.assertTrue(any("runner_unavailable" in row["outcomes"] for row in failed["evaluations"]))
        done = service.get(job["search_id"])
        self.assertIs(done["role"], True)
        self.assertGreater(done["work"], before["work"])

    def test_step_releases_sqlite_lock_during_node_replay_for_writers_readers_and_other_jobs(self):
        import sqlite3
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from copy import deepcopy
        from unittest.mock import patch
        import pvpoke_observed_search as obs_mod
        from pvpoke_observed_search import ObservedSearch
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        world_a = scripted_spec(energy=0, shield=1)
        world_a.update(actions=[], shield_decisions=[])
        world_b = deepcopy(world_a)
        world_b["combatants"][1]["initial"]["energy"] = 25
        controllers = [{"attack": "standard", "shield": "never"}]
        branches = [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}]

        service = ObservedSearch(fixture.sandbox)
        job_a = service.start([world_a], controllers, branches, 1)["search_id"]
        job_b = service.start([world_b], controllers, branches, 1)["search_id"]
        self.assertNotEqual(job_a, job_b)

        with service.store._reader() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")

        orig_replay = obs_mod.replay
        job_a_in_replay = threading.Event()
        concurrent_done = threading.Event()
        concurrent_results = {}

        def hooked_replay(sandbox, context, plan, scenario, item, timeout):
            # Trigger concurrency barrier only on job A's first replay.
            if (not job_a_in_replay.is_set()
                    and plan["manifest"][scenario]["battle"]["initial"][1].get("energy_points", 0) == 0):
                job_a_in_replay.set()
                self.assertTrue(concurrent_done.wait(timeout=5.0), "concurrent operations timed out")
            return orig_replay(sandbox, context, plan, scenario, item, timeout)

        def run_concurrent_ops():
            try:
                self.assertTrue(job_a_in_replay.wait(timeout=5.0), "job A did not enter replay")
                # 1. Another actual ObservedSearch job steps concurrently (writes + Node replay).
                stepped_b = ObservedSearch(fixture.sandbox).step(job_b, 0, 1)
                # 2. A BattleStore writer writes concurrently in DELETE mode.
                with service.store._writer() as db:
                    db.execute("INSERT OR IGNORE INTO battle_results VALUES (?,?,?,?,?,?)",
                               ("local-owner", "concurrent-key", "standard-summary-v1", b"{}", "h", 1))
                # 3. A reader inspects job A concurrently.
                got_a = ObservedSearch(fixture.sandbox).get(job_a)
                concurrent_results["job_b_work"] = stepped_b["work"]
                concurrent_results["job_a_work"] = got_a["work"]
                concurrent_results["ok"] = True
            except Exception as exc:
                concurrent_results["error"] = exc
            finally:
                concurrent_done.set()

        t = threading.Thread(target=run_concurrent_ops)
        with patch.object(obs_mod, "replay", side_effect=hooked_replay):
            t.start()
            try:
                res_a = service.step(job_a, 0, 1)
            finally:
                concurrent_done.set()
                t.join(timeout=5.0)
        self.assertTrue(concurrent_results.get("ok"), f"Concurrent error: {concurrent_results.get('error')}")
        self.assertEqual(concurrent_results["job_b_work"], 1)
        self.assertEqual(concurrent_results["job_a_work"], 0)
        self.assertEqual(res_a["work"], 1)

    def test_step_deduplication_and_occ_cross_process_conflict(self):
        from contextlib import nullcontext
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import pvpoke_observed_search as obs_mod
        from pvpoke_observed_search import ObservedSearch
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        world = scripted_spec(energy=0, shield=1)
        world.update(actions=[], shield_decisions=[])
        service = ObservedSearch(fixture.sandbox)
        sid = service.start([world], [{"attack": "standard", "shield": "never"}],
                            [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}], 1)["search_id"]

        # 1. In-process concurrent duplicate calls execute replay() only ONCE.
        replay_calls = []
        orig_replay = obs_mod.replay

        def count_replay(*args, **kwargs):
            replay_calls.append(1)
            return orig_replay(*args, **kwargs)

        with patch.object(obs_mod, "replay", side_effect=count_replay):
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda _: service.step(sid, 0, 1), range(2)))
        self.assertEqual([r["work"] for r in results], [1, 1])
        self.assertEqual(len(replay_calls), 1)

        # 2. Duplicate retry of already committed cursor=0 executes 0 replays.
        replay_calls.clear()
        with patch.object(obs_mod, "replay", side_effect=count_replay):
            stale_retry = service.step(sid, 0, 1)
        self.assertEqual(stale_retry["work"], 1)
        self.assertEqual(len(replay_calls), 0)

        # 3. Cross-process OCC simulation (bypass in-process _job_step_lock):
        # both workers compute position=1 concurrently; winner commits cursor=2, loser aborts commit cleanly.
        both_in_replay = threading.Barrier(2, timeout=5.0)

        def racing_replay(*args, **kwargs):
            both_in_replay.wait()
            return orig_replay(*args, **kwargs)

        with patch.object(obs_mod, "_job_step_lock", return_value=nullcontext()), \
             patch.object(obs_mod, "replay", side_effect=racing_replay):
            with ThreadPoolExecutor(2) as pool:
                occ_results = list(pool.map(lambda _: service.step(sid, 1, 1), range(2)))
        self.assertEqual([r["work"] for r in occ_results], [2, 2])
        with service.store._reader() as db:
            row_count = db.execute(
                "SELECT COUNT(*) FROM observed_work_v2 WHERE owner=? AND id=?",
                (service.store.owner_scope, sid),
            ).fetchone()[0]
        self.assertEqual(row_count, 2)

    def test_step_pause_during_replay_discards_uncommitted_receipt_and_resumes_cleanly(self):
        import threading
        from unittest.mock import patch
        import pvpoke_observed_search as obs_mod
        from pvpoke_observed_search import ObservedSearch
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        world = scripted_spec(energy=0, shield=1)
        world.update(actions=[], shield_decisions=[])
        service = ObservedSearch(fixture.sandbox)
        sid = service.start([world], [{"attack": "standard", "shield": "never"}],
                            [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}], 1)["search_id"]

        in_replay = threading.Event()
        paused_done = threading.Event()
        orig_replay = obs_mod.replay
        pause_result = {}

        def pause_during_replay(*args, **kwargs):
            in_replay.set()
            self.assertTrue(paused_done.wait(timeout=5.0))
            return orig_replay(*args, **kwargs)

        def call_pause():
            try:
                self.assertTrue(in_replay.wait(timeout=5.0))
                pause_result["summary"] = ObservedSearch(fixture.sandbox).pause(sid, paused=True)
            finally:
                paused_done.set()

        t = threading.Thread(target=call_pause)
        with patch.object(obs_mod, "replay", side_effect=pause_during_replay):
            t.start()
            try:
                stepped = service.step(sid, 0, 2)
            finally:
                paused_done.set()
                t.join(timeout=5.0)

        self.assertTrue(pause_result["summary"]["paused"])
        self.assertTrue(stepped["paused"])
        self.assertEqual(stepped["work"], 0)
        with service.store._reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM observed_work_v2 WHERE owner=? AND id=?",
                           (service.store.owner_scope, sid)).fetchone()[0],
                0,
            )
        # Resume and finish cleanly without duplicate receipts.
        service.pause(sid, paused=False)
        finished = service.step(sid, 0, 8)
        self.assertGreater(finished["work"], 0)
        self.assertFalse(finished["paused"])
        self.assertIsNotNone(finished["stop_reason"])

    def test_step_rejects_invalid_inputs_foreign_owner_stale_version_and_handles_replay_failure(self):
        from unittest.mock import patch
        from pvpoke_battle_store import BattleStore
        import pvpoke_observed_search as obs_mod
        from pvpoke_observed_search import ObservedSearch
        from test_observed_native_runner import NativeObservedMultiTurnTests
        from test_sandbox import scripted_spec

        fixture = NativeObservedMultiTurnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        world = scripted_spec(energy=0, shield=1)
        world.update(actions=[], shield_decisions=[])
        service = ObservedSearch(fixture.sandbox)
        sid = service.start([world], [{"attack": "standard", "shield": "never"}],
                            [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}], 1)["search_id"]

        with self.assertRaises(ValueError):
            service.step("bad-id", 0, 1)
        with self.assertRaises(ValueError):
            service.step(sid, -1, 1)
        with self.assertRaises(ValueError):
            service.step(sid, 0, 99)

        # Foreign owner cannot see or advance this job.
        foreign_sandbox = type(fixture.sandbox)(
            type(fixture.sandbox.standard)(
                fixture.sandbox.standard.client,
                store=BattleStore(service.store.path, owner_scope="other-owner"),
            )
        )
        self.assertIsNone(ObservedSearch(foreign_sandbox).step(sid, 0, 1))

        # Unexpected exception before save leaves work unchanged and lock released.
        with patch.object(obs_mod, "replay", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service.step(sid, 0, 1)
        self.assertEqual(service.get(sid)["work"], 0)

        # Wall timeout returns unknown reason wall_limit cleanly.
        with patch("pvpoke_observed_search.native_replay",
                   return_value=({"status": "unknown", "reason": "wall_limit"}, 123)):
            timed_out = service.step(sid, 0, 1)
        self.assertEqual(timed_out["work"], 1)
        self.assertEqual(timed_out["evaluations"][0]["outcomes"], ["wall_limit"])

        # Stale version rejection during commit leaves work unchanged on an active job.
        sid_active = service.start(
            [world],
            [{"attack": "standard", "shield": "never"}, {"attack": "charge_if_ready", "shield": "never"}],
            [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}],
            1,
        )["search_id"]
        orig_versions = obs_mod.versions
        calls = []
        def flip_version(sandbox, extended=False):
            calls.append(1)
            return orig_versions(sandbox, extended) if len(calls) == 1 else {"stale": "v"}

        with patch.object(obs_mod, "versions", side_effect=flip_version):
            res_stale = service.step(sid_active, 0, 1)
        self.assertEqual(res_stale["status"], "stale")
        self.assertEqual(service.get(sid_active)["work"], 0)

    def test_pause_releases_writer_lock_allowing_concurrent_writers_and_readers(self):
        """ObservedSearch.pause() must release writer lock before snapshot replay/summary."""
        from test_sandbox import scripted_spec
        from test_battle_service import FIXTURES
        from pvpoke_battle_store import BattleStore
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_sandbox import SandboxService
        from pvpoke_observed_search import ObservedSearch, Search, canonical, digest, _move_data
        from pvpoke_observed_observation import history_key, ObservationV2

        world = scripted_spec(energy=100, shield=1)
        world["combatants"][0]["initial"]["energy"] = 100
        world["actions"] = []
        world["shield_decisions"] = []
        controllers = [
            {"attack": atk, "shield": shd}
            for atk in ("standard", "charge_if_ready")
            for shd in ("standard", "always", "never", "first")
        ]
        branches = [
            {"fast_delay": d, "miss_first_fast": m, "reverse_fast_batch": False}
            for d in (0, 1) for m in (False, True)
        ]
        worlds = []
        for energy in range(32):
            w = copy.deepcopy(world)
            w["combatants"][1]["initial"]["energy"] = energy
            worlds.append(w)
        roles = [{"id": "win", "priority": 3, "outcomes": ["self_ko_win"],
                  "minimum": {"hp": 0, "energy": 0, "shields": 0}}]

        for mode in ("DELETE", "WAL"):
            with self.subTest(journal_mode=mode):
                root = Path(self.enterContext(tempfile.TemporaryDirectory()))
                store = BattleStore(root / f"test_{mode}.sqlite3")
                with store._writer() as db:
                    db.execute(f"PRAGMA journal_mode={mode}")
                client = DirectMatrixClient(gamemaster=FIXTURES / "strategy_gamemaster.json", log_dir=root)
                self.addCleanup(client.close)
                service = BattleService(client, store=store)
                sandbox = SandboxService(service)
                observed = ObservedSearch(sandbox)

                sid = observed.start(worlds, controllers, branches, 2, roles=roles)["search_id"]
                sid2 = observed.start(worlds[:1], controllers[:1], branches[:1], 1, roles=roles)["search_id"]

                # Seed 1024 receipts
                with store._reader() as db:
                    snap = observed._fetch(db, sid)
                loaded = observed._replay(snap)
                search, state = loaded["search"], loaded["state"]
                move_data = _move_data(sandbox)
                events = [{"seq": 1, "observed_time_range": [1, 1], "kind": "window"}]
                fkey = history_key(search.context, events)

                def next_row(pos):
                    item = state["frontier"][-1]
                    scenario = search.scenarios[item["index"]]
                    wid = observed._work_id(sid, search, state)
                    if fkey not in item["table"]:
                        view = ObservationV2.read(search.context, events)
                        receipt = {"status": "frontier", "key": fkey, "events": events,
                                   "legal": list(view.legal)}
                    else:
                        battle = loaded["plan"]["manifest"][scenario]["battle"]
                        init_state = [
                            [battle["initial"][s].get("hp_points", 100),
                             battle["initial"][s].get("energy_points", 0),
                             battle["shields"][s]]
                            for s in (0, 1)
                        ]
                        fast_id = battle["self"]["fast"]
                        egain = int(move_data[fast_id]["energyGain"])
                        receipt = {
                            "status": "complete", "outcome": "self_ko_win", "initial": init_state,
                            "moves": [{"actor": 0, "move": fast_id, "kind": "fast", "window": 1,
                                       "damage": init_state[1][0], "shielded": False}],
                            "terminal": [[init_state[0][0], min(100, init_state[0][1] + egain), init_state[0][2]],
                                         [0, init_state[1][1], init_state[1][2]]],
                        }
                    search.advance(state, receipt)
                    return (store.owner_scope, sid, pos, wid,
                            canonical(receipt), digest([wid, receipt, 1024]), 1024)

                for start_idx in range(0, 1024, 512):
                    end_idx = start_idx + 512
                    batch = [next_row(pos) for pos in range(start_idx, end_idx)]
                    with store._writer() as db:
                        db.executemany("INSERT INTO observed_work_v2 VALUES (?,?,?,?,?,?,?)", batch)
                        db.execute("UPDATE observed_jobs_v2 SET cursor=? WHERE owner=? AND id=?",
                                   (end_idx, store.owner_scope, sid))

                # Test concurrent writer during pause
                writer_success = threading.Event()
                writer_error = []

                orig_replay = observed._replay
                def slow_replay(snapshot):
                    # Simulate replay taking long enough that old lock would have caused timeout
                    try:
                        with store._writer(critical=False) as db:
                            db.execute("UPDATE observed_jobs_v2 SET cursor=0 WHERE id=?", (sid2,))
                        writer_success.set()
                    except Exception as exc:
                        writer_error.append(exc)
                    return orig_replay(snapshot)

                with patch.object(observed, "_replay", slow_replay):
                    res_p = observed.pause(sid, paused=True)
                    self.assertEqual(res_p["status"], "stopped")
                    self.assertEqual(res_p["work"], 1024)
                    self.assertTrue(writer_success.is_set())
                    self.assertEqual(writer_error, [])

                # Verify resume works cleanly
                res_r = observed.pause(sid, paused=False)
                self.assertEqual(res_r["status"], "pending")
                self.assertEqual(res_r["work"], 1024)

                # Validation checks on pause
                with self.assertRaises(ValueError):
                    observed.pause(sid, paused="not-a-bool")
                with self.assertRaises(ValueError):
                    observed.pause("invalid-sid", paused=True)
                self.assertIsNone(observed.pause("a" * 64, paused=True))

    def test_pause_resume_race_conditions_and_occ_scenarios(self):
        """ObservedSearch.step() OCC correctly handles pause during Node execution and resume."""
        from test_sandbox import scripted_spec
        from test_battle_service import FIXTURES
        from pvpoke_battle_store import BattleStore
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_sandbox import SandboxService
        from pvpoke_observed_search import ObservedSearch
        world = scripted_spec(energy=0, shield=1)
        world["actions"] = []
        world["shield_decisions"] = []
        controllers = [{"attack": "standard", "shield": "never"}]
        branches = [{"fast_delay": 0, "miss_first_fast": False, "reverse_fast_batch": False}]
        roles = [{"id": "win", "priority": 3, "outcomes": ["self_ko_win"],
                  "minimum": {"hp": 0, "energy": 0, "shields": 0}}]

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        store = BattleStore(root / "test_occ.sqlite3")
        client = DirectMatrixClient(gamemaster=FIXTURES / "strategy_gamemaster.json", log_dir=root)
        self.addCleanup(client.close)
        service = BattleService(client, store=store)
        sandbox = SandboxService(service)
        observed = ObservedSearch(sandbox)

        # 1. Pause during Node execution -> discard uncommitted receipt
        w1 = [copy.deepcopy(world)]
        w1[0]["combatants"][1]["initial"]["energy"] = 10
        sid1 = observed.start(w1, controllers, branches, 2, roles=roles)["search_id"]
        node_started = threading.Event()
        pause_done = threading.Event()

        import pvpoke_observed_search
        orig_replay = pvpoke_observed_search.replay
        def slow_replay(sandbox_arg, context_arg, plan_arg, scenario_key, item, remaining):
            node_started.set()
            pause_done.wait(timeout=5.0)
            return orig_replay(sandbox_arg, context_arg, plan_arg, scenario_key, item, remaining)

        def pause_worker():
            node_started.wait(timeout=5.0)
            observed.pause(sid1, paused=True)
            pause_done.set()

        t_pause = threading.Thread(target=pause_worker)
        with patch.object(pvpoke_observed_search, "replay", slow_replay):
            t_pause.start()
            s1 = observed.step(sid1, 0, 1)
            t_pause.join(timeout=5.0)

        self.assertEqual(s1["status"], "stopped")
        self.assertEqual(s1["work"], 0)
        with store._reader() as db:
            c1, p1 = db.execute("SELECT cursor, paused FROM observed_jobs_v2 WHERE id=?", (sid1,)).fetchone()
            w1_count = db.execute("SELECT COUNT(*) FROM observed_work_v2 WHERE id=?", (sid1,)).fetchone()[0]
        self.assertEqual(c1, 0)
        self.assertEqual(p1, 1)
        self.assertEqual(w1_count, 0)

        # 2. Pause then resume during Node execution -> valid commit succeeds
        w2 = [copy.deepcopy(world)]
        w2[0]["combatants"][1]["initial"]["energy"] = 20
        sid2 = observed.start(w2, controllers, branches, 2, roles=roles)["search_id"]
        node_started2 = threading.Event()
        resume_done = threading.Event()

        def slow_replay2(sandbox_arg, context_arg, plan_arg, scenario_key, item, remaining):
            node_started2.set()
            resume_done.wait(timeout=5.0)
            return orig_replay(sandbox_arg, context_arg, plan_arg, scenario_key, item, remaining)

        def pause_resume_worker():
            node_started2.wait(timeout=5.0)
            observed.pause(sid2, paused=True)
            observed.pause(sid2, paused=False)
            resume_done.set()

        t_pr = threading.Thread(target=pause_resume_worker)
        with patch.object(pvpoke_observed_search, "replay", slow_replay2):
            t_pr.start()
            s2 = observed.step(sid2, 0, 1)
            t_pr.join(timeout=5.0)

        self.assertEqual(s2["work"], 1)
        with store._reader() as db:
            c2, p2 = db.execute("SELECT cursor, paused FROM observed_jobs_v2 WHERE id=?", (sid2,)).fetchone()
            w2_count = db.execute("SELECT COUNT(*) FROM observed_work_v2 WHERE id=?", (sid2,)).fetchone()[0]
        self.assertEqual(c2, 1)
        self.assertEqual(p2, 0)
        self.assertEqual(w2_count, 1)

        # 3. Multiple pause/resume cycles preserve historical integrity
        w3 = [copy.deepcopy(world)]
        w3[0]["combatants"][1]["initial"]["energy"] = 30
        sid3 = observed.start(w3, controllers, branches, 2, roles=roles)["search_id"]
        for step_idx in range(2):
            observed.step(sid3, step_idx, 1)
            observed.pause(sid3, paused=True)
            self.assertEqual(observed.get(sid3)["status"], "stopped")
            observed.pause(sid3, paused=False)
            self.assertEqual(observed.get(sid3)["status"], "pending")
        self.assertEqual(observed.get(sid3)["work"], 2)
        with store._reader() as db:
            rows = db.execute("SELECT position FROM observed_work_v2 WHERE id=? ORDER BY position", (sid3,)).fetchall()
        self.assertEqual([r[0] for r in rows], [0, 1])
