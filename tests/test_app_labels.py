import unittest
from pvpoke_app_catalog import enrich_catalog
from pvpoke_app_labels import assign_nickname_codes


class AppLabelTests(unittest.TestCase):
    def test_evolution_and_forms_have_distinct_ascii_codes(self):
        names = ['bulbasaur', 'ivysaur', 'venusaur', 'wartortle', 'blastoise',
                 'quagsire', 'swadloon', 'swampert', 'leavanny', 'leafeon',
                 'quagsire_shadow', 'quagsire_galarian', 'quagsire_galarian_shadow']
        rows = {sid: {} for sid in names}
        assign_nickname_codes(rows)
        codes = [r['nickname_code'] for r in rows.values()]
        self.assertEqual(len(codes), len({c.casefold() for c in codes}))
        self.assertTrue(all(c.isascii() and c.isalnum() and len(c) <= 4 for c in codes))
        self.assertEqual(rows['leavanny']['nickname_code'], 'Lea')
        reverse = {sid: {} for sid in reversed(names)}
        assign_nickname_codes(reverse)
        self.assertEqual(rows, reverse)

    def test_grade_prefix_never_forms_a_blocked_word(self):
        rows = {sid: {} for sid in ('nacli', 'naclstack', 'garganacl',
                                     'naclstack_shadow')}
        assign_nickname_codes(rows)
        self.assertEqual(rows['naclstack']['nickname_code'], 'Nst')
        self.assertEqual(rows['garganacl']['nickname_code'], 'Gag')
        for row in rows.values():
            code = row['nickname_code']
            self.assertNotIn('anal', ('A' + code).casefold())
            self.assertNotIn('ass', ('S' + code).casefold())

    def test_collisions_do_not_alias_one_form_to_another(self):
        rows = {f'pokemon_form{i}': {} for i in range(60)}
        assign_nickname_codes(rows)
        self.assertEqual(len({r['nickname_code'].casefold() for r in rows.values()}), 60)
        self.assertTrue(all(len(r['nickname_code']) <= 4 for r in rows.values()))

    def test_japanese_form_keeps_region_shadow_and_sex(self):
        raw = {'corsola_galarian_shadow': {'dex': 222},
               'oinkologne_female': {'dex': 916}, 'aegislash': {'dex': 681}, 'morpeko_full_belly': {'dex': 877}}
        rows = {'corsola_galarian_shadow': {'name': 'Corsola (Galarian) (Shadow)'},
                'oinkologne_female': {'name': 'Oinkologne (Female)'},
                'aegislash': {'name': 'Aegislash (Shield)'},
                'morpeko_full_belly': {'name': 'Morpeko (Full Belly)'}}
        enrich_catalog(rows, raw)
        self.assertEqual(rows['corsola_galarian_shadow']['name_ja'], 'サニーゴ(ガラル) (シャドウ)')
        self.assertIn('メス', rows['oinkologne_female']['name_ja'])
        self.assertIn('シールド', rows['aegislash']['name_ja'])
        self.assertEqual(rows['morpeko_full_belly']['name_ja'], 'モルペコ(まんぷくもよう)')
