"""Second-pass ranking, unknown semantics, bounded work and real-engine integration."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pvpoke_party_backend import PartyBuilder
from pvpoke_party_strategy import (StrategyAnalysis, classify_pair, rank_refined,
    refinement_targets, role_team_summary)
from test_party_strategy import ROWS, GM, CATALOG, SPECIES, CPMS, engine


class RefinementMetricsTests(unittest.TestCase):
    def setUp(self):
        self.rosters = [list('abcdef'), list('abcdeg')]
        self.matrix = {(p, 'x', (2, 2)): 600 for p in 'abcdefg'}

    def plans(self):
        return [{'roster': r, 'static_rank': i + 1, 'detail': {'metrics': {
            k: {'coverage': float(i), 'known_weight': 1} for k in ('pressure', 'absorb', 'conserve')}}}
            for i, r in enumerate(self.rosters)]

    def test_fixed_role_policies_can_reverse_comparable_static_finalists(self):
        plans = self.plans()
        self.assertTrue(rank_refined(plans, ['x'], self.matrix, {'x': 1}, include_chase=False))
        self.assertEqual([p['static_rank'] for p in plans], [2, 1])
        self.assertEqual([p['detail']['score'] for p in plans], [1, 0])

    def test_unknown_cannot_lower_a_candidate_or_reorder_the_known_subset(self):
        for missing in ('role', 'standard'):
            plans = self.plans()
            matrix = dict(self.matrix)
            if missing == 'role':
                plans[0]['detail']['metrics']['absorb']['known_weight'] = .5
            else:
                matrix.pop(('f', 'x', (2, 2)))
            self.assertFalse(rank_refined(plans, ['x'], matrix, {'x': 1}, include_chase=False))
            self.assertEqual([p['static_rank'] for p in plans], [1, 2])
            self.assertTrue(all(p['detail']['score'] is None for p in plans))

    def test_detail_score_cannot_remove_a_sole_answer(self):
        plans = self.plans()
        matrix = {(p, 'x', (2, 2)): 400 for p in 'abcdefg'}
        matrix['f', 'x', (2, 2)] = 600
        rank_refined(plans, ['x'], matrix, {'x': 1}, include_chase=False)
        self.assertEqual(plans[0]['static_rank'], 1)

    def test_stress_set_is_shared_bounded_weighted_and_deduplicated(self):
        targets = [{'id': p} for p in 'xyzw']
        matrix = {(p, q, (2, 2)): 600 for p in 'abcdefg' for q in 'xyzw'}
        selected = refinement_targets(self.rosters, targets + [targets[0]], matrix,
                                      {'w': .7, 'x': .1, 'y': .1, 'z': .1})
        self.assertEqual(len(selected), 3)
        self.assertEqual(selected[0]['id'], 'w')
        self.assertEqual(selected, refinement_targets(self.rosters[::-1], targets[::-1], matrix,
                                                     {'w': .7, 'x': .1, 'y': .1, 'z': .1}))

    def test_unknown_or_role_exists_and_pair_directional_rescue(self):
        targets = [{'id': 'x'}]
        cells = {('a', 'x'): {'pressure': None, 'absorb': False, 'conserve': False},
                 ('b', 'x'): {'pressure': True, 'absorb': None, 'conserve': False}}
        summary = role_team_summary(['a', 'b'], targets, cells, {'x': 1})
        self.assertEqual(summary['metrics']['pressure'], {'coverage': 1, 'known_weight': 1})
        self.assertEqual(summary['metrics']['absorb']['known_weight'], 0)
        cells['a', 'x']['pressure'] = False
        roles = classify_pair('a', 'b', targets, cells,
                              {('a', 'x', (2, 2)): 400, ('b', 'x', (2, 2)): 450})
        self.assertEqual(roles['pressure']['rescue'], [{'member': 'b', 'covers_for': 'a', 'opponent': 'x'}])
        self.assertEqual(roles['absorb']['status'], 'unknown')


class RefinementIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        (self.work / 'gamemaster.json').write_text(json.dumps(GM))
        self.builder = PartyBuilder(self.work)
        self.fake = SimpleNamespace(DATA=self.work)
        self.own = PartyBuilder._normalize(ROWS, CATALOG, SPECIES, CPMS, engine, 'test')
        self.rows = {p['id']: p for p in self.own}
        self.weights = {p['id']: 1 / 6 for p in self.own}
        self.matrix = {(p['id'], q['id'], (2, 2)): 550 for p in self.own for q in self.own}

    def refine(self, **changes):
        return StrategyAnalysis(self.builder, 'j', 'v', self.fake, self.work).refine(
            [p['id'] for p in self.own], [{'roster': [p['id'] for p in self.own]}],
            self.rows, self.own, self.matrix, changes.get('weights', self.weights))

    def test_real_engine_cache_reweight_and_exact_state_reuse(self):
        one = self.refine()
        two = self.refine(weights={k: v * 10 for k, v in self.weights.items()})
        self.assertEqual(one['targets'], two['targets'])
        self.assertEqual(one['cache']['computed'], 75)
        self.assertEqual(two['cache']['computed'], 0)
        self.assertEqual(two['cache']['hits'], 75)
        self.assertEqual(one['cells'], two['cells'])
        self.assertEqual(one['budget']['max_detail_cells'], 288)
        self.assertEqual(len(one['cells']), 18)
        branch = one['finalists'][0]['detail']['branch']
        self.assertEqual(branch['remaining_two']['status'], 'unknown')
        self.assertFalse((self.work / 'latest.zip').exists())
        saved = self.builder.save_party({'name': 'Keep', 'members': ROWS, 'strategy_refinement': False})
        self.assertFalse(self.builder.get_party(saved['id'])['strategy_refinement'])

    def test_unsupported_is_unknown_and_cancel_stops_before_battle(self):
        self.rows[self.own[0]['id']]['species'] = 'minior_meteor'
        one = self.refine()
        self.assertTrue(any(c['status'] == 'unknown' for c in one['cells']))
        self.builder._cancel = True
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            self.refine()

    def test_work_is_bounded_with_disjoint_finalists_and_500_meta_rows(self):
        rows = {str(i): dict(self.own[0], id=str(i), species='test' + str(i),
                            roster_clause_id=str(i)) for i in range(524)}
        targets = list(rows.values())[24:]
        matrix = {(str(i), t['id'], (2, 2)): 600 for i in range(24) for t in targets}
        calls = []
        battle = {'status': 'calculated', 'rating': 600, 'breakthrough': False,
                  'damage': [{'fast': 60}], 'initial': [{'max_hp': 100}, {'max_hp': 100}],
                  'terminal': [{'hp': 70, 'energy_points': 0, 'shields': 1}, {'hp': 40}],
                  'shields_used': [0, 0], 'events': [
                      {'index': 0, 'actor': 1, 'kind': 'charged', 'turn': 1, 'target_hp': 80},
                      {'index': 1, 'actor': 0, 'kind': 'fast', 'damage': 20}]}
        def resolve(action, request):
            calls.append(action)
            return battle if action == 'detail' else {'status': 'calculated', 'chase': battle}
        analysis = StrategyAnalysis(self.builder, 'j', 'v', self.fake, self.work)
        with patch.object(analysis, 'resolve', side_effect=resolve):
            result = analysis.refine([str(i) for i in range(6)],
                [{'roster': [str(i) for i in range(start, start + 6)]} for start in (6, 12, 18)],
                rows, targets, matrix, {t['id']: 1 / 500 for t in targets})
        self.assertEqual(len(result['targets']), 3)
        self.assertEqual(calls.count('detail'), 288)
        self.assertEqual(calls.count('switch_prefix'), 4)
        self.assertEqual(calls.count('switch_branch'), 8)
        self.assertEqual(len(calls), 300)

    def test_full_worker_build_and_autocomplete_preserve_locks_and_baseline(self):
        extra = dict(species='primeape', fast='COUNTER', charged1='ICE_PUNCH', charged2='CLOSE_COMBAT')
        meta_file = self.work / 'meta.csv'
        meta_file.write_text(''.join(','.join(r[k] for k in engine.HEADER[:4]) + '\n' for r in ROWS))
        with patch.object(engine, 'DATA', self.work), \
             patch('pvpoke_party_backend.presets.snapshot', return_value=(meta_file, {'sha256': 'fixture'})), \
             patch('pvpoke_party_backend.calculation_version', return_value='v'):
            for mode in ('build', 'analyze'):
                args = {'mode': mode, 'members': ROWS, 'locked_slots': [0],
                        'candidate_pool': ROWS[1:] + [extra] if mode == 'build' else [extra],
                        'auto_complete': mode == 'analyze'}
                result = self.builder._compute('j', args, CATALOG, SPECIES, CPMS, engine, self.work)
                ref = result['refinement']
                self.assertIsNotNone(ref)
                self.assertLessEqual(len(ref['finalists']), 3)
                self.assertEqual(len(result['pairs']), 15)
                for p in ref['finalists']:
                    self.assertIn(self.own[0]['id'], p['roster'])
                    self.assertEqual(len({self.rows[x]['roster_clause_id'] if x in self.rows else 'primeape' for x in p['roster']}), 6)
                if mode == 'build':
                    self.assertEqual(result['roster'], ref['finalists'][0]['roster'])
                else:
                    self.assertEqual(result['roster'], [p['id'] for p in self.own])
                # Opt-out returns the unchanged fast static path.
                args['strategy_refinement'] = False
                quick = self.builder._compute('j', args, CATALOG, SPECIES, CPMS, engine, self.work)
                self.assertIsNone(quick['refinement'])


if __name__ == '__main__':
    unittest.main()
