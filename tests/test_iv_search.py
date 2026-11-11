from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_iv_search import IVSearch, _bitset, _pool, _prioritize
from pvpoke_missing_analysis import AnalysisUnavailable
from pvpoke_role_evaluation import condition_id
from test_battle_service import FIXTURES, battle_spec
from tools import cloud_migration_backup as backup


def indices(bits):
    raw = bytes.fromhex(bits)
    return {i for i in range(4096) if raw[i // 8] & 1 << (i % 8)}


class IVSearchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'volume' / 'battle_analysis.sqlite3')
        self.service = self.service_for(self.store)
        self.search = IVSearch(self.service)

    def service_for(self, store, game_data=None):
        client = DirectMatrixClient(gamemaster=game_data or FIXTURES / 'strategy_gamemaster.json',
                                    log_dir=self.root)
        self.addCleanup(client.close)
        return BattleService(client, store=store)

    def test_bitset_keeps_exact_iv_tuples(self):
        samples = {0x010, 0x101, 0x8fe, 0xfff}
        self.assertEqual(len(bytes.fromhex(_bitset(samples))), 512)
        self.assertEqual(indices(_bitset(samples)), samples)
        self.assertNotIn(0x111, indices(_bitset(samples)))

    def test_bounded_search_and_role_changes_reuse_existing_results(self):
        a, b = battle_spec(shields=(0, 0)), battle_spec(shields=(0, 1))
        specs = [a, b]
        with patch.object(self.service, 'simulate', side_effect=AssertionError('unexpected battle')):
            search_id = self.search.start(specs, iv_floors=(15, 15, 14))
            self.assertEqual(self.search.start(specs, iv_floors=(15, 15, 14)), search_id)
            first = self.search.step(search_id)
        self.assertEqual(first['state'], 'unknown')
        self.assertEqual(first['coverage']['raw_iv_count'], 4096)
        self.assertEqual(first['coverage']['eligible_iv_count'], 2)
        self.assertEqual(indices(first['coverage']['eligible_ivs']), {0xffe, 0xfff})
        self.assertEqual(first['new_battles'], 0)

        half = self.search.step(search_id, budget=1)
        self.assertEqual((half['state'], half['new_battles']), ('partial', 1))
        self.assertEqual(sum(c['completed_count'] for c in half['coverage']['conditions']), 1)
        self.assertEqual(half['coverage']['all_completed_iv_count'], 0)
        # A fresh service process resumes from the validated BattleStore evidence.
        restarted = IVSearch(self.service_for(self.store))
        self.assertEqual(restarted.step(search_id)['coverage'], half['coverage'])
        final = restarted.step(search_id, budget=3)
        self.assertEqual((final['state'], final['new_battles']), ('complete', 3))
        self.assertEqual(final['coverage']['all_completed_iv_count'], 2)
        role = dict(role_id='test', revision=1, priority=1, meta_snapshot='a' * 64,
                    requirements={condition_id(self.service._prepare(spec)[0], full_hp=True):
                                  {'minimum': {'fast_damage': 0}} for spec in specs})
        pass_set = restarted.step(search_id, budget=8, role=role)
        self.assertEqual(indices(pass_set['coverage']['qualifying_ivs']), {0xffe, 0xfff})
        self.assertEqual(pass_set['new_battles'], 0)
        role['requirements'][next(iter(role['requirements']))]['minimum']['fast_damage'] = 10000
        fail_set = restarted.step(search_id, role=role)
        self.assertEqual(indices(fail_set['coverage']['qualifying_ivs']), set())
        self.assertEqual(fail_set['new_battles'], 0)
        self.assertIsNone(IVSearch(self.service_for(BattleStore(self.store.path, owner_scope='other'))).step(search_id))

        target = self.root / 'backup'
        backup.backup({'volume': self.store.path.parent}, target)
        backup.verify(target)
        backup.restore(target, self.root / 'restored')
        restored = BattleStore(self.root / 'restored' / 'volume' / self.store.path.name)
        self.assertEqual(IVSearch(self.service_for(restored)).step(search_id)['coverage'], final['coverage'])

    def test_full_iv_pool_and_version_changes_do_not_claim_unplayed_matches(self):
        search_id = self.search.start([battle_spec()])
        initial = self.search.step(search_id)
        self.assertEqual(initial['coverage']['eligible_iv_count'], 4096)
        self.assertEqual(initial['coverage']['stat_iv_count'], 4096)
        self.assertEqual(initial['coverage']['all_completed_iv_count'], 0)
        self.assertEqual(self.service.cache_stats['engine_calls'], 0)
        self.assertTrue(indices(initial['coverage']['conditions'][0]['boundaries']['hp']))
        altered = self.root / 'altered.json'
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', altered)
        with altered.open('ab') as f:
            f.write(b'\n')
        changed = IVSearch(self.service_for(self.store, altered)).step(search_id, budget=1)
        self.assertEqual(changed['state'], 'stale')
        self.assertIsNone(changed['coverage'])
        self.assertEqual(changed['new_battles'], 0)

    def test_input_scope_and_corrupt_checkpoint_fail_closed(self):
        first = battle_spec()
        with self.assertRaises(ValueError):
            self.search.start([first, first])
        with self.assertRaises(ValueError):
            self.search.start([first, battle_spec(left=1)])
        with self.assertRaises(ValueError):
            self.search.start([first], iv_floors=(True, 1, 2))
        search_id = self.search.start([first], iv_floors=(15, 15, 15))
        with self.assertRaises(ValueError):
            self.search.step(search_id, budget=33)
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE important_iv_searches_v1 SET next_offset=1')
        with self.assertRaises(AnalysisUnavailable):
            self.search.step(search_id)
        self.assertEqual(self.service.cache_stats['engine_calls'], 0)

    def test_corrupt_saved_battle_does_not_consume_budget_or_change_database(self):
        search_id = self.search.start([battle_spec()], iv_floors=(15, 15, 15))
        self.assertEqual(self.search.step(search_id, budget=1)['state'], 'complete')
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE battle_results SET result_sha256=?', ('bad',))
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(AnalysisUnavailable, 'Could not read saved IV evidence'):
            self.search.step(search_id, budget=1)
        self.assertEqual(self.service.cache_stats['engine_calls'], 1)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_close_battle_prioritizes_an_unplayed_neighbor_within_budget(self):
        spec = battle_spec(left=0, right=0, shields=(0, 0))
        normalized, _ = self.service._prepare(spec)
        rows, _ = _pool(self.service, normalized, (14, 14, 15))
        pivot = rows[0xeef]
        spec['combatants'][1].update(
            level=pivot['level'], ivs={'attack': 14, 'defense': 14, 'hp': 15},
        )

        def order(profiles, stats, count, default_index):
            _, boundaries = _prioritize(profiles, stats, count, default_index)
            return [0xeef, 0xfff, 0xeff, 0xfef], boundaries

        with patch('pvpoke_iv_search._prioritize', side_effect=order):
            search_id = self.search.start([spec], iv_floors=(14, 14, 15))
        self.assertEqual(self.search.step(search_id, budget=1)['new_battles'], 1)
        step = self.search.step(search_id, budget=2)
        self.assertEqual(step['new_battles'], 2)
        self.assertEqual(indices(step['coverage']['all_completed_ivs']), {0xeef, 0xfff, 0xfef})
        self.assertEqual(self.search.step(search_id, budget=1)['state'], 'complete')
