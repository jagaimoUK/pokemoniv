import tempfile
import unittest
from pathlib import Path

import pvpoke_batch_v2 as engine
from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_missing_comparison import app_operation
import pvpoke_missing_ui as missing_ui
from pvpoke_ownership import Ownership


class MegaMissingAndInventoryTests(unittest.TestCase):
    def setUp(self):
        engine.game_data()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3')
        client = DirectMatrixClient(gamemaster=engine.DATA / 'gamemaster.json', log_dir=self.root)
        self.addCleanup(client.close)
        self.service = BattleService(client, store=self.store)
        self.ownership = Ownership(self.store, species_ids=self.service.species)

    def test_ownership_records_and_updates_mega_level_with_backward_compat(self):
        # Legacy observation without mega_level omits mega_level key
        legacy = self.ownership.confirm(
            'ev-legacy-1',
            'inst-legacy-1',
            expected_revision=0,
            state='confirmed_owned',
            observation={
                'species_id': 'quagsire',
                'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
                'current_cp': 1495,
                'current_level': 28.0,
                'current_moves': {'fast': 'MUD_SHOT', 'charged': ['AQUA_TAIL', 'STONE_EDGE']},
            },
            register_if_missing=True,
        )
        self.assertNotIn('mega_level', legacy['instance'])

        # Observation with mega_level=2 on base species beedrill
        ev1 = self.ownership.confirm(
            'ev-mega-1',
            'inst-mega-1',
            expected_revision=0,
            state='confirmed_owned',
            observation={
                'species_id': 'beedrill',
                'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                'current_cp': 1134,
                'current_level': 16.5,
                'current_moves': {'fast': 'BUG_BITE', 'charged': ['AERIAL_ACE', 'SLUDGE_BOMB']},
                'mega_level': 2,
            },
            register_if_missing=True,
        )
        self.assertEqual(ev1['instance']['mega_level'], 2)

        # Update mega_level to 4 (Super MAX)
        ev2 = self.ownership.confirm(
            'ev-mega-2',
            'inst-mega-1',
            expected_revision=1,
            state='confirmed_owned',
            observation={
                'species_id': 'beedrill',
                'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                'current_cp': 1134,
                'current_level': 16.5,
                'mega_level': 4,
            },
            preserve_identity=True,
        )
        self.assertEqual(ev2['instance']['mega_level'], 4)

        # Invalid mega_level is rejected
        for bad in (0, 5, '3', 2.5):
            with self.assertRaises(ValueError):
                self.ownership._observation({
                    'species_id': 'beedrill',
                    'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                    'mega_level': bad,
                })

    def test_match_rows_evaluates_mega_level_shortfall_and_charged3_compat(self):
        _, base_row = self.service._combatant({
            'species_id': 'beedrill',
            'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
            'level': 16.5,
            'moves': {'fast': 'BUG_BITE', 'charged': ['AERIAL_ACE', 'SLUDGE_BOMB']},
            'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
        })
        base_cp = base_row['cp']
        # Register base beedrill at exact GL CP/level/2-moves with mega_level=2
        self.ownership.confirm(
            'ev-bee-1',
            'inst-bee-1',
            expected_revision=0,
            state='confirmed_owned',
            observation={
                'species_id': 'beedrill',
                'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                'current_cp': base_cp,
                'current_level': 16.5,
                'current_moves': {'fast': 'BUG_BITE', 'charged': ['AERIAL_ACE', 'SLUDGE_BOMB']},
                'mega_level': 2,
            },
            register_if_missing=True,
        )
        # Evaluate against beedrill_mega with mega_level=3 and charged3
        res_need_lv = app_operation(self.service, {
            'action': 'evaluate',
            'candidates': [{
                'species_id': 'beedrill_mega',
                'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                'level': 16.5,
                'moves': {'fast': 'BUG_BITE', 'charged': ['AERIAL_ACE', 'SLUDGE_BOMB']},
                'mega_level': 3,
                'charged3': 'FELL_STINGER_PLUS',
            }],
            'scenarios': [{
                'opponent': {
                    'species_id': 'quagsire',
                    'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
                    'level': 28.0,
                    'moves': {'fast': 'MUD_SHOT', 'charged': ['AQUA_TAIL', 'STONE_EDGE']},
                },
                'shields': [1, 1],
                'requirement': {'outcomes': ['self_win']},
            }],
            'role': {'role_id': 'closer', 'revision': 1, 'priority': 1},
        })
        cand = res_need_lv['candidates'][0]
        self.assertEqual(cand['mega_level'], 3)
        self.assertEqual(len(cand['owned_instances']), 1)
        match = cand['owned_instances'][0]
        self.assertEqual(match['mega_level'], 2)
        self.assertTrue(match.get('needs_mega_level'))
        self.assertEqual(match['build_match'], 'unverified')

        # Upgrade owned mega_level to 3 -> exact match even when candidate has charged3
        app_operation(self.service, {
            'action': 'ownership',
            'instance_id': 'inst-bee-1',
            'event_id': 'ev-bee-2',
            'expected_revision': 1,
            'state': 'confirmed_owned',
            'register': False,
            'observation': {
                'species_id': 'beedrill',
                'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                'current_cp': base_cp,
                'current_level': 16.5,
                'mega_level': 3,
            },
        })
        res_ok = app_operation(self.service, {
            'action': 'evaluate',
            'candidates': [{
                'species_id': 'beedrill_mega',
                'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                'level': 16.5,
                'moves': {'fast': 'BUG_BITE', 'charged': ['AERIAL_ACE', 'SLUDGE_BOMB']},
                'mega_level': 3,
                'charged3': 'FELL_STINGER_PLUS',
            }],
            'scenarios': [{
                'opponent': {
                    'species_id': 'quagsire',
                    'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
                    'level': 28.0,
                    'moves': {'fast': 'MUD_SHOT', 'charged': ['AQUA_TAIL', 'STONE_EDGE']},
                },
                'shields': [1, 1],
                'requirement': {'outcomes': ['self_win']},
            }],
            'role': {'role_id': 'closer', 'revision': 1, 'priority': 1},
        })
        match_ok = res_ok['candidates'][0]['owned_instances'][0]
        self.assertEqual(match_ok['mega_level'], 3)
        self.assertFalse(match_ok.get('needs_mega_level', False))
        self.assertEqual(match_ok['build_match'], 'exact')

        # Check ownership_list exposes mega_level
        listed = app_operation(self.service, {'action': 'ownership_list'})
        self.assertEqual(listed['items'][0]['mega_level'], 3)

    def test_missing_ui_contains_mega_level_and_charged3_controls(self):
        html = missing_ui.HTML
        for token in (
            'メガレベル（メガ個体時）',
            '3枠目ゲージ技（メガ時）',
            'スーパーMAX (Lv4)',
            '現在のメガレベル（任意）',
            '手持ち メガLv',
            '目標メガLv不足',
        ):
            self.assertIn(token, html)


if __name__ == '__main__':
    unittest.main()
