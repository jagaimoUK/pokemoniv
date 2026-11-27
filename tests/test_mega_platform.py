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

    def test_battle_service_supports_gl_ul_mega_rules_and_rejects_mismatched_leagues(self):
        import json
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient

        fixtures = Path(__file__).resolve().parent / 'fixtures'
        gm_data = json.loads((fixtures / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        rows = json.loads((fixtures / 'strategy_rows.json').read_text(encoding='utf-8'))
        opponent_row = rows[0]

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
        mega_ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        gl_lvl, _ = max_level_and_cp(self.altaria_mega_stats, mega_ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        ul_lvl, ul_cp = max_level_and_cp(self.altaria_mega_stats, mega_ivs, cp_cap=2500, max_level=50.0, cpms=self.cpms)
        self.assertGreater(ul_cp, 1500)
        self.assertLessEqual(ul_cp, 2500)

        gm_data['pokemon'].append({
            'speciesId': 'altaria_mega',
            'speciesName': 'Altaria (Mega)',
            'dex': 334,
            'types': ['dragon', 'fairy'],
            'baseStats': self.altaria_mega_stats,
            'fastMoves': ['DRAGON_BREATH'],
            'chargedMoves': ['DRAGON_PULSE', 'MOONBLAST'],
            'extraChargedMoves': ['MEGA_BLAST_PLUS'],
            'tags': ['mega'],
        })
        master = self.root / 'gamemaster.json'
        master.write_text(json.dumps(gm_data), encoding='utf-8')
        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)

        def make_spec(rules, level):
            return {
                'schema': 'battle-spec-v1',
                'mode': 'standard',
                'rules': rules,
                'combatants': [
                    {
                        'species_id': 'altaria_mega',
                        'ivs': mega_ivs,
                        'level': level,
                        'mega_level': 4,
                        'moves': {'fast': 'DRAGON_BREATH', 'charged': ['DRAGON_PULSE', 'MOONBLAST', 'MEGA_BLAST_PLUS']},
                        'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
                    },
                    {
                        'species_id': opponent_row['species'],
                        'ivs': {'attack': opponent_row['atk'], 'defense': opponent_row['def'], 'hp': opponent_row['hp']},
                        'level': opponent_row['level'],
                        'moves': {'fast': opponent_row['fast'], 'charged': [opponent_row['charged1'], opponent_row['charged2']]},
                        'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
                    },
                ],
            }

        gl_mega = service.simulate(make_spec({'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega'}, gl_lvl))
        self.assertEqual(gl_mega['status'], 'complete', gl_mega.get('error'))
        self.assertTrue(gl_mega['spec']['rules']['allow_cp_downscaling'])

        gl_strict = service.simulate(make_spec({'league': 'great', 'cp_cap': 1500, 'cup_id': 'strict_unscaled', 'allow_cp_downscaling': False}, gl_lvl))
        self.assertEqual(gl_strict['status'], 'complete', gl_strict.get('error'))
        self.assertFalse(gl_strict['spec']['rules']['allow_cp_downscaling'])
        self.assertNotEqual(gl_mega['battle_key'], gl_strict['battle_key'])

        ul_mega = service.simulate(make_spec({'league': 'ultra', 'cp_cap': 2500, 'cup_id': 'ultra_mega'}, ul_lvl))
        self.assertEqual(ul_mega['status'], 'complete', ul_mega.get('error'))
        self.assertEqual(ul_mega['spec']['rules']['cp_cap'], 2500)
        self.assertTrue(ul_mega['spec']['rules']['allow_cp_downscaling'])

        # Mismatched league/cap or unknown cup must remain unsupported.
        self.assertEqual(service.simulate(make_spec({'league': 'ultra', 'cp_cap': 1500, 'cup_id': 'ultra_mega'}, gl_lvl))['status'], 'unsupported')
        self.assertEqual(service.simulate(make_spec({'league': 'great', 'cp_cap': 2500, 'cup_id': 'great_mega'}, gl_lvl))['status'], 'unsupported')
        self.assertEqual(service.simulate(make_spec({'league': 'great', 'cp_cap': 1500, 'cup_id': 'some_cup'}, gl_lvl))['status'], 'unsupported')

    def test_app_ui_mega_level_and_extra_charged_move_controls(self):
        import json
        import re
        import subprocess
        from pvpoke_app_ui import HTML as APP_HTML

        # Verify HTML controls exist.
        for control_id in ('id="megaMoveSettings"', 'id="megaLevel"', 'id="charged3Wrap"', 'id="charged3"'):
            self.assertIn(control_id, APP_HTML)

        script_body = re.search(r"<script>\s*(.*)\s*</script>", APP_HTML, re.S).group(1)
        # Extract only the pure option / fillMoveFields / moves / currentCandidate helpers to test in Node.
        js_harness = """
const assert = require('node:assert/strict');
const elements = {};
function makeEl(id, hidden = false) {
  return {
    id, hidden, value: '', options: [],
    replaceChildren() { this.options = []; this.value = ''; },
    append(o) { this.options.push(o); if (!this.value) this.value = o.value; },
  };
}
['species', 'fast', 'charged1', 'charged2', 'megaMoveSettings', 'megaLevel', 'charged3Wrap', 'charged3'].forEach(id => {
  elements[id] = makeEl(id, id === 'megaMoveSettings' || id === 'charged3Wrap');
});
elements.megaLevel.options = [{value:'1'},{value:'2'},{value:'3'},{value:'4'}];
elements.megaLevel.value = '3';
const el = id => elements[id];
const document = { createElement: () => ({ value: '', textContent: '' }) };
let catalog = {
  quagsire: { fastMoves: ['MUD_SHOT'], chargedMoves: ['AQUA_TAIL', 'STONE_EDGE'] },
  altaria_mega: { fastMoves: ['DRAGON_BREATH'], chargedMoves: ['DRAGON_PULSE', 'MOONBLAST'], tags: ['mega'], extraChargedMoves: [] },
  clefable_mega: { fastMoves: ['FAIRY_WIND'], chargedMoves: ['MOONBLAST', 'METEOR_MASH'], tags: ['mega', 'supermega'], extraChargedMoves: ['MOONBLAST_PLUS'] },
};
"""
        m_opts = re.search(r"function option\(select,values,selected,label=v=>v\)\{.*?\n\}", script_body, re.S)
        m_fill = re.search(r"function fillMoveFields\(sid,row,\[fast,charged1,charged2\],label\)\{.*?\n\}", script_body, re.S)
        m_moves = re.search(r"function moves\(row=\{\},sid=el\('species'\)\.value\)\{.*?\n\}", script_body, re.S)
        m_curr = re.search(r"function currentCandidate\(\)\{.*?\n\}", script_body, re.S)
        self.assertTrue(all((m_opts, m_fill, m_moves, m_curr)))

        test_script = js_harness + "\n".join(m.group(0) for m in (m_opts, m_fill, m_moves, m_curr)) + """
// 1. Non-Mega species hides Mega controls and omits mega_level / charged3.
elements.species.value = 'quagsire';
moves();
assert.equal(elements.megaMoveSettings.hidden, true);
assert.equal(elements.charged3Wrap.hidden, true);
const cNormal = currentCandidate();
assert.equal('mega_level' in cNormal, false);
assert.equal('charged3' in cNormal, false);

// 2. Mega species without extraChargedMoves shows megaLevel (default 3) and hides charged3.
elements.species.value = 'altaria_mega';
moves();
assert.equal(elements.megaMoveSettings.hidden, false);
assert.equal(elements.megaLevel.value, '3');
assert.equal(elements.charged3Wrap.hidden, true);
elements.megaLevel.value = '2';
assert.deepEqual(currentCandidate(), {
  species: 'altaria_mega', fast: 'DRAGON_BREATH', charged1: 'DRAGON_PULSE', charged2: 'MOONBLAST', mega_level: 2
});

// 3. SuperMega species with extraChargedMoves defaults megaLevel=4 and allows selecting charged3.
elements.species.value = 'clefable_mega';
moves({ charged3: 'MOONBLAST_PLUS' });
assert.equal(elements.megaMoveSettings.hidden, false);
assert.equal(elements.megaLevel.value, '4');
assert.equal(elements.charged3Wrap.hidden, false);
assert.deepEqual(currentCandidate(), {
  species: 'clefable_mega', fast: 'FAIRY_WIND', charged1: 'MOONBLAST', charged2: 'METEOR_MASH',
  mega_level: 4, charged3: 'MOONBLAST_PLUS'
});
console.log('APP_UI_MEGA_CONTROLS_OK');
"""
        proc = subprocess.run(['node', '-e', test_script], capture_output=True, text=True, check=True, timeout=10)
        self.assertIn('APP_UI_MEGA_CONTROLS_OK', proc.stdout)

    def test_real_pvpoke_ranking_70_or_and_form_mapping(self):
        from pvpoke_mega import load_gl_ranking_snapshot, resolve_gl_mega_ranking_70_or

        source_date, rows = load_gl_ranking_snapshot()
        self.assertEqual(source_date, '2026-10-15')
        self.assertGreater(len(rows), 1000)

        low_entry = next(r for r in rows if r['overall'] < 65 and '(' not in r['name'])
        synth_catalog = {
            'altaria': {'dex': 334, 'tags': []},
            'altaria_mega': {'dex': 334, 'tags': ['mega']},
            'azumarill': {'dex': 184, 'tags': []},
            'sableye': {'dex': 302, 'tags': []},
            'sableye_shadow': {'dex': 302, 'tags': ['shadow']},
            'sableye_mega': {'dex': 302, 'tags': ['mega']},
            'low_mon': {'dex': low_entry['dex'], 'name_ja': low_entry['name'], 'tags': []},
            'low_mon_mega': {'dex': low_entry['dex'], 'name_ja': low_entry['name'] + ' (メガ)', 'tags': ['mega']},
        }

        # 1. Real Normal GL >= 70 keeps Mega target even when Mega GL snapshot is not loaded.
        alt = resolve_gl_mega_ranking_70_or('altaria_mega', species_catalog=synth_catalog)
        self.assertTrue(alt['keep'])
        self.assertTrue(alt['verified'])
        self.assertEqual(alt['matched_leagues'], ['normal_gl'])
        self.assertEqual(alt['normal_gl_matched_name'], 'チルタリス')
        self.assertGreaterEqual(alt['normal_gl_overall'], 70.0)
        self.assertEqual(alt['normal_gl_source_date'], '2026-10-15')
        self.assertEqual(alt['mega_gl_status'], 'unverified')

        # 2. Shadow species cannot Mega Evolve -> has_mega_form=False and matches Shadow row.
        sab_sh = resolve_gl_mega_ranking_70_or('sableye_shadow', species_catalog=synth_catalog)
        self.assertFalse(sab_sh['has_mega_form'])
        self.assertEqual(sab_sh['mega_gl_status'], 'not_applicable')
        self.assertEqual(sab_sh['normal_gl_matched_name'], 'ヤミラミ (シャドウ)')
        self.assertTrue(sab_sh['keep'])

        # 3. Normal GL < 70 with Mega form and unverified Mega GL fails closed (never auto-drops).
        low_unverified = resolve_gl_mega_ranking_70_or('low_mon_mega', species_catalog=synth_catalog)
        self.assertLess(low_unverified['normal_gl_overall'], 70.0)
        self.assertTrue(low_unverified['keep'])
        self.assertFalse(low_unverified['verified'])
        self.assertEqual(low_unverified['reason'], 'ranking_unverified')

        # 4. Normal GL < 70 but Mega GL >= 70 keeps via OR rule.
        low_mega_pass = resolve_gl_mega_ranking_70_or(
            'low_mon_mega', species_catalog=synth_catalog, mega_scores={'low_mon_mega': {'overall': 74.5}}
        )
        self.assertTrue(low_mega_pass['keep'])
        self.assertTrue(low_mega_pass['verified'])
        self.assertEqual(low_mega_pass['matched_leagues'], ['mega_gl'])

        # 5. Both Normal GL < 70 and verified Mega GL < 70 -> below_threshold.
        low_both_fail = resolve_gl_mega_ranking_70_or(
            'low_mon_mega', species_catalog=synth_catalog, mega_scores={'low_mon_mega': {'overall': 61.2}}
        )
        self.assertFalse(low_both_fail['keep'])
        self.assertTrue(low_both_fail['verified'])
        self.assertEqual(low_both_fail['reason'], 'below_threshold')

    def test_power_up_candy_xl_boundaries_and_missing_analysis_integration(self):
        import json
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_mega import compute_power_up_cost
        from pvpoke_missing_analysis import MissingAnalysis
        from pvpoke_ownership import Ownership

        # Exact Pokémon GO Lv 39.5->40.0 vs Lv 40.0->40.5 XL Candy boundary.
        pre_xl = compute_power_up_cost(39.5, 40.0)
        self.assertEqual((pre_xl['stardust'], pre_xl['candy'], pre_xl['candy_xl'], pre_xl['uses_xl_candy']),
                         (10000, 15, 0, False))
        first_xl = compute_power_up_cost(40.0, 40.5)
        self.assertEqual((first_xl['stardust'], first_xl['candy'], first_xl['candy_xl'], first_xl['uses_xl_candy']),
                         (10000, 0, 10, True))

        # Exact cumulative Lv 1->40, Lv 40->50, Lv 1->50, Shadow/Purified/Lucky modifiers.
        to_40 = compute_power_up_cost(1.0, 40.0)
        self.assertEqual((to_40['stardust'], to_40['candy'], to_40['candy_xl']), (270000, 304, 0))
        xl_full = compute_power_up_cost(40.0, 50.0)
        self.assertEqual((xl_full['stardust'], xl_full['candy'], xl_full['candy_xl']), (250000, 0, 296))
        full = compute_power_up_cost(1.0, 50.0)
        self.assertEqual((full['stardust'], full['candy'], full['candy_xl']), (520000, 304, 296))
        self.assertEqual(compute_power_up_cost(40.0, 50.0, shadow=True)['candy_xl'], 360)
        self.assertEqual(compute_power_up_cost(40.0, 50.0, purified=True)['candy_xl'], 272)
        self.assertEqual(compute_power_up_cost(40.0, 50.0, lucky=True)['stardust'], 125000)

        # Unknown current level stays unverified without guessing cost; Super MAX PL+2 remains deferred.
        unknown_lvl = compute_power_up_cost(None, 45.0, mega_level=4)
        self.assertFalse(unknown_lvl['cost_verified'])
        self.assertIsNone(unknown_lvl['stardust'])
        self.assertTrue(unknown_lvl['uses_xl_candy'])
        self.assertEqual(unknown_lvl['super_max_pl_hypothesis_status'], 'unconfirmed_deferred')
        self.assertIn('仮説保留', unknown_lvl['super_max_pl_note'])

        capped = compute_power_up_cost(49.5, 51.0, mega_level=4)
        self.assertTrue(capped['target_level_capped_at_50'])
        self.assertEqual((capped['stardust'], capped['candy_xl']), (15000, 20))

        # Integration with MissingAnalysis.evidence: Mega candidate + owned pre-evo Swablu at Lv 20.
        fixtures = Path(__file__).resolve().parent / 'fixtures'
        gm_data = json.loads((fixtures / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        rows = json.loads((fixtures / 'strategy_rows.json').read_text(encoding='utf-8'))
        opp = rows[0]
        shared_fast = opp['fast']
        shared_charged = [opp['charged1'], opp['charged2']]
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        mega_lvl, _ = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        swablu_cp = compute_cp(self.catalog['swablu']['baseStats'], ivs, 10.0, self.cpms)
        gm_data['pokemon'].extend([
            {
                'speciesId': 'swablu', 'speciesName': 'Swablu', 'dex': 333,
                'types': ['normal', 'flying'],
                'baseStats': self.catalog['swablu']['baseStats'],
                'fastMoves': [shared_fast], 'chargedMoves': shared_charged,
                'family': {'evolutions': ['altaria']},
            },
            {
                'speciesId': 'altaria', 'speciesName': 'Altaria', 'dex': 334,
                'types': ['dragon', 'flying'],
                'baseStats': self.altaria_stats,
                'fastMoves': [shared_fast], 'chargedMoves': shared_charged,
                'family': {'parent': 'swablu', 'evolutions': ['altaria_mega']},
            },
            {
                'speciesId': 'altaria_mega', 'speciesName': 'Altaria (Mega)', 'dex': 334,
                'types': ['dragon', 'fairy'],
                'baseStats': self.altaria_mega_stats,
                'fastMoves': [shared_fast], 'chargedMoves': shared_charged,
                'tags': ['mega', 'supermega'], 'family': {'parent': 'altaria'},
            },
        ])
        gm_path = self.root / 'gm_missing_mega.json'
        gm_path.write_text(json.dumps(gm_data), encoding='utf-8')
        client = DirectMatrixClient(gamemaster=gm_path, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)

        inv = Ownership(self.store, species_ids=set(service.species))
        inv.register('swablu-10', {
            'species_id': 'swablu', 'ivs': ivs, 'current_level': 10.0,
            'current_cp': swablu_cp, 'current_moves': {'fast': shared_fast, 'charged': shared_charged},
        })
        inv.confirm('c-sw', 'swablu-10', expected_revision=0, state='confirmed_owned')

        spec = {
            'schema': 'battle-spec-v1',
            'mode': 'standard',
            'rules': {'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True},
            'combatants': [
                {
                    'species_id': 'altaria_mega', 'ivs': ivs, 'level': mega_lvl,
                    'moves': {'fast': shared_fast, 'charged': shared_charged},
                    'mega_level': 4,
                    'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
                },
                {
                    'species_id': opp['species'],
                    'ivs': {'attack': opp['atk'], 'defense': opp['def'], 'hp': opp['hp']},
                    'level': opp['level'],
                    'moves': {'fast': opp['fast'], 'charged': [opp['charged1'], opp['charged2']]},
                    'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
                },
            ],
        }
        analysis = MissingAnalysis(self.store)
        aid = analysis.save_plan(service, [spec])
        ev = analysis.evidence(aid, active_versions=service.versions, normalizer=service)
        cell = ev['cells'][0]
        self.assertEqual(cell['gl_mega_ranking']['normal_gl_matched_name'], 'チルタリス')
        self.assertTrue(cell['gl_mega_ranking']['keep'])
        self.assertEqual(cell['training_goal']['current_level'], 10.0)
        self.assertEqual(cell['training_goal']['target_level'], mega_lvl)
        self.assertTrue(cell['training_goal']['needs_evolution'])
        self.assertTrue(cell['training_goal']['needs_power_up'])
        expected_cost = compute_power_up_cost(10.0, mega_lvl, mega_level=4)
        self.assertGreater(expected_cost['stardust'], 0)
        self.assertGreater(expected_cost['candy'], 0)
        self.assertEqual(cell['training_goal']['stardust'], expected_cost['stardust'])
        self.assertEqual(cell['training_goal']['candy'], expected_cost['candy'])
        self.assertEqual(cell['training_goal']['candy_xl'], expected_cost['candy_xl'])
        self.assertEqual(cell['training_goal']['super_max_pl_hypothesis_status'], 'unconfirmed_deferred')
        self.assertEqual(cell['inventory_matches'][0]['training_goal']['stardust'], expected_cost['stardust'])

    def test_missing_ui_renders_70_or_and_training_goal_lines(self):
        import re
        import subprocess
        from pvpoke_missing_ui import HTML as MISSING_HTML

        fn_match = re.search(
            r'function ranking70OrInfo\(ranking\)\{.*?function trainingGoalLines\(goal\)\{.*?^\}',
            MISSING_HTML,
            re.S | re.M,
        )
        self.assertIsNotNone(fn_match)
        script = f"""
const assert = require('node:assert/strict');
{fn_match.group(0)}
const rPass = ranking70OrInfo({{
  reason: 'meets_threshold_or', matched_leagues: ['normal_gl'],
  normal_gl_overall: 93.0, has_mega_form: true, mega_gl_overall: null,
  normal_gl_source_date: '2026-10-15',
}});
assert.equal(rPass.label, '70点OR適合（通常GL）');
assert.equal(rPass.tone, 'good');
assert.ok(rPass.detail.includes('通常GL 93.0点'));
assert.ok(rPass.detail.includes('メガGL 未取得（保留）'));

const rWait = ranking70OrInfo({{
  reason: 'ranking_unverified', matched_leagues: [],
  normal_gl_overall: 58.0, has_mega_form: true, mega_gl_overall: null,
}});
assert.equal(rWait.label, 'ランキング未確定（自動除外保留）');
assert.equal(rWait.tone, 'wait');

const gCost = trainingGoalLines({{
  target_level: 45.0, current_level: 40.0, current_cp: 1200,
  needs_evolution: true, downscaled: false, cost_verified: true,
  power_ups: 10, stardust: 112000, candy: 0, candy_xl: 118,
  super_max_pl_hypothesis_status: 'unconfirmed_deferred',
  super_max_pl_note: 'スーパー MAX PL+2 仮説保留（仮補正なし）',
}});
assert.ok(gCost[0].includes('目標 PL45') && gCost[0].includes('要進化'));
assert.ok(gCost[1].includes('10回強化') && gCost[1].includes('アメXL 118'));
assert.equal(gCost[2], 'スーパー MAX PL+2 仮説保留（仮補正なし）');

const gUnk = trainingGoalLines({{
  target_level: 45.0, current_level: null, cost_verified: false, uses_xl_candy: true,
}});
assert.ok(gUnk[1].includes('現在PL未確認のため未確定') && gUnk[1].includes('アメXL'));
console.log('MISSING_UI_RANKING_GOAL_OK');
"""
        proc = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True, timeout=10)
        self.assertIn('MISSING_UI_RANKING_GOAL_OK', proc.stdout)

    def test_q1_preevo_mega_e2e_and_form_distinction(self):
        import json
        import shutil
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_mega import (
            can_evolve_to,
            discover_reachable_forms,
            pre_evolutions_for_target,
        )
        from pvpoke_missing_analysis import MissingAnalysis
        from pvpoke_missing_comparison import app_operation as missing_operation
        from test_battle_service import FIXTURES

        # 1. Reachability graph must discover normal evolutions & Mega without fabricating paths.
        reach_swablu = discover_reachable_forms('swablu', self.catalog, evaluated_species_id='altaria_mega')
        self.assertEqual(reach_swablu['owned_species_id'], 'swablu')
        self.assertEqual(reach_swablu['evaluated_species_id'], 'altaria_mega')
        self.assertTrue(reach_swablu['form_distinct'])
        self.assertEqual(reach_swablu['evolutions'], ['altaria'])
        self.assertEqual(reach_swablu['mega_forms'], ['altaria_mega'])
        self.assertEqual(reach_swablu['pre_evolutions'], ['altaria', 'swablu'])

        self.assertTrue(can_evolve_to('swablu', 'altaria', self.catalog))
        self.assertTrue(can_evolve_to('swablu', 'altaria_mega', self.catalog))
        self.assertFalse(can_evolve_to('slowpoke_galarian', 'slowbro_mega', self.catalog))
        self.assertEqual(pre_evolutions_for_target('altaria', self.catalog), ('swablu',))
        # Shadow isolation: Shadow forms never evolve into Mega.
        shadow_cat = {
            **self.catalog,
            'swablu_shadow': {'baseStats': self.swablu_stats, 'family': {'id': 'FAMILY_SWABLU', 'evolutions': ['altaria_shadow']}},
            'altaria_shadow': {'baseStats': self.altaria_stats, 'family': {'id': 'FAMILY_SWABLU', 'parent': 'swablu_shadow'}},
        }
        self.assertEqual(discover_reachable_forms('swablu_shadow', shadow_cat)['mega_forms'], [])
        self.assertFalse(can_evolve_to('swablu_shadow', 'altaria_mega', shadow_cat))

        # 2. E2E across fixture gamemaster -> Ownership -> MissingAnalysis -> MissingComparison -> SelectionHistory.
        master = self.root / 'gm_q1.json'
        gm = json.loads((FIXTURES / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        opp_row = json.loads((FIXTURES / 'strategy_rows.json').read_text(encoding='utf-8'))[0]
        shared_fast = opp_row['fast']
        shared_charged = [opp_row['charged1'], opp_row['charged2']]
        gm['pokemon'].extend([
            {
                'speciesId': 'swablu',
                'speciesName': 'Swablu',
                'dex': 333,
                'types': ['normal', 'flying'],
                'baseStats': dict(self.swablu_stats),
                'fastMoves': [shared_fast],
                'chargedMoves': shared_charged,
                'family': {'id': 'FAMILY_SWABLU', 'evolutions': ['altaria']},
            },
            {
                'speciesId': 'altaria',
                'speciesName': 'Altaria',
                'dex': 334,
                'types': ['dragon', 'flying'],
                'baseStats': dict(self.altaria_stats),
                'fastMoves': [shared_fast],
                'chargedMoves': shared_charged,
                'family': {'id': 'FAMILY_SWABLU', 'parent': 'swablu'},
            },
            {
                'speciesId': 'altaria_mega',
                'speciesName': 'Altaria (Mega)',
                'dex': 334,
                'types': ['dragon', 'fairy'],
                'baseStats': dict(self.altaria_mega_stats),
                'fastMoves': [shared_fast],
                'chargedMoves': shared_charged,
                'extraChargedMoves': shared_charged[:1],
                'tags': ['mega'],
            },
        ])
        master.write_text(json.dumps(gm), encoding='utf-8')

        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}

        inv = Ownership(self.store, species_ids=service.species)
        inv.register('swablu-owned', {
            'species_id': 'swablu', 'ivs': ivs, 'current_level': 12.0,
            'current_cp': 260, 'current_moves': {'fast': shared_fast, 'charged': shared_charged},
        })
        inv.confirm('q1-own', 'swablu-owned', expected_revision=0, state='confirmed_owned')

        # Normal evolution target (altaria) also discovers owned swablu while distinguishing forms.
        norm_spec = {
            'schema': 'battle-spec-v1',
            'mode': 'standard',
            'rules': {'league': 'great', 'cp_cap': 1500},
            'combatants': [
                {'species_id': 'altaria', 'ivs': ivs, 'level': 27.0,
                 'moves': {'fast': shared_fast, 'charged': shared_charged},
                 'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]}},
                {'species_id': opp_row['species'], 'ivs': {'attack': opp_row['atk'], 'defense': opp_row['def'], 'hp': opp_row['hp']},
                 'level': opp_row['level'], 'moves': {'fast': opp_row['fast'], 'charged': [opp_row['charged1'], opp_row['charged2']]},
                 'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]}},
            ],
        }
        analysis = MissingAnalysis(self.store)
        norm_plan = analysis.save_plan(service, [norm_spec])
        norm_ev = analysis.evidence(norm_plan, active_versions=service.versions, normalizer=service)
        norm_match = norm_ev['cells'][0]['inventory_matches'][0]
        self.assertEqual(norm_match['owned_species_id'], 'swablu')
        self.assertEqual(norm_match['evaluated_species_id'], 'altaria')
        self.assertTrue(norm_match['form_distinct'])
        self.assertTrue(norm_match['needs_evolution'])
        self.assertEqual(norm_ev['cells'][0]['reachable_forms']['mega_forms'], ['altaria_mega'])

        # Missing comparison carrying owned_species_id='swablu' for evaluated target='altaria_mega'.
        mega_lvl, _ = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        comp = missing_operation(service, {
            'action': 'evaluate',
            'candidates': [{
                'species_id': 'altaria_mega',
                'owned_species_id': 'swablu',
                'ivs': ivs,
                'level': mega_lvl,
                'moves': {'fast': shared_fast, 'charged': shared_charged},
                'mega_level': 3,
            }],
            'scenarios': [{
                'opponent': {
                    'species_id': opp_row['species'],
                    'ivs': {'attack': opp_row['atk'], 'defense': opp_row['def'], 'hp': opp_row['hp']},
                    'level': opp_row['level'],
                    'moves': {'fast': opp_row['fast'], 'charged': [opp_row['charged1'], opp_row['charged2']]},
                },
                'shields': [1, 1],
                'requirement': {'outcomes': ['self_win']},
            }],
            'role': {'role_id': 'role-q1', 'revision': 1, 'priority': 1},
        })
        cand = comp['candidates'][0]
        self.assertEqual(cand['species_id'], 'altaria_mega')
        self.assertEqual(cand['owned_species_id'], 'swablu')
        self.assertTrue(cand['form_distinct'])
        self.assertEqual(cand['reachable_forms']['pre_evolutions'], ['altaria', 'swablu'])
        self.assertEqual(comp['evidence_state'], 'unknown')

        # Selection history saving Mega candidate with owned_species_id='swablu'.
        calc_ver = 'a' * 64
        meta_ver = 'b' * 64
        selection_operation(
            self.store,
            {
                'action': 'selection_save',
                'species_id': 'altaria_mega',
                'owned_species_id': 'swablu',
                'request_id': 'q1-save-1',
                'meta_sha256': meta_ver,
                'calculation_version': calc_ver,
                'policy_version': 'box-first-v3',
                'ranking_source_date': '2026-10-15',
                'candidates': [{
                    'ivs': '0/14/15',
                    'role': 'important',
                    'moves': [shared_fast, *shared_charged],
                    'evidence': ['Reachable from swablu'],
                    'instance_id': 'swablu-owned',
                    'owned_species_id': 'swablu',
                    'goal': 'Evolve to Altaria Mega',
                }],
            },
            set(service.species),
        )
        latest = selection_operation(
            self.store,
            {'action': 'selection_latest', 'species_id': 'altaria_mega'},
            set(service.species),
            species_catalog=service.species,
        )['snapshot']
        self.assertEqual(latest['owned_species_id'], 'swablu')
        self.assertTrue(latest['reachable_forms']['form_distinct'])
        self.assertEqual(latest['reachable_forms']['pre_evolutions'], ['altaria', 'swablu'])

    def test_q11_tv09_freshness_invalidation_and_conservative_pending(self):
        import shutil
        from pvpoke_battle_service import BattleService
        from pvpoke_direct_backend import DirectMatrixClient
        from pvpoke_mega import evaluate_selection_freshness
        from pvpoke_missing_analysis import MissingAnalysis
        from test_battle_service import FIXTURES, battle_spec

        # 1. All TV-09 axes match -> current & fresh.
        base_ctx = {
            'calculation_version': 'a' * 64,
            'ranking_source_date': '2026-10-15',
            'meta_sha256': 'b' * 64,
            'policy_version': 'box-first-v3',
            'rules_digest': 'c' * 64,
        }
        ok = evaluate_selection_freshness(dict(base_ctx), dict(base_ctx))
        self.assertTrue(ok['fresh'])
        self.assertFalse(ok['needs_reevaluation'])
        self.assertEqual(ok['status'], 'current')

        # 2. Changes across each axis mark needs_reevaluation=True conservatively.
        for key, new_val, expected_reason in (
            ('calculation_version', 'f' * 64, 'calculation_version_changed'),
            ('ranking_source_date', '2026-11-01', 'ranking_changed'),
            ('meta_sha256', 'e' * 64, 'meta_changed'),
            ('policy_version', 'box-first-v4', 'policy_version_changed'),
            ('rules_digest', 'd' * 64, 'rules_changed'),
        ):
            with self.subTest(axis=key):
                res = evaluate_selection_freshness(dict(base_ctx), {**base_ctx, key: new_val})
                self.assertFalse(res['fresh'])
                self.assertTrue(res['needs_reevaluation'])
                self.assertEqual(res['status'], 'reevaluation_pending')
                self.assertIn(expected_reason, res['reasons'])
                self.assertTrue(res['old_result_preserved'])

        # 3. Missing / unprovable impact conservatively marks reevaluation_pending.
        unprovable = evaluate_selection_freshness(
            {'calculation_version': 'a' * 64},
            {**base_ctx, 'impact_provable': False},
        )
        self.assertTrue(unprovable['needs_reevaluation'])
        self.assertIn('ranking_unverified', unprovable['reasons'])
        self.assertIn('impact_not_provable', unprovable['reasons'])

        # 4. Selection history preserves old snapshots read-only while flagging staleness.
        species = {'quagsire'}
        selection_operation(
            self.store,
            {
                'action': 'selection_save',
                'species_id': 'quagsire',
                'request_id': 'tv09-save-1',
                'meta_sha256': base_ctx['meta_sha256'],
                'calculation_version': base_ctx['calculation_version'],
                'policy_version': base_ctx['policy_version'],
                'ranking_source_date': base_ctx['ranking_source_date'],
                'rules_digest': base_ctx['rules_digest'],
                'candidates': [{
                    'ivs': '0/11/12', 'role': 'important',
                    'moves': ['MUD_SHOT', 'STONE_EDGE', 'MUD_BOMB'],
                    'evidence': ['Old snapshot evidence'],
                }],
            },
            species,
        )
        stale_latest = selection_operation(
            self.store,
            {'action': 'selection_latest', 'species_id': 'quagsire'},
            species,
            current_context={**base_ctx, 'ranking_source_date': '2026-11-15'},
        )['snapshot']
        self.assertTrue(stale_latest['needs_reevaluation'])
        self.assertEqual(stale_latest['freshness']['status'], 'reevaluation_pending')
        self.assertIn('ranking_changed', stale_latest['freshness']['reasons'])
        self.assertEqual(stale_latest['candidates'][0]['evidence'], ['Old snapshot evidence'])

        stale_pool = selection_operation(
            self.store,
            {'action': 'selection_pool', 'species_ids': ['quagsire']},
            species,
            current_context={**base_ctx, 'rules_digest': '9' * 64},
        )['snapshots']['quagsire']
        self.assertTrue(stale_pool['needs_reevaluation'])
        self.assertIn('rules_changed', stale_pool['freshness']['reasons'])

        # 5. MissingAnalysis.evidence suppresses stale facts and flags needs_reevaluation.
        master = self.root / 'gm_tv09.json'
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', master)
        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)
        service = BattleService(client, store=self.store)
        analysis = MissingAnalysis(self.store)
        spec = battle_spec()
        service.simulate(spec)
        plan = analysis.save_plan(service, [spec])

        ev_stale_gm = analysis.evidence(plan, active_versions={**service.versions, 'game_data': '0' * 64})
        self.assertEqual(ev_stale_gm['state'], 'stale')
        self.assertTrue(ev_stale_gm['freshness']['needs_reevaluation'])
        self.assertIn('engine_or_gamemaster_changed', ev_stale_gm['freshness']['reasons'])
        self.assertEqual(ev_stale_gm['coverage']['completed'], 0)
        self.assertIsNone(ev_stale_gm['cells'][0]['facts'])

        ev_stale_rules = analysis.evidence(
            plan,
            active_versions=service.versions,
            active_context={'rules': {'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True}},
        )
        self.assertEqual(ev_stale_rules['state'], 'stale')
        self.assertTrue(ev_stale_rules['freshness']['needs_reevaluation'])
        self.assertIn('rules_changed', ev_stale_rules['freshness']['reasons'])

    def test_app_ui_and_missing_ui_q1_q11_e2e(self):
        import json
        import re
        import subprocess
        from pvpoke_app_ui import HTML as APP_HTML
        from pvpoke_missing_ui import HTML as MISSING_HTML

        # Syntax check both inline scripts cleanly.
        for label, html_doc in (('app_ui', APP_HTML), ('missing_ui', MISSING_HTML)):
            m = re.search(r'<script>(.*?)</script>', html_doc, re.S)
            self.assertIsNotNone(m, f'{label} inline script missing')
            tmp_js = self.root / f'{label}.js'
            tmp_js.write_text(m.group(1), encoding='utf-8')
            subprocess.run(['node', '--check', str(tmp_js)], check=True, capture_output=True, text=True, timeout=10)

        # Functional Node test for discoverReachableForms, freshnessNoticeText, readReferenceTransfer, renderResult stale & reachable UI.
        app_fns = []
        for pat in (
            r'function isMegaSpeciesId\(sid\)\{.*?^\}',
            r'function isShadowSpeciesId\(sid\)\{.*?^\}',
            r'function discoverReachableForms\(sid\)\{.*?^\}',
            r'function freshnessNoticeText\(saved\)\{.*?^\}',
        ):
            m = re.search(pat, APP_HTML, re.S | re.M)
            self.assertIsNotNone(m, f'Pattern missing in app_ui: {pat}')
            app_fns.append(m.group(0))

        miss_gaps = re.search(r'const gaps=\{.*?\};', MISSING_HTML)
        self.assertIsNotNone(miss_gaps)
        miss_transfer = re.search(r'function readReferenceTransfer\(\)\{.*?^\}', MISSING_HTML, re.S | re.M)
        self.assertIsNotNone(miss_transfer)
        miss_render = re.search(r'function defaultBuildForForm\(targetSid,sourceCandidate\)\{.*?function renderResult\(result,request,revision\)\{.*?^\}', MISSING_HTML, re.S | re.M)
        self.assertIsNotNone(miss_render)

        synth_cat = json.dumps({
            'swablu': {'name_ja': 'チルット', 'fastMoves': ['PECK'], 'chargedMoves': ['DISARMING_VOICE', 'AERIAL_ACE'], 'family': {'evolutions': ['altaria']}},
            'altaria': {'name_ja': 'チルタリス', 'fastMoves': ['DRAGON_BREATH'], 'chargedMoves': ['SKY_ATTACK', 'MOONBLAST'], 'family': {'parent': 'swablu'}},
            'altaria_mega': {'name_ja': 'メガチルタリス', 'fastMoves': ['DRAGON_BREATH'], 'chargedMoves': ['SKY_ATTACK', 'MOONBLAST'], 'tags': ['mega'], 'extraChargedMoves': ['MOONBLAST_PLUS']},
            'swablu_shadow': {'name_ja': 'シャドウチルット', 'family': {'evolutions': ['altaria_shadow']}},
            'altaria_shadow': {'name_ja': 'シャドウチルタリス', 'family': {'parent': 'swablu_shadow'}},
            'slowpoke_galarian': {'name_ja': 'ヤドン (ガラル)', 'family': {'evolutions': ['slowbro_galarian']}},
            'slowbro_galarian': {'name_ja': 'ヤドラン (ガラル)', 'family': {'parent': 'slowpoke_galarian'}},
            'slowbro_mega': {'name_ja': 'メガヤドラン', 'tags': ['mega']},
        })
        script = f"""
const assert = require('node:assert/strict');
const catalog = {synth_cat};
{''.join(app_fns)}
const rSwablu = discoverReachableForms('swablu');
assert.deepEqual(rSwablu.evolutions, ['altaria']);
assert.deepEqual(rSwablu.mega_forms, ['altaria_mega']);
assert.deepEqual(discoverReachableForms('swablu_shadow').mega_forms, []);
assert.deepEqual(discoverReachableForms('slowpoke_galarian').mega_forms, []);
const staleMsg = freshnessNoticeText({{ needs_reevaluation: true, freshness: {{ reasons: ['ranking_changed'] }} }});
assert.ok(staleMsg.includes('再評価が必要') && staleMsg.includes('ranking_changed'));

// Missing UI transfer & renderResult checks with minimal DOM stub:
const missingTransferKey = 'pokemoniv:missing-reference-transfer-v1';
const sessionStorage = {{
 _m: new Map(),
 getItem(k){{ return this._m.get(k) ?? null; }},
 setItem(k,v){{ this._m.set(k, String(v)); }},
 removeItem(k){{ this._m.delete(k); }},
}};
sessionStorage.setItem(missingTransferKey, JSON.stringify({{
 schema: 'missing-reference-transfer-v1',
 species_id: 'altaria_mega',
 owned_species_id: 'swablu',
 mega_level: 4,
 charged3: 'MOONBLAST_PLUS',
 moves: {{ fast: 'DRAGON_BREATH', charged: ['SKY_ATTACK', 'MOONBLAST'] }},
 ivs: {{ attack: 0, defense: 14, hp: 15 }},
}}));
{miss_transfer.group(0)}
const parsed = readReferenceTransfer();
assert.equal(parsed.species_id, 'altaria_mega');
assert.equal(parsed.owned_species_id, 'swablu');
assert.equal(parsed.mega_level, 4);
assert.equal(parsed.charged3, 'MOONBLAST_PLUS');

const texts = [];
const mkEl = (tag) => ({{
 tag, textContent: '', hidden: false, className: '', children: [],
 append(...xs){{ this.children.push(...xs); }},
 replaceChildren(...xs){{ this.children = xs; }},
 setAttribute(){{}},
}});
const resultTree = mkEl('div');
const tacticResults = mkEl('div');
const tacticPanel = Object.assign(mkEl('div'), {{ dataset: {{}} }});
const edited = mkEl('div');
const resultsSec = mkEl('div');
const $ = (id) => ({{ 'result-tree': resultTree, 'tactic-evidence-results': tacticResults, 'tactic-evidence-panel': tacticPanel, edited, results: resultsSec }}[id] || mkEl(id));
const document = {{ createElement: mkEl }};
const node = (tag, text, parent, cls) => {{ const n = mkEl(tag); if (text != null) {{ n.textContent = text; texts.push(text); }} if (parent) parent.append(n); return n; }};
const detail = (parent, summary) => {{ const d = node('details', null, parent); node('summary', summary, d); return d; }};
const tag = (parent, text) => node('span', text, parent);
const button = (parent, text, onclick) => {{ const b = node('button', text, parent); b.onclick = onclick; return b; }};
const fixedEvidenceTargets = new Map();
const roles = {{ r1: '役割1' }}, priorities = {{ 1: '標準' }}, metrics = {{}};
const assessment = {{ pending: ['未評価', 'wait'] }}, substitutes = {{ pending: ['保留', 'wait'] }};
const name = (id) => catalog[id]?.name_ja || id;
const ivText = (ivs) => [ivs.attack, ivs.defense, ivs.hp].join('/');
const moveText = (c) => [c.moves.fast, ...c.moves.charged].join('/');
const buildText = (c) => name(c.species_id) + ' ' + ivText(c.ivs);
const comparisonLabel = () => '比較';
const ranking70OrInfo = () => null;
const renderExploration = () => {{}};
const renderMatch = () => {{}};
const renderInventory = () => {{}};
const addAlternative = () => {{}};
let editRevision = 0, displayed = null;
{miss_gaps.group(0)}
{miss_render.group(0)}
renderResult({{
 state: 'evidence_pending',
 evidence_state: 'stale',
 freshness: {{ needs_reevaluation: true, reasons: ['ranking_changed'] }},
 evaluation_id: 'e1',
 role: {{ role_id: 'r1', priority: 1 }},
 reference: {{ species_id: 'altaria_mega', build_id: 'b1' }},
 candidates: [{{
  build_id: 'b1', species_id: 'altaria_mega', owned_species_id: 'swablu', form_distinct: true,
  ivs: {{ attack: 0, defense: 14, hp: 15 }}, level: 20,
  moves: {{ fast: 'DRAGON_BREATH', charged: ['SKY_ATTACK', 'MOONBLAST'] }},
  reachable_forms: {{ evolutions: ['altaria'], mega_forms: ['altaria_mega'] }},
  status: 'pending', conditions: [], owned_instances: [],
 }}],
}}, {{}}, 0);
assert.ok(texts.some(t => t.includes('再評価保留')));
assert.ok(texts.some(t => t.includes('ranking_changed')));
assert.ok(texts.some(t => t.includes('所持形態：チルット') && t.includes('評価対象：メガチルタリス')));
assert.ok(texts.some(t => t.includes('比較候補へ追加（チルタリス）')));
console.log('UI_Q1_Q11_E2E_OK');
"""
        proc = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True, timeout=10)
        self.assertIn('UI_Q1_Q11_E2E_OK', proc.stdout)

    def test_app_ui_mega_supermax_comparison_and_achievement_ratio(self):
        import json
        import re
        import subprocess
        from pvpoke_app_ui import HTML as APP_HTML

        cmp_match = re.search(
            r'function computeMegaSuperMaxComparison\(sid,ivsStr\)\{.*?^\}',
            APP_HTML,
            re.S | re.M,
        )
        render_match = re.search(
            r'function renderMegaSuperMaxComparison\(row,parent,result\)\{.*?^\}',
            APP_HTML,
            re.S | re.M,
        )
        cpm_match = re.search(
            r'function cpmForLevel\(lvl\)\{.*?^\}',
            APP_HTML,
            re.S | re.M,
        )
        cp_match = re.search(
            r'function computeCpForSpecies\(sid,ivsObj,lvl\)\{.*?^\}',
            APP_HTML,
            re.S | re.M,
        )
        self.assertIsNotNone(cmp_match)
        self.assertIsNotNone(render_match)
        self.assertIsNotNone(cpm_match)
        self.assertIsNotNone(cp_match)

        script = f"""
const catalog = {{
  sableye_mega: {{
    baseStats: {{ atk: 141, def: 136, hp: 137 }},
    tags: ['mega']
  }}
}};
const cpms = {json.dumps(self.cpms)};
function isMegaSpeciesId(sid){{ return Boolean(sid && (/_(mega|primal)(?:_[xy])?$/.test(sid) || (catalog[sid]?.tags || []).includes('mega'))); }}
function parseIvsText(text){{
  const parts = String(text || '').split(/[,\\s/]+/).map(x => x.trim()).filter(Boolean);
  if (parts.length !== 3) return null;
  const nums = parts.map(Number);
  if (!nums.every(n => Number.isInteger(n) && n >= 0 && n <= 15)) return null;
  return {{ attack: nums[0], defense: nums[1], hp: nums[2] }};
}}
function maxLevelForCap(sid, ivsObj, cpCap = 1500, maxLvl = 50) {{
  if (!catalog[sid]?.baseStats || !Array.isArray(cpms) || !cpms.length || !ivsObj) return null;
  const top = Math.min(Math.round(maxLvl * 2), cpms.length + 1);
  for (let d = top; d >= 2; d--) {{
    const lvl = d / 2;
    const cp = computeCpForSpecies(sid, ivsObj, lvl);
    if (cp != null && cp <= cpCap) return {{ level: lvl, cp }};
  }}
  return null;
}}
{cpm_match.group(0)}
{cp_match.group(0)}
{cmp_match.group(0)}

const cmp = computeMegaSuperMaxComparison('sableye_mega', '0,15,15');
console.log(JSON.stringify(cmp));
"""
        proc = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True, timeout=10)
        parsed = json.loads(proc.stdout)
        self.assertEqual(parsed['sid'], 'sableye_mega')
        self.assertEqual(parsed['cap']['level'], 49.5)
        self.assertEqual(parsed['cap']['cp'], 1499)
        self.assertEqual(parsed['cp50'], 1508)
        self.assertEqual(parsed['cp51'], 1526)
        self.assertEqual(parsed['cp52'], 1544)
        self.assertEqual(parsed['maxCp50'], 1668)
        self.assertEqual(parsed['maxCp51'], 1688)
        self.assertEqual(parsed['maxCp52'], 1708)
        self.assertEqual(parsed['ratio50'], '90.4')
        self.assertEqual(parsed['ratio51'], '90.4')
        self.assertEqual(parsed['ratio52'], '90.4')

    def test_iv_workflow_accepts_and_returns_mega_downscaling_rules(self):
        from pvpoke_iv_workflow import IVWorkflow
        from unittest.mock import MagicMock

        backend = MagicMock()
        backend.status.return_value = {'state': 'idle'}
        backend.meta_status.return_value = {'sha256': 'a' * 64}
        backend.start24.return_value = {'preview': {'result_cache': {'reused': False}}}

        def status_after_start():
            return {'state': 'running', 'started_at': '2026-11-27T00:00:00Z', 'batch24': True}

        backend.status.side_effect = [{'state': 'idle'}, status_after_start()]
        workflow = IVWorkflow(backend)

        # Invalid rules should fail closed with ValueError
        with self.assertRaises(ValueError):
            workflow.run(
                {'species': 'sableye_mega', 'fast': 'SHADOW_CLAW', 'charged1': 'FOUL_PLAY', 'charged2': 'POWER_GEM'},
                '0,15,15',
                rules={'league': 'great', 'cp_cap': 1500, 'allow_cp_downscaling': 'not-a-bool'},
            )

        # Valid Mega GL rules should be normalized and stored on the ticket
        backend.status.side_effect = [{'state': 'idle'}, status_after_start(), status_after_start()]
        res = workflow.run(
            {'species': 'sableye_mega', 'fast': 'SHADOW_CLAW', 'charged1': 'FOUL_PLAY', 'charged2': 'POWER_GEM'},
            '0,15,15',
            wait_seconds=0,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True},
        )
        self.assertEqual(res['state'], 'running')
        self.assertEqual(workflow._ticket['rules'], {
            'league': 'great',
            'cup_id': 'great_mega',
            'cp_cap': 1500,
            'max_level': 50.0,
            'allow_cp_downscaling': True,
            'rule_explicit': True,
        })
        backend.start24.assert_called_with(
            {'species': 'sableye_mega', 'fast': 'SHADOW_CLAW', 'charged1': 'FOUL_PLAY', 'charged2': 'POWER_GEM'},
            '0,15,15',
            'simple',
            rules=workflow._ticket['rules'],
        )

    def test_rules_propagation_web_run24_and_24_workflow_mega_downscaling(self):
        import csv
        import http.client
        import json
        import os
        import sys
        import threading
        import zipfile
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        import pvpoke_batch_v2 as engine
        import pvpoke_24_workflow as wf
        import pvpoke_result_cache as result_cache
        import pvpoke_web as web

        fixtures = Path(__file__).resolve().parent / 'fixtures'
        gm_data = json.loads((fixtures / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        gm_data['moves'].extend([
            {'moveId': 'MEGA_BLAST_PLUS', 'name': 'Mega Blast+', 'type': 'dragon', 'power': 80,
             'energy': 35, 'energyGain': 0, 'cooldown': 500, 'turns': 1, 'isMegaMove': True},
            {'moveId': 'MEGA_HEAVY', 'name': 'Mega Heavy', 'type': 'normal', 'power': 110,
             'energy': 90, 'energyGain': 0, 'cooldown': 500, 'turns': 1},
            {'moveId': 'MEGA_HEAVY_ALT', 'name': 'Mega Heavy Alt', 'type': 'normal', 'power': 120,
             'energy': 95, 'energyGain': 0, 'cooldown': 500, 'turns': 1},
        ])
        gm_data['pokemon'].append({
            'speciesId': 'altaria_mega',
            'speciesName': 'Altaria (Mega)',
            'dex': 334,
            'types': ['dragon', 'fairy'],
            'baseStats': {'atk': 222, 'def': 218, 'hp': 181},
            'fastMoves': ['DRAGON_BREATH'],
            'chargedMoves': ['MEGA_HEAVY', 'MEGA_HEAVY_ALT'],
            'extraChargedMoves': ['MEGA_BLAST_PLUS'],
            'tags': ['mega'],
        })
        pokemon_js_path = Path(__file__).resolve().parent.parent / 'vendor/pvpoke/src/js/pokemon/Pokemon.js'
        pokemon_js_text = pokemon_js_path.read_text(encoding='utf-8')
        species_map = {p['speciesId']: p for p in gm_data['pokemon']}
        import re
        cpms = [float(s.strip()) for s in re.search(r'\bvar\s+cpms\s*=\s*\[([^\]]+)\]', pokemon_js_text, re.S).group(1).split(',') if s.strip()]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / 'game_data'
            data_dir.mkdir()
            (data_dir / 'gamemaster.json').write_text(json.dumps(gm_data), encoding='utf-8')
            (data_dir / 'Pokemon.js').write_text(pokemon_js_text, encoding='utf-8')
            meta_csv = root / 'meta.csv'
            with meta_csv.open('w', encoding='utf-8', newline='') as fp:
                w = csv.writer(fp)
                w.writerow(['azumarill', 'BUBBLE', 'ICE_BEAM', 'PLAY_ROUGH'])

            cfg_path = root / 'batch_config.json'
            out_dir = root / 'out_24'
            mega_rules = {'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True}
            cand_payload = {
                'species': 'altaria_mega',
                'fast': 'DRAGON_BREATH',
                'charged1': 'MEGA_HEAVY',
                'charged2': 'MEGA_HEAVY_ALT',
                'mega_level': 4,
                'charged3': 'MEGA_BLAST_PLUS',
                'level_override': 35.0,
            }

            # 1. Verify result_cache separates strict vs downscaling rules
            ctx_strict = result_cache.context(
                cand_payload, [(0, 14, 15)], 'simple', 'm' * 64, 'v' * 64, 1500, 50,
                rules={'league': 'great', 'cp_cap': 1500, 'allow_cp_downscaling': False})
            ctx_down = result_cache.context(
                cand_payload, [(0, 14, 15)], 'simple', 'm' * 64, 'v' * 64, 1500, 50,
                rules=mega_rules)
            self.assertNotEqual(ctx_strict['key'], ctx_down['key'])

            # 2. Verify /api/run24 writes rules to BATCH_CONFIG and rejects strict CP-over Mega
            work_dir = root / 'work'
            work_dir.mkdir()
            prev_web = (web.WORK, web.BATCH_CONFIG, web.BATCH_OUTPUT, web.CATALOG.copy(),
                        dict(web.STATUS))
            prev_data = engine.DATA
            prev_env = os.environ.get('PVP_ENGINE')
            try:
                engine.DATA = data_dir
                web.WORK = work_dir
                web.BATCH_CONFIG = work_dir / 'batch_config.json'
                web.BATCH_OUTPUT = work_dir / 'batch_output'
                web.CATALOG.clear()
                web.CATALOG.update({'ready': True, 'species': species_map, 'cpms': cpms})

                server = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
                t = threading.Thread(target=server.serve_forever, daemon=True)
                t.start()
                self.addCleanup(server.shutdown)
                self.addCleanup(server.server_close)
                port = server.server_address[1]

                # 2a. Strict rule (allow_cp_downscaling=False) rejects PL 35.0 Mega in /api/prepare24
                with patch.object(web.meta_live, 'active_path', return_value=meta_csv):
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                    conn.request('POST', '/api/prepare24', json.dumps({
                        'candidate': cand_payload, 'ivs': '0,14,15', 'batch_mode': 'simple',
                        'rules': {'league': 'great', 'cp_cap': 1500, 'allow_cp_downscaling': False},
                    }), {'Content-Type': 'application/json', 'X-PvPoke-Token': web.TOKEN})
                    resp_strict = conn.getresponse()
                    resp_strict.read()
                    self.assertEqual(resp_strict.status, 400)
                    conn.close()

                    # 2b. Downscaling rule succeeds in /api/run24 and writes rules to BATCH_CONFIG
                    with patch.object(web, 'background_run'):
                        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                        conn.request('POST', '/api/run24', json.dumps({
                            'candidate': cand_payload, 'ivs': '0,14,15', 'batch_mode': 'simple',
                            'rules': mega_rules,
                        }), {'Content-Type': 'application/json', 'X-PvPoke-Token': web.TOKEN})
                        resp_ok = conn.getresponse()
                        body_ok = json.loads(resp_ok.read().decode('utf-8'))
                        self.assertEqual(resp_ok.status, 200)
                        self.assertTrue(body_ok['ok'])
                        self.assertTrue(body_ok['preview']['rules']['allow_cp_downscaling'])
                        conn.close()
                saved_cfg = json.loads(web.BATCH_CONFIG.read_text(encoding='utf-8'))
                self.assertEqual(saved_cfg['rules']['allow_cp_downscaling'], True)
                self.assertEqual(saved_cfg['candidate']['level_override'], 35.0)
                web.COMPUTE_OWNER = None

                # 3. Execute pvpoke_24_workflow.main() end-to-end with PVP_ENGINE=direct
                cfg_path.write_text(json.dumps(saved_cfg), encoding='utf-8')
                os.environ['PVP_ENGINE'] = 'direct'
                with patch.object(engine, 'game_data', return_value=(gm_data, cpms, species_map)), \
                     patch.object(sys, 'argv', [
                         'pvpoke_24_workflow.py', '--run',
                         '--config', str(cfg_path),
                         '--meta', str(meta_csv),
                         '--output', str(out_dir),
                         '--batch-mode', 'simple',
                     ]):
                    wf.main()

                zip_path = out_dir / 'pvpoke_24_conditions.zip'
                self.assertTrue(zip_path.is_file())
                with zipfile.ZipFile(zip_path) as zf:
                    manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
                    self.assertEqual(manifest['rules']['allow_cp_downscaling'], True)
                    self.assertEqual(manifest['cp_cap'], 1500)
                    summary = zf.read('ranking_summary.csv').decode('utf-8-sig')
                    self.assertIn('altaria_mega', summary)
            finally:
                engine.DATA = prev_data
                if prev_env is None:
                    os.environ.pop('PVP_ENGINE', None)
                else:
                    os.environ['PVP_ENGINE'] = prev_env
                web.WORK, web.BATCH_CONFIG, web.BATCH_OUTPUT = prev_web[0], prev_web[1], prev_web[2]
                web.CATALOG.clear()
                web.CATALOG.update(prev_web[3])
                web.STATUS.clear()
                web.STATUS.update(prev_web[4])


if __name__ == '__main__':
    unittest.main()
