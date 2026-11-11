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
