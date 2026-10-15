from copy import deepcopy
import unittest

from pvpoke_app_catalog import enrich_catalog
from pvpoke_app_input import parse_import

EXAMPLE = '個体値厳選 - - # クルマユ - 12,12,0 - 4,5,7 - 14,11,8 - 3,1,11 - 3,12,5 - 5,14,2 - - # クルマユ ハハコモリ - 5,3,15 - 15,5,5 - 6,0,11 - 3,1,11 - 1,4,12 - 0,12,0 - 1,14,5 - 1,14,0 - 11,14,9 - 12,11,3 - 0,11,1'


def catalog():
    raw = {
        'swadloon': {'dex': 541, 'speciesName': 'Swadloon', 'fastMoves': ['BUG_BITE', 'STRUGGLE_BUG'], 'chargedMoves': ['ENERGY_BALL', 'SILVER_WIND', 'BUG_BUZZ']},
        'leavanny': {'dex': 542, 'speciesName': 'Leavanny', 'fastMoves': ['SHADOW_CLAW', 'BUG_BITE'], 'chargedMoves': ['LEAF_BLADE', 'X_SCISSOR', 'SILVER_WIND']},
    }
    payload = {sid: {'name': p['speciesName'], 'fastMoves': p['fastMoves'], 'chargedMoves': p['chargedMoves']} for sid, p in raw.items()}
    enrich_catalog(payload, raw)
    return {'species': payload}


class GroupedInputTests(unittest.TestCase):
    def test_exact_user_example_and_species_scoped_dedup(self):
        r = parse_import(EXAMPLE, catalog())
        self.assertEqual(r['group_count'], 2)
        self.assertEqual(r['total_candidate_count'], 27)
        self.assertEqual(r['batch_mode'], 'simple')
        a, b = r['jobs']
        self.assertEqual([a['candidate_count'], b['candidate_count']], [16, 11])
        self.assertEqual([a['candidate']['species'], b['candidate']['species']], ['swadloon', 'leavanny'])
        self.assertEqual(a['ivs'].splitlines().count('3,1,11'), 1)
        self.assertIn('3,1,11', b['ivs'].splitlines())
        self.assertNotIn('12,12,0', b['ivs'].splitlines())
        self.assertEqual(a['candidate']['fast'], 'BUG_BITE')
        self.assertEqual(b['candidate']['fast'], 'SHADOW_CLAW')
        self.assertEqual(a['candidate']['charged1'], 'ENERGY_BALL')
        self.assertEqual(b['candidate']['charged1'], 'LEAF_BLADE')
        self.assertTrue(all(any('技省略' in w for w in j['warnings']) for j in r['jobs']))

    def test_newlines_and_hyphen_separators_mean_the_same(self):
        import re
        text = re.sub(r'\s+-\s+', '\n', EXAMPLE)
        a, b = parse_import(EXAMPLE, catalog()), parse_import(text, catalog())
        self.assertEqual(a['jobs'], b['jobs'])

    def test_equivalent_japanese_heading_and_empty_section(self):
        r = parse_import('個体値厳選 d\n#これ以降クルマユとハハコモリ\n1,2,3\n#クルマユ', catalog())
        self.assertEqual(r['group_count'], 2)
        self.assertTrue(all(j['ivs'] == '1,2,3' for j in r['jobs']))
        self.assertTrue(all(j['batch_mode'] == 'detailed' for j in r['jobs']))

    def test_explicit_moves_override_pvpoke_default_for_that_section(self):
        r = parse_import('#クルマユ\nSTRUGGLE_BUG,BUG_BUZZ,SILVER_WIND\n1,2,3\n#ハハコモリ\n1,2,3', catalog())
        self.assertEqual(r['jobs'][0]['candidate']['fast'], 'STRUGGLE_BUG')
        self.assertEqual(r['jobs'][1]['candidate']['fast'], 'SHADOW_CLAW')

    def test_unknown_species_bad_iv_and_ambiguous_form_do_not_fall_through(self):
        for text in ['#クルマユ 未知の名前\n1,2,3', '#クルマユ\n-1,2,3', '#クルマユ\n1,16,3']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_import(text, catalog())
        c = catalog()
        c['species']['other'] = {**deepcopy(c['species']['swadloon']), 'aliases': ['クルマユ']}
        with self.assertRaises(ValueError):
            parse_import('#クルマユ\n1,2,3', c)

    def test_stale_default_moves_are_rejected(self):
        c = catalog()
        c['species']['leavanny']['fastMoves'] = ['BUG_BITE']
        with self.assertRaisesRegex(ValueError, 'ハハコモリ'):
            parse_import('#クルマユ ハハコモリ\n1,2,3', c)

    def test_unknown_middle_line_is_not_silently_skipped(self):
        with self.assertRaises(ValueError):
            parse_import('#クルマユ\n1,2,3\nこれは未知の命令\n#ハハコモリ\n4,5,6', catalog())

    def test_repeated_heading_merges_only_same_species_and_moves(self):
        r = parse_import('#クルマユ\n1,2,3\n#クルマユ ハハコモリ\n1,2,3\n#クルマユ\nSTRUGGLE_BUG,BUG_BUZZ,SILVER_WIND\n1,2,3', catalog())
        self.assertEqual(r['group_count'], 3)
        self.assertTrue(all(j['candidate_count'] == 1 for j in r['jobs']))

    def test_bare_english_name_with_spaces_stays_a_single_species(self):
        c = catalog()
        c['species']['example'] = {**deepcopy(c['species']['swadloon']), 'name': 'Example With Spaces', 'aliases': []}
        r = parse_import('#Example With Spaces ハハコモリ\n1,2,3', c)
        self.assertEqual(r['jobs'][0]['candidate']['species'], 'example')


if __name__ == '__main__':
    unittest.main()
