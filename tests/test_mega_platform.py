"""Tests for Mega Evolution common foundation, explicit CP rules, ownership linking, and cache/history compatibility."""
from pathlib import Path
import tempfile
import unittest

from pvpoke_battle_store import BattleStore
from pvpoke_matchup_cache import cache_namespace
from pvpoke_mega import (
    MEGA_MOVE_BONUSES,
    base_species_id,
    can_mega_evolve,
    compute_cp,
    eligible_pre_evolutions,
    evaluate_owned_for_mega,
    is_mega_form,
    is_shadow_form,
    load_cpms,
    max_level_and_cp,
    mega_forms_for_base,
    resolve_battle_rules,
)
from pvpoke_ownership import Ownership
from pvpoke_selection_history import app_operation as selection_operation


class MegaPlatformTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'battle_analysis.sqlite3')
        self.swablu_stats = {'atk': 76, 'def': 132, 'hp': 128}
        self.altaria_stats = {'atk': 141, 'def': 201, 'hp': 181}
        self.altaria_mega_stats = {'atk': 222, 'def': 218, 'hp': 181}
        self.slowpoke_stats = {'atk': 109, 'def': 98, 'hp': 207}
        self.slowbro_stats = {'atk': 177, 'def': 180, 'hp': 216}
        self.slowbro_mega_stats = {'atk': 224, 'def': 259, 'hp': 216}
        self.catalog = {
            'swablu': {'baseStats': self.swablu_stats, 'family': {'id': 'FAMILY_SWABLU', 'evolutions': ['altaria']}},
            'swablu_shadow': {'baseStats': self.swablu_stats},
            'altaria': {'baseStats': self.altaria_stats, 'family': {'id': 'FAMILY_SWABLU', 'parent': 'swablu'}},
            'altaria_mega': {'baseStats': self.altaria_mega_stats},
            'altaria_shadow': {'baseStats': self.altaria_stats},
            'charmander': {'baseStats': {'atk': 116, 'def': 93, 'hp': 118}, 'family': {'id': 'FAMILY_CHARMANDER', 'evolutions': ['charmeleon']}},
            'charmeleon': {'baseStats': {'atk': 158, 'def': 126, 'hp': 151}, 'family': {'id': 'FAMILY_CHARMANDER', 'parent': 'charmander', 'evolutions': ['charizard']}},
            'charizard': {'baseStats': {'atk': 223, 'def': 173, 'hp': 186}, 'family': {'id': 'FAMILY_CHARMANDER', 'parent': 'charmeleon'}},
            'charizard_mega_x': {'baseStats': {'atk': 273, 'def': 213, 'hp': 186}},
            'charizard_mega_y': {'baseStats': {'atk': 319, 'def': 212, 'hp': 186}},
            'kyogre_primal': {'baseStats': {'atk': 353, 'def': 268, 'hp': 218}},
            'slowpoke': {'baseStats': self.slowpoke_stats, 'family': {'id': 'FAMILY_SLOWPOKE', 'evolutions': ['slowbro']}},
            'slowpoke_galarian': {'baseStats': self.slowpoke_stats, 'family': {'id': 'FAMILY_SLOWPOKE_GALARIAN', 'evolutions': ['slowbro_galarian']}},
            'slowbro': {'baseStats': self.slowbro_stats, 'family': {'id': 'FAMILY_SLOWPOKE', 'parent': 'slowpoke'}},
            'slowbro_galarian': {'baseStats': self.slowbro_stats, 'family': {'id': 'FAMILY_SLOWPOKE_GALARIAN', 'parent': 'slowpoke_galarian'}},
            'slowbro_mega': {'baseStats': self.slowbro_mega_stats},
        }
        self.cpms = load_cpms()

    def test_species_mapping_pre_evolutions_shadow_and_xy_distinction(self):
        self.assertTrue(is_mega_form('altaria_mega'))
        self.assertTrue(is_mega_form('charizard_mega_x'))
        self.assertTrue(is_mega_form('kyogre_primal'))
        self.assertFalse(is_mega_form('altaria'))
        self.assertFalse(is_mega_form('altaria_shadow'))

        self.assertEqual(base_species_id('altaria_mega'), 'altaria')
        self.assertEqual(base_species_id('charizard_mega_x'), 'charizard')
        self.assertEqual(base_species_id('charizard_mega_y'), 'charizard')
        self.assertEqual(base_species_id('kyogre_primal'), 'kyogre')

        self.assertTrue(is_shadow_form('altaria_shadow'))
        self.assertEqual(eligible_pre_evolutions('altaria_mega', self.catalog), ('altaria', 'swablu'))
        self.assertEqual(eligible_pre_evolutions('charizard_mega_x', self.catalog), ('charizard', 'charmeleon', 'charmander'))

        self.assertTrue(can_mega_evolve('altaria', 'altaria_mega', self.catalog))
        self.assertTrue(can_mega_evolve('swablu', 'altaria_mega', self.catalog))
        self.assertFalse(can_mega_evolve('altaria_shadow', 'altaria_mega', self.catalog))
        self.assertFalse(can_mega_evolve('swablu_shadow', 'altaria_mega', self.catalog))
        self.assertFalse(can_mega_evolve('charizard', 'altaria_mega', self.catalog))
        # Regional form isolation: Galarian Slowpoke cannot become Mega Slowbro.
        self.assertTrue(can_mega_evolve('slowpoke', 'slowbro_mega', self.catalog))
        self.assertFalse(can_mega_evolve('slowpoke_galarian', 'slowbro_mega', self.catalog))

        self.assertEqual(
            mega_forms_for_base('charmander', set(self.catalog), self.catalog),
            ['charizard_mega_x', 'charizard_mega_y'],
        )
        self.assertEqual(mega_forms_for_base('swablu_shadow', set(self.catalog), self.catalog), [])

    def test_cp1500_2500_boundaries_and_explicit_league_rules_no_cp_guessing(self):
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        gl_lvl, gl_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        ul_lvl, ul_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=2500, max_level=50.0, cpms=self.cpms)
        self.assertLessEqual(gl_cp, 1500)
        self.assertLessEqual(ul_cp, 2500)
        self.assertGreater(ul_lvl, gl_lvl)

        # Ultra League evaluation of a CP 1200 Altaria must NEVER be downgraded to GL 1500 rule!
        ul_target_lvl = ul_lvl
        cur_lvl = gl_lvl + 1.0  # ~Lv 20.5 -> base CP ~1200 (< 1500), STILL under UL cap!
        cur_cp_1200 = compute_cp(self.altaria_stats, ivs, cur_lvl, self.cpms)
        self.assertLess(cur_cp_1200, 1500)
        ul_eval = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': cur_lvl, 'current_cp': cur_cp_1200},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=ul_target_lvl,
            rules={'league': 'ultra', 'cp_cap': 2500, 'max_level': 50, 'cup_id': 'ultra_mega', 'allow_cp_downscaling': True},
            cpms=self.cpms,
        )
        self.assertTrue(ul_eval['eligible'])
        self.assertFalse(ul_eval['downscaled'])
        self.assertTrue(ul_eval['needs_power_up'])
        self.assertEqual(ul_eval['mega_theoretical']['cap_max_level'], ul_lvl)

        # Without explicit rules/cp_cap, never assume 1500 or downscaling.
        no_rule = resolve_battle_rules(None)
        self.assertIsNone(no_rule['cp_cap'])
        self.assertIsNone(no_rule['allow_cp_downscaling'])
        unverified_rule = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_cp': 1200},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            cpms=self.cpms,
        )
        self.assertIsNone(unverified_rule['eligible'])
        self.assertEqual(unverified_rule['reason'], 'cp_cap_rule_required')

    def test_three_cp_states_downscaling_powerup_unknown_pl_and_super_max(self):
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_lvl, mega_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        base_cp_at_cap = compute_cp(self.altaria_stats, ivs, mega_lvl, self.cpms)
        self.assertLess(base_cp_at_cap, 1500)

        # 1. Exact pre-Mega level & base equivalent CP under explicit GL rule.
        fit = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl, 'current_cp': base_cp_at_cap},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True},
            cpms=self.cpms,
        )
        self.assertTrue(fit['eligible'])
        self.assertFalse(fit['downscaled'])
        self.assertFalse(fit['needs_power_up'])
        self.assertEqual(fit['actual_owned']['cp'], base_cp_at_cap)
        self.assertEqual(fit['mega_theoretical']['target_cp'], mega_cp)
        self.assertEqual(fit['battle_effective']['cp'], mega_cp)
        self.assertTrue(fit['battle_effective']['matches_target'])

        # 2. Over-CP (e.g., GL normal Altaria Lv 27.5 CP ~1490) with explicit downscaling rule.
        high_lvl = 27.5
        high_cp = compute_cp(self.altaria_stats, ivs, high_lvl, self.cpms)
        over_cp = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': high_lvl, 'current_cp': high_cp},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True},
            cpms=self.cpms,
        )
        self.assertTrue(over_cp['eligible'])
        self.assertTrue(over_cp['downscaled'])
        self.assertFalse(over_cp['needs_power_up'])
        self.assertEqual(over_cp['reason'], 'ok_downscaled')
        self.assertEqual(over_cp['actual_owned']['cp'], high_cp)
        self.assertEqual(over_cp['battle_effective']['level'], mega_lvl)
        self.assertEqual(over_cp['battle_effective']['cp'], mega_cp)

        # Strict unscaled cup rejects over-CP individual.
        over_cp_strict = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': high_lvl, 'current_cp': high_cp},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'strict_unscaled', 'allow_cp_downscaling': False},
            cpms=self.cpms,
        )
        self.assertFalse(over_cp_strict['eligible'])
        self.assertEqual(over_cp_strict['reason'], 'level_exceeds_mega_cap')

        # Unspecified downscaling cup does NOT silently enable downscaling.
        over_cp_unspecified = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': high_lvl, 'current_cp': high_cp},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'all'},
            cpms=self.cpms,
        )
        self.assertIsNone(over_cp_unspecified['eligible'])
        self.assertEqual(over_cp_unspecified['reason'], 'downscaling_rule_unverified')

        # 3. Low PL needs power-up (no upscaling).
        under_cp = compute_cp(self.altaria_stats, ivs, mega_lvl - 2.0, self.cpms)
        under_lvl = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl - 2.0, 'current_cp': under_cp},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            allow_cp_downscaling=True,
            cpms=self.cpms,
        )
        self.assertTrue(under_lvl['eligible'])
        self.assertFalse(under_lvl['downscaled'])
        self.assertTrue(under_lvl['needs_power_up'])

        # 4. Unknown current_level with CP only -> cannot claim battle_effective matches_target.
        unknown_pl = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_cp': base_cp_at_cap},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            allow_cp_downscaling=True,
            cpms=self.cpms,
        )
        self.assertTrue(unknown_pl['eligible'])
        self.assertFalse(unknown_pl['battle_effective']['matches_target'])

        # 5. Super MAX (level 4): preserves move bonus multiplier, defers unconfirmed PL+2 CP shift.
        super_max_safe = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl, 'current_cp': base_cp_at_cap},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=mega_lvl,
            cp_cap=1500,
            allow_cp_downscaling=True,
            cpms=self.cpms,
            mega_level=4,
        )
        self.assertEqual(super_max_safe['mega_condition']['mega_level'], 4)
        self.assertEqual(super_max_safe['mega_condition']['move_bonus_multiplier'], MEGA_MOVE_BONUSES[3])
        self.assertFalse(super_max_safe['mega_condition']['super_max_cp_applied'])
        self.assertEqual(super_max_safe['mega_condition']['super_max_pl_hypothesis_status'], 'unconfirmed_deferred')
        self.assertEqual(super_max_safe['battle_effective']['cp'], mega_cp)

        # Speculative Super MAX hypothesis mode stays unconfirmed instead of guessing CP.
        super_max_spec = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl, 'current_cp': base_cp_at_cap},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            cp_cap=1500,
            cpms=self.cpms,
            mega_level=4,
            super_max_cp_mode='pl_plus_2_hyp1',
        )
        self.assertIsNone(super_max_spec['eligible'])
        self.assertEqual(super_max_spec['reason'], 'super_max_cp_unconfirmed')

    def test_ownership_build_match_safety_pre_evolutions_and_no_false_exact(self):
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_lvl, mega_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        base_cp = compute_cp(self.altaria_stats, ivs, mega_lvl, self.cpms)
        high_lvl = 27.5
        high_cp = compute_cp(self.altaria_stats, ivs, high_lvl, self.cpms)
        under_lvl = mega_lvl - 2.0
        under_cp = compute_cp(self.altaria_stats, ivs, under_lvl, self.cpms)
        swablu_cp = compute_cp(self.swablu_stats, ivs, mega_lvl, self.cpms)
        moves = {'fast': 'DRAGON_BREATH', 'charged': ['SKY_ATTACK', 'MOONBLAST']}
        swablu_moves = {'fast': 'PECK', 'charged': ['DISARMING_VOICE']}

        inv = Ownership(self.store, species_ids=set(self.catalog))
        inv.register('altaria-fit', {
            'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl,
            'current_cp': base_cp, 'current_moves': moves,
        })
        inv.confirm('c1', 'altaria-fit', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-over', {
            'species_id': 'altaria', 'ivs': ivs, 'current_level': high_lvl,
            'current_cp': high_cp, 'current_moves': moves,
        })
        inv.confirm('c2', 'altaria-over', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-cp-only', {
            'species_id': 'altaria', 'ivs': ivs, 'current_cp': base_cp, 'current_moves': moves,
        })
        inv.confirm('c3', 'altaria-cp-only', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-under', {
            'species_id': 'altaria', 'ivs': ivs, 'current_level': under_lvl,
            'current_cp': under_cp, 'current_moves': moves,
        })
        inv.confirm('c4', 'altaria-under', expected_revision=0, state='confirmed_owned')

        inv.register('swablu-fit', {
            'species_id': 'swablu', 'ivs': ivs, 'current_level': mega_lvl,
            'current_cp': swablu_cp, 'current_moves': swablu_moves,
        })
        inv.confirm('c5', 'swablu-fit', expected_revision=0, state='confirmed_owned')

        inv.register('altaria-shadow', {
            'species_id': 'altaria_shadow', 'ivs': ivs, 'current_level': mega_lvl,
            'current_cp': base_cp, 'current_moves': moves,
        })
        inv.confirm('c6', 'altaria-shadow', expected_revision=0, state='confirmed_owned')

        combatant = {
            'species_id': 'altaria_mega',
            'ivs': ivs,
            'level': mega_lvl,
            'moves': moves,
        }
        gl_mega_rules = {'league': 'great', 'cp_cap': 1500, 'max_level': 50, 'cup_id': 'great_mega', 'allow_cp_downscaling': True}
        with self.store._reader() as db:
            matches = inv._matches(
                db, combatant, mega_cp, species_catalog=self.catalog, cpms=self.cpms, rules=gl_mega_rules,
            )
            no_rule_matches = inv._matches(
                db, combatant, None, species_catalog=self.catalog, cpms=self.cpms, rules=None,
            )

        by_id = {m['instance_id']: m for m in matches}
        self.assertEqual(
            set(by_id),
            {'altaria-fit', 'altaria-over', 'altaria-cp-only', 'altaria-under', 'swablu-fit'},
        )
        # Only verified pre-Mega level + base CP + moves is 'exact'.
        self.assertEqual(by_id['altaria-fit']['build_match'], 'exact')
        self.assertFalse(by_id['altaria-fit'].get('mega_downscaled', False))
        # Downscaled individual is eligible & downscaled, yet build_match stays 'unverified' (never 'exact').
        self.assertTrue(by_id['altaria-over']['eligible'])
        self.assertTrue(by_id['altaria-over']['mega_downscaled'])
        self.assertEqual(by_id['altaria-over']['build_match'], 'unverified')
        # Unknown PL (CP only) is NEVER 'exact'.
        self.assertEqual(by_id['altaria-cp-only']['build_match'], 'unverified')
        # Under-leveled needs power-up.
        self.assertTrue(by_id['altaria-under']['needs_power_up'])
        self.assertEqual(by_id['altaria-under']['build_match'], 'different')
        # Pre-evolution Swablu is linked with needs_evolution=True and stays 'unverified'.
        self.assertTrue(by_id['swablu-fit']['needs_evolution'])
        self.assertEqual(by_id['swablu-fit']['build_match'], 'unverified')

        # Without rules and with cp=None: must not crash and must not claim 'exact'.
        by_id_no_rule = {m['instance_id']: m for m in no_rule_matches}
        self.assertEqual(by_id_no_rule['altaria-fit']['build_match'], 'unverified')
        self.assertTrue(by_id_no_rule['altaria-fit'].get('mega_rule_unverified'))

    def test_cache_namespace_separation_and_selection_history_compatibility(self):
        # Legacy cache_namespace signature output stays identical when Mega fields are defaulted.
        legacy = cache_namespace(gamemaster_hash='g', pokemonjs_hash='p', cp_cap=1500, max_level=50, engine_hash='e')
        m3_scaled = cache_namespace(
            gamemaster_hash='g', pokemonjs_hash='p', cp_cap=1500, max_level=50, engine_hash='e',
            mega_level=3, downscaling_mode='half_level', super_max_mode='none', cup_id='great_mega',
        )
        m4_unconfirmed = cache_namespace(
            gamemaster_hash='g', pokemonjs_hash='p', cp_cap=1500, max_level=50, engine_hash='e',
            mega_level=4, downscaling_mode='half_level', super_max_mode='unconfirmed', cup_id='great_mega',
        )
        ul_scaled = cache_namespace(
            gamemaster_hash='g', pokemonjs_hash='p', cp_cap=2500, max_level=50, engine_hash='e',
            mega_level=3, downscaling_mode='half_level', super_max_mode='none', cup_id='ultra_mega',
        )
        self.assertEqual(len({legacy, m3_scaled, m4_unconfirmed, ul_scaled}), 4)

        # Existing non-Mega selection snapshot stays intact when saving Mega selection snapshot.
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_lvl, _ = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        inv = Ownership(self.store, species_ids=set(self.catalog))
        inv.register('altaria-fit', {'species_id': 'altaria', 'ivs': ivs, 'current_level': mega_lvl})
        inv.confirm('c1', 'altaria-fit', expected_revision=0, state='confirmed_owned')

        selection_operation(self.store, {
            'action': 'selection_save',
            'request_id': 'normal-save-1',
            'species_id': 'altaria',
            'meta_sha256': 'a' * 64,
            'calculation_version': 'b' * 64,
            'policy_version': 'box-first-v3',
            'candidates': [{
                'ivs': '0/14/15',
                'role': 'important',
                'instance_id': 'altaria-fit',
                'goal': 'Normal GL',
                'moves': ['DRAGON_BREATH', 'SKY_ATTACK', 'MOONBLAST'],
                'evidence': ['Normal GL top rank'],
            }],
        }, species_ids=set(self.catalog))
        selection_operation(self.store, {
            'action': 'selection_save',
            'request_id': 'mega-save-1',
            'species_id': 'altaria_mega',
            'meta_sha256': 'c' * 64,
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

        normal_latest = selection_operation(self.store, {'action': 'selection_latest', 'species_id': 'altaria'}, species_ids=set(self.catalog))
        mega_latest = selection_operation(self.store, {'action': 'selection_latest', 'species_id': 'altaria_mega'}, species_ids=set(self.catalog))
        self.assertEqual(normal_latest['snapshot']['species_id'], 'altaria')
        self.assertEqual(normal_latest['snapshot']['candidates'][0]['goal'], 'Normal GL')
        self.assertEqual(mega_latest['snapshot']['species_id'], 'altaria_mega')
        self.assertEqual(mega_latest['snapshot']['candidates'][0]['instance_id'], 'altaria-fit')

    def test_gl_mega_70_or_rule_and_low_score_protection(self):
        from pvpoke_mega import evaluate_gl_mega_score_70_or
        from pvpoke_score_search import search_low_scores

        # Normal GL >= 70 keeps even if Mega GL < 70.
        v1 = evaluate_gl_mega_score_70_or(normal_gl_overall=75.0, mega_gl_overall=62.0)
        self.assertTrue(v1['keep'])
        self.assertEqual(v1['matched_leagues'], ['normal_gl'])

        # Mega GL >= 70 keeps even if Normal GL < 70.
        v2 = evaluate_gl_mega_score_70_or(normal_gl_overall=58.0, mega_gl_overall=81.5)
        self.assertTrue(v2['keep'])
        self.assertEqual(v2['matched_leagues'], ['mega_gl'])

        # Both verified < 70 -> exclude.
        v3 = evaluate_gl_mega_score_70_or(normal_gl_overall=58.0, mega_gl_overall=64.9)
        self.assertFalse(v3['keep'])
        self.assertTrue(v3['verified'])
        self.assertEqual(v3['reason'], 'below_threshold')

        # Unverified Mega GL ranking fails closed (never auto-drops).
        v4 = evaluate_gl_mega_score_70_or(normal_gl_overall=58.0, mega_gl_overall=None, has_mega_form=True)
        self.assertTrue(v4['keep'])
        self.assertFalse(v4['verified'])
        self.assertEqual(v4['reason'], 'ranking_unverified')

        # All-species mode never excludes by 70-point threshold.
        v5 = evaluate_gl_mega_score_70_or(normal_gl_overall=20.0, mega_gl_overall=25.0, all_species_mode=True)
        self.assertTrue(v5['keep'])
        self.assertEqual(v5['reason'], 'all_species_mode')

        # Integration with search_low_scores: without mega_scores, status is 'unverified'.
        baseline = search_low_scores({'mode': 'overall'})
        self.assertEqual(baseline['mega_gl_ranking_status'], 'unverified')
        sample_low = baseline['selected_preview'][0]['name']

        # With mega_scores >= 70 for sample_low, it is protected from low-score cleanup.
        protected = search_low_scores({'mode': 'overall'}, mega_scores={sample_low: {'overall': 74.2}})
        self.assertEqual(protected['mega_gl_ranking_status'], 'verified')
        self.assertEqual(protected['mega_gl_preserved_count'], 1)
        self.assertEqual(protected['selected_count'], baseline['selected_count'] - 1)
        self.assertEqual(protected['mega_gl_preserved'][0]['name'], sample_low)

    def test_web_ui_renders_minimal_mega_pl_evolution_and_super_max_badges(self):
        import json
        import re
        import subprocess
        from pvpoke_app_ui import HTML as APP_HTML
        from pvpoke_missing_ui import HTML as MISSING_HTML

        missing_match = re.search(
            r'function megaStatusBadges\(record,targetLevel,megaCondition\)\{.*?^\}',
            MISSING_HTML,
            re.S | re.M,
        )
        app_match = re.search(
            r'function megaStatusNotes\(row,result\)\{.*?^\}',
            APP_HTML,
            re.S | re.M,
        )
        self.assertIsNotNone(missing_match)
        self.assertIsNotNone(app_match)

        script = f"""
{missing_match.group(0)}
{app_match.group(0)}
const missingBadges = megaStatusBadges(
  {{needs_evolution: true, needs_power_up: true, mega_downscaled: true}},
  27.5,
  {{super_max_pl_hypothesis_status: 'unconfirmed_deferred'}}
).map(([label]) => label);
const appNotes = megaStatusNotes(
  {{needs_evolution: true, needs_power_up: true, level: 27.5, mega_downscaled: true}},
  {{mega_condition: {{super_max_pl_hypothesis_status: 'unconfirmed_deferred'}}}}
);
console.log(JSON.stringify({{missingBadges, appNotes}}));
"""
        proc = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True, timeout=10)
        parsed = json.loads(proc.stdout)
        expected = [
            '要進化',
            'PL27.5まで強化が必要',
            '一時ダウンスケーリング可（未証明）',
            'スーパー MAX PL+2 仮説保留',
        ]
        self.assertEqual(parsed['missingBadges'], expected)
        self.assertEqual(parsed['appNotes'], expected)

    def test_battle_service_and_matrix_mega_level_and_extra_charged_move(self):
        import json
        import shutil
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_ownership import build_id

        fixtures = Path(__file__).resolve().parent / 'fixtures'
        gm_data = json.loads((fixtures / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        rows = json.loads((fixtures / 'strategy_rows.json').read_text(encoding='utf-8'))
        opponent_row = rows[0]

        # Synthetic Mega Pokémon with 35-energy Mega extra move (higher priority than high-cost charged moves).
        gm_data['moves'].append({
            'moveId': 'MEGA_BLAST_PLUS',
            'name': 'Mega Blast+',
            'type': 'dragon',
            'power': 80,
            'energy': 35,
            'energyGain': 0,
            'cooldown': 500,
            'turns': 1,
            'isMegaMove': True,
        })
        gm_data['moves'].append({
            'moveId': 'MEGA_HEAVY',
            'name': 'Mega Heavy',
            'type': 'normal',
            'power': 110,
            'energy': 90,
            'energyGain': 0,
            'cooldown': 500,
            'turns': 1,
        })
        gm_data['moves'].append({
            'moveId': 'MEGA_HEAVY_ALT',
            'name': 'Mega Heavy Alt',
            'type': 'normal',
            'power': 120,
            'energy': 95,
            'energyGain': 0,
            'cooldown': 500,
            'turns': 1,
        })
        mega_ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_lvl, _ = max_level_and_cp(self.altaria_mega_stats, mega_ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        gm_data['pokemon'].append({
            'speciesId': 'altaria_mega',
            'speciesName': 'Altaria (Mega)',
            'dex': 334,
            'types': ['dragon', 'fairy'],
            'baseStats': self.altaria_mega_stats,
            'fastMoves': ['DRAGON_BREATH'],
            'chargedMoves': ['MEGA_HEAVY', 'MEGA_HEAVY_ALT'],
            'extraChargedMoves': ['MEGA_BLAST_PLUS'],
            'tags': ['mega'],
        })
        master = self.root / 'gamemaster.json'
        master.write_text(json.dumps(gm_data), encoding='utf-8')
        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)

        def make_spec(mega_level=None, charged=None):
            c0 = {
                'species_id': 'altaria_mega',
                'ivs': mega_ivs,
                'level': mega_lvl,
                'moves': {'fast': 'DRAGON_BREATH', 'charged': charged or ['MEGA_HEAVY', 'MEGA_HEAVY_ALT', 'MEGA_BLAST_PLUS']},
                'initial': {'hp': 'full', 'energy': 40, 'shields': 0, 'stages': [0, 0]},
            }
            if mega_level is not None:
                c0['mega_level'] = mega_level
            return {
                'schema': 'battle-spec-v1',
                'mode': 'standard',
                'rules': {'league': 'great', 'cp_cap': 1500},
                'combatants': [
                    c0,
                    {
                        'species_id': opponent_row['species'],
                        'ivs': {'attack': opponent_row['atk'], 'defense': opponent_row['def'], 'hp': opponent_row['hp']},
                        'level': opponent_row['level'],
                        'moves': {'fast': opponent_row['fast'], 'charged': [opponent_row['charged1'], opponent_row['charged2']]},
                        'initial': {'hp': 'full', 'energy': 0, 'shields': 0, 'stages': [0, 0]},
                    },
                ],
            }

        results_by_level = {}
        for ml in (1, 2, 3, 4):
            res = service.simulate(make_spec(mega_level=ml))
            self.assertEqual(res['status'], 'complete', res.get('error'))
            self.assertEqual(res['spec']['combatants'][0]['mega_level'], ml)
            extra_hits = [
                ev['damage'] for ev in res['executed_moves']
                if ev['actor'] == 0 and ev['kind'] == 'charged' and ev['move_id'] == 'MEGA_BLAST_PLUS'
            ]
            self.assertTrue(extra_hits, f'Expected MEGA_BLAST_PLUS execution at mega_level={ml}')
            results_by_level[ml] = (res['battle_key'], extra_hits[0])

        # All 4 mega levels produce distinct BattleStore keys and DamageCalculator scales isMegaMove damage.
        self.assertEqual(len({k for k, _ in results_by_level.values()}), 4)
        self.assertGreater(results_by_level[4][1], results_by_level[1][1])

        # Default mega_level normalizes to 3 (matching explicit mega_level=3 battle_key).
        default_res = service.simulate(make_spec(mega_level=None))
        self.assertEqual(default_res['status'], 'complete')
        self.assertEqual(default_res['spec']['combatants'][0]['mega_level'], 3)
        self.assertEqual(default_res['battle_key'], results_by_level[3][0])

        # Build IDs stay distinct across mega_level 1..4 while keeping non-Mega build_ids unchanged.
        b1 = build_id(make_spec(mega_level=1)['combatants'][0])
        b4 = build_id(make_spec(mega_level=4)['combatants'][0])
        self.assertNotEqual(b1, b4)

        # Reject invalid mega_level / 3rd charged move on non-Mega or unauthorized extra move.
        non_mega_invalid_ml = make_spec()
        non_mega_invalid_ml['combatants'][0] = {
            **non_mega_invalid_ml['combatants'][1],
            'mega_level': 2,
        }
        self.assertEqual(service.simulate(non_mega_invalid_ml)['status'], 'invalid')

        non_mega_invalid_c3 = make_spec()
        non_mega_invalid_c3['combatants'][0] = {
            **non_mega_invalid_c3['combatants'][1],
            'moves': {
                'fast': opponent_row['fast'],
                'charged': [opponent_row['charged1'], opponent_row['charged2'], 'MEGA_BLAST_PLUS'],
            },
        }
        self.assertEqual(service.simulate(non_mega_invalid_c3)['status'], 'invalid')

        bad_c3 = make_spec(charged=['MEGA_HEAVY', 'MEGA_HEAVY_ALT', 'MEGA_HEAVY'])
        self.assertEqual(service.simulate(bad_c3)['status'], 'invalid')

    def test_matchup_cache_separates_mega_level_and_charged3(self):
        from pvpoke_matchup_cache import MatchupCache, _prepared

        base_row = {
            'species': 'altaria_mega',
            'fast': 'DRAGON_BREATH',
            'charged1': 'MEGA_HEAVY',
            'charged2': 'MEGA_HEAVY_ALT',
            'atk': 0,
            'def': 14,
            'hp': 15,
            'level': 19.5,
            'cp': 1498,
        }
        opp_row = {
            'species': 'azumarill',
            'fast': 'BUBBLE',
            'charged1': 'ICE_BEAM',
            'charged2': 'PLAY_ROUGH',
            'atk': 0,
            'def': 15,
            'hp': 15,
            'level': 45.5,
            'cp': 1499,
        }
        # Legacy 10-element _prepared list preserved when charged3 & mega_level are absent.
        self.assertEqual(len(_prepared(base_row)), 10)

        ns = cache_namespace(gamemaster_hash='g', pokemonjs_hash='p', cp_cap=1500, max_level=50)
        with MatchupCache(self.root / 'matchups.sqlite3', ns) as cache:
            m1 = {**base_row, 'charged3': 'MEGA_BLAST_PLUS', 'mega_level': 1}
            m4 = {**base_row, 'charged3': 'MEGA_BLAST_PLUS', 'mega_level': 4}
            m4_alt = {**base_row, 'charged3': 'OTHER_PLUS', 'mega_level': 4}
            k1 = cache._key(m1, opp_row, [1, 1])
            k4 = cache._key(m4, opp_row, [1, 1])
            k4_alt = cache._key(m4_alt, opp_row, [1, 1])
            self.assertEqual(len({k1, k4, k4_alt}), 3)

            cache.store_matrix([m1], [opp_row], [1, 1], [
                ['Pokemon', 'Azumarill', 'Wins', 'Losses', 'Draws', 'Avg'],
                ['Altaria (Mega) 0/14/15', '510', '1', '0', '0', '510'],
            ])
            cache.store_matrix([m4], [opp_row], [1, 1], [
                ['Pokemon', 'Azumarill', 'Wins', 'Losses', 'Draws', 'Avg'],
                ['Altaria (Mega) 0/14/15', '620', '1', '0', '0', '620'],
            ])
            self.assertEqual(cache.lookup([m1], [opp_row], [1, 1])[(0, 0)][2], '510')
            self.assertEqual(cache.lookup([m4], [opp_row], [1, 1])[(0, 0)][2], '620')
            self.assertEqual(cache.lookup([m4_alt], [opp_row], [1, 1]), {})


if __name__ == '__main__':
    unittest.main()
