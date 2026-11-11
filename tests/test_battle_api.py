"""Opt-in battle API: authenticated gateway, local admission and persisted HTTP results.

All listeners bind localhost and use synthetic credentials and disposable storage.
"""
import copy
import http.client
import json
import os
from pathlib import Path
import shutil
import statistics
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)
import pvpoke_mcp_remote as gateway
import pvpoke_web as web
from pvpoke_battle_service import BattleService
from test_battle_service import FIXTURES, battle_spec


def post(server, path, body, *, token=None, origin=None, content_type='application/json'):
    connection = http.client.HTTPConnection(*server.server_address, timeout=75)
    headers = {'Content-Type': content_type}
    if token is not None:
        headers['Authorization'] = token
    if origin is not None:
        headers['Origin'] = origin
    connection.request('POST', path, body if isinstance(body, bytes) else json.dumps(body).encode(),
                       headers)
    response = connection.getresponse()
    code, raw = response.status, response.read()
    connection.close()
    return code, json.loads(raw) if raw else {}


class ServerFixture(unittest.TestCase):
    handler = None

    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class BattleGatewayTests(ServerFixture):
    handler = gateway.Handler
    path = '/app-api/battles/simulate'

    def request(self, spec=None, *, auth=True, **kwargs):
        return post(self.server, self.path, spec if spec is not None else battle_spec(),
                    token='Bearer ' + (gateway.API_KEY if auth else 'invalid'), **kwargs)

    def test_default_off_denies_without_forwarding(self):
        with patch.dict(os.environ, {'PVP_BATTLE_API_ENABLED': ''}), patch.object(
                gateway.backend, '_request') as backend:
            self.assertEqual(self.request()[0], 503)
            self.assertEqual(self.request(auth=False)[0], 401)
            backend.assert_not_called()

    def test_valid_request_is_a_single_fixed_internal_endpoint(self):
        with patch.dict(os.environ, {'PVP_BATTLE_API_ENABLED': '1'}), patch.object(
                gateway.backend, '_token', return_value='internal-test-token'), patch.object(
                gateway.backend, '_request', return_value={
                    'schema': 'battle-result-v1', 'status': 'complete'}) as backend:
            self.assertEqual(self.request()[0], 200)
            backend.assert_called_once_with('/api/battles/simulate', battle_spec(),
                headers={'X-PvPoke-Token': 'internal-test-token'}, timeout=65)
            self.assertEqual(self.request(origin='https://attacker.example')[0], 403)
            self.assertEqual(self.request(auth=False)[0], 401)
            self.assertEqual(self.request(content_type='text/plain')[0], 415)
            self.assertEqual(post(self.server, self.path, b'{', token='Bearer '+gateway.API_KEY)[0], 400)
            self.assertEqual(post(self.server, self.path, b'{"a":1,"a":2}',
                                  token='Bearer '+gateway.API_KEY)[0], 400)
            self.assertEqual(post(self.server, self.path, b'{"a":NaN}',
                                  token='Bearer '+gateway.API_KEY)[0], 400)
            self.assertEqual(post(self.server, self.path, b' ' * (128*1024+1),
                                  token='Bearer '+gateway.API_KEY)[0], 413)
            self.assertEqual(post(self.server, '/app-api/battles/arbitrary', {},
                                  token='Bearer '+gateway.API_KEY)[0], 404)
            backend.assert_called_once()

    def test_backend_failures_never_leak_local_paths_or_tracebacks(self):
        with patch.dict(os.environ, {'PVP_BATTLE_API_ENABLED': '1'}), patch.object(
                gateway.backend, '_token', return_value='internal-test-token'), patch.object(
                gateway.backend, '_request', side_effect=gateway.backend.BridgeError(
                    'ローカルアプリ HTTP 503: /private/secrets.db\nTraceback')):
            code, body = self.request()
            self.assertEqual(code, 503)
            self.assertNotIn('/private', json.dumps(body))
            self.assertNotIn('Traceback', json.dumps(body))

    def test_short_app_bearer_and_remembered_cookie(self):
        with patch.dict(os.environ, {'PVP_BATTLE_API_ENABLED': '1'}), patch.object(
                gateway.backend, '_token', return_value='internal'), patch.object(
                gateway.backend, '_request', return_value={'status': 'complete'}):
            short = gateway.APP_ACCESS.issue(gateway.APP_ORIGIN)['url'].split('#access=')[1]
            self.assertEqual(post(self.server, self.path, battle_spec(), token='Bearer '+short)[0], 200)
            cookie = gateway.BROWSER_LOGIN.issue().split(';', 1)[0]
            c = http.client.HTTPConnection(*self.server.server_address, timeout=20)
            c.request('POST', self.path, json.dumps(battle_spec()),
                      {'Content-Type': 'application/json', 'Cookie': cookie,
                       'Origin': gateway.APP_ORIGIN})
            response = c.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            c.close()


