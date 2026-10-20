"""Minior uses Meteor only for experimental GL simulation, Core in GO box."""
import unittest

from pvpoke_app_catalog import enrich_catalog
from pvpoke_app_input import parse_import
from pvpoke_app_selection import search_string


class MiniorCatalogTest(unittest.TestCase):
    def test_plain_japanese_minior_selects_meteor(self):
        species = {
            'minior_core': {
                'speciesId': 'minior_core', 'speciesName': 'Minior (Core)',
                'dex': 774, 'fastMoves': ['ROCK_THROW'],
                'chargedMoves': ['ROCK_SLIDE', 'ANCIENT_POWER'],
            },
            'minior_meteor': {
                'speciesId': 'minior_meteor', 'speciesName': 'Minior (Meteor)',
                'dex': 774, 'fastMoves': ['ROCK_THROW'],
                'chargedMoves': ['ROCK_SLIDE', 'ANCIENT_POWER'],
            },
        }
        catalog = {'species': {sid: {
            'name': info['speciesName'], 'dex': info['dex'],
            'fastMoves': info['fastMoves'],
            'chargedMoves': info['chargedMoves'],
        } for sid, info in species.items()}}
        enrich_catalog(catalog['species'], species)
        self.assertIn('メテノ', catalog['species']['minior_meteor']['aliases'])
        self.assertNotIn('メテノ', catalog['species']['minior_core']['aliases'])
        result = parse_import(
            '# メテノ\nROCK_THROW,ROCK_SLIDE,ANCIENT_POWER\n0,14,15',
            catalog)
        self.assertEqual(result['jobs'][0]['candidate']['species'], 'minior_meteor')

    def test_go_copy_uses_base_name(self):
        self.assertEqual(
            search_string('Minior (Meteor)', '0/14/15', species_id='minior_meteor'),
            'Minior&0attack&3defense&4hp')
        self.assertEqual(
            search_string('Minior (Core)', '0/14/15', species_id='minior_core'),
            'Minior&0attack&3defense&4hp')

    def test_other_species_unchanged(self):
        self.assertEqual(
            search_string('Quagsire', '0/14/15', species_id='quagsire'),
            'Quagsire&0attack&3defense&4hp')


if __name__ == '__main__':
    unittest.main()
