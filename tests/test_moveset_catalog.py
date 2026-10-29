import copy
import unittest
from unittest.mock import patch
import pvpoke_web as web


class MovesetCatalogTests(unittest.TestCase):
    def test_live_move_stats_and_effects_are_available_to_planner(self):
        raw = {'quagsire': {'speciesName': 'Quagsire', 'dex': 195,
            'types': ['water', 'ground'], 'baseStats': {},
            'fastMoves': ['MUD_SHOT'], 'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE']}}
        move = {'moveId': 'MUD_SHOT', 'name': 'Mud Shot', 'type': 'ground',
                'power': 4, 'energyGain': 8, 'energy': 0, 'cooldown': 1000}
        effect = {'moveId': 'AQUA_TAIL', 'name': 'Aqua Tail', 'type': 'water',
                  'power': 55, 'energy': 35, 'buffs': [0, -1],
                  'buffTarget': 'opponent', 'buffApplyChance': 0.3}
        with patch.object(web, 'configure_engine'), patch.object(web.engine, 'game_data',
                return_value=({'moves': [move, effect]}, [], raw)), \
                patch.object(web.engine, 'charged_move_pool', side_effect=lambda p: p['chargedMoves']), \
                patch.object(web.meta_variants, 'start'), patch.dict(web.CATALOG, copy.deepcopy(web.CATALOG)):
            web.load_catalog()
            self.assertTrue(web.CATALOG['ready'], web.CATALOG['error'])
            self.assertEqual(web.CATALOG['species']['quagsire']['types'], ['water', 'ground'])
            self.assertEqual(web.CATALOG['moves']['MUD_SHOT']['energyGain'], 8)
            self.assertEqual(web.CATALOG['moves']['AQUA_TAIL']['buffs'], [0, -1])
            self.assertEqual(web.CATALOG['moves']['AQUA_TAIL']['buffTarget'], 'opponent')


if __name__ == '__main__':
    unittest.main()
