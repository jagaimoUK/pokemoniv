import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pvpoke_mega as mega
import pvpoke_party_core as core
from pvpoke_party_backend import PartyBuilder


class PartyMegaRuleResolutionTests(unittest.TestCase):
    def test_standard_non_mega_rulesets_forbid_megas_in_pick_three(self):
        for rules in ('cp1500-lv50', 'all', 'open_great', {'ruleset': 'cp1500-lv50'}):
            with self.subTest(rules=rules):
                policy = mega.resolve_party_mega_rules(rules)
                self.assertTrue(policy['rule_verified'])
                self.assertFalse(policy['mega_allowed'])
                self.assertEqual(policy['max_megas_in_six'], 6)
                self.assertEqual(policy['max_megas_in_three'], 0)
                self.assertTrue(policy['allow_multiple_megas_in_six'])

    def test_known_mega_cups_allow_multi_mega_in_six_and_one_in_three(self):
        for cup in ('great_mega', 'ultra_mega', 'mega_edition'):
            with self.subTest(cup=cup):
                policy = mega.resolve_party_mega_rules({'ruleset': 'cp1500-lv50', 'cup_id': cup})
                self.assertTrue(policy['rule_verified'])
                self.assertTrue(policy['mega_allowed'])
                self.assertEqual(policy['max_megas_in_six'], 6)
                self.assertEqual(policy['max_megas_in_three'], 1)

    def test_explicit_multi_mega_rules_are_not_hardcoded_to_one(self):
        for limit in (0, 1, 2, 3):
            with self.subTest(limit=limit):
                policy = mega.resolve_party_mega_rules({
                    'cup_id': f'custom_cup_{limit}',
                    'max_megas_in_three': limit,
                })
                self.assertTrue(policy['rule_verified'])
                self.assertEqual(policy['max_megas_in_three'], limit)
                self.assertEqual(policy['mega_allowed'], limit > 0)

    def test_unknown_or_unverified_cup_never_guesses_one_mega(self):
        for rules in (None, 'mystery_cup', {'cup_id': 'mystery_cup'}, {'cup_id': 'mystery_cup', 'mega_allowed': True}):
            with self.subTest(rules=rules):
                policy = mega.resolve_party_mega_rules(rules)
                self.assertFalse(policy['rule_verified'])
                self.assertIsNone(policy['max_megas_in_three'])

    def test_contradictory_or_out_of_range_mega_rules_fail(self):
        for bad in (
            {'mega_allowed': False, 'max_megas_in_three': 1},
            {'mega_allowed': True, 'max_megas_in_three': 0},
            {'max_megas_in_three': 4},
            {'max_megas_in_three': True},
            {'max_megas_in_six': 7},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mega.resolve_party_mega_rules(bad)

    def test_validate_party_mega_rules_separates_show_six_from_pick_three(self):
        six = ['altaria_mega', 'sableye_mega', 'venusaur_mega', 'azumarill', 'clodsire', 'skarmory']
        pick_one = ['altaria_mega', 'azumarill', 'clodsire']
        pick_two = ['altaria_mega', 'sableye_mega', 'azumarill']

        res_1 = mega.validate_party_mega_rules(six, pick_two, rules='great_mega')
        self.assertTrue(res_1['six_roster_valid'])
        self.assertFalse(res_1['pick_three_valid'])
        self.assertEqual(res_1['reason'], 'mega_limit_exceeded')

        res_2 = mega.validate_party_mega_rules(
            six, pick_two, rules={'cup_id': 'special_double_mega', 'max_megas_in_three': 2}
        )
        self.assertTrue(res_2['six_roster_valid'])
        self.assertTrue(res_2['pick_three_valid'])
        self.assertEqual(res_2['reason'], 'ok')

        res_0 = mega.validate_party_mega_rules(six, pick_one, rules='cp1500-lv50')
        self.assertTrue(res_0['six_roster_valid'])
        self.assertFalse(res_0['pick_three_valid'])

        res_unverified = mega.validate_party_mega_rules(six, pick_one, rules='mystery_cup')
        self.assertTrue(res_unverified['six_roster_valid'])
        self.assertIsNone(res_unverified['pick_three_valid'])
        self.assertFalse(res_unverified['rule_verified'])


class PartyCoreMegaLimitTests(unittest.TestCase):
    def test_legal_triples_and_choose_three_enforce_cup_specific_mega_limits(self):
        ours = ['m1', 'm2', 'm3', 'n1', 'n2', 'n3']
        enemies = ['em1', 'em2', 'em3', 'en1', 'en2', 'en3']
        own_megas = {'m1', 'm2', 'm3'}
        enemy_megas = {'em1', 'em2', 'em3'}
        matrix = {
            (o, e, s): (700 if o in own_megas else 550)
            for o in ours for e in enemies for s in core.ALL_SHIELDS
        }

        expected_counts = {0: 1, 1: 10, 2: 19, 3: 20}
        for limit, count in expected_counts.items():
            triples = list(core.legal_triples(ours, mega_ids=own_megas, max_megas=limit))
            self.assertEqual(len(triples), count)
            self.assertTrue(all(sum(1 for x in t if x in own_megas) <= limit for t in triples))

            orders = list(core.role_orders(ours, mega_ids=own_megas, max_megas=limit))
            self.assertEqual(len(orders), count * 3)

            chosen = core.choose_three(
                ours, enemies, matrix, max_enemies=60,
                mega_ids=own_megas, max_megas=limit,
                enemy_mega_ids=enemy_megas, enemy_max_megas=limit,
            )
            self.assertEqual(chosen['own_variants'], count * 3)
            self.assertEqual(chosen['opponent_variants'], count * 3)
            for rec in chosen['recommendations']:
                self.assertLessEqual(sum(1 for x in rec['selection'] if x in own_megas), limit)
                self.assertLessEqual(sum(1 for x in rec['worst_opponent'] if x in enemy_megas), limit)

        # If not enough non-Megas exist for the cup's pick-3 Mega limit, choose_three rejects cleanly.
        four_megas = ['m1', 'm2', 'm3', 'm4', 'n1', 'n2']
        with self.assertRaisesRegex(ValueError, '合法な3体選出がありません'):
            core.choose_three(
                four_megas, enemies, matrix,
                mega_ids={'m1', 'm2', 'm3', 'm4'}, max_megas=0,
                enemy_mega_ids=enemy_megas, enemy_max_megas=0,
            )


class PartyBackendMegaLimitTests(unittest.TestCase):
    def _fixture(self, work: Path):
        catalog = {
            'altaria_mega': {'fastMoves': ['DRAGON_BREATH'], 'chargedMoves': ['SKY_ATTACK', 'MOONBLAST']},
            'sableye_mega': {'fastMoves': ['SHADOW_CLAW'], 'chargedMoves': ['FOUL_PLAY', 'POWER_GEM']},
            'venusaur_mega': {'fastMoves': ['VINE_WHIP'], 'chargedMoves': ['FRENZY_PLANT', 'SLUDGE_BOMB']},
            'charizard_mega_y': {'fastMoves': ['WING_ATTACK'], 'chargedMoves': ['BLAST_BURN', 'DRAGON_CLAW']},
            'ampharos_mega': {'fastMoves': ['VOLT_SWITCH'], 'chargedMoves': ['BRUTAL_SWING', 'THUNDER_PUNCH']},
            'azumarill': {'fastMoves': ['BUBBLE'], 'chargedMoves': ['ICE_BEAM', 'PLAY_ROUGH']},
            'clodsire': {'fastMoves': ['POISON_STING'], 'chargedMoves': ['STONE_EDGE', 'EARTHQUAKE']},
            'skarmory': {'fastMoves': ['STEEL_WING'], 'chargedMoves': ['SKY_ATTACK', 'BRAVE_BIRD']},
        }
        species = {
            'altaria_mega': {'speciesId': 'altaria_mega', 'dex': 334, 'baseStats': {'atk': 222, 'def': 218, 'hp': 181}, 'defaultIVs': {'cp1500': [20, 0, 14, 15]}},
            'sableye_mega': {'speciesId': 'sableye_mega', 'dex': 302, 'baseStats': {'atk': 151, 'def': 216, 'hp': 137}, 'defaultIVs': {'cp1500': [30, 0, 15, 15]}},
            'venusaur_mega': {'speciesId': 'venusaur_mega', 'dex': 3, 'baseStats': {'atk': 241, 'def': 246, 'hp': 190}, 'defaultIVs': {'cp1500': [18, 0, 15, 15]}},
            'charizard_mega_y': {'speciesId': 'charizard_mega_y', 'dex': 6, 'baseStats': {'atk': 319, 'def': 212, 'hp': 186}, 'defaultIVs': {'cp1500': [15, 0, 15, 15]}},
            'ampharos_mega': {'speciesId': 'ampharos_mega', 'dex': 181, 'baseStats': {'atk': 294, 'def': 203, 'hp': 207}, 'defaultIVs': {'cp1500': [16, 0, 15, 15]}},
            'azumarill': {'speciesId': 'azumarill', 'dex': 184, 'baseStats': {'atk': 112, 'def': 152, 'hp': 225}, 'defaultIVs': {'cp1500': [40, 0, 15, 15]}},
            'clodsire': {'speciesId': 'clodsire', 'dex': 980, 'baseStats': {'atk': 123, 'def': 177, 'hp': 277}, 'defaultIVs': {'cp1500': [30, 0, 15, 15]}},
            'skarmory': {'speciesId': 'skarmory', 'dex': 227, 'baseStats': {'atk': 148, 'def': 226, 'hp': 163}, 'defaultIVs': {'cp1500': [25, 0, 15, 15]}},
        }
        engine = SimpleNamespace(
            DATA=work,
            HEADER=['species', 'fast', 'charged1', 'charged2', 'atk', 'def', 'hp'],
            CP_CAP=1500,
            MAX_LEVEL=50,
            optimize=lambda rows, sp, cpms, label: [{**r, 'level': 30.0, 'cp': 1490} for r in rows],
        )
        (work / 'gamemaster.json').write_text('{"timestamp": "test"}', encoding='utf-8')
        meta_path = work / 'legacy.csv'
        with meta_path.open('w', encoding='utf-8', newline='') as f:
            csv.writer(f).writerow(['azumarill', 'BUBBLE', 'ICE_BEAM', 'PLAY_ROUGH'])
        return catalog, species, mega.load_cpms(), engine, meta_path

    def _row(self, sid, catalog):
        return {
            'species': sid,
            'fast': catalog[sid]['fastMoves'][0],
            'charged1': catalog[sid]['chargedMoves'][0],
            'charged2': catalog[sid]['chargedMoves'][1],
            'atk': 0, 'def': 15, 'hp': 15, 'level': 30.0, 'cp': 1490,
        }

    def test_backend_compute_allows_multi_mega_in_six_and_validates_cup_pick_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            catalog, species, cpms, engine, meta_path = self._fixture(work)
            builder = PartyBuilder(work)
            own = [self._row(s, catalog) for s in (
                'altaria_mega', 'sableye_mega', 'venusaur_mega', 'azumarill', 'clodsire', 'skarmory'
            )]
            enemy = [self._row(s, catalog) for s in (
                'charizard_mega_y', 'ampharos_mega', 'azumarill', 'clodsire', 'skarmory', 'venusaur_mega'
            )]

            class FakeMatrixClient:
                def __init__(self, **kwargs):
                    pass

                def simulate(self, own_chunk, opp_chunk, shield):
                    return [[''] + [q['species'] for q in opp_chunk]] + [
                        [p['species']] + [650 if mega.is_mega_form(p['species']) else 520 for _ in opp_chunk]
                        for p in own_chunk
                    ]

                def close(self):
                    pass

            preset_stub = (meta_path, {'sha256': 'stub-sha'})
            with patch('pvpoke_party_backend.DirectMatrixClient', FakeMatrixClient), \
                 patch('pvpoke_party_backend.presets.snapshot', return_value=preset_stub), \
                 patch('pvpoke_party_backend.calculation_version', return_value='calc-v1'):

                # 1. Known 1-Mega cup ('great_mega'): allows 3 Megas in 6, limits pick-3 to <=1 Mega.
                r1 = builder._compute('j1', {
                    'mode': 'select',
                    'members': own,
                    'opponents': enemy,
                    'mega_rules': {'cup_id': 'great_mega'},
                    'strategy_refinement': False,
                }, catalog, species, cpms, engine, work)
                self.assertEqual(len(r1['triples']), 10)
                self.assertEqual(r1['mega_policy']['max_megas_in_three'], 1)
                self.assertEqual(r1['selection']['status'], '計算済み')
                for rec in r1['selection']['recommendations']:
                    self.assertLessEqual(
                        sum(1 for pid in rec['selection'] if mega.is_mega_form(r1['labels'][pid]['species'])),
                        1,
                    )

                # 2. Explicit 2-Mega cup: allows up to 2 Megas in pick-3.
                r2 = builder._compute('j2', {
                    'mode': 'select',
                    'members': own,
                    'opponents': enemy,
                    'mega_rules': {'cup_id': 'special_double_mega', 'max_megas_in_three': 2},
                    'strategy_refinement': False,
                }, catalog, species, cpms, engine, work)
                self.assertEqual(len(r2['triples']), 19)
                self.assertEqual(r2['mega_policy']['max_megas_in_three'], 2)

                # 3. Standard non-Mega Open GL ('cp1500-lv50'): 6-member registration allowed, pick-3 limited to 0 Megas.
                r0 = builder._compute('j0', {
                    'mode': 'select',
                    'members': own,
                    'opponents': enemy,
                    'ruleset': 'cp1500-lv50',
                    'strategy_refinement': False,
                }, catalog, species, cpms, engine, work)
                self.assertEqual(len(r0['triples']), 1)
                self.assertEqual(r0['mega_policy']['max_megas_in_three'], 0)
                self.assertEqual(
                    sum(1 for pid in r0['triples'][0]['members'] if mega.is_mega_form(r0['labels'][pid]['species'])),
                    0,
                )

                # 4. Unverified cup fails closed instead of guessing 1 Mega.
                with self.assertRaisesRegex(ValueError, '未確認'):
                    builder._compute('j_bad', {
                        'mode': 'select',
                        'members': own,
                        'opponents': enemy,
                        'mega_rules': {'cup_id': 'mystery_unverified_cup'},
                        'strategy_refinement': False,
                    }, catalog, species, cpms, engine, work)

                # 5. Build mode allows multiple Megas in 6 while keeping legal 3-picks possible.
                pool_build = [self._row(s, catalog) for s in (
                    'altaria_mega', 'sableye_mega', 'venusaur_mega', 'charizard_mega_y',
                    'ampharos_mega', 'azumarill', 'clodsire', 'skarmory'
                )]
                rb = builder._compute('j_build', {
                    'mode': 'build',
                    'members': pool_build[:6],
                    'locked_slots': [0, 1],
                    'candidate_pool': pool_build[2:],
                    'mega_rules': {'cup_id': 'great_mega'},
                    'strategy_refinement': False,
                }, catalog, species, cpms, engine, work)
                built_mega_count = sum(
                    1 for pid in rb['roster'] if mega.is_mega_form(rb['labels'][pid]['species'])
                )
                self.assertGreaterEqual(built_mega_count, 2)
                self.assertLessEqual(built_mega_count, 4)
                self.assertTrue(rb['triples'])
                for row in rb['triples']:
                    self.assertLessEqual(
                        sum(1 for pid in row['members'] if mega.is_mega_form(rb['labels'][pid]['species'])),
                        1,
                    )


if __name__ == '__main__':
    unittest.main()
