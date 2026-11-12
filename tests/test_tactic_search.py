"""Resumable tactical search using local native PvPoke fixtures only."""
from contextlib import closing
import copy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_tactic_search import TacticSearch, TacticSearchError, MAX_CANDIDATES
from test_sandbox import FIXTURES, scripted_spec
from tools import cloud_migration_backup as backup


class TacticSearchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3')
        self.client = DirectMatrixClient(gamemaster=FIXTURES / 'strategy_gamemaster.json',
                                         log_dir=self.root)
        self.addCleanup(self.client.close)
        self.standard = BattleService(self.client, store=self.store)
        self.search = TacticSearch(self.standard)

    @staticmethod
    def seed():
        spec = scripted_spec(energy=0, shield=0)
        spec['actions'] = []
        spec['shield_decisions'] = []
        spec['combatants'][1]['initial']['energy'] = 100
        return spec

    def test_generation_is_bounded_fixed_self_and_does_not_start_battles(self):
        seed = self.seed()
        with patch('pvpoke_sandbox.subprocess.run') as node:
            identity = self.search.start(seed)
            self.assertEqual(identity, self.search.start(copy.deepcopy(seed)))
            node.assert_not_called()
        plan, offset, cells = self.search._load(identity)
        self.assertEqual((offset, cells), (0, []))
        self.assertLessEqual(len(plan['candidates']), MAX_CANDIDATES)
        self.assertGreater(len(plan['candidates']), 8)
        self.assertEqual(self.search.step(identity, budget=0)['coverage']['attempted_scripts'], 0)
        groups = {}
        for item in plan['candidates']:
            groups.setdefault(item['strategy'], set()).add(tuple(
                (a['id'], a['turn'], a['kind'], a.get('move_id')) for a in item['spec']['actions']
                if a['actor'] == 0))
            self.assertEqual(item['spec']['mode'], 'sandbox')
            self.assertEqual(item['spec']['combatants'], plan['seed']['combatants'])
        self.assertTrue(all(len(self_actions) == 1 for self_actions in groups.values()))
        self.assertTrue(any(c['response'] == 'alternate_charged' for c in plan['candidates']))

    def test_alternative_opponent_charged_is_native_executable_at_initial_energy(self):
        identity = self.search.start(self.seed())
        plan, _, _ = self.search._load(identity)
        candidate = next(c for c in plan['candidates'] if c['strategy'] == 'original' and
                         c['response'] == 'alternate_charged')
        self.assertEqual([a['turn'] for a in candidate['spec']['actions'] if a['actor'] == 1], [1])
        result = self.search.sandbox.simulate(candidate['spec'])
        self.assertEqual(result['status'], 'complete', result.get('error'))
        actions = {x['action_id']: x for x in result['summary']['action_results']}
        self.assertEqual(actions['search_opponent_alternate']['status'], 'executed')


    def test_charge_turns_use_energy_bounds_and_double_actions_are_preserved(self):
        seed = self.seed()
        identity = self.search.start(seed)
        plan, _, _ = self.search._load(identity)
        singles = [item for item in plan['candidates']
                   if item['strategy'] == 'charged_0_bank0' and item['response'] == 'original']
        self.assertEqual(len(singles), 1)
        self.assertGreater(singles[0]['spec']['actions'][0]['turn'], 1)
        doubles = [item for item in plan['candidates']
                   if item['strategy'] == 'double_0_0' and item['response'] == 'original']
        self.assertEqual(len(doubles), 1)
        own = [action for action in doubles[0]['spec']['actions'] if action['actor'] == 0]
        self.assertEqual([action['kind'] for action in own], ['charged', 'charged'])
        self.assertEqual([action['move_id'] for action in own],
                         [seed['combatants'][0]['moves']['charged'][0]] * 2)
        self.assertGreater(own[1]['turn'], own[0]['turn'] + 1)
        self.assertLessEqual(len(plan['candidates']), MAX_CANDIDATES)
        self.assertEqual(self.search.step(identity, budget=0)['attempts_this_step'], 0)

    def test_ready_initial_energy_supports_early_and_repeated_charged_moves(self):
        seed = self.seed()
        seed['combatants'][0]['initial']['energy'] = 100
        plan, _, _ = self.search._load(self.search.start(seed))
        single = next(c for c in plan['candidates']
                      if c['strategy'] == 'charged_0_bank0' and c['response'] == 'original')
        double = next(c for c in plan['candidates']
                      if c['strategy'] == 'double_0_0' and c['response'] == 'original')
        self.assertEqual([a['turn'] for a in single['spec']['actions'] if a['actor'] == 0], [1])
        self.assertEqual([a['turn'] for a in double['spec']['actions'] if a['actor'] == 0], [1, 3])
        result = self.search.sandbox.simulate(double['spec'])
        self.assertEqual(result['status'], 'complete', result.get('error'))
        by_id = {row['action_id']: row['status'] for row in result['summary']['action_results']}
        self.assertEqual([by_id[action_id] for action_id in double['self_actions']],
                         ['executed', 'executed'])

    def test_requested_shield_that_cannot_be_used_is_not_validated(self):
        seed = self.seed()
        seed['combatants'][0]['initial']['energy'] = 100
        seed['actions'] = [{'id': 'early', 'actor': 0, 'turn': 1,
                            'kind': 'charged', 'move_id': seed['combatants'][0]['moves']['charged'][0]}]
        seed['shield_decisions'] = [{'action_id': 'early', 'defender': 1, 'use_shield': True}]
        identity = self.search.start(seed)
        result = self.search.step(identity, budget=1)
        self.assertEqual(result['coverage']['attempted_scripts'], 1)
        self.assertFalse(result['results'][0]['all_requested_shields_honored'])
        self.assertEqual(result['coverage']['fully_executed_scripts'], 0)

    def test_opponent_alternative_can_request_our_shield_but_never_prove_reproducibility(self):
        seed = self.seed()
        seed['combatants'][0]['initial']['shields'] = 1
        plan, _, _ = self.search._load(self.search.start(seed))
        variants = [c for c in plan['candidates'] if
                    c['response'] == 'alternate_charged_self_shield']
        self.assertTrue(variants)
        self.assertTrue(all(any(d['defender'] == 0 and d['use_shield']
                                for d in candidate['spec']['shield_decisions']) for candidate in variants))
        self.assertTrue(all(c['spec']['mode'] == 'sandbox' for c in variants))

    def test_existing_opponent_charged_request_must_execute(self):
        seed = self.seed()
        seed['combatants'][1]['initial']['energy'] = 0
        opponent_move = seed['combatants'][1]['moves']['charged'][1]
        seed['actions'] = [{'id': 'opponent_early', 'actor': 1, 'turn': 1,
                            'kind': 'charged', 'move_id': opponent_move}]
        identity = self.search.start(seed)
        plan, _, _ = self.search._load(identity)
        first = plan['candidates'][0]
        self.assertEqual(first['response'], 'original')
        self.assertEqual(first['opponent_actions'], ['opponent_early'])
        report = self.search.step(identity, budget=1)
        self.assertEqual(report['coverage']['attempted_scripts'], 1)
        cell = report['results'][0]
        self.assertFalse(cell['opponent_response_executed'])
        self.assertEqual(report['coverage']['fully_executed_scripts'], 0)
        native = self.search.sandbox._get(cell['candidate_key'], first['spec'])
        self.assertIsNotNone(native)
        actions = {a['action_id']: a['status'] for a in native['summary']['action_results']}
        self.assertEqual(actions['opponent_early'], 'rejected')

    def test_alternate_self_shield_variant_tracks_requested_opponent_action(self):
        seed = self.seed()
        seed['combatants'][0]['initial']['shields'] = 1
        plan, _, _ = self.search._load(self.search.start(seed))
        alternative = next(c for c in plan['candidates']
                           if c['response'] == 'alternate_charged_self_shield')
        self.assertIn('search_opponent_alternate', alternative['opponent_actions'])
        self.assertEqual(alternative['opponent_alternate_id'], 'search_opponent_alternate')

    def test_budgets_owner_isolation_checkpoint_and_restored_cache(self):
        identity = self.search.start(self.seed())
        first = self.search.step(identity, budget=2)
        self.assertEqual(first['attempts_this_step'], 2)
        self.assertEqual(first['coverage']['attempted_scripts'], 2)
        self.assertEqual(self.search.step(identity, budget=0)['attempts_this_step'], 0)
        self.assertEqual(self.search.step(identity, budget=1)['coverage']['attempted_scripts'], 3)
        self.assertIsNone(TacticSearch(BattleService(self.client, store=BattleStore(
            self.store.path, owner_scope='another'))).step(identity))
        with self.assertRaises(ValueError):
            self.search.step(identity, budget=9)
        bundle = self.root / 'backup'
        backup.backup({'volume': self.store.path.parent}, bundle)
        backup.verify(bundle)
        backup.restore(bundle, self.root / 'restored')
        self.standard.store = BattleStore(self.root / 'restored' / 'volume' / self.store.path.name)
        resumed = TacticSearch(self.standard)
        state = resumed.step(identity, budget=0)
        self.assertEqual(state['coverage']['attempted_scripts'], 3)
        self.assertEqual(resumed.step(identity, budget=1)['coverage']['attempted_scripts'], 4)

    def test_corrupt_checkpoint_blocks_without_running_engine_or_deleting_history(self):
        identity = self.search.start(self.seed())
        self.search.step(identity, budget=1)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE tactic_search_cells_v1 SET digest='corrupt'")
        digest = hashlib.sha256(self.store.path.read_bytes()).digest()
        with patch('pvpoke_sandbox.subprocess.run') as node:
            with self.assertRaises(TacticSearchError):
                self.search.step(identity, budget=1)
            node.assert_not_called()
        self.assertEqual(hashlib.sha256(self.store.path.read_bytes()).digest(), digest)

    def test_new_version_blocks_resume(self):
        identity = self.search.start(self.seed())
        with patch.object(self.search, '_version', return_value='new-version'):
            result = self.search.step(identity, budget=4)
        self.assertEqual(result['state'], 'stale')
        self.assertEqual(result['attempts_this_step'], 0)

    def test_no_unsupported_claim_of_live_reproducibility(self):
        identity = self.search.start(self.seed())
        result = self.search.step(identity, budget=1)
        self.assertEqual(result['information_model'], 'fixed_script_counterfactual')
        self.assertEqual(result['live_reproducibility'], 'not_verified')
        self.assertEqual(result['results'][0]['evidence_class'], 'theoretical_script_only')


if __name__ == '__main__':
    unittest.main()
