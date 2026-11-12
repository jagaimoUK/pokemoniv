from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import shutil
import tempfile
from unittest.mock import patch

import test_battle_api as server
from pvpoke_battle_store import BattleStore
from pvpoke_sandbox import SandboxService
from pvpoke_sandbox_workspace import API_PATH, APP_PATH, PAGE_PATH, TacticConflict, TacticStore
from test_missing_comparison import request
from test_sandbox import FIXTURES, scripted_spec
from tools import cloud_migration_backup as backup


TACTIC = 'a' * 32


class SandboxGatewayTests(server.ServerFixture):
    handler = server.gateway.Handler

    def setUp(self):
        self.enterContext(patch.object(server.gateway, 'RATE_BUDGET', server.RateBudget()))
        super().setUp()

    def test_only_authenticated_same_origin_reaches_fixed_backend(self):
        auth = {'Authorization': 'Bearer ' + server.gateway.API_KEY, 'Content-Type': 'application/json'}
        payload = {'action': 'list'}
        with patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '0'}):
            self.assertEqual(request(self.server, PAGE_PATH)[0], 404)
            self.assertEqual(request(self.server, APP_PATH, payload, headers=auth)[0], 503)
        with patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '1'}), patch.object(
                server.gateway.backend, '_token', return_value='internal-test-token'), patch.object(
                server.gateway.backend, '_request', return_value={'items': []}) as call:
            code, html, headers = request(self.server, PAGE_PATH)
            self.assertEqual(code, 200)
            self.assertIn('対戦サンドボックス'.encode(), html)
            self.assertNotIn(server.gateway.API_KEY.encode(), html)
            self.assertIn('Content-Security-Policy', headers)
            self.assertEqual(request(self.server, APP_PATH, payload)[0], 401)
            self.assertEqual(request(self.server, APP_PATH, payload, headers={**auth, 'Origin': 'https://other.invalid'})[0], 403)
            self.assertEqual(request(self.server, APP_PATH, b'{"action":"list","action":"save"}', headers=auth)[0], 400)
            nested = b'{"action":"list","x":' + b'[' * 10000 + b'0' + b']' * 10000 + b'}'
            self.assertEqual(request(self.server, APP_PATH, nested, headers=auth)[0], 400)
            self.assertEqual(request(self.server, APP_PATH, payload, headers=auth)[0], 200)
            call.assert_called_once_with(API_PATH, payload, headers={'X-PvPoke-Token': 'internal-test-token'}, timeout=65)


class SandboxLocalTests(server.ServerFixture):
    handler = server.web.Handler

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', self.root / 'gamemaster.json')
        self.enterContext(patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '1',
                                                 'PVP_ARCHIVE_DIR': str(self.root / 'volume')}))
        self.enterContext(patch.object(server.web.engine, 'DATA', self.root))
        self.enterContext(patch.object(server.web, 'WORK', self.root / 'work'))
        self.enterContext(patch.dict(server.web.CATALOG, {'ready': True}))
        self.enterContext(patch.dict(server.web.STATUS, {'state': 'idle'}))
        super().setUp()

    def call(self, payload):
        headers = {'Content-Type': 'application/json', 'X-PvPoke-Token': server.web.TOKEN}
        status, body, _ = request(self.server, API_PATH, payload, headers=headers)
        return status, json.loads(body)

    def test_compute_compare_revision_conflict_and_restoration(self):
        spec = scripted_spec()
        self.assertEqual(request(self.server, API_PATH, {'action': 'list'})[0], 403)
        with patch.object(server.web, 'DirectMatrixClient') as node:
            self.assertEqual(self.call({'action': 'list'}), (200, {'items': []}))
            node.assert_not_called()
        create = {'action': 'save', 'tactic_id': TACTIC, 'expected_revision': 0,
                  'name': 'ヌオーの技順', 'spec': spec}
        with patch.object(SandboxService, 'simulate') as simulate:
            code, first = self.call(create)
            self.assertEqual((code, first['revision']), (200, 1))
            self.assertEqual(self.call(create), (200, first))
            update = {**create, 'expected_revision': 1, 'name': '新しい技順'}
            code, second = self.call(update)
            self.assertEqual((code, second['revision']), (200, 2))
            self.assertEqual(self.call({**update, 'name': '古いタブ'})[0], 409)
            self.assertEqual(self.call({'action': 'load', 'tactic_id': TACTIC, 'revision': 1}),
                             (200, {**first, 'latest_revision': 2}))
            self.assertEqual(self.call({'action': 'load', 'tactic_id': TACTIC}), (200, second))
            self.assertEqual(self.call({'action': 'load', 'tactic_id': TACTIC, 'owner_scope': 'other'})[0], 400)
            simulate.assert_not_called()
        with patch.dict(server.web.STATUS, {'state': 'running'}):
            self.assertEqual(self.call({'action': 'simulate', 'spec': spec})[0], 409)
            self.assertEqual(self.call({'action': 'list'})[0], 200)
        code, sandbox = self.call({'action': 'simulate', 'spec': spec})
        self.assertEqual((code, sandbox['status']), (200, 'complete'))
        code, standard = self.call({'action': 'standard', 'spec': spec})
        self.assertEqual((code, standard['status']), (200, 'complete'))
        self.assertNotEqual(sandbox['summary']['battle_key'], standard['battle_key'])
        self.assertEqual(standard['spec']['actions'], [])
        self.assertFalse(server.web.BATTLE_RUNNING)

        store = BattleStore.from_volume()
        self.assertIsNone(TacticStore(BattleStore(store.path, owner_scope='foreign')).load(TACTIC))
        self.assertEqual([i['revision'] for i in self.call({'action': 'list'})[1]['items']], [2])
        bundle = self.root / 'bundle'
        backup.backup({'volume': store.path.parent}, bundle)
        backup.verify(bundle)
        backup.restore(bundle, self.root / 'restored')
        restored = TacticStore(BattleStore(self.root / 'restored' / 'volume' / store.path.name))
        self.assertEqual(restored.load(TACTIC, 1)['name'], first['name'])
        self.assertEqual(restored.load(TACTIC)['name'], second['name'])

    def test_concurrent_save_conflicts_without_overwrite(self):
        class Normalizer:
            @staticmethod
            def prepare(spec):
                return spec, None

        store = TacticStore(BattleStore.from_volume())
        spec = scripted_spec()
        store.save(Normalizer(), TACTIC, 0, 'first', spec)

        def attempt(name):
            try:
                return store.save(Normalizer(), TACTIC, 1, name, spec)
            except TacticConflict:
                return None

        with ThreadPoolExecutor(2) as pool:
            results = [value for value in pool.map(attempt, ('second', 'third')) if value is not None]
        self.assertEqual(len(results), 1)
        self.assertEqual(store.load(TACTIC), results[0])
        self.assertEqual(store.load(TACTIC, 1)['name'], 'first')
