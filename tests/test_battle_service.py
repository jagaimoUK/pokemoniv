import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_direct_backend import DirectMatrixClient, DirectMatrixError

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
ROWS = json.loads((FIXTURES / 'strategy_rows.json').read_text())
GOLDEN = json.loads((FIXTURES / 'strategy_standard_ratings.json').read_text())


def battle_spec(left=0, right=2, shields=(1, 1)):
    combatants = []
    for row, shield in zip((ROWS[left], ROWS[right]), shields):
        combatants.append({
            'species_id': row['species'],
            'ivs': {'attack': row['atk'], 'defense': row['def'], 'hp': row['hp']},
            'level': row['level'],
            'moves': {'fast': row['fast'], 'charged': [row['charged1'], row['charged2']]},
            'initial': {'hp': 'full', 'energy': 0, 'shields': shield, 'stages': [0, 0]},
        })
    return {
        'schema': 'battle-spec-v1', 'mode': 'standard',
        'rules': {'league': 'great', 'cp_cap': 1500}, 'combatants': combatants,
    }


class BattleServiceTests(unittest.TestCase):
    def setUp(self):
        work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        master = work / 'gamemaster.json'
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', master)
        self.client = DirectMatrixClient(gamemaster=master, log_dir=work)
        self.addCleanup(self.client.close)
        self.service = BattleService(self.client)

    def test_rating_matches_all_324_standard_golden_cases(self):
        for a in range(3):
            for b in range(3):
                for left in range(len(ROWS)):
                    for right in range(len(ROWS)):
                        with self.subTest(a=a, b=b, left=left, right=right):
                            result = self.service.simulate(battle_spec(left, right, (a, b)))
                            self.assertEqual(result['status'], 'complete', result.get('error'))
                            self.assertEqual(result['rating'], GOLDEN[3 * a + b][left][right])

    def test_standard_resources_and_moves_match_existing_detail_runner(self):
        for shields in ((0, 0), (0, 2), (2, 1)):
            spec = battle_spec(shields=shields)
            spec['combatants'][0]['initial'].update(hp=70, energy=80, stages=[1, -1])
            with self.subTest(shields=shields):
                direct_payload = {
                    'self': ROWS[0], 'opponent': ROWS[2], 'shields': list(shields),
                    'initial': [{'hp_points': 70, 'energy_points': 80, 'buffs': [1, -1]}, {}],
                }
                before = self.client.strategy('detail', direct_payload)
                after = self.service.simulate(json.dumps(spec))
                unchanged = self.client.strategy('detail', direct_payload)
                self.assertEqual(before, unchanged)
                self.assertEqual(after['rating'], before['rating'])
                self.assertEqual(after['outcome'], {'self_ko_win': 'self_win',
                    'opponent_ko_win': 'opponent_win', 'simultaneous_ko': 'simultaneous_ko'}[before['outcome']])
                for new, old in zip(after['terminal'], before['terminal'], strict=True):
                    self.assertEqual(new, {key: old[key] for key in new})
                self.assertEqual(after['damage'], before['damage'])
                self.assertEqual(after['shields_used'], before['shields_used'])
                self.assertEqual(after['executed_moves'], before['events'])
                self.assertEqual(after['action_results'], [])

    def test_bad_inputs_do_not_start_a_battle(self):
        cases = [
            (('combatants', 0, 'ivs', 'attack'), 16, 'invalid'),
            (('combatants', 0, 'ivs', 'defense'), -1, 'invalid'),
            (('combatants', 0, 'ivs', 'hp'), True, 'invalid'),
            (('rules', 'cp_cap'), -1, 'invalid'),
            (('rules', 'cp_cap'), 2500, 'unsupported'),
            (('rules', 'league'), 'ultra', 'unsupported'),
            (('rules', 'cup_id'), 'some_cup', 'unsupported'),
            (('combatants', 0, 'moves', 'fast'), 'FAKE_MOVE', 'invalid'),
            (('combatants', 0, 'moves', 'charged'), ['AQUA_TAIL', 'AQUA_TAIL'], 'invalid'),
            (('combatants', 0, 'species_id'), 'unknown_species', 'invalid'),
            (('combatants', 0, 'species_id'), 'quagsire_unreleased_form', 'invalid'),
            (('combatants', 0, 'level'), 50, 'invalid'),
            (('combatants', 0, 'level'), 28.1, 'invalid'),
            (('combatants', 0, 'initial', 'hp'), 10000, 'invalid'),
            (('combatants', 0, 'initial', 'energy'), 101, 'invalid'),
            (('combatants', 0, 'initial', 'shields'), -1, 'invalid'),
            (('combatants', 0, 'initial', 'stages'), [0, 5], 'invalid'),
            (('combatants', 0, 'initial', 'stages'), [0, float('inf')], 'invalid'),
            (('combatants', 0, 'initial', 'file_path'), '/data/game.json', 'invalid'),
            (('gamemaster_path',), '/data/game.json', 'invalid'),
            (('calculation_version',), '0' * 64, 'unsupported'),
        ]
        with patch.object(self.client, 'strategy') as run:
            for path, value, status in cases:
                with self.subTest(path=path, value=value):
                    spec = battle_spec()
                    target = spec
                    for field in path[:-1]:
                        target = target[field]
                    target[path[-1]] = value
                    result = self.service.simulate(spec)
                    self.assertEqual(result['status'], status, result)
                    self.assertNotIn('outcome', result)
                    self.assertNotIn('rating', result)
            for data in ('{', b'\xff', '{"energy": NaN}', '{"a":0,"a":1}', '[' * 2000,
                         b' ' * (128 * 1024 + 1)):
                self.assertEqual(self.service.simulate(data)['status'], 'invalid')
            run.assert_not_called()

    def test_sandbox_and_manual_shield_policy_are_rejected(self):
        spec = battle_spec()
        spec['mode'] = 'sandbox'
        spec['actions'] = [{'id': 'a', 'actor': 0, 'turn': 1, 'kind': 'charged', 'move_id': 'AQUA_TAIL'}]
        spec['shield_decisions'] = [{'action_id': 'a', 'defender': 1, 'use_shield': True}]
        with patch.object(self.client, 'strategy') as run:
            self.assertEqual(self.service.simulate(spec)['status'], 'unsupported')
            spec['shield_decisions'][0]['defender'] = 0
            self.assertEqual(self.service.simulate(spec)['status'], 'invalid')
            spec = battle_spec()
            spec['policies'] = {'shield': ['manual', 'standard']}
            self.assertEqual(self.service.simulate(spec)['status'], 'unsupported')
            run.assert_not_called()

    def test_key_normalizes_defaults_and_separates_combat_conditions(self):
        spec = battle_spec()
        baseline = self.service.simulate(spec)
        explicit = copy.deepcopy(baseline['spec'])
        explicit['rules'] = dict(reversed(list(explicit['rules'].items())))
        self.assertEqual(self.service.simulate(explicit)['battle_key'], baseline['battle_key'])
        for field, value in (('energy', 1), ('shields', 0), ('stages', [0, 1]), ('hp', 1)):
            changed = copy.deepcopy(spec)
            changed['combatants'][0]['initial'][field] = value
            self.assertNotEqual(self.service.simulate(changed)['battle_key'], baseline['battle_key'])

    def test_engine_timeout_is_partial_and_not_a_loss(self):
        spec = battle_spec(2, 2, (0, 0))
        spec['policies'] = {'attack': ['fast_only', 'fast_only']}
        for combatant in spec['combatants']:
            combatant['initial']['stages'] = [-4, 4]
        result = self.service.simulate(spec)
        self.assertEqual((result['status'], result['outcome']), ('partial', 'timeout'))
        self.assertTrue(all(state['hp'] > 0 for state in result['terminal']))

    def test_failed_result_does_not_leak_engine_error_or_fake_metrics(self):
        with patch.object(self.client, 'strategy', side_effect=DirectMatrixError('internal /data/path')):
            result = self.service.simulate(battle_spec())
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('/data/path', str(result))
        self.assertNotIn('outcome', result)
        self.assertNotIn('rating', result)

    def test_data_update_during_client_lifetime_does_not_publish_a_result(self):
        master = self.client.gamemaster
        master.write_bytes(master.read_bytes() + b'\n')
        self.assertEqual(self.service.simulate(battle_spec())['status'], 'failed')
        new = BattleService(self.client)
        self.assertEqual(new.simulate(battle_spec())['status'], 'complete')
        self.assertNotEqual(self.service.calculation_version, new.calculation_version)

    def test_shedinja_full_hp_follows_the_engine_special_case(self):
        master = self.client.gamemaster
        data = json.loads(master.read_bytes())
        pokemon = next(p for p in data['pokemon'] if p['speciesId'] == ROWS[0]['species'])
        # Synthetic fixture exercises the pinned dex-292 HP rule with a known moveset.
        data['pokemon'].append({**pokemon, 'speciesId': 'shedinja', 'dex': 292,
                                'baseStats': {**pokemon['baseStats'], 'hp': 1}})
        master.write_text(json.dumps(data), encoding='utf-8')
        service = BattleService(self.client)
        spec = battle_spec()
        spec['combatants'][0].update(species_id='shedinja', level=50)
        result = service.simulate(spec)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(result['spec']['combatants'][0]['initial']['hp'], 10)
        self.assertEqual(result['terminal'][0]['max_hp'], 10)
        spec['combatants'][0]['initial']['hp'] = 11
        self.assertEqual(service.simulate(spec)['status'], 'invalid')

    def test_invalid_engine_result_is_not_reported_as_complete(self):
        spec = battle_spec()
        _, payload = self.service._prepare(spec)
        raw = self.client.strategy('detail', payload, include_engine_sources=True)
        cases = (
            {'rating': 'not a rating'},
            {'damage': []},
            {'events': [{**raw['events'][0], 'unexpected': 'internal metadata'}]},
        )
        for replacement in cases:
            with self.subTest(replacement=replacement), patch.object(
                self.client, 'strategy', return_value={**raw, **replacement}
            ):
                result = self.service.simulate(spec)
                self.assertEqual(result['status'], 'failed', result)
                self.assertNotIn('internal metadata', str(result))

    def test_running_engine_does_not_claim_an_updated_source_version(self):
        root = self.client.gamemaster.parent
        source = root / 'engine'
        shutil.copytree(self.client.source, source)
        client = DirectMatrixClient(gamemaster=self.client.gamemaster, log_dir=root, source=source)
        self.addCleanup(client.close)
        spec = battle_spec()
        before = BattleService(client).simulate(spec)
        self.assertEqual(before['status'], 'complete')
        battle = source / 'src/js/battle/Battle.js'
        battle.write_bytes(battle.read_bytes() + b'\n// newer revision\n')
        updated = BattleService(client)
        self.assertNotEqual(before['spec']['calculation_version'], updated.calculation_version)
        self.assertEqual(updated.simulate(spec)['status'], 'failed')
