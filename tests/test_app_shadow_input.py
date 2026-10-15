"""Pasted shadow headings preserve species, forms and every supplied IV."""
import unittest

from pvpoke_app_catalog import enrich_catalog
from pvpoke_app_defaults import GL_MOVES
from pvpoke_app_input import parse_import


IVS = ('15,11,11\n7,11,14\n15,13,10\n14,11,10\n8,14,8\n7,13,8\n'
       '2,10,10\n3,4,14\n5,4,11\n6,5,6\n5,0,5\n3,0,6')
MOVES = 'BITE,CRUNCH,POISON_FANG'


def catalog():
    raw, payload = {}, {}
    for base, dex in (('carvanha', 318), ('sharpedo', 319), ('muk', 89)):
        for form in ('', '_shadow') if base != 'muk' else ('', '_alolan', '_alolan_shadow'):
            sid = base + form
            moves = GL_MOVES.get(sid, ['BITE', 'CRUNCH', 'POISON_FANG'])
            raw[sid] = {'dex': dex}
            suffix = ' (Alolan)' if 'alolan' in form else ''
            suffix += ' (Shadow)' if 'shadow' in form else ''
            payload[sid] = {'name': base.capitalize() + suffix,
                            'fastMoves': [moves[0]], 'chargedMoves': list(moves[1:])}
    enrich_catalog(payload, raw)
    return {'species': payload}


class ShadowInputTests(unittest.TestCase):
    def test_user_heading_all_12_ivs_go_to_both_shadow_species(self):
        for heading in ('キバニア (シャドウ) サメハダー (シャドウ)',
                        'シャドウキバニア シャドウサメハダー',
                        'キバニア(シャドウ) サメハダー(シャドウ)',
                        'キバニア （シャドウ） サメハダー（シャドウ）',
                        'キバニア　（シャドウ）　シャドウサメハダー'):
            with self.subTest(heading=heading):
                result = parse_import('個体値厳選\n\n# ' + heading + '\n' + MOVES + '\n\n' + IVS, catalog())
                self.assertEqual([j['candidate']['species'] for j in result['jobs']],
                                 ['carvanha_shadow', 'sharpedo_shadow'])
                self.assertEqual(result['total_candidate_count'], 24)
                self.assertTrue(all(j['candidate_count'] == 12 and j['ivs'] == IVS
                                    for j in result['jobs']))

    def test_plain_and_shadow_do_not_merge(self):
        result = parse_import('# キバニア キバニア (シャドウ)\n' + MOVES + '\n1,2,3', catalog())
        self.assertEqual([j['candidate']['species'] for j in result['jobs']],
                         ['carvanha', 'carvanha_shadow'])

    def test_bare_japanese_and_existing_english_or_id_forms(self):
        for name in ('キバニア (シャドウ)', 'キバニア（シャドウ）',
                     'シャドウキバニア', 'shadow キバニア', 'キバニア shadow',
                     'Carvanha (Shadow)', 'carvanha_shadow', 'carvanha_shadow-shadow'):
            with self.subTest(name=name):
                result = parse_import(name + '\n' + MOVES + '\n1,2,3', catalog())
                self.assertEqual(result['candidate']['species'], 'carvanha_shadow')

    def test_regional_shadow_keeps_region(self):
        for name in ('アローラベトベトン (シャドウ)', 'ベトベトン(アローラ)(シャドウ)',
                     'シャドウアローラベトベトン'):
            with self.subTest(name=name):
                result = parse_import('# ' + name + '\n1,2,3', catalog())
                self.assertEqual(result['candidate']['species'], 'muk_alolan_shadow')

    def test_unrecognized_shadow_annotation_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_import('# キバニア (シャドウ不明)\n1,2,3', catalog())

    def test_missing_recommended_moves_asks_for_moves_after_resolving_name(self):
        for name in ('キバニア (シャドウ)', 'シャドウキバニア'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, '推奨技がありません'):
                parse_import('# ' + name + '\n' + IVS, catalog())


if __name__ == '__main__':
    unittest.main()
