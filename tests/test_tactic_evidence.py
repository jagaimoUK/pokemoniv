"""Stage H: owner-scoped, read-only evidence integration without standard rewrites."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService, _json_hash
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_analysis import MissingAnalysis
from pvpoke_role_evaluation import RoleEvaluation, condition_id
from pvpoke_tactic_evidence import TacticEvidenceUnavailable, compare_tactics
from pvpoke_tactic_search import TacticSearch
from test_sandbox import FIXTURES, scripted_spec


class TacticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'archive' / 'battle_analysis.sqlite3')
        self.client = DirectMatrixClient(gamemaster=FIXTURES / 'strategy_gamemaster.json',
                                         log_dir=self.root)
        self.addCleanup(self.client.close)
        self.service = BattleService(self.client, store=self.store)
        self.script = scripted_spec(energy=100, shield=0)
        self.script['actions'] = []
        self.script['shield_decisions'] = []
        self.script['combatants'][1]['initial']['energy'] = 100
        baseline = {key: self.script[key] for key in ('schema', 'rules', 'combatants')}
        baseline = {**baseline, 'mode': 'standard'}
        self.standard_spec = baseline
        plan_id = MissingAnalysis(self.store).save_plan(self.service, [baseline])
        normalized, _ = self.service._prepare(baseline)
        slot = condition_id(normalized)
        role = {'role_id': 'critical', 'revision': 1, 'priority': 4,
                'meta_snapshot': 'f' * 64,
                'requirements': {slot: {'minimum': {'fast_damage': 0}}}}
        self.evaluation = RoleEvaluation(self.store).evaluate(
            plan_id, role, active_versions=self.service.versions, normalizer=self.service)
        self.search = TacticSearch(self.service)
        self.search_id = self.search.start(self.script)

    def test_tactic_evidence_is_read_only_and_never_promotes_standard_gap(self):
        self.assertEqual(self.evaluation['state'], 'evidence_pending')
        self.search.step(self.search_id, budget=2)
        with closing(sqlite3.connect(self.store.path)) as db:
            before = db.execute('SELECT COUNT(*) FROM battle_results').fetchone()[0]
        self.assertEqual(before, 0)
        with patch('pvpoke_sandbox.subprocess.run', side_effect=AssertionError('unexpected battle')):
            data = compare_tactics(self.service, self.evaluation['evaluation_id'], [self.search_id])
        self.assertEqual(data['schema'], 'missing-tactic-evidence-v1')
        self.assertEqual(data['standard_state'], 'evidence_pending')
        self.assertEqual(data['status'], 'counterfactual_only')
        self.assertEqual(data['information_fairness'], 'not_established')
        self.assertEqual(data['live_reproducibility'], 'not_verified')
        self.assertEqual(data['new_battles'], 0)
        self.assertFalse(data['builds'][0]['practical_role_covered'])
        self.assertEqual(data['builds'][0]['conditions'][0]['standard']['status'], 'unknown')
        self.assertEqual(data['builds'][0]['conditions'][0]['tested_scripts'], 2)
        self.assertTrue(data['builds'][0]['conditions'][0]['paths'])
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_results').fetchone()[0], 0)
        self.assertEqual(self.service.cache_stats['engine_calls'], 0)

    def test_wrong_owner_and_unrelated_matchup_are_rejected(self):
        other = BattleService(self.client, store=BattleStore(self.store.path, owner_scope='other'))
        with self.assertRaises(ValueError):
            compare_tactics(other, self.evaluation['evaluation_id'], [self.search_id])
        changed = {**self.script, 'combatants': [dict(c) for c in self.script['combatants']]}
        changed['combatants'][1] = {**changed['combatants'][1], 'initial': {
            **changed['combatants'][1]['initial'], 'shields': 1}}
        unrelated = self.search.start(changed)
        with self.assertRaises(ValueError):
            compare_tactics(self.service, self.evaluation['evaluation_id'], [unrelated])

    def test_version_drift_and_changed_standard_evidence_rejected(self):
        with patch.object(TacticSearch, '_version', return_value='0' * 64):
            with self.assertRaises(TacticEvidenceUnavailable):
                compare_tactics(self.service, self.evaluation['evaluation_id'], [self.search_id])
        result = self.service.simulate(self.standard_spec)
        self.assertEqual(result['status'], 'complete')
        with self.assertRaises(TacticEvidenceUnavailable):
            compare_tactics(self.service, self.evaluation['evaluation_id'], [self.search_id])

    def test_verified_sandbox_cache_required_and_corruption_never_recomputed(self):
        self.search.step(self.search_id, budget=1)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE sandbox_results_v1 SET digest='corrupt'")
        with patch('pvpoke_sandbox.subprocess.run', side_effect=AssertionError('not allowed')):
            with self.assertRaises((ValueError, sqlite3.Error)):
                compare_tactics(self.service, self.evaluation['evaluation_id'], [self.search_id])

    def test_invalid_search_list_is_not_accepted(self):
        for search_ids in ([], [self.search_id] * 2, ['xyz'], [self.search_id] * 7, 'bad'):
            with self.assertRaises(ValueError):
                compare_tactics(self.service, self.evaluation['evaluation_id'], search_ids)


if __name__ == '__main__':
    unittest.main()
