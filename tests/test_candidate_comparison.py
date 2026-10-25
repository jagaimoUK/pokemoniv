"""Compare optimized summaries with the exhaustive definitions, including ties."""
import random
import unittest

from pvpoke_candidate_comparison import rating_dominators, rival_summaries
from pvpoke_app_selection import search_string
from pvpoke_score_search import _search_term


class CandidateComparisonTests(unittest.TestCase):
    def test_pairwise_dominance_and_order_match_exhaustive_definition(self):
        rng = random.Random(669)
        for _ in range(100):
            ivs = [str(i) for i in range(rng.randint(1, 40))]
            size = rng.randint(1, 24)
            pool = [tuple(rng.choice([499, 500, 501, 550]) for _ in range(size))
                    for _ in range(rng.randint(1, len(ivs)))]
            vectors = {iv: rng.choice(pool) for iv in ivs}
            owners, groups = {}, {}
            for iv in sorted(ivs):
                vector = vectors[iv]
                if vector in owners:
                    groups[owners[vector]].append(iv)
                else:
                    owners[vector] = iv
                    groups[iv] = []
            expected = {iv: [other for other in ivs if other != iv
                              and all(a >= b for a, b in zip(vectors[other], vectors[iv]))
                              and any(a > b for a, b in zip(vectors[other], vectors[iv]))]
                        for iv in ivs}
            self.assertEqual(rating_dominators(ivs, vectors, groups), expected)

    def test_rivals_include_ties_draws_and_dominated_groups(self):
        rng = random.Random(500)
        for n in range(1, 101):
            scores = {str(i): rng.choice([0, 499, 500, 501, 1000]) for i in range(n)}
            expected = {}
            for iv in scores:
                others = [r for other, r in scores.items() if other != iv]
                expected[iv] = (max(others, default=None), any(r <= 500 for r in others))
            self.assertEqual(rival_summaries(scores), expected)

    def test_flabebe_uses_exact_dex_and_preserves_query_filters(self):
        for name in ('Flabébé', 'Flabebe', 'Flabe\u0301be\u0301', 'FLABÉBÉ', 'フラベベ'):
            self.assertEqual(search_string(name, '0/11/15'), '669&0attack&3defense&4hp')
        self.assertEqual(search_string('Flabébé (Blue Flower) (Shadow)', '1/2/3', True, 'flabebe_shadow'),
                         '669&1attack&1defense&1hp&shadow')
        self.assertEqual(search_string('Floette', '0/11/15', species_id='floette'),
                         'Floette&0attack&3defense&4hp')
        self.assertEqual(_search_term({'name': 'フラベベ', 'dex': 669}, {}, 'Flabébé'),
                         (('669', ('!shadow',)), None))


if __name__ == '__main__':
    unittest.main()
