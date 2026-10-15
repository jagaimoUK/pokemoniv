import unittest

from pvpoke_app_input import app_presets, parse_import


CANDIDATE = dict(species='quagsire', fast='MUD_SHOT', charged1='AQUA_TAIL', charged2='STONE_EDGE')
SPECIES = {
    'quagsire': {'name': 'Quagsire', 'fastMoves': ['MUD_SHOT'], 'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE', 'MUD_BOMB']},
    'quagsire_shadow': {'name': 'Quagsire (Shadow)', 'fastMoves': ['MUD_SHOT'], 'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE']},
    'blastoise': {'name': 'Blastoise', 'fastMoves': ['BITE'], 'chargedMoves': ['HYDRO_CANNON', 'SKULL_BASH']},
}
CATALOG = {'ready': True, 'species': SPECIES, 'presets': [{**CANDIDATE, 'name': 'ヌオー'}]}


class AppInputTests(unittest.TestCase):
    def test_pasted_command_with_japanese_preset_name(self):
        result = parse_import('個体値厳選 d\nヌオー\n0,11,12\n3/13/8\n技構成:MUD_SHOT,AQUA_TAIL,STONE_EDGE', CATALOG)
        self.assertEqual(result['candidate'], CANDIDATE)
        self.assertEqual(result['ivs'], '0,11,12\n3,13,8')
        self.assertEqual(result['batch_mode'], 'detailed')

    def test_species_outside_presets_in_existing_eight_column_csv(self):
        result = parse_import('blastoise,BITE,HYDRO_CANNON,SKULL_BASH,22.5,13,9,3\nblastoise,BITE,HYDRO_CANNON,SKULL_BASH,24,0,15,15', CATALOG)
        self.assertEqual(result['candidate']['species'], 'blastoise')
        self.assertEqual(result['ivs'], '13,9,3\n0,15,15')
        self.assertTrue(any('レベル' in x for x in result['warnings']))

    def test_command_roundtrip_with_moves_and_all_ivs(self):
        result = parse_import('個体値厳選\nquagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n0,11,12\n3,13,8\n2,15,13', CATALOG)
        self.assertEqual(result['candidate'], CANDIDATE)
        self.assertEqual(result['candidate_count'], 3)

    def test_seven_column_csv_and_header_csv(self):
        rows = ['quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE,0,11,12',
                'species,fast,charged1,charged2,level,atk,def,hp,cp\nquagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE,25,0,11,12,1499']
        for text in rows:
            with self.subTest(text=text):
                r = parse_import(text, CATALOG)
                self.assertEqual(r['candidate'], CANDIDATE)
                self.assertEqual(r['ivs'], '0,11,12')

    def test_fullwidth_voice_input_and_duplicate_notice(self):
        r = parse_import('個体値リスト\n# Quagsire\n０，１１，１２\n0,11,12\n3,13,8 2,15,13', CATALOG)
        self.assertEqual(r['candidate_count'], 3)
        self.assertTrue(any('重複' in x for x in r['warnings']))

    def test_important_iv_only_input_keeps_explicit_current_moves(self):
        r = parse_import('重要個体値\n0,11,12\n2,15,13', CATALOG, CANDIDATE)
        self.assertEqual(r['candidate'], CANDIDATE)
        self.assertEqual(len(r['warnings']), 2)

    def test_unknown_species_still_fail(self):
        with self.assertRaises(ValueError):
            parse_import('UnknownMon\n0,11,12', CATALOG)

    def test_mixed_species_csv_are_separate_jobs(self):
        r = parse_import('quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE,0,11,12\nblastoise,BITE,HYDRO_CANNON,SKULL_BASH,0,15,15', CATALOG)
        self.assertEqual(r['group_count'], 2)
        self.assertEqual([x['ivs'] for x in r['jobs']], ['0,11,12', '0,15,15'])
        self.assertNotIn('candidate', r)

    def test_mixed_moves_and_bad_ivs_fail(self):
        for text in ['quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n0,16,12',
                     'blastoise,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n0,11,12',
                     'quagsire,MUD_SHOT,AQUA_TAIL,AQUA_TAIL\n0,11,12']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_import(text, CATALOG)

    def test_distinct_moves_are_separate_jobs(self):
        r = parse_import('quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE,0,11,12\nquagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB,3,13,8', CATALOG)
        self.assertEqual(r['group_count'], 2)
        self.assertEqual([x['candidate']['charged2'] for x in r['jobs']], ['STONE_EDGE', 'MUD_BOMB'])

    def test_ambiguous_preset_moves_require_explicit_selection(self):
        catalog = {**CATALOG, 'app_presets': [CANDIDATE, {**CANDIDATE, 'charged2': 'MUD_BOMB'}]}
        with self.assertRaisesRegex(ValueError, '技構成を指定'):
            parse_import('quagsire\n0,11,12', catalog)

    def test_export_shadow_suffix_preserved(self):
        r = parse_import('quagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE,25,0,11,12', CATALOG)
        self.assertEqual(r['candidate']['species'], 'quagsire_shadow')

    def test_meta_presets_include_all_valid_distinct_move_sets(self):
        meta = ('quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
                'quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n'
                'quagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n'
                'blastoise,BITE,HYDRO_CANNON,SKULL_BASH\n'
                'blastoise,WRONG,HYDRO_CANNON,SKULL_BASH\n')
        rows = app_presets(SPECIES, CATALOG['presets'], meta)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['key'] for r in rows}), 4)
        self.assertEqual(rows[0]['name'], 'ヌオー')
        self.assertEqual(sum(r['species'] == 'quagsire' for r in rows), 2)


if __name__ == '__main__':
    unittest.main()
