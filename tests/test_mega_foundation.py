"""Tests for Mega Evolution common foundation integrated into main."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pvpoke_app_ui import HTML as APP_HTML
from pvpoke_batch_v2 import optimize
from pvpoke_direct_backend import DirectMatrixClient, DirectMatrixError
from pvpoke_matchup_cache import MatchupCache, _prepared, cache_namespace
from pvpoke_mega import (
    MEGA_MOVE_BONUSES,
    base_species_id,
    build_training_goal,
    can_mega_evolve,
    compute_cp,
    compute_power_up_cost,
    discover_reachable_forms,
    eligible_pre_evolutions,
    evaluate_gl_mega_score_70_or,
    evaluate_owned_for_mega,
    evaluate_selection_freshness,
    is_mega_form,
    is_shadow_form,
    load_cpms,
    load_gl_ranking_snapshot,
    max_level_and_cp,
    mega_forms_for_base,
    resolve_battle_rules,
    resolve_gl_mega_ranking_70_or,
)
from pvpoke_score_search import search_low_scores


class MegaFoundationMainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
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
            'altaria_mega': {'baseStats': self.altaria_mega_stats, 'tags': ['mega']},
            'altaria_shadow': {'baseStats': self.altaria_stats},
            'charmander': {'baseStats': {'atk': 116, 'def': 93, 'hp': 118}, 'family': {'id': 'FAMILY_CHARMANDER', 'evolutions': ['charmeleon']}},
            'charmeleon': {'baseStats': {'atk': 158, 'def': 126, 'hp': 151}, 'family': {'id': 'FAMILY_CHARMANDER', 'parent': 'charmander', 'evolutions': ['charizard']}},
            'charizard': {'baseStats': {'atk': 223, 'def': 173, 'hp': 186}, 'family': {'id': 'FAMILY_CHARMANDER', 'parent': 'charmeleon'}},
            'charizard_mega_x': {'baseStats': {'atk': 273, 'def': 213, 'hp': 186}, 'tags': ['mega']},
            'charizard_mega_y': {'baseStats': {'atk': 319, 'def': 212, 'hp': 186}, 'tags': ['mega']},
            'kyogre_primal': {'baseStats': {'atk': 353, 'def': 268, 'hp': 218}, 'tags': ['mega']},
            'slowpoke': {'baseStats': self.slowpoke_stats, 'family': {'id': 'FAMILY_SLOWPOKE', 'evolutions': ['slowbro']}},
            'slowpoke_galarian': {'baseStats': self.slowpoke_stats, 'family': {'id': 'FAMILY_SLOWPOKE_GALARIAN', 'evolutions': ['slowbro_galarian']}},
            'slowbro': {'baseStats': self.slowbro_stats, 'family': {'id': 'FAMILY_SLOWPOKE', 'parent': 'slowpoke'}},
            'slowbro_galarian': {'baseStats': self.slowbro_stats, 'family': {'id': 'FAMILY_SLOWPOKE_GALARIAN', 'parent': 'slowpoke_galarian'}},
            'slowbro_mega': {'baseStats': self.slowbro_mega_stats, 'tags': ['mega']},
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
        self.assertTrue(can_mega_evolve('slowpoke', 'slowbro_mega', self.catalog))
        self.assertFalse(can_mega_evolve('slowpoke_galarian', 'slowbro_mega', self.catalog))

        self.assertEqual(
            mega_forms_for_base('charmander', set(self.catalog), self.catalog),
            ['charizard_mega_x', 'charizard_mega_y'],
        )
        self.assertEqual(mega_forms_for_base('swablu_shadow', set(self.catalog), self.catalog), [])

        reach = discover_reachable_forms('swablu', self.catalog, evaluated_species_id='altaria_mega')
        self.assertEqual(reach['owned_species_id'], 'swablu')
        self.assertEqual(reach['evolutions'], ['altaria'])
        self.assertEqual(reach['mega_forms'], ['altaria_mega'])

    def test_cp_rules_three_state_separation_and_super_max_deferred(self):
        ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        gl_lvl, gl_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        ul_lvl, ul_cp = max_level_and_cp(self.altaria_mega_stats, ivs, cp_cap=2500, max_level=50.0, cpms=self.cpms)
        self.assertLessEqual(gl_cp, 1500)
        self.assertLessEqual(ul_cp, 2500)
        self.assertGreater(ul_lvl, gl_lvl)

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

        base_cp_at_cap = compute_cp(self.altaria_stats, ivs, gl_lvl, self.cpms)
        high_cp = compute_cp(self.altaria_stats, ivs, 27.5, self.cpms)
        over_cp = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': 27.5, 'current_cp': high_cp},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=gl_lvl,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'great_mega', 'allow_cp_downscaling': True},
            cpms=self.cpms,
        )
        self.assertTrue(over_cp['eligible'])
        self.assertTrue(over_cp['downscaled'])
        self.assertEqual(over_cp['battle_effective']['cp'], gl_cp)

        over_cp_strict = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': 27.5, 'current_cp': high_cp},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=gl_lvl,
            rules={'league': 'great', 'cp_cap': 1500, 'cup_id': 'strict_unscaled', 'allow_cp_downscaling': False},
            cpms=self.cpms,
        )
        self.assertFalse(over_cp_strict['eligible'])
        self.assertEqual(over_cp_strict['reason'], 'level_exceeds_mega_cap')

        super_max_safe = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': gl_lvl, 'current_cp': base_cp_at_cap},
            mega_species_id='altaria_mega',
            base_stats=self.altaria_stats,
            mega_stats=self.altaria_mega_stats,
            target_level=gl_lvl,
            cp_cap=1500,
            allow_cp_downscaling=True,
            cpms=self.cpms,
            mega_level=4,
        )
        self.assertEqual(super_max_safe['mega_condition']['move_bonus_multiplier'], MEGA_MOVE_BONUSES[3])
        self.assertFalse(super_max_safe['mega_condition']['super_max_cp_applied'])
        self.assertEqual(super_max_safe['mega_condition']['super_max_pl_hypothesis_status'], 'unconfirmed_deferred')

        super_max_spec = evaluate_owned_for_mega(
            {'species_id': 'altaria', 'ivs': ivs, 'current_level': gl_lvl, 'current_cp': base_cp_at_cap},
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

    def test_power_up_candy_xl_boundaries_and_training_goal(self):
        pre_xl = compute_power_up_cost(39.5, 40.0)
        self.assertEqual((pre_xl['stardust'], pre_xl['candy'], pre_xl['candy_xl'], pre_xl['uses_xl_candy']),
                         (10000, 15, 0, False))
        first_xl = compute_power_up_cost(40.0, 40.5)
        self.assertEqual((first_xl['stardust'], first_xl['candy'], first_xl['candy_xl'], first_xl['uses_xl_candy']),
                         (10000, 0, 10, True))
        self.assertEqual(compute_power_up_cost(40.0, 50.0, shadow=True)['candy_xl'], 360)
        self.assertEqual(compute_power_up_cost(40.0, 50.0, purified=True)['candy_xl'], 272)
        self.assertEqual(compute_power_up_cost(40.0, 50.0, lucky=True)['stardust'], 125000)

        goal = build_training_goal(
            {'current_level': 49.5},
            target_level=51.0,
            needs_evolution=False,
            downscaled=False,
            mega_level=4,
        )
        self.assertTrue(goal['target_level_capped_at_50'])
        self.assertEqual(goal['super_max_pl_hypothesis_status'], 'unconfirmed_deferred')
        self.assertIn('仮説保留', goal['super_max_pl_note'])

    def test_real_gl_ranking_70_or_and_score_search(self):
        source_date, rows = load_gl_ranking_snapshot()
        self.assertEqual(source_date, '2026-10-15')
        self.assertGreater(len(rows), 1000)

        low_entry = next(r for r in rows if r['overall'] < 65 and '(' not in r['name'])
        synth_catalog = {
            'altaria': {'dex': 334, 'tags': []},
            'altaria_mega': {'dex': 334, 'tags': ['mega']},
            'sableye': {'dex': 302, 'tags': []},
            'sableye_shadow': {'dex': 302, 'tags': ['shadow']},
            'low_mon': {'dex': low_entry['dex'], 'name_ja': low_entry['name'], 'tags': []},
            'low_mon_mega': {'dex': low_entry['dex'], 'name_ja': low_entry['name'] + ' (メガ)', 'tags': ['mega']},
        }
        alt = resolve_gl_mega_ranking_70_or('altaria_mega', species_catalog=synth_catalog)
        self.assertTrue(alt['keep'])
        self.assertEqual(alt['matched_leagues'], ['normal_gl'])
        self.assertEqual(alt['mega_gl_status'], 'unverified')

        low_unverified = resolve_gl_mega_ranking_70_or('low_mon_mega', species_catalog=synth_catalog)
        self.assertTrue(low_unverified['keep'])
        self.assertFalse(low_unverified['verified'])
        self.assertEqual(low_unverified['reason'], 'ranking_unverified')

        low_mega_pass = resolve_gl_mega_ranking_70_or(
            'low_mon_mega', species_catalog=synth_catalog, mega_scores={'low_mon_mega': {'overall': 74.5}}
        )
        self.assertTrue(low_mega_pass['keep'])
        self.assertEqual(low_mega_pass['matched_leagues'], ['mega_gl'])

        baseline = search_low_scores({'mode': 'overall'})
        self.assertEqual(baseline['mega_gl_ranking_status'], 'unverified')
        sample_low = baseline['selected_preview'][0]['name']
        protected = search_low_scores({'mode': 'overall'}, mega_scores={sample_low: {'overall': 74.2}})
        self.assertEqual(protected['mega_gl_ranking_status'], 'verified')
        self.assertEqual(protected['mega_gl_preserved_count'], 1)
        self.assertEqual(protected['selected_count'], baseline['selected_count'] - 1)

        all_sp = evaluate_gl_mega_score_70_or(normal_gl_overall=20.0, mega_gl_overall=25.0, all_species_mode=True)
        self.assertTrue(all_sp['keep'])

    def test_matchup_cache_separates_mega_level_and_charged3(self):
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
        self.assertEqual(len(_prepared(base_row)), 10)
        ns1 = cache_namespace(gamemaster_hash='g', pokemonjs_hash='p', cp_cap=1500, max_level=50)
        ns_downscale = cache_namespace(
            gamemaster_hash='g', pokemonjs_hash='p', cp_cap=1500, max_level=50,
            downscaling_mode='great_mega', cup_id='great_mega',
        )
        self.assertNotEqual(ns1, ns_downscale)

        with MatchupCache(self.root / 'matchups.sqlite3', ns1) as cache:
            m1 = {**base_row, 'charged3': 'MEGA_BLAST_PLUS', 'mega_level': 1}
            m4 = {**base_row, 'charged3': 'MEGA_BLAST_PLUS', 'mega_level': 4}
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

    def test_batch_optimize_and_node_matrix_mega_level_charged3_and_cp_cap(self):
        fixtures = Path(__file__).resolve().parent / 'fixtures'
        gm_data = json.loads((fixtures / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        rows = json.loads((fixtures / 'strategy_rows.json').read_text(encoding='utf-8'))
        opp_row = rows[0]

        gm_data['moves'].extend([
            {'moveId': 'MEGA_BLAST_PLUS', 'name': 'Mega Blast+', 'type': 'dragon', 'power': 80,
             'energy': 35, 'energyGain': 0, 'cooldown': 500, 'turns': 1, 'isMegaMove': True},
            {'moveId': 'MEGA_HEAVY', 'name': 'Mega Heavy', 'type': 'normal', 'power': 110,
             'energy': 90, 'energyGain': 0, 'cooldown': 500, 'turns': 1},
            {'moveId': 'MEGA_HEAVY_ALT', 'name': 'Mega Heavy Alt', 'type': 'normal', 'power': 120,
             'energy': 95, 'energyGain': 0, 'cooldown': 500, 'turns': 1},
        ])
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
        species_map = {p['speciesId']: p for p in gm_data['pokemon']}
        prepared = optimize([{
            'species': 'altaria_mega', 'fast': 'DRAGON_BREATH',
            'charged1': 'MEGA_HEAVY', 'charged2': 'MEGA_HEAVY_ALT',
            'charged3': 'MEGA_BLAST_PLUS', 'mega_level': 4,
            'atk': 0, 'def': 14, 'hp': 15, 'level_override': mega_lvl,
        }], species_map, self.cpms, 'mega.csv', cp_cap=1500)[0]
        self.assertEqual(prepared['cp'] <= 1500, True)

        with self.assertRaises(ValueError):
            optimize([{
                'species': opp_row['species'], 'fast': opp_row['fast'],
                'charged1': opp_row['charged1'], 'charged2': opp_row['charged2'],
                'charged3': 'MEGA_BLAST_PLUS',
                'atk': opp_row['atk'], 'def': opp_row['def'], 'hp': opp_row['hp'],
            }], species_map, self.cpms, 'bad.csv')

        master = self.root / 'gamemaster.json'
        master.write_text(json.dumps(gm_data), encoding='utf-8')
        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)

        damages = {}
        for ml in (1, 4):
            detail = client.strategy('detail', {
                'cp_cap': 1500,
                'self': {**prepared, 'mega_level': ml, 'charged3': 'MEGA_BLAST_PLUS'},
                'opponent': opp_row,
                'shields': [0, 0],
                'initial': [{'energy_points': 40}, {}],
            })
            self.assertEqual(detail['status'], 'calculated')
            hits = [ev['damage'] for ev in detail['events']
                    if ev.get('actor') == 0 and ev.get('move_id') == 'MEGA_BLAST_PLUS']
            self.assertTrue(hits)
            damages[ml] = hits[0]
        self.assertGreater(damages[4], damages[1])

        bad_cand = {**opp_row, 'mega_level': 3}
        with self.assertRaises(DirectMatrixError):
            client.simulate([bad_cand], [opp_row], (0, 0))

    def test_selection_freshness_fail_closed(self):
        base_ctx = {
            'calculation_version': 'gm-v1',
            'ranking_source_date': '2026-10-15',
            'meta_sha256': 'abc123',
            'policy_version': 'box-first-v3',
            'rules_digest': 'r1',
        }
        same = evaluate_selection_freshness(base_ctx, base_ctx)
        self.assertTrue(same['fresh'])
        self.assertFalse(same['needs_reevaluation'])

        changed = evaluate_selection_freshness(base_ctx, {**base_ctx, 'calculation_version': 'gm-v2'})
        self.assertFalse(changed['fresh'])
        self.assertTrue(changed['needs_reevaluation'])
        self.assertIn('calculation_version_changed', changed['reasons'])
        self.assertTrue(changed['old_result_preserved'])

    def test_app_ui_mega_controls_and_web_catalog_fields(self):
        for control_id in ('id="megaMoveSettings"', 'id="megaLevel"', 'id="charged3Wrap"', 'id="charged3"'):
            self.assertIn(control_id, APP_HTML)

        script_body = re.search(r'<script>\s*(.*)\s*</script>', APP_HTML, re.S).group(1)
        m_opts = re.search(r"function option\(select,values,selected,label=v=>v\)\{.*?\n\}", script_body, re.S)
        m_fill = re.search(r"function fillMoveFields\(sid,row,\[fast,charged1,charged2\],label\)\{.*?\n\}", script_body, re.S)
        m_moves = re.search(r"function moves\(row=\{\},sid=el\('species'\)\.value\)\{.*?\n\}", script_body, re.S)
        m_curr = re.search(r"function currentCandidate\(\)\{.*?\n\}", script_body, re.S)
        self.assertTrue(all((m_opts, m_fill, m_moves, m_curr)))

        js = """
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
  clefable_mega: { fastMoves: ['FAIRY_WIND'], chargedMoves: ['MOONBLAST', 'METEOR_MASH'], tags: ['mega', 'supermega'], extraChargedMoves: ['MOONBLAST_PLUS'] },
};
""" + "\n".join(m.group(0) for m in (m_opts, m_fill, m_moves, m_curr)) + """
elements.species.value = 'quagsire';
moves();
assert.equal(elements.megaMoveSettings.hidden, true);
assert.equal('mega_level' in currentCandidate(), false);

