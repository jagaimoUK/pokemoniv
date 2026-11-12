"""Independent regression cases for species-aware IV search eligibility."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pvpoke_battle_service import BattleService
from pvpoke_battle_store import BattleStore
from pvpoke_direct_backend import DirectMatrixClient
from pvpoke_iv_search import IVSearch
from pvpoke_role_evaluation import condition_id
from test_battle_service import FIXTURES, battle_spec


def decoded_ivs(bits):
    value = int.from_bytes(bytes.fromhex(bits), 'little')
    return [(i >> 8, (i >> 4) & 15, i & 15) for i in range(4096) if value >> i & 1]


class AstraIVEligibilityTests(unittest.TestCase):
    def service(self, *, side=0, tags=('untradeable',)):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        request = battle_spec()
        data = json.loads((FIXTURES / 'strategy_gamemaster.json').read_text())
        species = request['combatants'][side]['species_id']
        next(row for row in data['pokemon'] if row['speciesId'] == species)['tags'] = list(tags)
        master = root / 'synthetic.json'
        master.write_text(json.dumps(data))
        client = DirectMatrixClient(gamemaster=master, log_dir=root)
        self.addCleanup(client.close)
        service = BattleService(client, store=BattleStore(root / 'isolated.sqlite3'))
        return service, IVSearch(service), request

    def test_untradeable_self_search_never_qualifies_below_catalogue_floor(self):
        service, search, request = self.service()
        search_id = search.start([request])
        role = {'role_id': 'review', 'revision': 1, 'priority': 1, 'meta_snapshot': 'a' * 64,
                'requirements': {condition_id(service._prepare(request)[0], full_hp=True):
                                 {'minimum': {'fast_damage': 0}}}}
        result = search.step(search_id, budget=8, role=role)
        eligible = decoded_ivs(result['coverage']['eligible_ivs'])
        qualifying = decoded_ivs(result['coverage']['qualifying_ivs'])
        self.assertEqual(result['coverage']['eligible_iv_count'], 6 ** 3)
        self.assertTrue(qualifying)
        self.assertTrue(all(min(ivs) >= 10 for ivs in eligible + qualifying))
        self.assertEqual(result['new_battles'], 8)

    def test_opponent_search_combines_species_and_explicit_per_axis_floors(self):
        service, search, request = self.service(side=1)
        result = search.opponent_boundaries(request, iv_floors=(0, 14, 15))
        self.assertEqual(result['iv_floors'], [10, 14, 15])
        self.assertEqual(result['eligible_iv_count'], 12)
        self.assertTrue(all(row['attack'] >= 10 and row['defense'] >= 14 and row['hp'] == 15
                            for row in result['representatives']))
        self.assertEqual(service.cache_stats['engine_calls'], 0)
        self.assertFalse(result['battle_outcomes_verified'])

    def test_shadow_legendary_search_uses_six_with_stricter_requested_axes(self):
        _, search, request = self.service(tags=('legendary', 'shadow', 'wildlegendary'))
        search_id = search.start([request], iv_floors=(0, 14, 15))
        result = search.step(search_id)
        self.assertEqual(result['iv_floors'], [6, 14, 15])
        self.assertEqual(result['coverage']['eligible_iv_count'], 20)
        self.assertEqual(result['new_battles'], 0)

    def test_floor_implementation_version_change_rejects_old_checkpoint(self):
        from pvpoke_iv_search import content_hash

        service, search, request = self.service()
        old_id = search.start([request], iv_floors=(15, 15, 15))
        previous = search.step(old_id, budget=1)
        calls = service.cache_stats['engine_calls']
        def changed_hash(path):
            return 'f' * 64 if path.name == 'pvpoke_iv_modes.py' else content_hash(path)
        with patch('pvpoke_iv_search.content_hash', side_effect=changed_hash):
            stale = search.step(old_id, budget=1)
            self.assertEqual(stale['state'], 'stale')
            self.assertIsNone(stale['coverage'])
            self.assertEqual(stale['new_battles'], 0)
            new_id = search.start([request], iv_floors=(15, 15, 15))
            self.assertNotEqual(new_id, old_id)
            self.assertEqual(search.step(new_id)['coverage'], previous['coverage'])
        self.assertEqual(service.cache_stats['engine_calls'], calls)
        self.assertEqual(search.step(old_id)['coverage'], previous['coverage'])
