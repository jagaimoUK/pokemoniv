"""Rule regressions: preserve specialist roles, refuse loss-only improvements,
compare all modes and keep the established GPT path compatible.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pvpoke_app_selection import recommend, search_string, validate_policy
from pvpoke_selection_matrix import SelectionMatrix, SHIELDS, MODES
from pvpoke_iv_workflow import IVWorkflow
from test_iv_workflow import CANDIDATE, IVS, FakeBackend


def matrix(rows, opponents=None):
    opponents = opponents or ['Corviknight', 'Quagsire', 'Feraligatr'][:len(next(iter(rows.values())))]
    return SelectionMatrix(opponents, list(rows),
                           {s: {iv: list(r) for iv, r in rows.items()} for s in SHIELDS}, {})


class AppSelectionTests(unittest.TestCase):
    def test_three_specialists_survive_with_low_average(self):
        data = matrix({'0/11/12': [506, 350, 200], '3/13/8': [490, 600, 499],
                       '2/15/13': [480, 590, 510]})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire', ['Corviknight'])
        rows = {r['ivs']: r for r in result['recommendations']}
        self.assertEqual(set(rows), set(data.candidates))
        self.assertEqual(rows['0/11/12']['grade'], 'S候補')
        self.assertEqual(rows['0/11/12']['search_string'], 'Quagsire&0attack&3defense&3hp')
        self.assertEqual(result['total_ratings_checked'], 54)

    def test_loss_only_rating_lead_is_reviewed_not_recommended(self):
        data = matrix({'0/11/12': [480, 450], '3/13/8': [450, 480]})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire')
        self.assertFalse(result['recommendations'])
        self.assertEqual(len(result['review_candidates']), 2)

    def test_strict500_boundary_and_exact_draw(self):
        data = matrix({'0/11/12': [500, 450], '3/13/8': [499, 510]})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire')
        events = {r['ivs']: r['evidence'] for r in result['recommendations']}
        self.assertEqual(events['0/11/12'][0]['kind'], 'unique_eq500')
        self.assertEqual(events['3/13/8'][0]['kind'], 'unique_gt500')

    def test_dominance_requires_same_rival_across_all24_conditions(self):
        a, b = '0/11/12', '3/13/8'
        simple = matrix({a: [550], b: [500]})
        reverse = matrix({a: [480], b: [510]})
        detailed = {'default': simple, **{m: reverse for m in MODES[1:]}}
        result = recommend(detailed, CANDIDATE, 'Quagsire')
        self.assertFalse(result['dominated_by'])
        self.assertEqual(len(result['recommendations']), 2)
        self.assertEqual(result['condition_count'], 24)
        self.assertEqual(result['total_ratings_checked'], 48)

    def test_equivalent_alternatives_and_strict_dominance(self):
        data = matrix({'0/11/12': [510, 520], '3/13/8': [510, 520], '2/15/13': [500, 520]})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire')
        self.assertEqual(len(result['recommendations']), 1)
        self.assertEqual(result['recommendations'][0]['equivalent_candidates'][0]['ivs'], '3/13/8')
        self.assertIn('2/15/13', result['dominated_by'])

    def test_unique_win_must_include_dominated_rivals(self):
        data = matrix({'0/11/12': [550], '3/13/8': [540]})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire', ['Corviknight'])
        row = result['recommendations'][0]
        self.assertEqual(row['grade'], 'A候補')
        self.assertEqual(row['evidence'][0]['kind'], 'available_matchup')
        self.assertEqual(row['evidence'][0]['next_best'], 540)

    def test_no_recommendation_cap_and_every_candidate_accounted_for(self):
        rows = {f'{i}/10/8': [510 if i == j else 490 for j in range(15)] for i in range(15)}
        result = recommend({'default': matrix(rows, [f'Opponent {i}' for i in range(15)])}, CANDIDATE, 'Quagsire')
        self.assertEqual(len(result['recommendations']), 15)
        self.assertEqual(result['total_ratings_checked'], 15 * 15 * 6)

    def test_invalid_policy_and_missing_mode_fail_before_battle(self):
        for v in [0, float('nan'), float('inf'), True, '20']:
            with self.assertRaises(ValueError):
                validate_policy({'meaningful_win_lead': v})
        with self.assertRaises(ValueError):
            recommend({'rank1': matrix({'0/11/12': [510]})}, CANDIDATE, 'Quagsire')
        backend = FakeBackend()
        with self.assertRaises(ValueError):
            IVWorkflow(backend).run(CANDIDATE, IVS, report_format='app', selection_policy={'meaningful_win_lead': 0})
        self.assertEqual(backend.run_count, 0)

    def test_threshold_controls_winning_margins_only(self):
        data = matrix({'0/11/12': [550, 530], '3/13/8': [520, 550]})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire', policy={'meaningful_win_lead': 50})
        self.assertFalse(result['recommendations'])
        self.assertEqual(len(result['review_candidates']), 2)

    def test_missing_focus_is_visible(self):
        result = recommend({'default': matrix({'0/11/12': [510]})}, CANDIDATE, 'Quagsire', ['missing'])
        self.assertEqual(result['unmatched_focus'], ['missing'])

    def test_shadow_and_iv_buckets(self):
        self.assertEqual(search_string('Blastoise', '0/5/15', True), 'Blastoise&0attack&1defense&4hp&shadow')
        self.assertEqual(search_string('Quagsire', '6/11/14'), 'Quagsire&2attack&3defense&3hp')

    def test_verified_workflow_and_cached_app_results(self):
        backend = FakeBackend()
        backend.candidate_name = lambda sid: 'Quagsire'
        runner = IVWorkflow(backend)
        ref = runner.run(CANDIDATE, IVS, report_format='app', wait_seconds=0)['run_ref']
        backend.state = 'done'
        with patch.object(backend, '_zip', wraps=backend._zip) as download:
            first = runner.result(ref)
            self.assertEqual(first['selection']['format'], 'app-recommendations-v1')
            self.assertEqual(first['total_ratings_checked'], 24)
            first['selection']['recommendations'].clear()
            self.assertTrue(runner.result(ref)['selection']['recommendations'])
            self.assertEqual(download.call_count, 1)
        backend.time = 'changed'
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            runner.result(ref)

    def test_real_saved_production_ratings_used_without_recalculation(self):
        fixture = json.loads((Path(__file__).parent / 'phase3_full_production_baseline.json').read_text())
        ivs = fixture['metadata']['candidate_ivs']
        conditions = fixture['conditions']
        names = conditions['s0'][0]['opponents']
        data = SelectionMatrix(names, ivs, {
            s: {iv: row['ratings'] for iv, row in zip(ivs, conditions[s])} for s in SHIELDS
        }, {})
        result = recommend({'default': data}, CANDIDATE, 'Quagsire')
        self.assertEqual(result['total_ratings_checked'], 3 * 87 * 6)
        seen = set(result['dominated_by']) | {r['ivs'] for r in result['review_candidates']}
        for row in result['recommendations']:
            seen.add(row['ivs'])
            seen.update(e['ivs'] for e in row['equivalent_candidates'])
            for e in row['evidence']:
                self.assertEqual(e['rating'], data.ratings[e['shield']][row['ivs']][names.index(e['opponent'])])
        self.assertEqual(seen, set(ivs))


if __name__ == '__main__':
    unittest.main()
