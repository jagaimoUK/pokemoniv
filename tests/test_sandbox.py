import copy
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_sandbox import SandboxService
from test_battle_service import FIXTURES, battle_spec
from tools import cloud_migration_backup as backup


def scripted_spec(*, energy=100, shield=1):
    spec = battle_spec(shields=(0, shield))
    spec['mode'] = 'sandbox'
    spec['combatants'][0]['initial']['energy'] = energy
    spec['actions'] = [
        {'id': 'a', 'actor': 0, 'turn': 1, 'kind': 'charged', 'move_id': 'AQUA_TAIL'},
        {'id': 'locked', 'actor': 0, 'turn': 2, 'kind': 'charged', 'move_id': 'AQUA_TAIL'},
        {'id': 'b', 'actor': 0, 'turn': 3, 'kind': 'charged', 'move_id': 'AQUA_TAIL'},
        {'id': 'late', 'actor': 0, 'turn': 500, 'kind': 'wait'},
    ]
    spec['shield_decisions'] = [
        {'action_id': aid, 'defender': 1, 'use_shield': True} for aid in ('a', 'locked', 'b')
    ]
    return spec


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3')
        client = DirectMatrixClient(gamemaster=FIXTURES / 'strategy_gamemaster.json', log_dir=self.root)
        self.addCleanup(client.close)
        self.standard = BattleService(client, store=self.store)
        self.sandbox = SandboxService(self.standard)

    def test_manual_shields_and_engine_turn_lock(self):
        result = self.sandbox.simulate(scripted_spec())
        self.assertEqual(result['status'], 'complete', result.get('error'))
        battle = result['summary']
        actions = {row['action_id']: row for row in battle['action_results']}
        self.assertEqual([actions[key]['status'] for key in ('a', 'locked', 'b', 'late')],
                         ['executed', 'rejected', 'executed', 'not_reached'])
        self.assertEqual(actions['locked']['reason'], 'post_charged_lock')
        shield = {row['action_id']: row for row in result['shield_results']}
        self.assertIs(shield['a']['used'], True)
        self.assertIsNone(shield['locked']['used'])
        self.assertIs(shield['b']['used'], False)
        self.assertEqual(shield['b']['reason'], 'no_shields')
        self.assertEqual(battle['shields_used'], [0, 1])
        self.assertEqual([step['phase'] for step in result['trace'] if step.get('action_id') == 'a'],
                         ['start', 'resolve', 'effects'])
        self.assertEqual([(event['action_id'], event['turn']) for event in battle['executed_moves']
                          if 'action_id' in event], [('a', 1), ('b', 3)])

    def test_failed_request_and_fallback_are_separate_from_start_and_resolution(self):
        spec = scripted_spec(energy=0)
        spec['actions'] = spec['actions'][:1]
        spec['shield_decisions'] = spec['shield_decisions'][:1]
        result = self.sandbox.simulate(spec)
        self.assertEqual(result['status'], 'complete', result.get('error'))
        summary = result['summary']
        self.assertEqual(summary['action_results'], [{'action_id': 'a', 'requested_turn': 1,
                         'status': 'rejected', 'reason': 'insufficient_energy'}])
        self.assertTrue(any(event['turn'] == 1 and event['actor'] == 0 and
                            event['kind'] == 'fast' and 'action_id' not in event for event in result['trace']))
        self.assertFalse(any('action_id' in event for event in summary['executed_moves']))

    def test_standard_cache_and_version_remain_separate_and_restore_sandbox(self):
        baseline = self.standard.simulate(battle_spec())
        self.assertEqual(baseline['status'], 'complete')
        scripted = self.sandbox.simulate(scripted_spec())
        self.assertEqual(scripted['status'], 'complete', scripted.get('error'))
        summary = scripted['summary']
        self.assertNotEqual(summary['battle_key'], baseline['battle_key'])
        self.assertNotEqual(summary['versions']['engine'], baseline['versions']['engine'])
        self.assertEqual(summary['versions']['game_data'], baseline['versions']['game_data'])
        self.assertEqual(self.standard.simulate(battle_spec()), baseline)
        self.assertEqual(self.standard.cache_stats['engine_calls'], 1)

        bundle = self.root / 'backup'
        backup.backup({'volume': self.store.path.parent}, bundle)
        backup.verify(bundle)
        backup.restore(bundle, self.root / 'restored')
        restored = BattleStore(self.root / 'restored' / 'volume' / self.store.path.name)
        self.standard.store = restored
        replay = SandboxService(self.standard)
        reversed_actions = copy.deepcopy(summary['spec'])
        reversed_actions['actions'].reverse()
        reversed_actions['shield_decisions'].reverse()
        with patch('pvpoke_sandbox.subprocess.run') as child:
            self.assertEqual(replay.simulate(reversed_actions), scripted)
            child.assert_not_called()

    def test_invalid_requests_never_spawn_and_corruption_fails_closed(self):
        spec = scripted_spec()
        with patch('pvpoke_sandbox.subprocess.run') as child:
            self.assertEqual(self.sandbox.simulate({**spec, 'gamemaster_path': '/tmp/data'})['status'], 'invalid')
            self.assertEqual(self.sandbox.simulate({**spec, 'owner_scope': 'other'})['status'], 'invalid')
            self.assertEqual(self.sandbox.simulate({**spec, 'policies': {'shield': ['standard'] * 2}})['status'],
                             'unsupported')
            bad_move = copy.deepcopy(spec)
            bad_move['actions'][0]['move_id'] = 'BUBBLE'
            self.assertEqual(self.sandbox.simulate(bad_move)['status'], 'invalid')
            child.assert_not_called()
        result = self.sandbox.simulate(spec)
        self.assertEqual(result['status'], 'complete')
        foreign_store = BattleStore(self.store.path, owner_scope='foreign')
        self.standard.store = foreign_store
        foreign = SandboxService(self.standard)
        with patch('pvpoke_sandbox.subprocess.run', side_effect=OSError('test')) as child:
            self.assertEqual(foreign.simulate(spec)['status'], 'failed')
            child.assert_called_once()
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE sandbox_results_v1 SET digest=?', ('corrupt',))
        before = hashlib.sha256(self.store.path.read_bytes()).digest()
        with patch('pvpoke_sandbox.subprocess.run') as child:
            self.assertEqual(self.sandbox.simulate(spec)['status'], 'failed')
            child.assert_not_called()
        self.assertEqual(hashlib.sha256(self.store.path.read_bytes()).digest(), before)

    def test_rehashed_inconsistent_sandbox_records_are_rejected_without_recalculation(self):
        import json
        from pvpoke_battle_service import _canonical_json, _json_hash
        cases = (
            lambda value: value['summary'].update(outcome='timeout'),
            lambda value: value['summary']['terminal'][0].update(hp=99999),
            lambda value: value['summary']['action_results'][0].update(status='rejected', reason='test'),
            lambda value: value['summary']['shields_used'].__setitem__(1, 2),
            lambda value: value['trace'].pop(next(i for i, event in enumerate(value['trace'])
                                                   if event['phase'] == 'resolve')),
        )
        for corrupt in cases:
            with self.subTest(corrupt=corrupt):
                case_root = self.root / ('case-' + str(cases.index(corrupt)))
                case_store = BattleStore(case_root / 'analysis.sqlite3')
                self.standard.store = case_store
                sandbox = SandboxService(self.standard)
                result = sandbox.simulate(scripted_spec())
                self.assertEqual(result['status'], 'complete', result.get('error'))
                key, spec = result['summary']['battle_key'], result['summary']['spec']
                with closing(sqlite3.connect(case_store.path)) as db, db:
                    row = db.execute('SELECT body FROM sandbox_results_v1').fetchone()[0]
                    stored = json.loads(row)
                    corrupt(stored)
                    body = _canonical_json(stored)
                    db.execute('UPDATE sandbox_results_v1 SET body=?,digest=?',
                               (body, _json_hash(stored)))
                with patch('pvpoke_sandbox.subprocess.run',
                           side_effect=AssertionError('engine must not start')) as native:
                    with self.assertRaises(ValueError):
                        sandbox._get(key, spec)
                    failed = sandbox.simulate(spec)
                    self.assertEqual(failed['status'], 'failed')
                    native.assert_not_called()

    def test_wait_only_timeout_is_partial_and_not_saved(self):
        spec = scripted_spec(energy=0)
        spec['actions'] = [
            {'id': f'wait-{side}-{turn}', 'actor': side, 'turn': turn, 'kind': 'wait'}
            for turn in range(1, 501) for side in (0, 1)
        ]
        spec['shield_decisions'] = []
        result = self.sandbox.simulate(spec)
        self.assertEqual(result['status'], 'partial', result.get('error'))
        self.assertEqual(result['summary']['outcome'], 'timeout')
        self.assertEqual(result['summary']['executed_moves'], [])
        self.assertTrue(all(step['kind'] == 'wait' and step['phase'] == 'start' for step in result['trace']))
        self.assertTrue(any(action['status'] == 'not_reached' for action in result['summary']['action_results']))
        self.assertFalse(self.store.path.exists())
