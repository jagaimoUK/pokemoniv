import copy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore, SCHEMA_VERSION
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_analysis import AnalysisUnavailable, MissingAnalysis
from test_battle_service import FIXTURES, battle_spec
from tools import cloud_migration_backup as backup


class MissingAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        master = self.root / 'gamemaster.json'
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', master)
        self.store = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3')
        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)
        self.service = BattleService(client, store=self.store)
        self.analysis = MissingAnalysis(self.store)

    def test_coverage_exact_conditions_and_evaluation_do_not_start_engine(self):
        spec = battle_spec()
        changed = copy.deepcopy(spec)
        changed['combatants'][0]['initial']['energy'] = 80
        with patch.object(self.service.client, 'strategy') as run:
            plan = self.analysis.save_plan(self.service, [spec, changed, spec])
            state = self.analysis.evidence(plan, active_versions=self.service.versions)
            self.assertEqual(state['state'], 'unknown')
            self.assertEqual(state['coverage'], {'requested': 2, 'completed': 0})
            self.assertTrue(all(cell['facts'] is None for cell in state['cells']))
            run.assert_not_called()

        first = self.service.simulate(spec)
        self.assertEqual(first['status'], 'complete')
        with patch.object(self.service.client, 'strategy') as run:
            state = self.analysis.evidence(plan, active_versions=self.service.versions)
            self.assertEqual(state['state'], 'partial')
            self.assertEqual(state['coverage'], {'requested': 2, 'completed': 1})
            by_key = {cell['battle_key']: cell for cell in state['cells']}
            known = by_key[first['battle_key']]
            self.assertEqual(known['facts']['rating'], first['rating'])
            unknown = next(cell for cell in state['cells'] if cell['state'] == 'unknown')
            self.assertIsNone(unknown['facts'])
            self.assertTrue(all(cell['ownership'] == 'unknown' and cell['recommendation'] == 'unreviewed'
                                for cell in state['cells']))
            self.assertEqual(plan, self.analysis.save_plan(self.service, [changed, first['spec']]))
            # Two consumers can change their rating criterion on the same facts.
            rating = known['facts']['rating']
            self.assertEqual([rating >= floor for floor in (rating, rating + 1)], [True, False])
            run.assert_not_called()

        self.assertEqual(self.service.simulate(changed)['status'], 'complete')
        state = self.analysis.evidence(plan, active_versions=self.service.versions)
        self.assertEqual(state['state'], 'complete')
        self.assertEqual(self.service.cache_stats['engine_calls'], 2)

    def test_old_version_and_other_owner_do_not_supply_current_evidence(self):
        first = self.service.simulate(battle_spec())
        plan = self.analysis.save_plan(self.service, [battle_spec()])
        for field in ('engine', 'game_data'):
            with self.subTest(field=field):
                new = {**self.service.versions, field: '0' * 64}
                state = self.analysis.evidence(plan, active_versions=new)
                self.assertEqual(state['state'], 'stale')
                self.assertIsNone(state['cells'][0]['facts'])
                self.assertEqual(state['coverage']['completed'], 0)
        other_store = BattleStore(self.store.path, owner_scope='another-owner')
        other = MissingAnalysis(other_store)
        self.assertIsNone(other.evidence(plan, active_versions=self.service.versions))
        self.assertEqual(other.save_plan(self.service, [battle_spec()]), plan)
        self.assertEqual(other.evidence(plan, active_versions=self.service.versions)['state'], 'unknown')
        self.assertEqual(self.store.get(first['battle_key'], first['spec'], first['versions']), first)

    def test_corrupt_row_and_database_are_not_modified(self):
        first = self.service.simulate(battle_spec())
        plan = self.analysis.save_plan(self.service, [battle_spec()])
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE battle_results SET result_sha256 = ?', ('0' * 64,))
        damaged = self.store.path.read_bytes()
        state = self.analysis.evidence(plan, active_versions=self.service.versions)
        self.assertEqual(state['state'], 'unknown')
        self.assertEqual(state['cells'][0]['evidence_error'], 'invalid_saved_result')
        self.assertIsNone(state['cells'][0]['facts'])
        self.assertEqual(self.store.path.read_bytes(), damaged)
        self.store.path.write_bytes(b'corrupt database')
        with self.assertRaises(AnalysisUnavailable):
            self.analysis.evidence(plan, active_versions=self.service.versions)
        with self.assertRaises(AnalysisUnavailable):
            self.analysis.save_plan(self.service, [first['spec']])
        self.assertEqual(self.store.path.read_bytes(), b'corrupt database')

    def test_backup_restore_and_new_process_reuse_same_v1_database(self):
        first = self.service.simulate(battle_spec())
        plan = self.analysis.save_plan(self.service, [first['spec']])
        bundle = self.root / 'backup'
        restored = self.root / 'restored'
        backup.backup({'volume': self.store.path.parent}, bundle)
        backup.verify(bundle)
        backup.restore(bundle, restored)
        path = restored / 'volume' / self.store.path.name
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        script = """
import json, sys
from pathlib import Path
from pvpoke_battle_store import BattleStore
from pvpoke_missing_analysis import MissingAnalysis
request = json.load(sys.stdin)
print(json.dumps(MissingAnalysis(BattleStore(Path(sys.argv[1]))).evidence(
    request['id'], active_versions=request['versions'])))
"""
        child = subprocess.run([sys.executable, '-c', script, str(path)], check=True, capture_output=True,
                               input=json.dumps({'id': plan, 'versions': first['versions']}),
                               text=True, timeout=10)
        self.assertEqual(json.loads(child.stdout), self.analysis.evidence(plan, active_versions=first['versions']))
        self.assertEqual(BattleStore(path).get(first['battle_key'], first['spec'], first['versions']), first)
        self.assertEqual(self.service.cache_stats['engine_calls'], 1)

    def test_invalid_plan_or_capacity_failure_does_not_replace_existing_rows(self):
        first = self.service.simulate(battle_spec())
        with self.assertRaises(ValueError):
            self.analysis.save_plan(self.service, [])
        with self.assertRaises(ValueError):
            self.analysis.save_plan(self.service, [battle_spec()] * 129)
        limited = MissingAnalysis(BattleStore(self.store.path, max_bytes=self.store.path.stat().st_size))
        with self.assertRaises(AnalysisUnavailable):
            limited.save_plan(self.service, [battle_spec()])
        self.assertEqual(self.store.get(first['battle_key'], first['spec'], first['versions']), first)

    def _seed_128_matchups(self):
        from pvpoke_battle_service import _json_hash
        from pvpoke_ownership import Ownership
        base = battle_spec()
        first = self.service.simulate(base)
        self.assertEqual(first['status'], 'complete')
        inventory = Ownership(self.store, species_ids=self.service.species)
        combatant0 = first['spec']['combatants'][0]
        _, combatant0_row = self.service._combatant(combatant0)
        inventory.confirm(
            'evt-owned-1', 'inst-owned-1', expected_revision=0, state='confirmed_owned',
            observation={'species_id': combatant0['species_id'], 'ivs': combatant0['ivs'],
                         'current_cp': combatant0_row['cp'], 'current_level': combatant0['level'],
                         'current_moves': {'fast': combatant0['moves']['fast'],
                                           'charged': combatant0['moves']['charged']}},
            register_if_missing=True,
        )
        requests = []
        for idx in range(128):
            req = copy.deepcopy(base)
            if idx <= 100:
                req['combatants'][1]['initial']['energy'] = idx
            else:
                req['combatants'][0]['initial']['energy'] = idx - 100
            norm, _ = self.service._prepare(req)
            key = _json_hash(norm)
            self.store.put(key, norm, first['versions'], {**first, 'battle_key': key, 'spec': norm})
            requests.append(req)
        plan_id = self.analysis.save_plan(self.service, requests)
        return plan_id, first, requests

    def test_evidence_handles_128_matchups_and_releases_reader_before_decoding(self):
        import threading
        import time
        from pvpoke_ownership import Ownership
        plan_id, first, requests = self._seed_128_matchups()

        with self.store._reader() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')

        # Measure SQLite _reader lock hold time vs total evidence() duration across 128 matchups.
        orig_reader = self.store._reader
        lock_hold_s = []

        from contextlib import contextmanager
        @contextmanager
        def timed_reader():
            start = time.perf_counter()
            with orig_reader() as db:
                yield db
            lock_hold_s.append(time.perf_counter() - start)

        with patch.object(self.store, '_reader', timed_reader):
            t0 = time.perf_counter()
            ev = self.analysis.evidence(plan_id, active_versions=first['versions'], normalizer=self.service)
            total_s = time.perf_counter() - t0
        self.assertEqual(ev['state'], 'complete')
        self.assertEqual(ev['coverage'], {'requested': 128, 'completed': 128})
        self.assertEqual(ev['ledger_revision'], 1)
        self.assertEqual(len(ev['cells']), 128)
        self.assertTrue(all(c['ownership'] == 'confirmed_owned' and c['starts_at_full_hp'] is True for c in ev['cells']))
        self.assertEqual(len(lock_hold_s), 1)
        self.assertLess(lock_hold_s[0], total_s)

        # Now prove concurrent writer in DELETE mode succeeds immediately while _decode is running.
        orig_decode = BattleStore._decode
        decode_entered = threading.Event()
        writer_done = threading.Event()
        writer_result = {}

        def slow_decode(row, key, spec, versions):
            if not decode_entered.is_set():
                decode_entered.set()
                self.assertTrue(writer_done.wait(timeout=5.0), 'concurrent writer timed out')
            return orig_decode(row, key, spec, versions)

        def concurrent_writer():
            try:
                self.assertTrue(decode_entered.wait(timeout=5.0))
                other = copy.deepcopy(requests[0])
                other['combatants'][1]['initial']['hp'] = 50
                norm, _ = self.service._prepare(other)
                from pvpoke_battle_service import _json_hash
                other_key = _json_hash(norm)
                self.store.put(other_key, norm, first['versions'], {**first, 'battle_key': other_key, 'spec': norm})
                Ownership(self.store, species_ids=self.service.species).register(
                    'inst-new-2', {'species_id': 'azumarill', 'ivs': {'attack': 0, 'defense': 15, 'hp': 15}})
                writer_result['ok'] = True
            except Exception as exc:
                writer_result['error'] = exc
            finally:
                writer_done.set()

        t = threading.Thread(target=concurrent_writer)
        with patch.object(BattleStore, '_decode', side_effect=slow_decode):
            t.start()
            try:
                in_flight = self.analysis.evidence(plan_id, active_versions=first['versions'], normalizer=self.service)
            finally:
                writer_done.set()
                t.join(timeout=5.0)
        self.assertTrue(writer_result.get('ok'), f"Writer failed: {writer_result.get('error')}")
        self.assertEqual(in_flight['ledger_revision'], 1)
        self.assertEqual(in_flight['coverage'], {'requested': 128, 'completed': 128})
        # Next call observes updated revision cleanly.
        after = self.analysis.evidence(plan_id, active_versions=first['versions'], normalizer=self.service)
        self.assertEqual(after['ledger_revision'], 2)

    def test_evidence_snapshot_isolation_and_wal_mode_concurrency(self):
        import threading
        from pvpoke_battle_service import _json_hash
        from pvpoke_ownership import Ownership

        for mode in ('delete', 'wal'):
            with self.subTest(journal_mode=mode):
                root = self.root / f'mode-{mode}'
                root.mkdir(parents=True, exist_ok=True)
                store = BattleStore(root / 'analysis.sqlite3')
                client = DirectMatrixClient(gamemaster=self.root / 'gamemaster.json', log_dir=root)
                self.addCleanup(client.close)
                service = BattleService(client, store=store)
                analysis = MissingAnalysis(store)
                spec0 = battle_spec()
                res0 = service.simulate(spec0)
                spec1 = copy.deepcopy(spec0)
                spec1['combatants'][1]['initial']['energy'] = 40
                plan_id = analysis.save_plan(service, [spec0, spec1])

                with closing(sqlite3.connect(store.path)) as db:
                    actual = db.execute(f'PRAGMA journal_mode = {mode.upper()}').fetchone()[0]
                    self.assertEqual(actual.lower(), mode)

                orig_decode = BattleStore._decode
                in_decode = threading.Event()
                updated = threading.Event()
                writer_err = []

                def pause_in_decode(row, key, spec, versions):
                    if not in_decode.is_set():
                        in_decode.set()
                        self.assertTrue(updated.wait(timeout=5.0))
                    return orig_decode(row, key, spec, versions)

                def mutate_db():
                    try:
                        self.assertTrue(in_decode.wait(timeout=5.0))
                        norm1, _ = service._prepare(spec1)
                        key1 = _json_hash(norm1)
                        store.put(key1, norm1, res0['versions'], {**res0, 'battle_key': key1, 'spec': norm1})
                        Ownership(store, species_ids=service.species).confirm(
                            'evt-snap', 'inst-snap', expected_revision=0, state='confirmed_owned',
                            observation={'species_id': res0['spec']['combatants'][0]['species_id'],
                                         'ivs': res0['spec']['combatants'][0]['ivs']},
                            register_if_missing=True,
                        )
                    except Exception as exc:
                        writer_err.append(exc)
                    finally:
                        updated.set()

                t = threading.Thread(target=mutate_db)
                with patch.object(BattleStore, '_decode', side_effect=pause_in_decode):
                    t.start()
                    try:
                        snap = analysis.evidence(plan_id, active_versions=res0['versions'], normalizer=service)
                    finally:
                        updated.set()
                        t.join(timeout=5.0)
                self.assertEqual(writer_err, [])
                # In-flight snapshot must not mix pre-update ledger_revision=0 with post-update battle/ownership rows.
                self.assertEqual(snap['ledger_revision'], 0)
                self.assertEqual(snap['state'], 'partial')
                self.assertEqual(snap['coverage'], {'requested': 2, 'completed': 1})
                self.assertTrue(all(c['ownership'] == 'unknown' for c in snap['cells']))

                # Fresh read after mutation sees consistent updated snapshot.
                fresh = analysis.evidence(plan_id, active_versions=res0['versions'], normalizer=service)
                self.assertEqual(fresh['ledger_revision'], 1)
                self.assertEqual(fresh['state'], 'complete')
                self.assertEqual(fresh['coverage'], {'requested': 2, 'completed': 2})

    def test_evidence_releases_lock_on_tampered_plan_and_inventory_failure(self):
        from pvpoke_ownership import Ownership
        first = self.service.simulate(battle_spec())
        plan = self.analysis.save_plan(self.service, [battle_spec()])
        # Corrupt inventory record digest -> evidence() raises AnalysisUnavailable and releases reader lock.
        inv = Ownership(self.store, species_ids=self.service.species)
        inv.confirm('evt-tamper', 'inst-tamper', expected_revision=0, state='confirmed_owned',
                    observation={'species_id': first['spec']['combatants'][0]['species_id'],
                                 'ivs': first['spec']['combatants'][0]['ivs']},
                    register_if_missing=True)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE owned_instances_v1 SET digest='bad' WHERE instance_id='inst-tamper'")
        with self.assertRaises(AnalysisUnavailable):
            self.analysis.evidence(plan, active_versions=self.service.versions, normalizer=self.service)
        # Subsequent writer succeeds cleanly.
        with self.store._writer() as db:
            db.execute("UPDATE owned_instances_v1 SET body=body WHERE instance_id='inst-tamper'")
        # Tamper plan JSON (valid JSON, wrong checksum vs analysis_id) -> AnalysisUnavailable and lock released.
        with closing(sqlite3.connect(self.store.path)) as db, db:
            row = db.execute('SELECT plan_json FROM missing_analysis_plans_v1').fetchone()[0]
            tampered = row.replace(b'"energy":0', b'"energy":1')
            self.assertNotEqual(tampered, row)
            db.execute('UPDATE missing_analysis_plans_v1 SET plan_json=?', (tampered,))
        with self.assertRaises(AnalysisUnavailable):
            self.analysis.evidence(plan, active_versions=self.service.versions, normalizer=self.service)
        with self.store._writer() as db:
            db.execute('DELETE FROM missing_analysis_plans_v1')
