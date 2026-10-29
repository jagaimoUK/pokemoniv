"""Moveset ranking must use complete matrices and exact, shared matchup axes."""
import unittest
from pvpoke_app_selection import recommend
from pvpoke_selection_matrix import MODES, SHIELDS, SelectionMatrix

CANDIDATE = dict(species='quagsire', fast='MUD_SHOT', charged1='AQUA_TAIL', charged2='STONE_EDGE')

def matrix(rows, opponents=('A', 'B')):
    return SelectionMatrix(list(opponents), list(rows),
                           {s: {iv: list(r) for iv, r in rows.items()} for s in SHIELDS}, {})

class MovesetSummaryTests(unittest.TestCase):
    def test_full_ratings_not_sparse_evidence_and_strict_win_boundary(self):
        result = recommend({'default': matrix({'0/15/15': [500, 200], '1/15/15': [499, 700]})}, CANDIDATE, 'Quagsire')
        summary = result['moveset_summary']
        self.assertEqual(summary['version'], 1)
        self.assertEqual(summary['mean_rating'], 474.75)
        self.assertEqual(summary['iv_mean_ratings'], {'0/15/15': 350, '1/15/15': 599.5})
        self.assertEqual(summary['available_wins'], '01' * 6)
        self.assertEqual(summary['rating_count'], 24)
        self.assertEqual(len(summary['axis_sha256']), 64)

    def test_axes_include_order_names_modes_and_shields_but_not_candidate_ratings(self):
        a = matrix({'0/15/15': [510, 520]})
        b = matrix({'0/15/15': [100, 200]})
        def summary(m): return recommend(m, CANDIDATE, 'Quagsire')['moveset_summary']
        base = summary({'default': a})
        self.assertEqual(base['axis_sha256'], summary({'default': b})['axis_sha256'])
        self.assertNotEqual(base['axis_sha256'], summary({'default': matrix({'0/15/15': [510, 520]}, ('B', 'A'))})['axis_sha256'])
        detailed = summary({mode: a for mode in MODES})
        self.assertNotEqual(base['axis_sha256'], detailed['axis_sha256'])
        self.assertEqual(detailed['rating_count'], 48)

if __name__ == '__main__': unittest.main()