elements.species.value = 'clefable_mega';
moves({ charged3: 'MOONBLAST_PLUS' });
assert.equal(elements.megaMoveSettings.hidden, false);
assert.equal(elements.megaLevel.value, '4');
assert.equal(elements.charged3Wrap.hidden, false);
assert.deepEqual(currentCandidate(), {
  species: 'clefable_mega', fast: 'FAIRY_WIND', charged1: 'MOONBLAST', charged2: 'METEOR_MASH',
  mega_level: 4, charged3: 'MOONBLAST_PLUS'
});
console.log('MAIN_APP_UI_MEGA_CONTROLS_OK');
"""
        proc = subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True, timeout=10)
        self.assertIn('MAIN_APP_UI_MEGA_CONTROLS_OK', proc.stdout)

        import pvpoke_web
        sample_species = {
            'altaria_mega': {
                'speciesName': 'Altaria (Mega)',
                'dex': 334,
                'baseStats': self.altaria_mega_stats,
                'types': ['dragon', 'fairy'],
                'fastMoves': ['DRAGON_BREATH'],
                'chargedMoves': ['DRAGON_PULSE', 'MOONBLAST'],
                'extraChargedMoves': ['MOONBLAST_PLUS'],
                'tags': ['mega'],
                'family': {'id': 'FAMILY_SWABLU', 'parent': 'altaria'},
            }
        }
        with patch.object(pvpoke_web, 'configure_engine'), \
             patch.object(pvpoke_web.engine, 'game_data', return_value=({'moves': [], 'timestamp': 1}, self.cpms, sample_species)), \
             patch.object(pvpoke_web, 'enrich_catalog'), \
             patch.object(pvpoke_web, 'public_catalog', return_value={'moves': {}}), \
             patch.object(pvpoke_web.meta_variants, 'start'):
            pvpoke_web.load_catalog()
            self.assertTrue(pvpoke_web.CATALOG['ready'])
            self.assertEqual(pvpoke_web.CATALOG['cpms'], list(self.cpms))
            entry = pvpoke_web.CATALOG['species']['altaria_mega']
            self.assertEqual(entry['extraChargedMoves'], ['MOONBLAST_PLUS'])
            self.assertEqual(entry['tags'], ['mega'])
            self.assertEqual(entry['family'], {'id': 'FAMILY_SWABLU', 'parent': 'altaria'})

    def test_optimize_mega_downscaling_rules_and_matrix_simulation(self):
        fixtures = Path(__file__).resolve().parent / 'fixtures'
        gm_data = json.loads((fixtures / 'strategy_gamemaster.json').read_text(encoding='utf-8'))
        rows = json.loads((fixtures / 'strategy_rows.json').read_text(encoding='utf-8'))
        opp_row = rows[0]

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
            'baseStats': self.altaria_mega_stats,
            'fastMoves': ['DRAGON_BREATH'],
            'chargedMoves': ['MEGA_HEAVY', 'MEGA_HEAVY_ALT'],
            'extraChargedMoves': ['MEGA_BLAST_PLUS'],
            'tags': ['mega'],
        })
        species_map = {p['speciesId']: p for p in gm_data['pokemon']}
        mega_ivs = {'attack': 0, 'defense': 14, 'hp': 15}
        cap_lvl, cap_cp = max_level_and_cp(self.altaria_mega_stats, mega_ivs, cp_cap=1500, max_level=50.0, cpms=self.cpms)
        over_lvl = 35.0
        over_mega_row = {
            'species': 'altaria_mega', 'fast': 'DRAGON_BREATH',
            'charged1': 'MEGA_HEAVY', 'charged2': 'MEGA_HEAVY_ALT',
            'charged3': 'MEGA_BLAST_PLUS', 'mega_level': 4,
            'atk': 0, 'def': 14, 'hp': 15, 'level_override': over_lvl,
        }

        # 1. Without downscaling rules or with allow_cp_downscaling=False, CP-exceeding level_override fails.
        with self.assertRaises(ValueError):
            optimize([over_mega_row], species_map, self.cpms, 'strict.csv', cp_cap=1500)
        with self.assertRaises(ValueError):
            optimize([over_mega_row], species_map, self.cpms, 'strict.csv',
                     rules={'league': 'great', 'allow_cp_downscaling': False})

        # 2. Non-Mega CP-exceeding level_override is never downscaled even when allow_cp_downscaling=True.
        opp_over = {**opp_row, 'level_override': 50.0}
        with self.assertRaises(ValueError):
            optimize([opp_over], species_map, self.cpms, 'opp_over.csv',
                     rules={'league': 'great', 'cup_id': 'great_mega', 'allow_cp_downscaling': True})

        # 3. With allow_cp_downscaling=True, Mega is downscaled to cap_lvl / cap_cp and runs Matrix simulation.
        prepared = optimize([over_mega_row], species_map, self.cpms, 'mega_gl.csv',
                            rules={'league': 'great', 'cup_id': 'great_mega', 'allow_cp_downscaling': True})
        self.assertEqual(len(prepared), 1)
        cand = prepared[0]
        self.assertEqual(cand['level'], cap_lvl)
        self.assertEqual(cand['cp'], cap_cp)
        self.assertLessEqual(cand['cp'], 1500)
        self.assertTrue(cand['downscaled'])
        self.assertEqual(cand['original_level'], over_lvl)
        self.assertGreater(cand['original_cp'], 1500)

        master = self.root / 'gamemaster_downscale.json'
        master.write_text(json.dumps(gm_data), encoding='utf-8')
        client = DirectMatrixClient(gamemaster=master, log_dir=self.root)
        self.addCleanup(client.close)
        matrix = client.simulate(prepared, [opp_row], (1, 1))
        self.assertEqual(len(matrix), 2)
        rating = int(matrix[1][1])
        self.assertTrue(0 <= rating <= 1000)

