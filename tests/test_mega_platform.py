"""Tests for the common Mega Evolution foundation, CP1500 linking, and selection persistence."""
from pathlib import Path
import tempfile
import unittest

from pvpoke_battle_store import BattleStore
from pvpoke_mega import (
    base_species_id,
    can_mega_evolve,
    compute_cp,
    evaluate_owned_for_mega,
    is_mega_form,
    is_shadow_form,
    load_cpms,
    max_level_and_cp,
    mega_forms_for_base,
)
from pvpoke_ownership import Ownership
from pvpoke_selection_history import app_operation as selection_operation


class MegaPlatformTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'battle_analysis.sqlite3')
        self.altaria_stats = {'atk': 141, 'def': 201, 'hp': 181}
        self.altaria_mega_stats = {'atk': 222, 'def': 218, 'hp': 181}
        self.catalog = {
            'altaria': {'baseStats': self.altaria_stats},
            'altaria_mega': {'baseStats': self.altaria_mega_stats},
            'altaria_shadow': {'baseStats': self.altaria_stats},
            'charizard': {'baseStats': {'atk': 223, 'def': 173, 'hp': 186}},
            'charizard_mega_x': {'baseStats': {'atk': 273, 'def': 213, 'hp': 186}},
            'charizard_mega_y': {'baseStats': {'atk': 319, 'def': 212, 'hp': 186}},
            'kyogre_primal': {'baseStats': {'atk': 353, 'def': 268, 'hp': 218}},
        }
        self.cpms = load_cpms()

    def test_species_mapping_and_shadow_exclusion(self):
        self.assertTrue(is_mega_form('altaria_mega'))
        self.assertTrue(is_mega_form('charizard_mega_x'))
        self.assertTrue(is_mega_form('kyogre_primal'))
        self.assertFalse(is_mega_form('altaria'))
        self.assertFalse(is_mega_form('altaria_shadow'))

        self.assertEqual(base_species_id('altaria_mega'), 'altaria')
        self.assertEqual(base_species_id('charizard_mega_x'), 'charizard')
        self.assertEqual(base_species_id('charizard_mega_y'), 'charizard')
        self.assertEqual(base_species_id('kyogre_primal'), 'kyogre')
        self.assertEqual(base_species_id('altaria'), 'altaria')

        self.assertTrue(is_shadow_form('altaria_shadow'))
        self.assertTrue(can_mega_evolve('altaria', 'altaria_mega'))
        self.assertFalse(can_mega_evolve('altaria_shadow', 'altaria_mega'))
        self.assertFalse(can_mega_evolve('charizard', 'altaria_mega'))

        self.assertEqual(
            mega_forms_for_base('charizard', set(self.catalog)),
            ['charizard_mega_x', 'charizard_mega_y'],
        )
        self.assertEqual(mega_forms_for_base('altaria_shadow', set(self.catalog)), [])

    def test_gl_cp_cap_evaluation_for_pre_mega_individual(self):
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_cap = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        self.assertIsNotNone(mega_cap)
        mega_lvl, mega_cp = mega_cap
        self.assertLessEqual(mega_cp, 1500)
        base_cp_at_cap = compute_cp(self.altaria_stats, ivs, mega_lvl, self.cpms)
        self.assertLess(base_cp_at_cap, 1500)

        # An Altaria kept at base_cp_at_cap fits GL directly without downscaling.
        fit = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl, 'current_cp': base_cp_at_cap},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            cpms=self.cpms,
        )
        self.assertTrue(fit['eligible'])
        self.assertFalse(fit['downscaled'])
        self.assertFalse(fit['needs_power_up'])
        self.assertEqual(fit['reason'], 'ok')
        self.assertEqual(fit['mega_cp'], mega_cp)

        # Live GBL Mega rule: an over-CP / over-level Altaria (e.g. CP 1490) IS eligible via temporary half-level downscaling.
        over_cp = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_cp': 1490},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            cpms=self.cpms,
        )
        self.assertTrue(over_cp['eligible'])
        self.assertTrue(over_cp['downscaled'])
        self.assertFalse(over_cp['needs_power_up'])
        self.assertEqual(over_cp['reason'], 'ok_downscaled')
        self.assertEqual(over_cp['mega_cp'], mega_cp)

        # Strict non-scaled mode rejects over-CP individuals when requested.
        over_cp_strict = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_cp': 1490},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            cpms=self.cpms,
            allow_cp_downscaling=False,
        )
        self.assertFalse(over_cp_strict['eligible'])
        self.assertEqual(over_cp_strict['reason'], 'cp_exceeds_mega_cap')

        # Under-leveled individual is not upscaled in battle and still needs power-up.
        under_lvl = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl - 2.0, 'current_cp': 700},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            cpms=self.cpms,
        )
        self.assertTrue(under_lvl['eligible'])
        self.assertFalse(under_lvl['downscaled'])
        self.assertTrue(under_lvl['needs_power_up'])

        # Shadow Altaria can never Mega Evolve.
        shadow = evaluate_owned_for_mega(
            {'species_id': 'altaria_shadow', 'ivs': ivs, 'current_cp': 900},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            cpms=self.cpms,
        )
        self.assertFalse(shadow['eligible'])
        self.assertEqual(shadow['reason'], 'incompatible_species')

    def test_ownership_links_pre_mega_individual_and_selection_saves_mega_form(self):
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_lvl, mega_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        base_cp = compute_cp(self.altaria_stats, ivs, mega_lvl, self.cpms)
        moves = {'fast': 'DRAGON_BREATH', 'charged': ['SKY_ATTACK', 'MOONBLAST']}

        inv = Ownership(self.store, species_ids=set(self.catalog))
        inv.register('altaria-fit', {
            'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl,
            'current_cp': base_cp, 'current_moves': moves,
        })
        inv.confirm('c1', 'altaria-fit', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-over', {
            'species_id': 'altaria', 'ivs': ivs, 'current_cp': 1495, 'current_moves': moves,
        })
        inv.confirm('c2', 'altaria-over', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-under', {
            'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl - 2.0,
            'current_cp': 700, 'current_moves': moves,
        })
        inv.confirm('c3', 'altaria-under', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-shadow', {
            'species_id': 'altaria_shadow', 'ivs': ivs, 'current_level': mega_lvl,
            'current_cp': base_cp, 'current_moves': moves,
        })
        inv.confirm('c4', 'altaria-shadow', expected_revision=0, state='confirmed_owned')

        combatant = {
            'species_id': 'altaria_mega',
            'ivs': ivs,
            'level': mega_lvl,
            'moves': moves,
        }
        with self.store._reader() as db:
            matches = inv._matches(db, combatant, mega_cp, species_catalog=self.catalog, cpms=self.cpms)

        by_id = {m['instance_id']: m for m in matches}
        self.assertEqual(set(by_id), {'altaria-fit', 'altaria-over', 'altaria-under'})  # Shadow excluded
        self.assertEqual(by_id['altaria-fit']['build_match'], 'exact')
        self.assertFalse(by_id['altaria-fit'].get('mega_downscaled', False))
        self.assertEqual(by_id['altaria-fit']['base_species_id'], 'altaria')
        self.assertEqual(by_id['altaria-over']['build_match'], 'exact')
        self.assertTrue(by_id['altaria-over'].get('mega_downscaled'))
        self.assertEqual(by_id['altaria-under']['build_match'], 'different')
        self.assertTrue(by_id['altaria-under'].get('needs_power_up'))

        # Selection history now permits saving Mega forms linked to the pre-Mega confirmed individual.
        saved = selection_operation(self.store, {
            'action': 'selection_save',
            'request_id': 'mega-save-1',
            'species_id': 'altaria_mega',
            'meta_sha256': 'a' * 64,
            'calculation_version': 'b' * 64,
            'policy_version': 'box-first-v3',
            'candidates': [{
                'ivs': '0/14/15',
                'role': 'important',
                'instance_id': 'altaria-fit',
                'goal': f'PL {mega_lvl} (Mega GL)',
                'moves': ['DRAGON_BREATH', 'SKY_ATTACK', 'MOONBLAST'],
                'evidence': ['Mega GL cap fit'],
            }],
        }, species_ids=set(self.catalog))
        self.assertGreater(saved['revision'], 0)
        latest = selection_operation(self.store, {
            'action': 'selection_latest',
            'species_id': 'altaria_mega',
        }, species_ids=set(self.catalog))
        self.assertEqual(latest['snapshot']['candidates'][0]['instance_id'], 'altaria-fit')


if __name__ == '__main__':
    unittest.main()
