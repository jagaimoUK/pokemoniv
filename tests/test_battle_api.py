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
import sqlite3
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
from pvpoke_http_security import RateBudget
from test_battle_service import FIXTURES, battle_spec


def post(server, path, body, *, token=None, origin=None, content_type='application/json'):
    connection = http.client.HTTPConnection(*server.server_address, timeout=75)
    headers = {'Content-Type': content_type}
    if token is not None:
        headers['Authorization'] = token
    if path == '/api/battles/simulate':
        headers['X-PvPoke-Token'] = web.TOKEN
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

    def setUp(self):
        budget = patch.object(gateway, 'RATE_BUDGET', RateBudget())
        budget.start()
        self.addCleanup(budget.stop)
        super().setUp()

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



    def test_loopback_host_rebinding_and_content_type_guards(self):
        """A forged Host must never expose local GET data or run battles."""
        port = self.server.server_address[1]
        for path in ('/', '/api/catalog', '/api/status', '/download'):
            for host in ('attacker.example', f'127.0.0.1:{port}.attacker.example'):
                with self.subTest(path=path, host=host):
                    conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
                    try:
                        conn.request('GET', path, headers={'Host': host})
                        response = conn.getresponse()
                        data = response.read()
                        self.assertEqual(response.status, 403)
                        self.assertNotIn(web.TOKEN.encode(), data)
                    finally:
                        conn.close()

        # Ordinary browser/bridge requests still work on both loopback names.
        for host in (f'127.0.0.1:{port}', f'localhost:{port}'):
            conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
            try:
                conn.request('GET', '/', headers={'Host': host})
                response = conn.getresponse()
                body = response.read()
                self.assertEqual(response.status, 200)
                self.assertIn(web.TOKEN.encode(), body)
            finally:
                conn.close()

        with patch.object(web, 'DirectMatrixClient') as client:
            conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
            try:
                conn.request('POST', '/api/battles/simulate',
                             json.dumps(battle_spec()).encode(),
                             {'Host': 'attacker.example', 'Content-Type': 'application/json',
                              'X-PvPoke-Token': web.TOKEN})
                response = conn.getresponse()
                response.read()
                self.assertEqual(response.status, 403)
            finally:
                conn.close()

            for disguised in ('text/plain; application/json', 'application/json-invalid'):
                with self.subTest(content_type=disguised):
                    code, _ = post(self.server, '/api/battles/simulate', battle_spec(),
                                   content_type=disguised)
                    self.assertEqual(code, 415)
            client.assert_not_called()

    def test_unexpected_loopback_failure_does_not_return_private_details(self):
        """Unexpected 500 responses reveal no internal filesystem details."""
        marker = 'TEST_PRIVATE_DB_PATH_TOKEN_NOT_REAL'
        with patch.object(web, 'prepare_payload', side_effect=RuntimeError(marker)):
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.request('POST', '/api/prepare', b'{}',
                                   {'Content-Type': 'application/json',
                                    'X-PvPoke-Token': web.TOKEN})
                response = connection.getresponse()
                data = response.read()
                self.assertEqual(response.status, 500)
                self.assertNotIn(marker.encode(), data)
                self.assertIn('error', json.loads(data))
            finally:
                connection.close()

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
        self.assertEqual(self.request({'schema': 'battle-spec-v1', 'owner_id': 'other'})[0], 400)
        with patch.object(web, 'DirectMatrixClient') as node, patch.object(
                web, 'BattleStore') as store:
            # Duplicate JSON keys are rejected before Node startup.
            self.assertEqual(post(self.server, self.path, b'{"schema":0,"schema":1}')[0], 400)
            node.assert_not_called()
            store.assert_not_called()
        with patch.object(web, 'BattleService') as service, patch.object(
                web, 'DirectMatrixClient'), patch.object(web.BattleStore, 'from_volume'):
            service.return_value.simulate.return_value = {'status': 'partial', 'rating': 50}
            code, data = self.request()
            self.assertEqual(code, 422)
            self.assertEqual(data, {'error': 'Battle was not completed'})
        self.assertFalse(web.BATTLE_RUNNING)

    def test_authenticated_gateway_reaches_real_local_battle_store(self):
        # No gateway mock: this exercises both HTTP servers and the fixed local path.
        upstream = 'http://127.0.0.1:%d' % self.server.server_address[1]
        with patch.object(gateway.backend, 'BASE', upstream), patch.object(
                gateway, 'RATE_BUDGET', RateBudget()):
            gate = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
            worker = threading.Thread(target=gate.serve_forever, daemon=True)
            worker.start()
            try:
                spec = battle_spec()
                code, first = post(gate, '/app-api/battles/simulate', spec,
                                   token='Bearer ' + gateway.API_KEY, origin=gateway.APP_ORIGIN)
                self.assertEqual(code, 200, first)
                code, second = post(gate, '/app-api/battles/simulate', spec,
                                    token='Bearer ' + gateway.API_KEY, origin=gateway.APP_ORIGIN)
                self.assertEqual(code, 200, second)
                self.assertEqual(second, first)
                self.assertEqual(first['schema'], 'battle-result-v1')
            finally:
                gate.shutdown()
                gate.server_close()
                worker.join()
        self.assertFalse(web.BATTLE_RUNNING)

    def test_store_unavailable_and_sandbox_are_not_successes(self):
        with patch.object(web.BattleStore, 'from_volume', side_effect=OSError('private path')), patch.object(
                web, 'DirectMatrixClient') as node:
            code, result = self.request()
            self.assertEqual(code, 503)
            self.assertNotIn('private path', json.dumps(result))
            node.assert_not_called()
        spec = battle_spec()
        spec['mode'] = 'sandbox'
        code, result = self.request(spec)
        self.assertEqual(code, 422)
        self.assertEqual(result['status'], 'unsupported')
        self.assertNotIn('rating', result)
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
            new_times = [new_ms]
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
            began = time.perf_counter()
            code, second = self.request(changed)
            new_times.append((time.perf_counter()-began)*1000)
            self.assertEqual(code, 200, second)
            self.assertNotEqual(second['battle_key'], first['battle_key'])
            self.assertEqual(created[-1].cache_stats['engine_calls'], 1)
            for energy in (1, 2, 3, 4):
                another = copy.deepcopy(battle_spec())
                another['combatants'][0]['initial']['energy'] = energy
                began = time.perf_counter()
                code, result = self.request(another)
                new_times.append((time.perf_counter()-began)*1000)
                self.assertEqual(code, 200, result)
                self.assertEqual(created[-1].cache_stats['engine_calls'], 1)
            self.assertEqual(self.request()[1], first)
            self.assertEqual(created[-1].cache_stats['hits'], 1)
        # Each HTTP request deliberately closes its Node process; SQLite is durable.
        self.assertTrue(all(service.client.proc is None for service in created))
        from pvpoke_battle_store import BattleStore
        db = BattleStore.from_volume()
        self.assertTrue(db.path.is_file())
        with sqlite3.connect(db.path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM battle_results').fetchone()[0], 6)
        self.assertFalse(web.BATTLE_RUNNING)
        try:
            import resource
            python_peak_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
        except ImportError:
            python_peak_mb = None
        node_peaks = [sample.get('peak_rss_mb', 0) for service in created
                      for sample in service.client.memory_samples]
        sqlite_reads = [1000*service.cache_stats['read_seconds'] for service in created]
        new_sorted, reuse_sorted = sorted(new_times), sorted(reused)
        print('BATTLE_API_BENCH new_median_ms=%.2f new_p95_ms=%.2f '
              'reuse_median_ms=%.2f reuse_p95_ms=%.2f '
              'sqlite_read_median_ms=%.3f python_peak_mb=%s node_peak_mb=%s '
              'new_samples=%d reuse_samples=%d new_calls=%d cache_hits=%d' % (
                statistics.median(new_sorted), new_sorted[-1],
                statistics.median(reuse_sorted), reuse_sorted[-1],
                statistics.median(sqlite_reads), python_peak_mb,
                max(node_peaks) if node_peaks else 'unavailable',
                len(new_times), len(reused),
                sum(service.cache_stats['engine_calls'] for service in created),
                sum(service.cache_stats['hits'] for service in created)))


if __name__ == '__main__':
    unittest.main()
