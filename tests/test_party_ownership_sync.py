import tempfile
import unittest
from pathlib import Path

import pvpoke_batch_v2 as engine
from pvpoke_app_catalog import enrich_catalog
from pvpoke_battle_store import BattleStore
from pvpoke_ownership import Ownership
from pvpoke_party_backend import owned_candidates_for_party
import pvpoke_missing_ui as missing_ui
import pvpoke_party_ui as party_ui


class PartyOwnershipSyncTests(unittest.TestCase):
    def setUp(self):
        _, _, species = engine.game_data()
        self.species = species
        self.catalog = {
            sid: {
                'name': p.get('speciesName'),
                'dex': p.get('dex'),
                'fastMoves': list(p.get('fastMoves', [])),
                'chargedMoves': engine.charged_move_pool(p),
                'extraChargedMoves': list(p.get('extraChargedMoves', [])),
                'tags': list(p.get('tags', [])),
            }
            for sid, p in species.items()
        }
        enrich_catalog(self.catalog, species)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'battle_analysis.sqlite3')
        self.ownership = Ownership(self.store, species_ids=self.species)

    def test_owned_candidates_for_party_filters_and_preserves_mega_fields(self):
        # 1. Empty store returns empty safely
        empty_res = owned_candidates_for_party(self.ownership, self.catalog)
        self.assertEqual(empty_res['items'], [])
        self.assertEqual(empty_res['ledger_revision'], 0)

        # 2. Confirmed owned normal species
        self.ownership.confirm(
            'ev-sync-1',
            'inst-sync-azu',
            expected_revision=0,
            state='confirmed_owned',
            observation={
                'species_id': 'azumarill',
                'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
                'current_cp': 1499,
                'current_level': 45.5,
                'current_moves': {'fast': 'BUBBLE', 'charged': ['ICE_BEAM', 'PLAY_ROUGH']},
            },
            register_if_missing=True,
        )

        # 3. Confirmed owned Mega species (sableye_mega) with mega_level=3
        self.ownership.confirm(
            'ev-sync-2',
            'inst-sync-sabmega',
            expected_revision=0,
            state='confirmed_owned',
            observation={
                'species_id': 'sableye_mega',
                'ivs': {'attack': 15, 'defense': 15, 'hp': 15},
                'current_cp': 1498,
                'current_level': 27.0,
                'current_moves': {'fast': 'SHADOW_CLAW', 'charged': ['FOUL_PLAY', 'POWER_GEM']},
                'mega_level': 3,
            },
            register_if_missing=True,
        )

        # 4. Confirmed absent species (must NOT be exported)
        self.ownership.confirm(
            'ev-sync-3a',
            'inst-sync-absent',
            expected_revision=0,
            state='confirmed_owned',
            observation={
                'species_id': 'skarmory',
                'ivs': {'attack': 0, 'defense': 15, 'hp': 14},
                'current_cp': 1500,
                'current_level': 27.5,
                'current_moves': {'fast': 'STEEL_WING', 'charged': ['BRAVE_BIRD', 'SKY_ATTACK']},
            },
            register_if_missing=True,
        )
        self.ownership.confirm(
            'ev-sync-3b',
            'inst-sync-absent',
            expected_revision=1,
            state='confirmed_absent',
        )

        res = owned_candidates_for_party(self.ownership, self.catalog)
        self.assertEqual(len(res['items']), 2)
        by_species = {item['species']: item for item in res['items']}
        self.assertIn('azumarill', by_species)
        self.assertIn('sableye_mega', by_species)
        self.assertNotIn('skarmory', by_species)

        azu = by_species['azumarill']
        self.assertEqual((azu['atk'], azu['def'], azu['hp']), (0, 15, 15))
        self.assertEqual(azu['level_override'], 45.5)
        self.assertEqual(azu['fast'], 'BUBBLE')
        self.assertNotIn('mega_level', azu)

        sab = by_species['sableye_mega']
        self.assertEqual((sab['atk'], sab['def'], sab['hp']), (15, 15, 15))
        self.assertEqual(sab['mega_level'], 3)
        self.assertEqual(sab['level_override'], 27.0)
        self.assertEqual(sab['fast'], 'SHADOW_CLAW')

    def test_ui_contains_handoff_and_load_owned_controls(self):
        self.assertIn('loadOwnedPool', party_ui.HTML)
        self.assertIn('pvpoke_party_handoff_v1', party_ui.HTML)
        self.assertIn('pvpoke_party_handoff_v1', missing_ui.HTML)
        self.assertIn('パーティ作成へ送る', missing_ui.HTML)


if __name__ == '__main__':
    unittest.main()
