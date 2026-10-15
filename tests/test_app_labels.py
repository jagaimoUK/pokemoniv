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
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(c.isascii() and c.isalnum() and len(c) <= 4 for c in codes))
        self.assertEqual(rows['leavanny']['nickname_code'], 'Lea')
        reverse = {sid: {} for sid in reversed(names)}
        assign_nickname_codes(reverse)
        self.assertEqual(rows, reverse)

    def test_collisions_do_not_alias_one_form_to_another(self):
        rows = {f'pokemon_form{i}': {} for i in range(60)}
        assign_nickname_codes(rows)
        self.assertEqual(len({r['nickname_code'] for r in rows.values()}), 60)
        self.assertTrue(all(len(r['nickname_code']) <= 4 for r in rows.values()))

    def test_japanese_form_keeps_region_shadow_and_sex(self):
        raw = {'corsola_galarian_shadow': {'dex': 222},
               'oinkologne_female': {'dex': 916}, 'aegislash': {'dex': 681}}
        rows = {'corsola_galarian_shadow': {'name': 'Corsola (Galarian) (Shadow)'},
                'oinkologne_female': {'name': 'Oinkologne (Female)'},
                'aegislash': {'name': 'Aegislash (Shield)'}}
        enrich_catalog(rows, raw)
        self.assertEqual(rows['corsola_galarian_shadow']['name_ja'], 'サニーゴ(ガラル) (シャドウ)')
        self.assertIn('メス', rows['oinkologne_female']['name_ja'])
        self.assertIn('シールド', rows['aegislash']['name_ja'])
