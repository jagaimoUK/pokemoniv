"""Stage-5 read-only observed-policy integration, entirely synthetic fixtures."""
import copy
import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_analysis import MissingAnalysis
from pvpoke_observed_evidence import compare_observed, _policy_condition, _check_receipt_budget
from pvpoke_observed_search import ObservedSearch
from pvpoke_role_evaluation import RoleEvaluation, condition_id
from pvpoke_sandbox import SandboxService
from test_battle_service import FIXTURES
from test_sandbox import scripted_spec


class MissingObservedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / "analysis.sqlite3")
        self.client = DirectMatrixClient(gamemaster=FIXTURES / "strategy_gamemaster.json",
                                         log_dir=self.root)
        self.addCleanup(self.client.close)
        self.service = BattleService(self.client, store=self.store)
        self.sandbox = SandboxService(self.service)
        self.world = scripted_spec(energy=0, shield=1)
        self.world["actions"] = []
        self.world["shield_decisions"] = []
        self.controllers = [{"attack": "standard", "shield": "never"}]
        self.branches = [{"fast_delay": 0, "miss_first_fast": False,
                          "reverse_fast_batch": False}]
        self.roles = [{"id": "win", "priority": 3, "outcomes": ["self_ko_win"],
                       "minimum": {"hp": 0, "energy": 0, "shields": 0}}]

    def evaluation(self, requirement=None):
        request = {"schema": self.world["schema"], "mode": "standard",
                   "rules": self.world["rules"], "combatants": self.world["combatants"]}
        analysis = MissingAnalysis(self.store)
        analysis_id = analysis.save_plan(self.service, [request])
        normalized, _ = self.service._prepare(request)
        role = {"role_id": "win", "revision": 1, "meta_snapshot": "a" * 64,
                "priority": 3, "requirements": {
                    condition_id(normalized, full_hp=True):
                        requirement or {"outcomes": ["self_win"]}}}
        return RoleEvaluation(self.store).evaluate(
            analysis_id, role, active_versions=self.service.versions, normalizer=self.service)

    def observed(self, *, world=None, horizon=1, roles=None):
        return ObservedSearch(self.sandbox).start(
            [self.world if world is None else world], self.controllers,
            self.branches, horizon, roles=self.roles if roles is None else roles)["search_id"]

    def test_policy_scenario_counts_are_not_combined_across_opponents(self):
        policy = {"policy_hash": "e" * 64,
                  "outcomes": ["self_ko_win", "opponent_ko_win", None, "timeout"],
                  "roles": [{"id": "win", "scenario_meets": [True, False, None, False]}]}
        left = _policy_condition(policy, [0, 2], ["win"])
        right = _policy_condition(policy, [1, 3], ["win"])
        self.assertEqual(left["outcomes"]["self_ko_win"], 1)
        self.assertEqual(left["outcomes"]["opponent_ko_win"], 0)
        self.assertEqual(left["outcomes"]["unknown"], 1)
        self.assertIsNone(left["aligned_roles"][0]["meets"])
        self.assertEqual(right["outcomes"]["opponent_ko_win"], 1)
        self.assertEqual(right["outcomes"]["timeout"], 1)
        self.assertEqual(right["outcomes"]["self_ko_win"], 0)
        self.assertIs(right["aligned_roles"][0]["meets"], False)

    def test_link_matches_only_exact_build_and_starting_conditions_without_writes(self):
        role = self.evaluation()
        search_id = self.observed()
        old = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        with patch.object(self.sandbox.standard.client, "strategy",
                          side_effect=AssertionError("no native calculations")):
            result = compare_observed(self.service, role["evaluation_id"], [search_id])
        self.assertEqual(result["schema"], "missing-observed-evidence-v1")
        self.assertEqual(result["new_battles"], 0)
        self.assertTrue(result["standard_assessment_unchanged"])
        self.assertFalse(result["practical_role_covered"])
        self.assertEqual(result["information_fairness"], "not_established")
        self.assertEqual(result["live_reproducibility"], "not_verified")
        self.assertEqual(len(result["links"]), 1)
        linked = result["links"][0]
        self.assertEqual(linked["matching_worlds"], 1)
        self.assertEqual(linked["additional_worlds"], 0)
        self.assertEqual(len(linked["conditions"]), 1)
        self.assertEqual(linked["conditions"][0]["aligned_role_ids"], ["win"])
        self.assertIsNone(linked["conditions"][0]["standard_meets"])
        self.assertEqual(linked["evaluation_count"], 0)
        self.assertEqual(old, hashlib.sha256(self.store.path.read_bytes()).hexdigest())

    def test_different_opponent_iv_and_own_energy_cannot_be_joined(self):
        role = self.evaluation()
        for variant in ("opponent_iv", "own_energy", "other_build"):
            with self.subTest(variant=variant):
                other = copy.deepcopy(self.world)
                if variant == "opponent_iv":
                    # Lowering DEF remains legal at the same level and CP cap.
                    other["combatants"][1]["ivs"]["defense"] = 14
                elif variant == "own_energy":
                    other["combatants"][0]["initial"]["energy"] = 35
                else:
                    other["combatants"][0]["ivs"]["defense"] = (
                        other["combatants"][0]["ivs"]["defense"] + 1) % 16
                with self.assertRaisesRegex(ValueError, "does not match"):
                    compare_observed(self.service, role["evaluation_id"],
                                     [self.observed(world=other)])

    def test_unrelated_role_metrics_are_not_claimed_equivalent(self):
        role = self.evaluation({"minimum": {"fast_damage": 12}})
        result = compare_observed(self.service, role["evaluation_id"], [self.observed()])
        self.assertEqual(result["links"][0]["conditions"][0]["aligned_role_ids"], [])

    def test_foreign_owner_stale_search_and_invalid_ids_fail_closed(self):
        role = self.evaluation()
        search_id = self.observed()
        foreign = BattleService(
            self.client, store=BattleStore(self.store.path, owner_scope="foreign"))
        with self.assertRaisesRegex(ValueError, "unavailable for this owner"):
            compare_observed(foreign, role["evaluation_id"], [search_id])
        with self.assertRaises(ValueError):
            compare_observed(self.service, role["evaluation_id"], [search_id, search_id])
        with self.assertRaises(ValueError):
            compare_observed(self.service, role["evaluation_id"], ["x" * 64])
        with patch("pvpoke_observed_search.versions", return_value={}):
            with self.assertRaisesRegex(ValueError, "stale"):
                compare_observed(self.service, role["evaluation_id"], [search_id])

    def test_large_saved_replay_is_rejected_before_deep_verification(self):
        """One bounded comparison never consumes unrestricted saved receipts."""
        role = self.evaluation()
        search_id = self.observed()
        observed = ObservedSearch(self.sandbox)
        observed.step(search_id, 0, 1)
        with patch("pvpoke_observed_evidence.MAX_COMPARE_RECEIPTS", 0):
            with patch.object(ObservedSearch, "_fetch",
                              side_effect=AssertionError("expensive fetch must not start")):
                with patch.object(ObservedSearch, "_replay",
                                  side_effect=AssertionError("expensive replay must not start")):
                    with self.assertRaisesRegex(ValueError, "too large"):
                        compare_observed(self.service, role["evaluation_id"], [search_id])
        with patch("pvpoke_observed_evidence.MAX_COMPARE_RECEIPT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "too large"):
                compare_observed(self.service, role["evaluation_id"], [search_id])
        # A rejected advisory lookup must not delete or alter its saved job.
        self.assertEqual(observed.get(search_id)["work"], 1)

    def test_preflight_boundary_is_inclusive_but_rejects_either_excess(self):
        # All receipts are synthetic blobs. Only the cheap SQL preflight runs;
        # opaque bytes are never represented as valid replay results.
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE observed_jobs_v2(owner TEXT,id TEXT,cursor INTEGER)")
            db.execute("CREATE TABLE observed_work_v2(owner TEXT,id TEXT,receipt BLOB)")
            owner, sid = "synthetic-owner", "b" * 64
            db.execute("INSERT INTO observed_jobs_v2 VALUES (?,?,?)", (owner, sid, 1024))
            db.executemany("INSERT INTO observed_work_v2 VALUES (?,?,?)",
                           ((owner, sid, b"x" * 16384) for _ in range(1024)))
            self.assertEqual(_check_receipt_budget(db, owner, [sid]),
                             (1024, 16 * 1024 * 1024))
            with self.assertRaisesRegex(ValueError, "unavailable for this owner"):
                _check_receipt_budget(db, "another-owner", [sid])
            db.execute("UPDATE observed_jobs_v2 SET cursor=1025")
            with self.assertRaisesRegex(ValueError, "too large"):
                _check_receipt_budget(db, owner, [sid])
            db.execute("UPDATE observed_jobs_v2 SET cursor=1024")
            db.execute("UPDATE observed_work_v2 SET receipt=? WHERE rowid=1",
                       (b"x" * 16385,))
            with self.assertRaisesRegex(ValueError, "too large"):
                _check_receipt_budget(db, owner, [sid])

    def test_preflight_and_replay_share_one_sqlite_snapshot(self):
        role = self.evaluation()
        sid = self.observed()
        import pvpoke_observed_evidence as module
        original_check = module._check_receipt_budget
        original_fetch = ObservedSearch._fetch
        original_replay = ObservedSearch._replay
        snapshot = []
        replayed = []

        def preflight(db, owner, ids):
            snapshot.append(db)
            return original_check(db, owner, ids)

        def fetch(search, db, search_id):
            self.assertIs(db, snapshot[0])
            return original_fetch(search, db, search_id)

        def replay(search, raw):
            with self.assertRaises(sqlite3.ProgrammingError):
                snapshot[0].execute("SELECT 1")
            replayed.append(raw["search_id"])
            return original_replay(search, raw)

        with patch.object(module, "_check_receipt_budget", side_effect=preflight):
            with patch.object(ObservedSearch, "_fetch", autospec=True, side_effect=fetch):
                with patch.object(ObservedSearch, "_replay", autospec=True, side_effect=replay):
                    result = compare_observed(self.service, role["evaluation_id"], [sid])
        self.assertEqual(replayed, [sid])
        self.assertEqual(result["links"][0]["search_id"], sid)

    def test_parallel_readers_return_same_owner_scoped_result(self):
        role = self.evaluation()
        sid = self.observed()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda _: compare_observed(self.service, role["evaluation_id"], [sid]),
                range(12)))
        self.assertTrue(all(row == results[0] for row in results))

    def test_multiple_saved_jobs_do_not_merge_policies(self):
        role = self.evaluation()
        ids = [self.observed(horizon=horizon) for horizon in (1, 2)]
        result = compare_observed(self.service, role["evaluation_id"], ids)
        self.assertEqual([row["search_id"] for row in result["links"]], ids)
        self.assertTrue(all(row["build_id"] == result["links"][0]["build_id"]
                            for row in result["links"]))

    def test_concurrent_writer_succeeds_during_reader_replay_in_delete_mode(self):
        """In DELETE mode, reader releases its SHARED lock before in-memory replay so writers proceed."""
        role = self.evaluation()
        sid = self.observed()
        observed = ObservedSearch(self.sandbox)
        observed.step(sid, 0, 1)

        with self.store._reader() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")

        from pvpoke_observed_search import Search
        original_advance = Search.advance

        for mode in ("compare_observed", "observed_get"):
            with self.subTest(mode=mode):
                reader_in_replay = threading.Event()
                writer_done = threading.Event()
                writer_result = {}
                key = f"test-key-{mode}"

                def hook_advance(search_inst, state, value):
                    reader_in_replay.set()
                    self.assertTrue(writer_done.wait(timeout=5.0), "writer thread timed out")
                    return original_advance(search_inst, state, value)

                def writer_task():
                    try:
                        self.assertTrue(reader_in_replay.wait(timeout=5.0), "reader did not enter replay")
                        with self.store._writer(critical=False) as db:
                            db.execute(
                                "INSERT OR IGNORE INTO battle_results VALUES (?,?,?,?,?,?)",
                                ("local-owner", key, "standard-summary-v1", b"{}", "hash", 1),
                            )
                        writer_result["success"] = True
                    except Exception as exc:
                        writer_result["error"] = exc
                    finally:
                        writer_done.set()

                thread = threading.Thread(target=writer_task)
                with patch.object(Search, "advance", hook_advance):
                    thread.start()
                    try:
                        if mode == "compare_observed":
                            result = compare_observed(self.service, role["evaluation_id"], [sid])
                            self.assertEqual(result["links"][0]["search_id"], sid)
                        else:
                            summary = observed.get(sid)
                            self.assertEqual(summary["work"], 1)
                    finally:
                        writer_done.set()
                        thread.join(timeout=5.0)
                self.assertFalse(thread.is_alive())
                self.assertTrue(writer_result.get("success"),
                                f"Writer failed with error: {writer_result.get('error')}")
                with self.store._reader() as db:
                    count = db.execute(
                        "SELECT COUNT(*) FROM battle_results WHERE owner_scope=? AND battle_key=?",
                        ("local-owner", key),
                    ).fetchone()[0]
                self.assertEqual(count, 1)

    def test_snapshot_isolation_prevents_concurrent_append_mixing(self):
        """Concurrent observed.step during replay must not corrupt the in-flight snapshot."""
        role = self.evaluation()
        sid = self.observed(horizon=2)
        observed = ObservedSearch(self.sandbox)
        observed.step(sid, 0, 1)

        from pvpoke_observed_search import Search
        original_advance = Search.advance
        reader_thread = threading.current_thread()
        reader_in_replay = threading.Event()
        writer_done = threading.Event()
        writer_result = {}

        def hook_advance(search_inst, state, value):
            if threading.current_thread() is reader_thread and not reader_in_replay.is_set():
                reader_in_replay.set()
                self.assertTrue(writer_done.wait(timeout=5.0), "concurrent step timed out")
            return original_advance(search_inst, state, value)

        def concurrent_step():
            try:
                self.assertTrue(reader_in_replay.wait(timeout=5.0), "reader did not enter replay")
                stepped = ObservedSearch(self.sandbox).step(sid, 1, 1)
                writer_result["work"] = stepped["work"]
            except Exception as exc:
                writer_result["error"] = exc
            finally:
                writer_done.set()

        thread = threading.Thread(target=concurrent_step)
        with patch.object(Search, "advance", hook_advance):
            thread.start()
            try:
                result = compare_observed(self.service, role["evaluation_id"], [sid])
            finally:
                writer_done.set()
                thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive())
        self.assertNotIn("error", writer_result)
        self.assertEqual(writer_result.get("work"), 2)
        self.assertEqual(result["links"][0]["work"], 1)
        after = compare_observed(self.service, role["evaluation_id"], [sid])
        self.assertEqual(after["links"][0]["work"], 2)

    def test_reader_cleans_up_on_fetch_and_replay_errors(self):
        """Errors during SQL fetch or in-memory replay must not leak SQLite locks."""
        role = self.evaluation()
        sid = self.observed()
        observed = ObservedSearch(self.sandbox)
        observed.step(sid, 0, 1)

        from pvpoke_battle_store import BattleStoreError
        # 1. Error during _fetch (e.g. non-existent search ID)
        with self.assertRaisesRegex(ValueError, "unavailable for this owner"):
            compare_observed(self.service, role["evaluation_id"], ["f" * 64])

        # 2. Error during _replay (corrupt digest)
        with self.store._writer(critical=True) as db:
            db.execute("UPDATE observed_work_v2 SET digest='invalid' WHERE id=?", (sid,))
        with self.assertRaises(BattleStoreError):
            compare_observed(self.service, role["evaluation_id"], [sid])

        # Writer must proceed immediately after both failure paths
        with self.store._writer(critical=False) as db:
            db.execute("INSERT OR IGNORE INTO battle_results VALUES (?,?,?,?,?,?)",
                       ("local-owner", "test-key-cleanup", "standard-summary-v1", b"{}", "hash", 1))

    def test_1024_valid_receipts_succeed_and_1025_is_rejected_before_fetch(self):
        """Exact 1024 valid receipts replay cleanly; 1025th fails in SQL preflight before _fetch."""
        from pvpoke_observed_observation import history_key
        from pvpoke_observed_search import canonical, digest, _move_data

        role = self.evaluation()
        controllers = [
            {"attack": "standard", "shield": "never"},
            {"attack": "charge_if_ready", "shield": "never"},
            {"attack": "standard", "shield": "always"},
            {"attack": "charge_if_ready", "shield": "always"},
        ]
        branches = [
            {"fast_delay": d, "miss_first_fast": m, "reverse_fast_batch": False}
            for d in (0, 1) for m in (False, True)
        ]
        worlds = []
        for energy in range(32):
            world = copy.deepcopy(self.world)
            world["combatants"][1]["initial"]["energy"] = energy
            worlds.append(world)

        observed = ObservedSearch(self.sandbox)
        sid = observed.start(worlds, controllers, branches, 1, roles=self.roles)["search_id"]
        with self.store._reader() as db:
            snap = observed._fetch(db, sid)
        loaded = observed._replay(snap)
        search, state = loaded["search"], loaded["state"]
        move_data = _move_data(self.sandbox)
        events = [{"seq": 1, "observed_time_range": [1, 1], "kind": "window"}]
        fkey = history_key(search.context, events)

        def next_row(pos):
            item = state["frontier"][-1]
            scenario = search.scenarios[item["index"]]
            wid = observed._work_id(sid, search, state)
            if fkey not in item["table"]:
                receipt = {"status": "frontier", "key": fkey, "events": events,
                           "legal": ["fast", "wait_one_window"]}
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
            return (self.store.owner_scope, sid, pos, wid,
                    canonical(receipt), digest([wid, receipt, 1024]), 1024)

        rows_1024 = [next_row(pos) for pos in range(1024)]
        with self.store._writer() as db:
            db.executemany("INSERT INTO observed_work_v2 VALUES (?,?,?,?,?,?,?)", rows_1024)
            db.execute("UPDATE observed_jobs_v2 SET cursor=? WHERE owner=? AND id=?",
                       (1024, self.store.owner_scope, sid))

        result = compare_observed(self.service, role["evaluation_id"], [sid])
        self.assertEqual(result["links"][0]["work"], 1024)
        self.assertEqual(observed.get(sid)["work"], 1024)

        row_1025 = next_row(1024)
        with self.store._writer() as db:
            db.execute("INSERT INTO observed_work_v2 VALUES (?,?,?,?,?,?,?)", row_1025)
            db.execute("UPDATE observed_jobs_v2 SET cursor=? WHERE owner=? AND id=?",
                       (1025, self.store.owner_scope, sid))

        with patch.object(ObservedSearch, "_fetch",
                          side_effect=AssertionError("_fetch must not run past 1024")):
            with self.assertRaisesRegex(ValueError, "too large"):
                compare_observed(self.service, role["evaluation_id"], [sid])


if __name__ == "__main__":
    unittest.main()
