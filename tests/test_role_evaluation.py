from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_analysis import AnalysisUnavailable
from pvpoke_ownership import Ownership, build_id
from pvpoke_role_evaluation import RoleEvaluation, condition_id
from test_battle_service import FIXTURES, battle_spec


class RoleEvaluationTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(root / 'battle_analysis.sqlite3')
        client = DirectMatrixClient(gamemaster=FIXTURES / 'strategy_gamemaster.json', log_dir=root)
        self.addCleanup(client.close)
        self.service = BattleService(client, store=self.store)
        self.roles = RoleEvaluation(self.store)
        self.ownership = Ownership(self.store, species_ids=self.service.species)

    def definition(self, *specs, minimum=None):
        return {'role_id': 'lead', 'revision': 1, 'priority': 4, 'meta_snapshot': '1' * 64,
                'requirements': {condition_id(self.service._prepare(spec)[0], full_hp=True):
                                 {'minimum': minimum or {'fast_damage': 0}} for spec in specs}}

    def evaluate(self, plan, definition, roles=None):
        with patch.object(self.service.client, 'strategy') as engine:
            result = (roles or self.roles).evaluate(plan, definition, active_versions=self.service.versions,
                                                     normalizer=self.service)
            engine.assert_not_called()
            return result

    def confirm(self, spec, instance):
        normalized, rows = self.service._prepare(spec)
        combatant = normalized['combatants'][0]
        self.ownership.register(instance, {
            'species_id': combatant['species_id'], 'ivs': combatant['ivs'], 'current_cp': rows['self']['cp'],
            'current_level': combatant['level'], 'current_moves': combatant['moves'],
        })
        self.ownership.confirm('evt-' + instance, instance, expected_revision=0, state='confirmed_owned')

    def test_one_owned_build_must_supply_every_condition(self):
        a, b = battle_spec(left=0, right=2), battle_spec(left=1, right=3)
        self.confirm(a, 'a')
        self.confirm(b, 'b')
        plan = self.roles.analysis.save_plan(self.service, [a, b])
        for spec in (a, b):
            self.assertEqual(self.service.simulate(spec)['status'], 'complete')
        definition = self.definition(a, b)
        pending = self.evaluate(plan, definition)
        self.assertEqual(pending['state'], 'evidence_pending')
        self.assertEqual([item['meets'] for item in pending['candidates']], [None, None])
        self.assertEqual([len(item['checks']) for item in pending['candidates']], [1, 1])
        a2 = battle_spec(left=0, right=3)
        self.assertEqual(self.service.simulate(a2)['status'], 'complete')
        plan2 = self.roles.analysis.save_plan(self.service, [a, a2, b])
        covered = self.evaluate(plan2, definition)
        self.assertEqual(covered['state'], 'covered')
        matches = {item['build_id']: item['confirmed_instances'] for item in covered['candidates']}
        self.assertEqual(matches[build_id(self.service._prepare(a)[0]['combatants'][0])], ['a'])
        self.assertEqual(matches[build_id(self.service._prepare(b)[0]['combatants'][0])], [])

    def test_reuse_revision_coverage_stale_and_owner_scope(self):
        spec = battle_spec()
        plan = self.roles.analysis.save_plan(self.service, [spec])
        definition = self.definition(spec)
        unknown = self.evaluate(plan, definition)
        self.assertEqual(unknown['state'], 'evidence_pending')
        self.assertEqual(self.service.simulate(spec)['status'], 'complete')
        known = self.evaluate(plan, definition)
        self.assertEqual(known['state'], 'ownership_confirmation_needed')
        self.assertNotEqual(known['evaluation_id'], unknown['evaluation_id'])
        with patch('pvpoke_role_evaluation._assess', side_effect=AssertionError('Unexpected reevaluation')):
            self.assertEqual(self.evaluate(plan, definition, RoleEvaluation(BattleStore(self.store.path))), known)

        self.confirm(spec, 'instance')
        self.assertEqual(self.evaluate(plan, definition)['state'], 'covered')
        revised = self.definition(spec, minimum={'fast_damage': 10000})
        revised.update(revision=2, priority=1)
        failed = self.evaluate(plan, revised)
        self.assertEqual((failed['state'], failed['scope']), ('gap', 'analysis_plan'))
        self.assertEqual(self.roles.history(known['evaluation_id']), known)
        stale = self.roles.evaluate(plan, revised, active_versions={**self.service.versions, 'engine': '0' * 64})
        self.assertEqual((stale['state'], stale['evidence_state']), ('evidence_pending', 'stale'))
        other = RoleEvaluation(BattleStore(self.store.path, owner_scope='other'))
        self.assertIsNone(other.history(known['evaluation_id']))
        self.assertIsNone(self.evaluate(plan, definition, other))
        self.assertEqual(self.service.cache_stats['engine_calls'], 1)

    def test_full_health_requirement_rejects_short_start(self):
        short = battle_spec()
        short['combatants'][0]['initial']['hp'] = 1
        plan = self.roles.analysis.save_plan(self.service, [short])
        self.assertEqual(self.service.simulate(short)['status'], 'complete')
        self.assertEqual(self.evaluate(plan, self.definition(battle_spec()))['state'], 'evidence_pending')

    def test_invalid_definition_and_corrupt_history_fail_closed(self):
        spec = battle_spec()
        plan = self.roles.analysis.save_plan(self.service, [spec])
        definition = self.definition(spec)
        with self.assertRaises(ValueError):
            self.evaluate(plan, {**definition, 'revision': True})
        with self.assertRaises(ValueError):
            self.evaluate(plan, self.definition(spec, minimum={'average_rating': 0}))
        snapshot = self.evaluate(plan, definition)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE missing_role_evaluations_v1 SET digest=?', ('0' * 64,))
        with self.assertRaises(AnalysisUnavailable):
            self.roles.history(snapshot['evaluation_id'])
