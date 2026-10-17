import unittest
from pvpoke_app_input import parse_import


class ObservedCPTests(unittest.TestCase):
    def catalog(self):
        return {'species': {
            sid: {'name': en, 'aliases': [ja], 'fastMoves': ['A'], 'chargedMoves': ['B', 'C'],
                  'default_moves': {'fast': 'A', 'charged1': 'B', 'charged2': 'C'}}
            for sid, en, ja in [('wooper', 'Wooper', 'ウパー'), ('quagsire', 'Quagsire', 'ヌオー'),
                                 ('wooper_shadow', 'Wooper (Shadow)', 'シャドウウパー')]}}

    def test_evolution_cp_uses_original_species_and_preserves_multiple_cps(self):
        r = parse_import('個体値厳選\n# ウパー ヌオー\n0,11,12 CP717 | ウパー\n0,11,12 CP625 | ウパー\n1,2,3', self.catalog())
        self.assertEqual(len(r['jobs']), 2)
        for job in r['jobs']:
            self.assertEqual(job['candidate_count'], 2)
            self.assertEqual([x['cp'] for x in job['source_records']], [717, 625])
            self.assertEqual(job['source_records'][0]['search_string'], 'Wooper&0attack&3defense&3hp&cp717')

    def test_regional_source_cp_search_preserves_read_iv_and_exact_cp(self):
        region_catalog = self.catalog()
        region_catalog['species']['wooper_paldean'] = {
            'name': 'Wooper (Paldean)',
            'aliases': ['パルデアウパー', 'ウパー(パルデア)'],
            'fastMoves': ['A'], 'chargedMoves': ['B', 'C'],
            'default_moves': {'fast': 'A', 'charged1': 'B', 'charged2': 'C'},
        }
        r = parse_import(
            '# パルデアウパー\n13,8,11 CP458 | wooper_paldean',
            region_catalog)
        self.assertEqual(r['source_records'][0]['species'], 'wooper_paldean')
        self.assertEqual(
            r['source_records'][0]['search_string'],
            'Wooper&paldea&3attack&2defense&3hp&cp458')

    def test_shadow_regional_source_cp_and_normal_source_remain_separate(self):
        catalog = self.catalog()
        catalog['species']['wooper_paldean_shadow'] = {
            'name': 'Wooper (Paldean) (Shadow)',
            'aliases': ['シャドウパルデアウパー'],
            'fastMoves': ['A'], 'chargedMoves': ['B', 'C'],
            'default_moves': {'fast': 'A', 'charged1': 'B', 'charged2': 'C'},
        }
        r = parse_import(
            '# シャドウパルデアウパー\n13,8,11 CP458 | wooper_paldean_shadow',
            catalog)
        self.assertEqual(
            r['source_records'][0]['search_string'],
            'Wooper&paldea&3attack&2defense&3hp&shadow&cp458')

    def test_shadow_and_fullwidth(self):
        r = parse_import('# シャドウウパー\n０，１１，１２ ＣＰ７１７ | シャドウウパー', self.catalog())
        self.assertIn('&shadow&cp717', r['source_records'][0]['search_string'])

    def test_old_input_does_not_invent_cp(self):
        r = parse_import('# ヌオー\n0,11,12', self.catalog())
        self.assertEqual(r['source_records'], [])

    def test_simulator_cp_is_not_observed_cp(self):
        text = 'species,fast,charged1,charged2,atk,def,hp,cp\nquagsire,A,B,C,0,11,12,1499'
        self.assertEqual(parse_import(text, self.catalog())['source_records'], [])
        r = parse_import(text.replace(',cp', ',source_cp'), self.catalog())
        self.assertEqual(r['source_records'][0]['cp'], 1499)

    def test_invalid_cp_or_unknown_source_rejects_all(self):
        for line in ['0,11,12 CP0 | ウパー', '0,11,12 CP10001 | ウパー',
                     '0,11,12 CP717 | Unknown', '16,11,12 CP717 | ウパー']:
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_import('# ヌオー\n1,2,3\n' + line, self.catalog())

    def test_sections_do_not_cross_species_or_cp(self):
        r = parse_import('# ウパー\n0,11,12 CP717 | ウパー\n# ヌオー\n0,11,12 CP1300 | ヌオー', self.catalog())
        self.assertEqual([j['source_records'][0]['cp'] for j in r['jobs']], [717, 1300])


if __name__ == '__main__':
    unittest.main()
