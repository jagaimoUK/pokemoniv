"""Verify selection snapshots on a pre-feature database and its portable backup."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from pvpoke_battle_store import BattleStore
from pvpoke_ownership import Ownership, OwnershipConflict
from pvpoke_selection_history import app_operation
import pvpoke_web as web
from tools import cloud_migration_backup as backup


class SelectionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BattleStore(self.root / 'old-volume' / 'battle_analysis.sqlite3')
        self.species = {'quagsire', 'wooper_paldean'}
        self.observation = dict(species_id='quagsire', ivs=dict(attack=0, defense=11, hp=12))
        self.inventory = Ownership(self.store, species_ids=self.species)
        self.inventory.register('confirmed-individual', self.observation)
        self.inventory.confirm('old-event', 'confirmed-individual', expected_revision=0,
                               state='confirmed_owned')
        self.previous = backup.sqlite_inventory(self.store.path)

    def payload(self, request='save-1', species='quagsire', goal='PL 29, add second move'):
        return dict(action='selection_save', request_id=request, species_id=species,
                    meta_sha256='a' * 64, calculation_version='b' * 64,
                    policy_version='box-first-v3', candidates=[
                        dict(ivs='0/11/12', role='important', instance_id='confirmed-individual',
                             goal=goal, moves=['MUD_SHOT', 'STONE_EDGE', 'MUD_BOMB'],
                             evidence=['Synthetic shield matchup']),
                        dict(ivs='0/12/11', role='alternative',
                             moves=['MUD_SHOT', 'STONE_EDGE', 'MUD_BOMB'], evidence=[]),
                    ])

    def operation(self, payload, store=None):
        return app_operation(store or self.store, payload, self.species)

    def latest(self, species, store=None):
        return self.operation(dict(action='selection_latest', species_id=species), store)['snapshot']

    def history(self, store=None, **cursor):
        return self.operation(dict(action='selection_history', instance_id='confirmed-individual', **cursor), store)

    def test_legacy_history_reopen_and_isolated_restore(self):
        self.assertIsNone(self.latest('quagsire'))
        self.assertEqual(self.history()['items'], [])
        self.assertEqual(backup.sqlite_inventory(self.store.path), self.previous)

        first = self.operation(self.payload())
        self.assertEqual(self.operation(self.payload()), first)
        with self.assertRaises(OwnershipConflict):
            self.operation(self.payload(goal='different data with same request ID'))
        second = self.operation(self.payload('save-2', goal='PL 29.5'))
        regional = self.payload('save-3', species='wooper_paldean')
        regional['candidates'] = regional['candidates'][1:]
        self.operation(regional)

        reopened = BattleStore(self.store.path)
        self.assertEqual(self.latest('quagsire', reopened)['revision'], second['revision'])
        self.assertEqual(self.latest('quagsire', reopened)['candidates'][1]['role'], 'alternative')
        self.assertEqual(len(self.latest('wooper_paldean', reopened)['candidates']), 1)
        history = self.history(reopened)['items']
        self.assertEqual([item['evaluation']['goal'] for item in history], ['PL 29.5', 'PL 29, add second move'])
        self.assertEqual(history[0]['evaluation']['evidence'], ['Synthetic shield matchup'])
        self.assertEqual(history[0]['meta_sha256'], 'a' * 64)
        self.assertEqual(history[0]['calculation_version'], 'b' * 64)
        restarted = subprocess.check_output([sys.executable, '-B', '-c',
            'import json, sys; from pathlib import Path; '
            'from pvpoke_battle_store import BattleStore; '
            'from pvpoke_selection_history import app_operation; '
            'print(json.dumps(app_operation(BattleStore(Path(sys.argv[1])), '
            '{"action":"selection_history","instance_id":"confirmed-individual"})))',
            str(reopened.path)], timeout=10)
        self.assertEqual(json.loads(restarted)['items'], history)

        before_backup = backup.sqlite_inventory(reopened.path)
        for name, entry in self.previous['tables'].items():
            self.assertEqual(before_backup['tables'][name], entry)
        self.assertEqual(before_backup['user_version'], self.previous['user_version'])
        bundle, restore = self.root / 'bundle', self.root / 'restore'
        self.assertTrue(backup.backup({'volume': reopened.path.parent}, bundle)['verified'])
        backup.verify(bundle)
        backup.restore(bundle, restore)
        restored = BattleStore(restore / 'volume' / reopened.path.name)
        self.assertEqual(backup.sqlite_inventory(restored.path), before_backup)
        self.assertEqual(self.latest('quagsire', restored), self.latest('quagsire'))
        self.assertEqual(self.history(restored), self.history())
        foreign = BattleStore(restored.path, owner_scope='another-owner')
        self.assertIsNone(self.latest('quagsire', foreign))
        self.assertEqual(self.history(foreign)['items'], [])

    def test_backend_route_saves_and_reads_without_computation(self):
        def post(payload, token):
            handler = Mock()
            handler.path = web.MISSING_API_PATH
            handler._trusted_local_host.return_value = True
            raw = json.dumps(payload).encode()
            handler.rfile = io.BytesIO(raw)
            handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw)),
                               'X-PvPoke-Token': token}
            web.Handler.do_POST(handler)
            return handler.respond.call_args.args

        with (patch.dict('os.environ', {'PVP_MISSING_ANALYSIS_ENABLED': '1'}),
              patch.object(web, 'CATALOG', {'species': {'quagsire': {}}}),
              patch.object(web.BattleStore, 'from_volume', return_value=self.store),
              patch.object(web, 'try_reserve_compute') as reserve):
            self.assertEqual(post(self.payload(), 'invalid-token')[0], 403)
            status, written = post(self.payload(), web.TOKEN)
            self.assertEqual(status, 200)
            status, response = post(dict(action='selection_latest', species_id='quagsire'), web.TOKEN)
            self.assertEqual(status, 200)
            self.assertEqual(response['snapshot']['revision'], written['revision'])
            reserve.assert_not_called()

    def test_pool_uses_only_latest_requested_forms_in_owner_scope(self):
        query = dict(action='selection_pool', species_ids=['quagsire', 'wooper', 'wooper_paldean', 'quagsire'])
        self.assertEqual(self.operation(query), {'snapshots': {}})
        self.operation(self.payload())
        latest = self.payload('new', goal='Current goal')
        latest['candidates'][1]['ivs'] = '1/15/14'
        latest['candidates'].append(dict(latest['candidates'][1]))
        revision = self.operation(latest)['revision']
        regional = self.payload('regional', species='wooper_paldean')
        regional['candidates'] = regional['candidates'][1:]
        self.operation(regional)

        before = backup.sqlite_inventory(self.store.path)
        pool = self.operation(query)['snapshots']
        self.assertEqual(set(pool), {'quagsire', 'wooper_paldean'})
        self.assertEqual(pool['quagsire'], {
            'revision': revision, 'ivs': ['0/11/12', '1/15/14'],
            'links': [{'ivs': '0/11/12', 'instance_id': 'confirmed-individual', 'goal': 'Current goal'}],
        })
        self.assertEqual(pool['wooper_paldean']['ivs'], ['0/12/11'])
        foreign = BattleStore(self.store.path, owner_scope='another-owner')
        self.assertEqual(self.operation(query, foreign), {'snapshots': {}})
        self.assertEqual(backup.sqlite_inventory(self.store.path), before)

    def test_invalid_link_does_not_replace_latest_or_create_partial_history(self):
        first = self.operation(self.payload())
        for edits in ({'ivs': '15/15/15'}, {'instance_id': 'unknown'}, {'instance_id': None}):
            attempt = copy.deepcopy(self.payload('save-2'))
            attempt['candidates'][0].update(edits)
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                self.operation(attempt)
            self.assertEqual(self.latest('quagsire')['revision'], first['revision'])
            self.assertEqual(len(self.history()['items']), 1)

    def test_empty_latest_keeps_old_history_and_cursor(self):
        for i in range(21):
            self.operation(self.payload(f'save-{i}'))
        empty = self.payload('empty')
        empty['candidates'] = []
        self.operation(empty)
        self.assertEqual(self.latest('quagsire')['candidates'], [])
        first = self.history()
        second = self.history(before=first['next_before'])
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(len(second['items']), 1)
        self.assertLess(second['items'][0]['revision'], first['next_before'])
        self.assertIsNone(second['next_before'])
