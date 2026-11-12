from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore, BattleStoreError
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_analysis import AnalysisUnavailable, MissingAnalysis
from pvpoke_ownership import Ownership, OwnershipConflict, OwnershipUnavailable
from test_battle_service import FIXTURES, battle_spec
from tools import cloud_migration_backup as backup


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3')
        client = DirectMatrixClient(gamemaster=FIXTURES / 'strategy_gamemaster.json', log_dir=self.root)
        self.addCleanup(client.close)
        self.service = BattleService(client, store=self.store)
        self.inventory = Ownership(self.store, species_ids=set(self.service.species) | {'quagsire_shadow'})
        self.analysis = MissingAnalysis(self.store)
        self.spec = battle_spec()
        normalized, payload = self.service._prepare(self.spec)
        candidate = normalized['combatants'][0]
        self.observed = {
            'species_id': candidate['species_id'], 'ivs': candidate['ivs'],
            'current_cp': payload['self']['cp'], 'current_level': candidate['level'],
            'current_moves': candidate['moves'],
        }

    def evidence(self, plan, **kwargs):
        return self.analysis.evidence(plan, active_versions=self.service.versions,
                                      normalizer=self.service, **kwargs)

    def test_inventory_events_commit_when_disposable_writes_are_paused(self):
        with patch('pvpoke_battle_store.shutil.disk_usage') as disk:
            disk.return_value.free = 0
            with self.assertRaisesRegex(BattleStoreError, 'disk space'):
                with self.store._writer() as db:
                    db.execute('CREATE TABLE should_not_be_written (value INTEGER)')
            self.inventory.register('critical-instance', self.observed)
            confirmed = self.inventory.confirm('critical-event', 'critical-instance',
                                               expected_revision=0, state='confirmed_owned')
            self.assertEqual(confirmed['new_state'], 'confirmed_owned')
            self.assertEqual(self.inventory.get('critical-instance')['state'], 'confirmed_owned')
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM sqlite_schema WHERE name='should_not_be_written'").fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ownership_events_v1').fetchone()[0], 1)

    def test_disk_full_abort_is_atomic_for_owned_instance_history_and_revision(self):
        """Inject an actual SQLite statement abort, in DELETE and external WAL modes.

        A late append failure must roll back the earlier instance UPDATE and
        ledger revision bump. Never mutate production data or require ENOSPC.
        """
        for journal_mode in ('delete', 'wal'):
            with self.subTest(journal_mode=journal_mode):
                isolated = BattleStore(self.root / f'injected-{journal_mode}.sqlite3')
                owner = Ownership(isolated, species_ids=self.inventory.species_ids)
                other = Ownership(BattleStore(isolated.path, owner_scope='other'),
                                  species_ids=self.inventory.species_ids)
                owner.register('subject', self.observed)
                before = owner.get('subject')
                before_revision = owner.revision()
                with closing(sqlite3.connect(isolated.path)) as db:
                    selected, = db.execute(f'PRAGMA journal_mode={journal_mode}').fetchone()
                    self.assertEqual(selected, journal_mode)
                    db.execute("""
                        CREATE TRIGGER simulate_disk_full BEFORE INSERT
                        ON ownership_events_v1 BEGIN
                            SELECT RAISE(ABORT, 'database or disk is full');
                        END
                    """)
                with self.assertRaisesRegex(sqlite3.DatabaseError, 'database or disk is full'):
                    owner.confirm('confirmed-event', 'subject', expected_revision=0,
                                  state='confirmed_owned')
                self.assertEqual(owner.get('subject'), before)
                self.assertEqual(owner.revision(), before_revision)
                self.assertEqual(owner.history('subject'), [])
                self.assertIsNone(other.get('subject'))
                self.assertEqual(other.revision(), 0)
                with closing(sqlite3.connect(isolated.path)) as db:
                    self.assertEqual(db.execute(
                        'SELECT COUNT(*) FROM ownership_events_v1').fetchone()[0], 0)
                    db.execute('DROP TRIGGER simulate_disk_full')
                event = owner.confirm('confirmed-event', 'subject', expected_revision=0,
                                      state='confirmed_owned')
                self.assertEqual(event['new_state'], 'confirmed_owned')
                self.assertEqual(owner.get('subject')['state'], 'confirmed_owned')
                self.assertEqual(owner.revision(), before_revision + 1)
                self.assertEqual(len(owner.history('subject')), 1)
                self.assertEqual(owner.confirm('confirmed-event', 'subject',
                                               expected_revision=0,
                                               state='confirmed_owned'), event)
                self.assertIsNone(other.get('subject'))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Requires Linux RLIMIT_FSIZE')
    def test_real_kernel_file_limit_rolls_back_owner_history_and_recovers(self):
        """An OS-refused file write must preserve owner state and event history.

        RLIMIT_FSIZE yields EFBIG / SQLite I/O errors, NOT filesystem ENOSPC.
        The limit is process-local, applied only to a child and disposable DB.
        """
        script = """
import resource, signal, sqlite3, sys
from pathlib import Path
from pvpoke_battle_store import BattleStore
from pvpoke_ownership import Ownership

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024, 64 * 1024))
owner = Ownership(BattleStore(Path(sys.argv[1])), species_ids={sys.argv[2]})
try:
    owner.confirm('kernel-limited-event', 'subject', expected_revision=0,
                  state='confirmed_owned')
except (sqlite3.DatabaseError, OSError):
    sys.exit(21)
sys.exit(22)
"""
        for journal_mode in ('delete', 'wal'):
            with self.subTest(journal_mode=journal_mode):
                store = BattleStore(self.root / f'kernel-limit-{journal_mode}.sqlite3')
                owner = Ownership(store, species_ids=self.inventory.species_ids)
                foreign = Ownership(BattleStore(store.path, owner_scope='foreign'),
                                    species_ids=self.inventory.species_ids)
                owner.register('subject', self.observed)
                before = owner.get('subject')
                before_revision = owner.revision()
                with closing(sqlite3.connect(store.path)) as db, db:
                    actual, = db.execute(f'PRAGMA journal_mode={journal_mode}').fetchone()
                    self.assertEqual(actual, journal_mode)
                    db.execute('CREATE TABLE ballast_for_fault (payload BLOB)')
                    # Cause the late ownership event append to allocate OS-level
                    # pages beyond the child's 64 KiB per-file limit.
                    db.execute("""
                        CREATE TRIGGER fault_large_event BEFORE INSERT
                        ON ownership_events_v1 BEGIN
                            INSERT INTO ballast_for_fault VALUES (zeroblob(262144));
                        END
                    """)
                child = subprocess.run(
                    [sys.executable, '-c', script, str(store.path), self.observed['species_id']],
                    text=True, capture_output=True, timeout=15)
                self.assertEqual(child.returncode, 21, child.stderr or child.stdout)
                self.assertEqual(owner.get('subject'), before)
                self.assertEqual(owner.revision(), before_revision)
                self.assertEqual(owner.history('subject'), [])
                self.assertIsNone(foreign.get('subject'))
                with closing(sqlite3.connect(store.path)) as db, db:
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(db.execute(
                        'SELECT COUNT(*) FROM ballast_for_fault').fetchone()[0], 0)
                    db.execute('DROP TRIGGER fault_large_event')
                confirmed = owner.confirm('kernel-limited-event', 'subject',
                                          expected_revision=0, state='confirmed_owned')
                self.assertEqual(confirmed['new_state'], 'confirmed_owned')
                self.assertEqual(owner.revision(), before_revision + 1)
                self.assertEqual(len(owner.history('subject')), 1)
                self.assertEqual(owner.confirm('kernel-limited-event', 'subject',
                                               expected_revision=0,
                                               state='confirmed_owned'), confirmed)
                self.assertIsNone(foreign.get('subject'))

    def test_equal_ivs_keep_distinct_ids_and_only_confirmation_changes_ownership(self):
        result = self.service.simulate(self.spec)
        plan = self.analysis.save_plan(self.service, [self.spec])
        self.inventory.register('a', self.observed)
        self.inventory.register('b', self.observed)
        self.assertEqual([i['state'] for i in self.inventory.instances()], ['unknown', 'unknown'])
        before = self.evidence(plan)['cells'][0]
        self.assertEqual(before['state'], 'complete')
        self.assertEqual(before['ownership'], 'unknown')
        self.assertEqual(before['recommendation'], 'unreviewed')
        self.assertEqual(before['gap_state'], 'ownership_confirmation_needed')
        self.assertEqual(before['facts']['rating'], result['rating'])

        with patch.object(self.service.client, 'strategy') as run:
            self.inventory.confirm('evt-a', 'a', expected_revision=0, state='confirmed_owned')
            self.inventory.confirm('evt-b', 'b', expected_revision=0, state='confirmed_owned')
            cell = self.evidence(plan)['cells'][0]
            self.assertEqual(cell['ownership'], 'confirmed_owned')
            self.assertEqual(cell['gap_state'], 'evidence_pending')
            self.assertEqual(cell['recommendation'], 'unreviewed')
            self.assertEqual(cell['build_id'], before['build_id'])
            self.assertEqual([item['instance_id'] for item in cell['inventory_matches']], ['a', 'b'])
            self.assertEqual([item['build_match'] for item in cell['inventory_matches']], ['exact', 'exact'])
            self.inventory.confirm('evt-release-a', 'a', expected_revision=1, state='confirmed_absent')
            self.assertEqual(self.evidence(plan)['cells'][0]['ownership'], 'confirmed_owned')
            self.inventory.confirm('evt-release-b', 'b', expected_revision=1, state='confirmed_absent')
            self.assertEqual(self.evidence(plan)['cells'][0]['ownership'], 'unknown')
            run.assert_not_called()
        self.assertEqual(self.inventory.get('a')['state'], 'confirmed_absent')
        self.assertEqual(len(self.inventory.instances()), 2)
        self.assertEqual(self.service.cache_stats['engine_calls'], 1)

    def test_form_iv_level_cp_and_moves_do_not_supply_an_inexact_build(self):
        self.service.simulate(self.spec)
        plan = self.analysis.save_plan(self.service, [self.spec])
        observations = {
            'form': {**self.observed, 'species_id': 'quagsire_shadow'},
            'iv': {**self.observed, 'ivs': {**self.observed['ivs'], 'hp': 0}},
            'unknown-level': {**self.observed, 'current_level': None},
            'unknown-cp': {**self.observed, 'current_cp': None},
            'different-level': {**self.observed, 'current_level': 1},
            'different-cp': {**self.observed, 'current_cp': 10},
            'different-moves': {**self.observed, 'current_moves': {'fast': 'MUD_SHOT', 'charged': ['STONE_EDGE']}},
        }
        for ident, observation in observations.items():
            self.inventory.register(ident, observation)
            self.inventory.confirm('event-' + ident, ident, expected_revision=0, state='confirmed_owned')
        matches = {i['instance_id']: i['build_match'] for i in self.evidence(plan)['cells'][0]['inventory_matches']}
        self.assertEqual(matches, {'unknown-level': 'unverified', 'unknown-cp': 'unverified',
                                   'different-level': 'different', 'different-cp': 'different',
                                   'different-moves': 'different'})
        self.inventory.register('exact', self.observed)
        self.inventory.confirm('event-exact', 'exact', expected_revision=0, state='confirmed_owned')
        no_catalog = self.analysis.evidence(plan, active_versions=self.service.versions)
        self.assertEqual(no_catalog['cells'][0]['ownership'], 'unknown')
        stale = self.analysis.evidence(plan, active_versions={**self.service.versions, 'engine': '0' * 64})
        self.assertEqual(stale['cells'][0]['state'], 'stale')
        self.assertIsNone(stale['cells'][0]['facts'])
        self.assertEqual(stale['cells'][0]['ownership'], 'unknown')
        self.assertEqual(stale['cells'][0]['inventory_matches'], [])

    def test_uncomputed_match_has_no_rating_even_when_instance_matches(self):
        plan = self.analysis.save_plan(self.service, [self.spec])
        self.inventory.register('a', self.observed)
        self.inventory.confirm('e', 'a', expected_revision=0, state='confirmed_owned')
        cell = self.evidence(plan)['cells'][0]
        self.assertEqual((cell['state'], cell['ownership'], cell['gap_state']),
                         ('unknown', 'confirmed_owned', 'evidence_pending'))
        self.assertIsNone(cell['facts'])
        self.assertEqual(self.service.cache_stats['engine_calls'], 0)

    def test_replay_does_not_reapply_old_event_and_revision_conflict_is_atomic(self):
        self.inventory.register('a', self.observed)
        args = dict(expected_revision=0, state='confirmed_owned')
        first = self.inventory.confirm('one', 'a', **args)
        self.inventory.confirm('two', 'a', expected_revision=1, state='confirmed_absent')
        self.assertEqual(self.inventory.confirm('one', 'a', **args), first)
        with self.assertRaises(OwnershipConflict):
            self.inventory.confirm('one', 'a', expected_revision=2, state='confirmed_owned')
        with self.assertRaises(OwnershipConflict):
            self.inventory.confirm('three', 'a', **args)
        self.assertEqual(self.inventory.get('a')['state'], 'confirmed_absent')
        history = self.inventory.history('a')
        self.assertEqual([e['output_revision'] for e in history], [1, 2])
        self.assertEqual([e['previous_state'] for e in history], ['unknown', 'confirmed_owned'])
        self.assertEqual([e['event_id'] for e in self.inventory.history('a', after_revision=1)], ['two'])
        self.assertEqual(self.inventory.revision(), 3)

    def test_same_revision_concurrent_writers_have_one_winner(self):
        self.inventory.register('a', self.observed)
        def update(index):
            try:
                return self.inventory.confirm('evt-' + str(index), 'a', expected_revision=0, state='confirmed_owned')
            except OwnershipConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.inventory.history('a')), 1)
        self.assertEqual(self.inventory.get('a')['revision'], 1)

    def test_scope_history_is_distinct_and_invalidated_by_newer_scope_or_inventory(self):
        self.inventory.register('a', self.observed)
        args = dict(expected_ledger_revision=self.inventory.revision(),
                    species_id=self.observed['species_id'], search='0attack', box_range=(1, 50),
                    complete=True, absence_confirmed=True)
        first = self.inventory.confirm_scope('scope-1', **args)
        self.assertEqual(self.inventory.confirm_scope('scope-1', **args), first)
        self.assertTrue(self.inventory.scope_status('scope-1')['current'])
        self.assertEqual(self.inventory.get('a')['state'], 'unknown')
        self.inventory.confirm_scope('scope-2', **{**args, 'complete': False, 'absence_confirmed': False})
        self.assertFalse(self.inventory.scope_status('scope-1')['current'])
        self.assertFalse(self.inventory.scope_status('scope-2')['absence_confirmed'])
        self.inventory.register('b', self.observed)
        self.assertFalse(self.inventory.scope_status('scope-2')['current'])
        with self.assertRaises(OwnershipConflict):
            self.inventory.confirm_scope('scope-3', **args)
        self.assertEqual(self.inventory.history('a'), [])
        with self.assertRaises(ValueError):
            self.inventory.confirm_scope('scope-3', **{**args, 'complete': False})

    def test_other_owner_cannot_read_or_change_instances_events_or_matches(self):
        self.inventory.register('a', self.observed)
        self.inventory.confirm('same-event', 'a', expected_revision=0, state='confirmed_owned')
        self.inventory.confirm_scope('scope', expected_ledger_revision=2,
                                     species_id=self.observed['species_id'], search='', box_range=[1, 2],
                                     complete=True, absence_confirmed=False)
        other_store = BattleStore(self.store.path, owner_scope='other')
        other = Ownership(other_store, species_ids=self.inventory.species_ids)
        self.assertIsNone(other.get('a'))
        self.assertIsNone(other.scope_status('scope'))
        self.assertEqual(other.history('a'), [])
        self.assertEqual(other.revision(), 0)
        with self.assertRaises(OwnershipConflict):
            other.confirm('same-event', 'a', expected_revision=1, state='confirmed_absent')
        plan = MissingAnalysis(other_store).save_plan(self.service, [self.spec])
        facts = MissingAnalysis(other_store).evidence(plan, active_versions=self.service.versions,
                                                      normalizer=self.service)
        self.assertEqual(facts['cells'][0]['inventory_matches'], [])

    def test_invalid_identifiers_inputs_and_revisions_do_not_write(self):
        bad_observations = ({**self.observed, 'species_id': 'not_in_catalogue'},
                            {**self.observed, 'ivs': {'attack': True, 'defense': 10, 'hp': 10}},
                            {**self.observed, 'owner_scope': 'other'})
        for observation in bad_observations:
            with self.assertRaises(ValueError):
                self.inventory.register('a', observation)
        with self.assertRaises(ValueError):
            self.inventory.register('../outside', self.observed)
        for event, revision, state in (('bad event', 0, 'confirmed_owned'), ('ok', True, 'confirmed_owned'),
                                       ('ok', -1, 'confirmed_owned'), ('ok', 0, 'keep_candidate')):
            with self.assertRaises(ValueError):
                self.inventory.confirm(event, 'a', expected_revision=revision, state=state)
        for cursor in (None, False, 0, [], {}):
            with self.assertRaises(ValueError):
                self.inventory.instances(after=cursor)
        self.assertFalse(self.store.path.exists())

    def test_capacity_or_corruption_does_not_replace_existing_battle(self):
        result = self.service.simulate(self.spec)
        restricted = Ownership(BattleStore(self.store.path, max_bytes=self.store.path.stat().st_size),
                               species_ids=self.inventory.species_ids)
        with self.assertRaises(sqlite3.DatabaseError):
            restricted.register('a', self.observed)
        self.assertEqual(self.store.get(result['battle_key'], result['spec'], result['versions']), result)
        self.assertIsNone(self.inventory.get('a'))
        self.inventory.register('a', self.observed)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE owned_instances_v1 SET digest=?', ('0' * 64,))
        damaged = self.store.path.read_bytes()
        with self.assertRaises(OwnershipUnavailable):
            self.inventory.confirm('evt', 'a', expected_revision=0, state='confirmed_owned')
        self.assertEqual(self.store.path.read_bytes(), damaged)
        plan = self.analysis.save_plan(self.service, [self.spec])
        with self.assertRaises(AnalysisUnavailable):
            self.evidence(plan)
        self.store.path.write_bytes(b'not a sqlite file')
        with self.assertRaises(sqlite3.DatabaseError):
            self.inventory.get('a')
        with self.assertRaises(sqlite3.DatabaseError):
            self.inventory.register('b', self.observed)
        self.assertEqual(self.store.path.read_bytes(), b'not a sqlite file')

    def test_process_exit_during_write_rolls_back_instance_revision_and_event(self):
        self.inventory.register('a', self.observed)
        self.inventory.confirm('first', 'a', expected_revision=0, state='confirmed_owned')
        script = """
import os, sys
from pathlib import Path
from pvpoke_battle_store import BattleStore
from pvpoke_ownership import Ownership
inventory = Ownership(BattleStore(Path(sys.argv[1])))
inventory._append = lambda *args: os._exit(73)
inventory.confirm('crash', 'a', expected_revision=1, state='confirmed_absent')
"""
        child = subprocess.run([sys.executable, '-c', script, str(self.store.path)], timeout=10, check=False)
        self.assertEqual(child.returncode, 73)
        self.assertEqual(self.inventory.get('a')['state'], 'confirmed_owned')
        self.assertEqual(self.inventory.get('a')['revision'], 1)
        self.assertEqual(self.inventory.revision(), 2)
        self.assertEqual([event['event_id'] for event in self.inventory.history('a')], ['first'])

    def test_backup_restore_preserves_history_scope_and_evidence(self):
        self.service.simulate(self.spec)
        plan = self.analysis.save_plan(self.service, [self.spec])
        self.inventory.register('a', self.observed)
        event = self.inventory.confirm('first', 'a', expected_revision=0, state='confirmed_owned')
        self.inventory.confirm_scope('scope', expected_ledger_revision=2,
                                     species_id=self.observed['species_id'], search='', box_range=[1, 2],
                                     complete=True, absence_confirmed=False)
        before = self.evidence(plan)
        bundle = self.root / 'backup'
        restored = self.root / 'restored'
        backup.backup({'volume': self.store.path.parent}, bundle)
        backup.verify(bundle)
        backup.restore(bundle, restored)
        path = restored / 'volume' / self.store.path.name
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        restored_store = BattleStore(path)
        restored_inventory = Ownership(restored_store)
        self.assertEqual(restored_inventory.get('a'), event['instance'])
        self.assertEqual(restored_inventory.revision(), 2)
        self.assertEqual(restored_inventory.history('a'), [event])
        self.assertEqual(restored_inventory.scope_status('scope'), self.inventory.scope_status('scope'))
        self.service.client.close()
        self.assertEqual(MissingAnalysis(restored_store).evidence(
            plan, active_versions=self.service.versions, normalizer=self.service), before)
        self.assertEqual(self.service.cache_stats['engine_calls'], 1)
