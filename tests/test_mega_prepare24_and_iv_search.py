import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import pvpoke_24_workflow as wf
import pvpoke_batch_v2 as engine
from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_iv_search import IVSearch, _pool
import pvpoke_result_cache as result_cache
import pvpoke_web as web


class MegaPrepare24AndIVSearchTests(unittest.TestCase):
    def test_normalize_pokemon_options_validates_mega_level_and_charged3(self):
        web.load_catalog()
        catalog = web.CATALOG['species']
        opts = web.normalize_pokemon_options(
            {
                'species': 'beedrill_mega',
                'fast': 'BUG_BITE',
                'charged1': 'AERIAL_ACE',
                'charged2': 'SLUDGE_BOMB',
                'mega_level': 3,
                'charged3': 'FELL_STINGER_PLUS',
            },
            catalog,
            '自分',
        )
        self.assertEqual(opts, {'mega_level': 3, 'charged3': 'FELL_STINGER_PLUS'})

        with self.assertRaises(ValueError):
            web.normalize_pokemon_options(
                {'species': 'quagsire', 'fast': 'MUD_SHOT', 'charged1': 'AQUA_TAIL', 'charged2': 'STONE_EDGE', 'mega_level': 3},
                catalog,
                '自分',
            )
        with self.assertRaises(ValueError):
            web.normalize_pokemon_options(
                {'species': 'beedrill_mega', 'fast': 'BUG_BITE', 'charged1': 'AERIAL_ACE', 'charged2': 'SLUDGE_BOMB', 'mega_level': 5},
                catalog,
                '自分',
            )
        with self.assertRaises(ValueError):
            web.normalize_pokemon_options(
                {'species': 'beedrill_mega', 'fast': 'BUG_BITE', 'charged1': 'AERIAL_ACE', 'charged2': 'SLUDGE_BOMB', 'charged3': 'AERIAL_ACE'},
                catalog,
                '自分',
            )

    def test_prepare_payload_and_save_input_preserve_mega_options(self):
        web.load_catalog()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prev = (web.WORK, web.CAND, web.OPPS, web.LAST_CONFIG, engine.CAND, engine.OPPS)
            try:
                web.WORK = root
                web.CAND = root / 'candidates.csv'
                web.OPPS = root / 'opponents.csv'
                web.LAST_CONFIG = root / 'last.json'
                engine.CAND = web.CAND
                engine.OPPS = web.OPPS
                cleaned, crows, orows, preview = web.prepare_payload({
                    'candidate': {
                        'species': 'beedrill_mega',
                        'fast': 'BUG_BITE',
                        'charged1': 'AERIAL_ACE',
                        'charged2': 'SLUDGE_BOMB',
                        'mega_level': 2,
                        'charged3': 'FELL_STINGER_PLUS',
                    },
                    'ivs': '0,15,15',
                    'opponents': [{
                        'species': 'azumarill',
                        'fast': 'BUBBLE',
                        'charged1': 'ICE_BEAM',
                        'charged2': 'PLAY_ROUGH',
                        'iv_mode': 'default',
                    }],
                    'shields': 'all',
                })
                self.assertEqual(cleaned['candidate']['mega_level'], 2)
                self.assertEqual(cleaned['candidate']['charged3'], 'FELL_STINGER_PLUS')
                self.assertEqual(len(preview['candidates']), 1)
                web.save_input(cleaned, crows, orows)
                loaded = engine.get_rows(web.CAND)
                self.assertEqual(loaded[0]['mega_level'], 2)
                self.assertEqual(loaded[0]['charged3'], 'FELL_STINGER_PLUS')
            finally:
                web.WORK, web.CAND, web.OPPS, web.LAST_CONFIG, engine.CAND, engine.OPPS = prev

    def test_24_workflow_input_config_and_result_cache_separate_mega_options(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / 'batch.json'
            cfg.write_text(json.dumps({
                'candidate': {
                    'species': 'beedrill_mega',
                    'fast': 'BUG_BITE',
                    'charged1': 'AERIAL_ACE',
                    'charged2': 'SLUDGE_BOMB',
                    'mega_level': 4,
                    'charged3': 'FELL_STINGER_PLUS',
                },
                'ivs': '0,15,15',
            }), encoding='utf-8')
            cand, _ = wf.input_config(cfg)
            self.assertEqual(cand['mega_level'], 4)
            self.assertEqual(cand['charged3'], 'FELL_STINGER_PLUS')

            c1 = result_cache.context(
                {'species': 'beedrill_mega', 'fast': 'BUG_BITE', 'charged1': 'AERIAL_ACE', 'charged2': 'SLUDGE_BOMB', 'mega_level': 1},
                [(0, 15, 15)], 'simple', 'm' * 64, 'v' * 64, 1500, 50,
            )
            c3 = result_cache.context(
                {'species': 'beedrill_mega', 'fast': 'BUG_BITE', 'charged1': 'AERIAL_ACE', 'charged2': 'SLUDGE_BOMB', 'mega_level': 3, 'charged3': 'FELL_STINGER_PLUS'},
                [(0, 15, 15)], 'simple', 'm' * 64, 'v' * 64, 1500, 50,
            )
            self.assertNotEqual(c1['key'], c3['key'])

            zpath = root / 'bundle.zip'
            with zipfile.ZipFile(zpath, 'w') as zf:
                zf.writestr('manifest.json', json.dumps({
                    'batch_mode': 'simple',
                    'meta_sha256': 'm' * 64,
                    'calculation_version': 'v' * 64,
                    'cp_cap': 1500,
                    'max_level': 50,
                    'candidates': 1,
                    'engine': {'browser_fallbacks': 0},
                }))
                zf.writestr('ranking_summary.csv',
                            'opponent_iv_mode,species,fast,charged1,charged2,atk,def,hp\n'
                            'default,beedrill_mega,BUG_BITE,AERIAL_ACE,SLUDGE_BOMB,0,15,15\n')
                for name in ('default_s0.csv', 'default_s1.csv', 'default_s2.csv',
                             'default_i0y1.csv', 'default_i0y2.csv', 'default_i1y2.csv'):
                    zf.writestr(name, 'candidate,azumarill,Wins,Losses,Draws,Average\n0/15/15,500,1,0,0,500\n')
            result_cache._validate(zpath, c3['request'])

    def test_iv_search_mega_level_and_charged3_pool_boundaries_and_step(self):
        engine.game_data()
        gm_path = engine.DATA / 'gamemaster.json'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = BattleStore(root / 'battle.sqlite3')
            client = DirectMatrixClient(gamemaster=gm_path, log_dir=root)
            self.addCleanup(client.close)
            service = BattleService(client, store=store)
            search = IVSearch(service)

            req_lv3 = {
                'schema': 'battle-spec-v1',
                'mode': 'standard',
                'rules': {'league': 'great', 'cp_cap': 1500, 'max_level': 50, 'cup_id': 'great_mega'},
                'combatants': [
                    {
                        'species_id': 'beedrill_mega',
                        'ivs': {'attack': 0, 'defense': 11, 'hp': 15},
                        'level': 16.5,
                        'moves': {'fast': 'BUG_BITE', 'charged': ['AERIAL_ACE', 'SLUDGE_BOMB', 'FELL_STINGER_PLUS']},
                        'mega_level': 3,
                        'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
                    },
                    {
                        'species_id': 'azumarill',
                        'ivs': {'attack': 0, 'defense': 15, 'hp': 15},
                        'level': 45.5,
                        'moves': {'fast': 'BUBBLE', 'charged': ['ICE_BEAM', 'PLAY_ROUGH']},
                        'initial': {'hp': 'full', 'energy': 0, 'shields': 1, 'stages': [0, 0]},
                    },
                ],
            }
            req_lv1 = {
                **req_lv3,
                'combatants': [{**req_lv3['combatants'][0], 'mega_level': 1}, req_lv3['combatants'][1]],
            }
            with self.assertRaises(ValueError):
                search.start([req_lv3, req_lv1])

            search_id = search.start([req_lv3])
            plan, _ = search._load(search_id)
            rows, _ = _pool(service, plan['source']['templates'][0], plan['source']['floors'])
            sample_row = next(iter(rows.values()))
            self.assertEqual(sample_row['mega_level'], 3)
            self.assertEqual(sample_row['charged3'], 'FELL_STINGER_PLUS')

            stepped = search.step(search_id, budget=2)
            self.assertEqual(stepped['coverage']['conditions'][0]['completed_count'], 2)


if __name__ == '__main__':
    unittest.main()
