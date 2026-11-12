import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService, _canonical_json
from pvpoke_battle_store import BattleStore, BattleStoreError, MAX_DB_BYTES
from pvpoke_direct_backend import DirectMatrixClient
from test_battle_service import FIXTURES, battle_spec
from tools import cloud_migration_backup as backup


class BattleStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.master = self.root / 'gamemaster.json'
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', self.master)
        self.volume = self.root / 'volume'
        with patch.dict(os.environ, {'PVP_ARCHIVE_DIR': str(self.volume)}):
            self.store = BattleStore.from_volume()
        self.spec = battle_spec()
        self.service = self.make_service()

    def make_service(self, store=None, source=None):
        client = DirectMatrixClient(gamemaster=self.master, log_dir=self.root, source=source)
        self.addCleanup(client.close)
        return BattleService(client, store=self.store if store is None else store)

    def record_count(self):
        with closing(sqlite3.connect(self.store.path)) as db:
            return db.execute('SELECT count(*) FROM battle_results').fetchone()[0]

    def test_equal_conditions_skip_engine_after_restart_and_normalize_defaults(self):
        first = self.service.simulate(self.spec)
        self.assertEqual(first['status'], 'complete')
        self.assertEqual(self.service.cache_stats['engine_calls'], 1)
        with patch.object(self.service.client, 'strategy', wraps=self.service.client.strategy) as run:
            self.assertEqual(self.service.simulate(first['spec']), first)
            run.assert_not_called()
        self.service.client.close()
        reopened = self.make_service()
        with patch.object(reopened.client, 'strategy', wraps=reopened.client.strategy) as run:
            self.assertEqual(reopened.simulate(self.spec), first)
            self.assertEqual(reopened.simulate(self.spec), first)
            run.assert_called_once_with('engine_identity', {})
        self.assertEqual(reopened.cache_stats['engine_calls'], 0)
        self.assertEqual(reopened.cache_stats['hits'], 2)
        self.assertEqual(self.record_count(), 1)

    def test_condition_scope_and_completeness_are_independent(self):
        first = self.service.simulate(self.spec)
        self.assertIsNone(self.store.get(first['battle_key'], first['spec'], first['versions'],
                                         completeness='detailed-trace-v1'))
        different = copy.deepcopy(self.spec)
        different['combatants'][0]['initial']['energy'] = 80
        second = self.service.simulate(different)
        self.assertNotEqual(first['battle_key'], second['battle_key'])
        other = self.make_service(BattleStore(self.store.path, owner_scope='second-owner'))
        self.assertEqual(other.simulate(self.spec)['status'], 'complete')
        self.assertEqual(other.cache_stats['engine_calls'], 1)
        self.assertEqual(other.cache_stats['hits'], 0)
        self.assertEqual(self.record_count(), 3)

    def test_reopened_store_rejects_an_incomplete_worker_identity(self):
        self.assertEqual(self.service.simulate(self.spec)['status'], 'complete')
        reopened = self.make_service()
        name = 'js/pokemon/Pokemon.js'
        with patch.object(reopened.client, 'strategy', return_value={
            'engine_sources': {name: reopened.source_hashes[name]},
        }) as identity:
            self.assertEqual(reopened.simulate(self.spec)['status'], 'failed')
        identity.assert_called_once_with('engine_identity', {})
        self.assertEqual(reopened.cache_stats['hits'], 0)

    def test_data_and_engine_updates_do_not_hit_old_records(self):
        first = self.service.simulate(self.spec)
        self.master.write_bytes(self.master.read_bytes() + b'\n')
        self.assertEqual(self.service.simulate(self.spec)['status'], 'failed')
        updated = self.make_service()
        second = updated.simulate(self.spec)
        self.assertEqual(second['status'], 'complete')
        self.assertNotEqual(first['versions']['game_data'], second['versions']['game_data'])
        self.assertNotEqual(first['battle_key'], second['battle_key'])
        self.assertEqual(updated.cache_stats['hits'], 0)

        source = self.root / 'engine'
        shutil.copytree(self.service.client.source, source)
        stale = self.make_service(source=source)
        self.assertEqual(stale.simulate(self.spec), second)  # Load the old worker JS.
        battle = source / 'src/js/battle/Battle.js'
        battle.write_bytes(battle.read_bytes() + b'\n// new engine revision\n')
        self.assertEqual(stale.simulate(self.spec)['status'], 'failed')
        fresh = self.make_service(source=source)
        third = fresh.simulate(self.spec)
        self.assertEqual(third['status'], 'complete')
        self.assertNotEqual(second['versions']['engine'], third['versions']['engine'])
        self.assertNotEqual(second['battle_key'], third['battle_key'])
        self.assertEqual(fresh.cache_stats['hits'], 0)
        rebound = BattleService(stale.client, store=self.store)
        self.assertEqual(rebound.simulate(self.spec)['status'], 'failed')
        self.assertEqual(rebound.cache_stats['hits'], 0)
        self.assertEqual(self.record_count(), 3)

    def test_unfinished_failed_or_unsupported_results_never_write(self):
        spec = battle_spec(2, 2, (0, 0))
        spec['policies'] = {'attack': ['fast_only', 'fast_only']}
        for combatant in spec['combatants']:
            combatant['initial']['stages'] = [-4, 4]
        self.assertEqual(self.service.simulate(spec)['status'], 'partial')
        self.assertEqual(self.service.simulate({**self.spec, 'mode': 'sandbox'})['status'], 'unsupported')
        self.assertEqual(self.service.simulate({})['status'], 'invalid')
        self.service.client.close()
        self.assertEqual(self.service.simulate(self.spec)['status'], 'failed')
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.service.cache_stats['hits'], 0)

    def test_corrupt_records_are_never_served_or_overwritten(self):
        original = self.service.simulate(self.spec)
        wrong_version = copy.deepcopy(original)
        del wrong_version['versions']['engine']
        wrong_schema = {**original, 'schema': 'battle-result-v0'}
        wrong_rating = {**original, 'rating': '123'}
        for raw in (b'invalid JSON', _canonical_json(wrong_version), _canonical_json(wrong_schema),
                    _canonical_json(wrong_rating)):
            with self.subTest(payload=raw[:40]):
                checksum = hashlib.sha256(raw).hexdigest()
                with closing(sqlite3.connect(self.store.path)) as db, db:
                    db.execute('UPDATE battle_results SET result_json=?, result_sha256=?', (raw, checksum))
                result = self.service.simulate(self.spec)
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['rating'], original['rating'])
                self.assertEqual(self.service.cache_stats['hits'], 0)
                with closing(sqlite3.connect(self.store.path)) as db:
                    self.assertEqual(db.execute('SELECT result_json FROM battle_results').fetchone()[0], raw)
        self.assertEqual(self.service.cache_stats['storage_errors'], 8)

    def test_checksum_and_unknown_database_version_are_rejected(self):
        first = self.service.simulate(self.spec)
        args = (first['battle_key'], first['spec'], first['versions'])
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE battle_results SET result_sha256 = ?', ('0' * 64,))
        with self.assertRaisesRegex(BattleStoreError, 'checksum'):
            self.store.get(*args)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('PRAGMA user_version = 999')
        self.assertEqual(self.service.simulate(self.spec)['status'], 'complete')
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 999)
            self.assertEqual(db.execute('SELECT result_sha256 FROM battle_results').fetchone()[0], '0' * 64)

    def test_corrupt_database_and_permission_errors_allow_fresh_results(self):
        self.store.path.parent.mkdir(parents=True)
        damaged = b'not a SQLite database' * 40
        self.store.path.write_bytes(damaged)
        self.assertEqual(self.service.simulate(self.spec)['status'], 'complete')
        self.assertEqual(self.store.path.read_bytes(), damaged)
        with patch('pvpoke_battle_store.sqlite3.connect', side_effect=PermissionError('/private/internal')):
            result = self.service.simulate(self.spec)
        self.assertEqual(result['status'], 'complete')
        self.assertNotIn('/private/internal', str(result))
        self.assertEqual(self.service.cache_stats['storage_errors'], 4)

    def test_reserved_database_quota_preserves_space_for_critical_events(self):
        from pvpoke_battle_store import RESERVED_DB_PAGE_FRACTION
        path = self.root / 'capacity-reserve.sqlite3'
        limited = BattleStore(path, max_bytes=256 * 1024)
        with limited._writer() as db:
            db.execute('CREATE TABLE disposable_test_cache (id INTEGER PRIMARY KEY, payload BLOB)')
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            expected = limited.max_bytes // page_size
            self.assertEqual(db.execute('PRAGMA max_page_count').fetchone()[0],
                             expected - expected // RESERVED_DB_PAGE_FRACTION)
        stopped = False
        for index in range(32):
            try:
                with limited._writer() as db:
                    db.execute('INSERT INTO disposable_test_cache VALUES (?, zeroblob(16384))',
                               (index,))
            except (BattleStoreError, sqlite3.OperationalError):
                stopped = True
                break
        self.assertTrue(stopped, 'Low-priority writes should stop at the reserved boundary')
        with limited._writer(critical=True) as db:
            self.assertEqual(db.execute('PRAGMA max_page_count').fetchone()[0], expected)
            db.execute('CREATE TABLE critical_test_events (event_id TEXT PRIMARY KEY)')
            db.execute('INSERT INTO critical_test_events VALUES (?)', ('kept',))
        with limited._reader() as db:
            self.assertEqual(db.execute('SELECT event_id FROM critical_test_events').fetchone()[0],
                             'kept')
            self.assertGreater(db.execute('SELECT COUNT(*) FROM disposable_test_cache').fetchone()[0],
                               0)
            self.assertLessEqual(db.execute('PRAGMA page_count').fetchone()[0], expected)

    def test_default_journal_mode_and_synthetic_low_disk_priority(self):
        """Validate actual journal setting and low-space refusal without real ENOSPC."""
        from types import SimpleNamespace
        from pvpoke_battle_store import NONCRITICAL_DISK_RESERVE_BYTES

        store = BattleStore(self.root / 'isolated-disk-policy.sqlite3')
        with store._writer(critical=True) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            db.execute('CREATE TABLE owner_events (name TEXT PRIMARY KEY)')
            db.execute('INSERT INTO owner_events VALUES (?)', ('first',))
        simulated = SimpleNamespace(free=NONCRITICAL_DISK_RESERVE_BYTES - 1)
        with patch('pvpoke_battle_store.shutil.disk_usage', return_value=simulated):
            with self.assertRaises(BattleStoreError):
                with store._writer() as db:
                    db.execute('INSERT INTO owner_events VALUES (?)', ('disposable',))
            with store._writer(critical=True) as db:
                db.execute('INSERT INTO owner_events VALUES (?)', ('second',))
        with store._reader() as db:
            self.assertEqual([row[0] for row in db.execute(
                'SELECT name FROM owner_events ORDER BY name')], ['first', 'second'])

    def test_external_wal_growth_pauses_only_disposable_writes_and_recovers(self):
        """Real WAL file growth in a disposable local SQLite; NOT disk ENOSPC."""
        isolated = BattleStore(self.root / 'wal-growth.sqlite3', max_bytes=128 * 1024)
        with isolated._writer(critical=True) as db:
            db.execute('CREATE TABLE external_events (value TEXT)')
            db.execute('INSERT INTO external_events VALUES (?)', ('initial',))
        with closing(sqlite3.connect(isolated.path)) as external:
            self.assertEqual(external.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            external.execute('PRAGMA wal_autocheckpoint=0')
            for sequence in range(45):
                with external:
                    external.execute('UPDATE external_events SET value=?', (str(sequence),))
            wal = isolated.path.with_name(isolated.path.name + '-wal')
            self.assertGreater(wal.stat().st_size, isolated.max_bytes)
            with self.assertRaisesRegex(BattleStoreError, 'oversized SQLite WAL'):
                with isolated._writer() as db:
                    db.execute('UPDATE external_events SET value=?', ('disposable',))
            # Important owner-authored changes retain the reserved write path.
            with isolated._writer(critical=True) as db:
                db.execute('UPDATE external_events SET value=?', ('critical',))
            self.assertEqual(external.execute(
                'SELECT value FROM external_events').fetchone()[0], 'critical')
            self.assertEqual(external.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0], 0)
            with isolated._writer() as db:
                db.execute('UPDATE external_events SET value=?', ('recovered',))
            self.assertEqual(external.execute(
                'SELECT value FROM external_events').fetchone()[0], 'recovered')
            self.assertEqual(external.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_sqlite_full_fails_safely_without_eviction(self):
        original = self.service.simulate(self.spec)
        limited = self.make_service(BattleStore(self.store.path, max_bytes=8192))
        changed = copy.deepcopy(self.spec)
        changed['combatants'][0]['initial']['energy'] = 80
        self.assertEqual(limited.simulate(changed)['status'], 'complete')
        self.assertGreater(limited.cache_stats['storage_errors'], 0)
        self.assertEqual(self.service.simulate(self.spec), original)
        self.assertEqual(self.record_count(), 1)
        self.assertLess(self.store.path.stat().st_size, MAX_DB_BYTES)

    def test_concurrent_identical_writes_and_conflict(self):
        result = self.service.simulate(self.spec)
        args = (result['battle_key'], result['spec'], result['versions'])
        independent = BattleStore(self.root / 'other.sqlite3')
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: independent.put(*args, result), range(8)))
        different = {**result, 'rating': (result['rating'] + 1) % 1001}
        with self.assertRaisesRegex(BattleStoreError, 'Conflicting'):
            independent.put(*args, different)
        self.assertEqual(independent.get(*args), result)
        with closing(sqlite3.connect(independent.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_results').fetchone()[0], 1)

    def test_migration_failure_rolls_back_and_retry_succeeds(self):
        migrate = self.store._migrate
        def interrupted(db):
            migrate(db)
            raise sqlite3.OperationalError('synthetic write failure after migration')
        with patch.object(self.store, '_migrate', side_effect=interrupted):
            self.assertEqual(self.service.simulate(self.spec)['status'], 'complete')
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM sqlite_schema').fetchone()[0], 0)
        self.assertEqual(self.service.simulate(self.spec)['status'], 'complete')
        self.assertEqual(self.record_count(), 1)

    def test_process_crash_before_commit_leaves_previous_record(self):
        first = self.service.simulate(self.spec)
        changed = copy.deepcopy(self.spec)
        changed['combatants'][0]['initial']['energy'] = 80
        second = BattleService(self.service.client).simulate(changed)
        code = """
import json, os, sqlite3, sys
from pathlib import Path
from unittest.mock import patch
from pvpoke_battle_store import BattleStore
connect = sqlite3.connect
def interrupted(*args, **kwargs):
    db = connect(*args, **kwargs)
    db.set_trace_callback(lambda sql: os._exit(73) if sql == 'COMMIT' else None)
    return db
result = json.load(sys.stdin)
with patch('pvpoke_battle_store.sqlite3.connect', side_effect=interrupted):
    BattleStore(Path(sys.argv[1])).put(result['battle_key'], result['spec'], result['versions'], result)
"""
        child = subprocess.run([sys.executable, '-c', code, str(self.store.path)],
                               input=json.dumps(second), text=True, timeout=10, check=False)
        self.assertEqual(child.returncode, 73)
        self.assertEqual(self.record_count(), 1)
        self.assertEqual(self.service.simulate(self.spec), first)

    def test_backup_integrity_restore_and_reuse_in_fresh_process(self):
        first = self.service.simulate(self.spec)
        bundle = self.root / 'bundle'
        restored = self.root / 'restored'
        backup.backup({'volume': self.volume}, bundle)
        manifest = backup.verify(bundle)
        entry = next(item for item in manifest['files'] if item['path'].endswith('battle_analysis.sqlite3'))
        backup.restore(bundle, restored)
        db_path = restored / 'volume' / self.store.path.relative_to(self.volume)
        self.assertEqual(backup.sqlite_inventory(db_path), entry['sqlite'])
        with closing(sqlite3.connect(db_path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        code = """
import json, sys
from pathlib import Path
from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
client = DirectMatrixClient(gamemaster=Path(sys.argv[1]), log_dir=Path(sys.argv[2]))
try:
    service = BattleService(client, store=BattleStore(Path(sys.argv[3])))
    print(json.dumps({'result': service.simulate(json.load(sys.stdin)), 'stats': service.cache_stats}))
finally:
    client.close()
"""
        self.service.client.close()
        child = subprocess.run([sys.executable, '-c', code, str(self.master), str(self.root), str(db_path)],
                               input=json.dumps(self.spec), text=True, capture_output=True, timeout=10, check=True)
        output = json.loads(child.stdout)
        self.assertEqual(output['result'], first)
        self.assertEqual(output['stats']['hits'], 1)
        self.assertEqual(output['stats']['engine_calls'], 0)