class LocalBattleAPITests(ServerFixture):
    handler = web.Handler
    path = '/api/battles/simulate'

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copyfile(FIXTURES / 'strategy_gamemaster.json', self.root / 'gamemaster.json')
        self.env = patch.dict(os.environ, {
            'PVP_BATTLE_API_ENABLED': '1', 'PVP_ARCHIVE_DIR': str(self.root / 'volume')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.patches = [patch.object(web.engine, 'DATA', self.root),
                        patch.object(web, 'WORK', self.root / 'work'),
                        patch.dict(web.CATALOG, {'ready': True})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        with web.LOCK:
            self.assertFalse(web.BATTLE_RUNNING)
            web.STATUS['state'] = 'idle'
        super().setUp()

    def request(self, spec=None):
        return post(self.server, self.path, battle_spec() if spec is None else spec)

    def test_opt_in_invalid_unsupported_and_busy(self):
        with patch.dict(os.environ, {'PVP_BATTLE_API_ENABLED': ''}), patch.object(
                web, 'DirectMatrixClient') as node:
            self.assertEqual(self.request()[0], 503)
            node.assert_not_called()
        with web.LOCK:
            web.BATTLE_RUNNING = True
        try:
            self.assertEqual(self.request()[0], 409)
            with patch.object(web, 'DirectMatrixClient') as node:
                node.assert_not_called()
        finally:
            with web.LOCK:
                web.BATTLE_RUNNING = False
        with patch.object(web, 'DirectMatrixClient') as node, patch.object(
                web, 'BattleStore') as store:
            self.assertEqual(self.request({'schema': 'battle-spec-v1', 'owner_id': 'other'})[0], 400)
            # Malformed JSON is rejected before Node startup.
            self.assertEqual(post(self.server, self.path, b'{"schema":0,"schema":1}')[0], 400)
            node.assert_not_called()
            store.assert_not_called()
        with patch.object(web, 'BattleService') as service, patch.object(
                web, 'DirectMatrixClient'), patch.object(web.BattleStore, 'from_volume'):
            service.return_value.simulate.return_value = {'status': 'partial', 'rating': 50}
            code, data = self.request()
            self.assertEqual(code, 422)
            self.assertNotIn('rating', data)
        self.assertFalse(web.BATTLE_RUNNING)

    def test_completed_http_battle_is_durable_and_reused(self):
        created = []
        def make_service(client, *, store):
            instance = BattleService(client, store=store)
            created.append(instance)
            return instance
        with patch.object(web, 'BattleService', side_effect=make_service):
            began = time.perf_counter()
            first_code, first = self.request()
            new_ms = (time.perf_counter()-began) * 1000
            self.assertEqual(first_code, 200, first)
            self.assertEqual(first['status'], 'complete')
            self.assertEqual(created[-1].cache_stats['engine_calls'], 1)
            reused = []
            for _ in range(5):
                began = time.perf_counter()
                code, result = self.request()
                reused.append((time.perf_counter()-began)*1000)
                self.assertEqual(code, 200)
                self.assertEqual(result, first)
                self.assertEqual(created[-1].cache_stats['engine_calls'], 0)
                self.assertEqual(created[-1].cache_stats['hits'], 1)
            changed = copy.deepcopy(battle_spec())
            changed['combatants'][0]['initial']['energy'] = 80
            code, second = self.request(changed)
            self.assertEqual(code, 200, second)
            self.assertNotEqual(second['battle_key'], first['battle_key'])
            self.assertEqual(created[-1].cache_stats['engine_calls'], 1)
            self.assertEqual(self.request()[1], first)
            self.assertEqual(created[-1].cache_stats['hits'], 1)
        # Each HTTP request deliberately closes its Node process; SQLite is durable.
        from pvpoke_battle_store import BattleStore
        db = BattleStore.from_volume()
        self.assertTrue(db.path.is_file())
        self.assertEqual(len(list(db.path.parent.glob('battle_analysis.sqlite3'))), 1)
        self.assertFalse(web.BATTLE_RUNNING)
        s = sorted(reused)
        print('BATTLE_API_BENCH first_ms=%.2f reuse_median_ms=%.2f reuse_p95_ms=%.2f '
              'samples=5 new_calls=2 cache_hits=6' % (new_ms, statistics.median(s), s[-1]))


if __name__ == '__main__':
    unittest.main()
