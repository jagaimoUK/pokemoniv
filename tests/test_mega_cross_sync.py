"""Cross-app schema and consistency verification tests for Mega Evolution between Web and Android."""
from pathlib import Path
import tempfile
import unittest

from pvpoke_battle_store import BattleStore
from pvpoke_individual_sync import (
    IndividualConnections,
    IndividualUnavailable,
    app_operation,
    validate_mega_sync_individual,
    validate_overlay_export_item,
)
from pvpoke_ownership import Ownership


class MegaCrossSyncSchemaTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'battle-analysis.sqlite3')
        self.inventory = Ownership(self.store, species_ids={'sableye', 'sableye_mega', 'swablu', 'altaria_mega'})

    def test_mega_individual_sync_schema_and_attributes(self):
        # Register a confirmed owned base sableye with mega attributes
        obs = {
            'species_id': 'sableye',
            'current_cp': 1490,
            'current_level': 41.5,
            'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
            'mega_level': 3,
        }
        self.inventory.register('sab-01', obs)
        self.inventory.confirm('ev-01', 'sab-01', expected_revision=0, state='confirmed_owned')

        read_res = app_operation(self.store, {'action': 'individual_get', 'instance_id': 'sab-01'})
        ind = read_res['individual']
        self.assertEqual(ind['instance_id'], 'sab-01')
        self.assertEqual(ind['species_id'], 'sableye')
        self.assertEqual(ind['mega_level'], 3)
        self.assertEqual(ind['current_level'], 41.5)
        self.assertEqual(ind['ivs'], {'attack': 0, 'defense': 15, 'hp': 15})
        self.assertTrue(validate_mega_sync_individual(ind))

        # Check field patch with nickname and memo
        patch_res = app_operation(self.store, {
            'action': 'individual_patch',
            'instance_id': 'sab-01',
            'request_id': 'req-sync-1',
            'changes': {
                'nickname': {'revision': 0, 'value': 'MegaSab90'},
                'memo': {'revision': 0, 'value': 'Mega Level 3, target PL50 (achievement 90.4%)'},
            },
        })
        self.assertEqual(patch_res['outcomes'], {'nickname': 'applied', 'memo': 'applied'})
        self.assertEqual(patch_res['fields']['nickname']['value'], 'MegaSab90')
        self.assertEqual(patch_res['fields']['memo']['value'], 'Mega Level 3, target PL50 (achievement 90.4%)')
        self.assertEqual(patch_res['individual']['mega_level'], 3)

    def test_mega_sync_validation_rejects_invalid_values(self):
        # Invalid mega level (> 4)
        bad_ind_1 = {
            'instance_id': 'sab-02',
            'species_id': 'sableye',
            'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
            'mega_level': 5,
        }
        with self.assertRaises(ValueError):
            validate_mega_sync_individual(bad_ind_1)

        # Invalid mega level (< 1)
        bad_ind_2 = {
            'instance_id': 'sab-02',
            'species_id': 'sableye',
            'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
            'mega_level': 0,
        }
        with self.assertRaises(ValueError):
            validate_mega_sync_individual(bad_ind_2)

        # Invalid target level (> 55.0)
        bad_ind_3 = {
            'instance_id': 'sab-02',
            'species_id': 'sableye',
            'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
            'target_level': 56.0,
        }
        with self.assertRaises(ValueError):
            validate_mega_sync_individual(bad_ind_3)

        # Invalid super max hypothesis status
        bad_ind_4 = {
            'instance_id': 'sab-02',
            'species_id': 'sableye',
            'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
            'super_max_pl_hypothesis_status': 'unknown_arbitrary_status',
        }
        with self.assertRaises(ValueError):
            validate_mega_sync_individual(bad_ind_4)

        # Valid mega individual with all fields
        valid_ind = {
            'instance_id': 'sab-02',
            'species_id': 'sableye',
            'current_cp': 1490,
            'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
            'mega_level': 3,
            'charged3': 'FOUL_PLAY',
            'target_level': 50.0,
            'super_max_pl_hypothesis_status': 'unconfirmed_deferred',
        }
        self.assertTrue(validate_mega_sync_individual(valid_ind))

    def test_overlay_export_item_validation(self):
        valid_overlay_item = {
            'search': '302&cp1490',
            'nickname': 'MegaSab',
            'ivs': '0/15/15',
            'cp': 1490,
            'species': 'sableye',
            'target_species': 'sableye_mega',
            'target_name': 'ヤミラミ(メガ)',
            'mega_level': 3,
            'charged3': 'FOUL_PLAY',
            'super_max_pl_hypothesis_status': 'unconfirmed_deferred',
            'needs_evolution': True,
            'needs_power_up': True,
        }
        self.assertTrue(validate_overlay_export_item(valid_overlay_item))

        # Invalid mega_level in overlay item
        bad_overlay = dict(valid_overlay_item)
        bad_overlay['mega_level'] = 99
        with self.assertRaises(ValueError):
            validate_overlay_export_item(bad_overlay)

        # Invalid super_max status
        bad_overlay2 = dict(valid_overlay_item)
        bad_overlay2['super_max_pl_hypothesis_status'] = 'invalid_state'
        with self.assertRaises(ValueError):
            validate_overlay_export_item(bad_overlay2)
