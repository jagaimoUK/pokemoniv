"""Local-only security regressions. No real credentials, jobs or remote MCP calls."""
import base64
import hashlib
import http.client
import json
import os
import re
import sqlite3
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)
import pvpoke_mcp_remote as remote
from pvpoke_app_access import BrowserLogin
from pvpoke_auth_store import CredentialStore
from pvpoke_child_env import child_environment, iv_worker_environment
from pvpoke_http_security import BoundedHTTPServer, RateBudget
from visual_backup import BackupTokens


class GatewaySecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CredentialStore(Path(self.temp.name) / 'auth.sqlite3')
        self.patchers = [patch.object(remote, 'BROWSER_LOGIN', BrowserLogin(remote.API_KEY, store=self.store)),
                         patch.object(remote, 'BACKUP_TOKENS', BackupTokens(remote.API_KEY, store=self.store)),
                         patch.object(remote, 'RATE_BUDGET', RateBudget())]
        for p in self.patchers:
            p.start()
        self.server = BoundedHTTPServer(('127.0.0.1', 0), remote.Handler,
                                        socket_timeout=0.2, request_timeout=0.5, max_workers=2)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def request(self, path, auth=None, cookie=None, payload=None, get=False):
        c = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        headers = {'Content-Type': 'application/json'}
        if auth is not None:
            headers['Authorization'] = auth
        if cookie:
            headers['Cookie'] = cookie
        c.request('GET' if get else 'POST', path, None if get else json.dumps(payload or {}), headers)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read()
        c.close()
        return result

    def test_short_token_cannot_mint_long_cookie_or_backup_connection(self):
        token = remote.APP_ACCESS.issue(remote.APP_ORIGIN)['url'].split('#access=')[1]
        for path in ('/app-api/session', '/app-api/visual-backup-token', '/app-api/visual-backup-connections'):
            status, headers, _ = self.request(path, 'Bearer ' + token)
            self.assertEqual(status, 401)
            self.assertNotIn('Set-Cookie', headers)

    def test_invalid_authorization_is_401_and_next_request_succeeds(self):
        for token in ('Bearer \xe9', 'Bearer ' + 'x' * 5000, 'Basic xxx', 'Bearer', ''):
            self.assertEqual(self.request('/app-api/session', token)[0], 401)
        self.assertEqual(self.request('/app-api/session', 'Bearer ' + remote.API_KEY)[0], 200)

    def test_cookie_store_failure_returns_503_without_exposing_details(self):
        cookie = remote.BROWSER_LOGIN.issue().split(';', 1)[0]
        with patch.object(self.store, 'active', side_effect=sqlite3.OperationalError('private-db-details')):
            status, _, body = self.request('/app-api/meta-status', cookie=cookie)
            self.assertEqual(status, 503)
            self.assertNotIn(b'private-db-details', body)


    def test_authenticated_bridge_failures_never_expose_private_upstream_details(self):
        """No internal URL, backend response body or fake secret in app JSON."""
        marker = 'TEST_PRIVATE_ENDPOINT_127.0.0.1:8765_TOKEN_NOT_REAL'
        key = 'Bearer ' + remote.API_KEY
        with patch.object(remote.backend, 'meta_status', side_effect=remote.backend.BridgeError(
                'ローカルアプリに接続できません: http://127.0.0.1:8765/' + marker)) as backend:
            status, _, data = self.request('/app-api/meta-status')
            self.assertEqual(status, 401)
            backend.assert_not_called()
            status, _, data = self.request('/app-api/meta-status', key)
            self.assertEqual(status, 503)
            self.assertNotIn(marker.encode(), data)
            self.assertNotIn(b'127.0.0.1', data)
            self.assertIn('error', json.loads(data))

        # A remembered app cookie may access app endpoints, but it should
        # never reveal the backend's private HTTP error response body.
        cookie = remote.BROWSER_LOGIN.issue().split(';', 1)[0]
        with patch.object(remote.backend, 'meta_presets', side_effect=remote.backend.BridgeError(
                'ローカルアプリ HTTP 400: {"error":"' + marker + '"}')):
            status, _, data = self.request('/app-api/meta-presets', cookie=cookie)
            self.assertEqual(status, 400)
            self.assertNotIn(marker.encode(), data)
            self.assertNotIn(b'127.0.0.1', data)
            self.assertIn('error', json.loads(data))


    def test_unexpected_app_and_public_cleanup_errors_do_not_log_private_details(self):
        marker = 'SYNTHETIC_PRIVATE_EXCEPTION_PAYLOAD'
        cases = (
            ('/app-api/meta-status', remote.backend, 'meta_status', False),
            ('/reader-api/v1/cleanup', remote, 'cached_reader_cleanup', True),
        )
        for path, target, method, public in cases:
            with self.subTest(path=path), patch.object(
                    target, method, side_effect=RuntimeError(marker)), self.assertLogs(level='ERROR') as logs:
                status, _, body = self.request(
                    path, auth=None if public else 'Bearer ' + remote.API_KEY, get=public)
                self.assertEqual(status, 503 if public else 500)
                self.assertNotIn(marker.encode(), body)
            self.assertNotIn(marker, '\n'.join(logs.output))
            self.assertTrue(all(record.exc_info is None for record in logs.records))


    def test_all_authenticated_json_routes_reject_duplicate_and_nonfinite_fields(self):
        """Ambiguous payloads never reach app, backup or MCP dispatch."""
        key = 'Bearer ' + remote.API_KEY
        backup_token = 'Bearer ' + remote.BACKUP_TOKENS.issue()
        cases = (
            ('/app-api/meta-status', key,
             (b'{"x":1,"x":2}', b'{"x":{"nested":1,"nested":2}}', b'{"x":NaN}')),
            ('/visual-backup/v1/status', backup_token,
             (b'{"action":"status","action":"upload"}', b'{"x":Infinity}')),
            ('/mcp', key,
             (b'{"jsonrpc":"2.0","id":3,"method":"ping","method":"tools/call"}',
              b'{"jsonrpc":"2.0","id":3,"method":"ping","params":{"x":-Infinity}}')),
        )
        with patch.object(remote.backend, 'meta_status') as app, \
             patch.object(remote.VISUAL_BACKUP, 'head') as backup, \
             patch.object(remote, 'call_tool') as dispatch:
            for path, credential, payloads in cases:
                for body in payloads:
                    with self.subTest(path=path, body=body[:40]):
                        connection = http.client.HTTPConnection(*self.server.server_address,
                                                                timeout=4)
                        try:
                            connection.request('POST', path, body, {
                                'Content-Type': 'application/json',
                                'Authorization': credential})
                            response = connection.getresponse()
                            result = response.read()
                            self.assertEqual(response.status, 400, result)
                            self.assertIn('error', json.loads(result))
                        finally:
                            connection.close()
            app.assert_not_called()
            backup.assert_not_called()
            dispatch.assert_not_called()

    def test_mcp_unexpected_errors_and_protocol_rejections_hide_details(self):
        """Authenticated tools must not return backend paths in error text."""
        secret = 'TEST_PRIVATE_BACKEND_PATH_TOKEN_NOT_REAL'
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'Bearer ' + remote.API_KEY}
        payload = {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                   'params': {'name': remote.TOOLS[0]['name'], 'arguments': {}}}

        for failure in (RuntimeError(secret), remote.backend.BridgeError(secret),
                        KeyError(secret)):
            with self.subTest(error=type(failure).__name__), patch.object(
                    remote, 'call_tool', side_effect=failure):
                status, _, body = self.request('/mcp', auth=headers['Authorization'],
                                                payload=payload)
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)['result']['isError'])
                self.assertNotIn(secret.encode(), body)

        with patch.object(remote, 'call_tool', side_effect=ValueError(
                'invalid candidate inputs')):
            status, _, body = self.request('/mcp', auth=headers['Authorization'],
                                            payload=payload)
            self.assertEqual(status, 200)
            self.assertIn(b'invalid candidate inputs', body)

        with patch.object(remote.Handler, 'read_body', side_effect=RuntimeError(secret)):
            status, _, body = self.request('/mcp', auth=headers['Authorization'],
                                            payload=payload)
            self.assertEqual(status, 400)
            self.assertNotIn(secret.encode(), body)
            self.assertEqual(json.loads(body)['error']['code'], -32700)

    def test_app_unexpected_key_errors_do_not_echo_private_fields(self):
        secret = 'TEST_PRIVATE_FIELD_TOKEN_NOT_REAL'
        with patch.object(remote.backend, 'meta_status', side_effect=KeyError(secret)):
            status, _, body = self.request('/app-api/meta-status',
                                            auth='Bearer ' + remote.API_KEY)
            self.assertEqual(status, 400)
            self.assertNotIn(secret.encode(), body)

    def test_unauthed_public_shells_and_private_operations_under_feature_flags(self):
        """Public pages have no root credential, and APIs reject before dispatch."""
        flags = {'PVP_SANDBOX_ENABLED': '1',
                 'PVP_MISSING_ANALYSIS_ENABLED': '1',
                 'PVP_TACTIC_SEARCH_ENABLED': '1'}
        with patch.dict(os.environ, flags), patch.object(
                remote.backend, '_request', side_effect=AssertionError(
                    'anonymous access reached a private backend')) as backend:
            for path in ('/app', '/app/party', '/app/missing', '/app/sandbox',
                         '/app/migration'):
                with self.subTest(page=path):
                    status, _, body = self.request(path, get=True)
                    self.assertEqual(status, 200)
                    self.assertNotIn(remote.API_KEY.encode(), body)
            for path in ('/app-api/catalog', '/app-api/party/list',
                         '/app-api/missing-analysis', '/app-api/sandbox',
                         '/app-api/battles/simulate', '/app-api/meta-presets',
                         '/app-api/visual-backup-connections'):
                with self.subTest(api=path):
                    status, _, body = self.request(path)
                    self.assertEqual(status, 401)
                    self.assertNotIn(remote.API_KEY.encode(), body)
            backend.assert_not_called()

    def test_backup_store_failure_returns_503(self):
        token = remote.BACKUP_TOKENS.issue()
        with patch.object(self.store, 'active', side_effect=OSError('private-file-details')):
            status, _, body = self.request('/visual-backup/v1/status', 'Bearer ' + token)
            self.assertEqual(status, 503)
            self.assertNotIn(b'private-file-details', body)

    def test_logout_revokes_cookie_copy_survives_store_reopen_and_keeps_other_device(self):
        key = 'Bearer ' + remote.API_KEY
        _, headers, _ = self.request('/app-api/session', key)
        copied = headers['Set-Cookie'].split(';', 1)[0]
        other = remote.BROWSER_LOGIN.issue().split(';', 1)[0]
        self.assertEqual(self.request('/app-api/logout', cookie=copied)[0], 200)
        self.assertEqual(self.request('/app-api/meta-status', cookie=copied)[0], 401)
        reopened = BrowserLogin(remote.API_KEY, store=CredentialStore(self.store.path))
        self.assertFalse(reopened.valid(copied))
        self.assertTrue(reopened.valid(other))

    def test_logout_revokes_short_token_copy(self):
        token = remote.APP_ACCESS.issue(remote.APP_ORIGIN)['url'].split('#access=')[1]
        self.assertEqual(self.request('/app-api/logout', 'Bearer ' + token)[0], 200)
        self.assertFalse(remote.APP_ACCESS.valid('Bearer ' + token))

    def test_backup_connection_listing_and_individual_revocation(self):
        first, second = remote.BACKUP_TOKENS.issue(), remote.BACKUP_TOKENS.issue()
        key = 'Bearer ' + remote.API_KEY
        status, _, body = self.request('/app-api/visual-backup-connections', key)
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['items']), 2)
        self.assertNotIn(first.encode(), body)
        self.assertEqual(self.request('/app-api/visual-backup-revoke', key,
                        payload={'id': self.store.fingerprint(first)})[0], 200)
        self.assertFalse(remote.BACKUP_TOKENS.valid(first))
        self.assertTrue(remote.BACKUP_TOKENS.valid(second))
        self.assertEqual(self.request('/visual-backup/v1/status', 'Bearer ' + first)[0], 401)

    def test_legacy_signed_cookie_is_accepted_then_revocable(self):
        # Legacy v1 format does not require a mass logout on deployment.
        login = remote.BROWSER_LOGIN
        payload = 'v1.%s.legacy' % (int(time.time()) + 60)
        value = payload + '.' + login._sign(payload)
        cookie = login.COOKIE_NAME + '=' + value
        self.assertTrue(login.valid(cookie))
        login.revoke(cookie)
        self.assertFalse(login.valid(cookie))

    def test_all_html_scripts_are_hash_authorized_without_unsafe_inline(self):
        for path in ('/app', '/app/party', '/flashcards', '/reader-backup'):
            status, headers, body = self.request(path, get=True)
            self.assertEqual(status, 200)
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            policy = headers['Content-Security-Policy']
            self.assertNotIn("'unsafe-inline'", policy.split('script-src ')[1].split(';')[0])
            for script in re.findall(rb'<script[^>]*>(.*?)</script\s*>', body, re.I | re.S):
                self.assertIn(base64.b64encode(hashlib.sha256(script).digest()).decode(), policy)

    def test_owner_compute_budget_and_retry_after(self):
        with patch.object(remote, 'RATE_BUDGET') as budget:
            budget.allow.side_effect = lambda name, *args: name != 'compute-owner'
            status, headers, _ = self.request('/app-api/run', 'Bearer ' + remote.API_KEY)
            self.assertEqual(status, 429)
            self.assertIn('Retry-After', headers)

    def test_backup_concurrency_is_bounded_before_reading_large_body(self):
        remote.BACKUP_SLOTS.acquire()
        try:
            self.assertEqual(self.request('/visual-backup/v1/upload', 'Bearer invalid')[0], 503)
        finally:
            remote.BACKUP_SLOTS.release()

    def test_duplicate_content_length_is_rejected(self):
        with socket.create_connection(self.server.server_address, timeout=2) as c:
            c.sendall(b'POST /app-api/session HTTP/1.1\r\nHost: test\r\n'
                      b'Content-Length: 2\r\nContent-Length: 3\r\n\r\n{}')
            self.assertIn(b'400', c.recv(1000))

    def test_slow_header_timeout_and_normal_health(self):
        with socket.create_connection(self.server.server_address, timeout=2) as slow:
            slow.sendall(b'GET /health HTTP/1.1\r\nHost:')
            self.assertEqual(self.request('/health', get=True)[0], 200)
            slow.settimeout(1)
            self.assertEqual(slow.recv(100), b'')

    def test_absolute_deadline_releases_trickled_headers(self):
        with socket.create_connection(self.server.server_address, timeout=2) as slow:
            slow.sendall(b'GET /health HTTP/1.1\r\nX-Slow: ')
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                try:
                    slow.sendall(b'x')
                    time.sleep(0.05)
                except OSError:
                    break
            self.assertLess(time.monotonic(), deadline)
        self.assertEqual(self.request('/health', get=True)[0], 200)

    def test_worker_overflow_is_503_then_recovers(self):
        with patch.object(remote.Handler, 'do_GET') as get:
            release = threading.Event()
            entered = threading.Event()
            count = []
            def block(*args):
                count.append(1)
                if len(count) == 2:
                    entered.set()
                release.wait(1)
            get.side_effect = block
            clients = [socket.create_connection(self.server.server_address, timeout=2) for _ in range(2)]
            try:
                for c in clients:
                    c.sendall(b'GET /health HTTP/1.0\r\n\r\n')
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.request('/health', get=True)[0], 503)
            finally:
                release.set()
                for c in clients:
                    c.close()

    def test_mcp_compute_tools_share_compute_owner_budget_without_double_charge(self):
        auth = 'Bearer ' + remote.API_KEY
        # /app-api/run calls call_tool('run_iv_selection', ...) internally;
        # 12 calls must consume 12 tokens (no double charge) and the 13th hits 429.
        with patch.object(remote.backend, 'meta_status', return_value={'sha256': '0' * 64}), \
             patch.object(remote, 'call_tool', return_value={'state': 'done'}):
            for i in range(12):
                status, _, _ = self.request('/app-api/run', auth, payload={'candidate': {}, 'ivs': '0,15,15'})
                self.assertEqual(status, 200, f'/app-api/run {i + 1}th call should succeed')
            status, headers, _ = self.request('/app-api/run', auth, payload={'candidate': {}, 'ivs': '0,15,15'})
            self.assertEqual(status, 429)
            self.assertIn('Retry-After', headers)
            # Exhausted compute-owner budget must also block MCP compute-starting tools.
            for tool_name in ('start_battle', 'start_24_conditions', 'run_iv_selection'):
                with self.subTest(tool=tool_name):
                    status, headers, _ = self.request('/mcp', auth, payload={
                        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': tool_name, 'arguments': {}},
                    })
                    self.assertEqual(status, 429)
                    self.assertIn('Retry-After', headers)
            # Lightweight status/read MCP tools must remain available.
            for tool_name in ('get_status', 'get_catalog', 'prepare_battle', 'get_results'):
                with self.subTest(light_tool=tool_name):
                    status, _, body = self.request('/mcp', auth, payload={
                        'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                        'params': {'name': tool_name, 'arguments': {}},
                    })
                    self.assertEqual(status, 200)
                    self.assertFalse(json.loads(body)['result']['isError'])

        # Mixed consumption: 10 via /mcp compute tools + 2 via /app-api/run -> 13th blocked on both.
        with patch.object(remote, 'RATE_BUDGET', RateBudget()), \
             patch.object(remote.backend, 'meta_status', return_value={'sha256': '0' * 64}), \
             patch.object(remote, 'call_tool', return_value={'ok': True}):
            for i in range(10):
                status, _, _ = self.request('/mcp', auth, payload={
                    'jsonrpc': '2.0', 'id': i + 10, 'method': 'tools/call',
                    'params': {'name': 'run_iv_selection', 'arguments': {}},
                })
                self.assertEqual(status, 200)
            for _ in range(2):
                status, _, _ = self.request('/app-api/run', auth, payload={'candidate': {}, 'ivs': '0,15,15'})
                self.assertEqual(status, 200)
            self.assertEqual(self.request('/mcp', auth, payload={
                'jsonrpc': '2.0', 'id': 99, 'method': 'tools/call',
                'params': {'name': 'start_battle', 'arguments': {}},
            })[0], 429)
            self.assertEqual(self.request('/app-api/run', auth, payload={'candidate': {}, 'ivs': '0,15,15'})[0], 429)

    def test_mcp_compute_tools_share_app_slots_and_release_on_error_or_disconnect(self):
        auth = 'Bearer ' + remote.API_KEY
        server = BoundedHTTPServer(('127.0.0.1', 0), remote.Handler,
                                    socket_timeout=2, request_timeout=5, max_workers=8)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=2)))

        entered = threading.Event()
        release = threading.Event()
        in_flight = 0
        lock = threading.Lock()

        def slow_call(name, args):
            nonlocal in_flight
            with lock:
                in_flight += 1
                if in_flight == 4:
                    entered.set()
            release.wait(timeout=3)
            return {'ok': True}

        def post_srv(path, payload):
            c = http.client.HTTPConnection(*server.server_address, timeout=4)
            try:
                c.request('POST', path, json.dumps(payload), {
                    'Content-Type': 'application/json',
                    'Authorization': auth,
                })
                r = c.getresponse()
                return r.status, r.read()
            finally:
                c.close()

        from concurrent.futures import ThreadPoolExecutor
        # Saturate all 4 APP_REQUEST_SLOTS with real concurrent /mcp compute requests.
        with patch.object(remote, 'call_tool', side_effect=slow_call), \
             patch.object(remote, 'RATE_BUDGET', RateBudget()):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [
                    pool.submit(post_srv, '/mcp', {
                        'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                        'params': {'name': 'run_iv_selection', 'arguments': {}},
                    })
                    for i in range(4)
                ]
                self.assertTrue(entered.wait(timeout=2))
                try:
                    # 5th compute request via /mcp OR /app-api gets 503.
                    for name in ('start_battle', 'start_24_conditions', 'run_iv_selection'):
                        self.assertEqual(post_srv('/mcp', {
                            'jsonrpc': '2.0', 'id': 10, 'method': 'tools/call',
                            'params': {'name': name, 'arguments': {}},
                        })[0], 503)
                    self.assertEqual(post_srv('/app-api/catalog', {})[0], 503)
                    # Lightweight /mcp status check remains unblocked even when 4 compute slots are full.
                    with patch.object(remote.backend, 'status', return_value={'state': 'running'}):
                        code, body = post_srv('/mcp', {
                            'jsonrpc': '2.0', 'id': 11, 'method': 'tools/call',
                            'params': {'name': 'get_status', 'arguments': {}},
                        })
                        self.assertEqual(code, 200)
                        self.assertFalse(json.loads(body)['result']['isError'])
                finally:
                    release.set()
                for f in futures:
                    self.assertEqual(f.result()[0], 200)

        # Verify slots recover cleanly after ValueError, RuntimeError, and client disconnect.
        with patch.object(remote, 'RATE_BUDGET', RateBudget()):
            for exc in (ValueError('bad input'), RuntimeError('boom')):
                with patch.object(remote, 'call_tool', side_effect=exc):
                    code, body = post_srv('/mcp', {
                        'jsonrpc': '2.0', 'id': 20, 'method': 'tools/call',
                        'params': {'name': 'start_battle', 'arguments': {}},
                    })
                    self.assertEqual(code, 200)
                    self.assertTrue(json.loads(body)['result']['isError'])

            # Simulate client disconnecting before response finishes.
            disconn_entered = threading.Event()
            disconn_release = threading.Event()

            def slow_disconnect(name, args):
                disconn_entered.set()
                disconn_release.wait(timeout=2)
                return {'ok': True}

            with patch.object(remote, 'call_tool', side_effect=slow_disconnect):
                sock = socket.create_connection(server.server_address, timeout=2)
                req_body = json.dumps({
                    'jsonrpc': '2.0', 'id': 21, 'method': 'tools/call',
                    'params': {'name': 'run_iv_selection', 'arguments': {}},
                }).encode()
                sock.sendall(
                    b'POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\n'
                    b'Content-Type: application/json\r\n'
                    b'Authorization: ' + auth.encode() + b'\r\n'
                    b'Content-Length: ' + str(len(req_body)).encode() + b'\r\n\r\n' + req_body
                )
                self.assertTrue(disconn_entered.wait(timeout=2))
                sock.close()
                disconn_release.set()
                time.sleep(0.1)

            # All 4 slots must be available after errors and client disconnect.
            for _ in range(4):
                self.assertTrue(remote.APP_REQUEST_SLOTS.acquire(blocking=False))
            for _ in range(4):
                remote.APP_REQUEST_SLOTS.release()

    def test_gateway_4_slots_vs_backend_single_active_job_409(self):
        """Real Gateway->Backend HTTP call: Backend enforces 1 active job (HTTP 409) within Gateway's 4 slots."""
        import pvpoke_web as web
        import urllib.request
        import urllib.error
        backend_srv = BoundedHTTPServer(('127.0.0.1', 0), web.Handler,
                                        socket_timeout=2, request_timeout=5, max_workers=8)
        b_thread = threading.Thread(target=backend_srv.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        b_thread.start()
        self.addCleanup(lambda: (backend_srv.shutdown(), backend_srv.server_close(), b_thread.join(timeout=2)))

        gw_srv = BoundedHTTPServer(('127.0.0.1', 0), remote.Handler,
                                   socket_timeout=2, request_timeout=5, max_workers=8)
        g_thread = threading.Thread(target=gw_srv.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        g_thread.start()
        self.addCleanup(lambda: (gw_srv.shutdown(), gw_srv.server_close(), g_thread.join(timeout=2)))

        b_port = backend_srv.server_port
        in_backend = threading.Event()
        release_backend = threading.Event()

        def forward_to_real_backend(path, payload=None, *, headers=None, timeout=65):
            req_headers = {'Content-Type': 'application/json', **(headers or {})}
            data = b'{}' if payload is None else json.dumps(payload).encode()
            req = urllib.request.Request(f'http://127.0.0.1:{b_port}{path}', data=data,
                                         headers=req_headers, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                raise remote.backend.BridgeError(f'ローカルアプリ HTTP {exc.code}: {exc.read().decode("utf-8", "ignore")}')

        def slow_sim(service, payload):
            in_backend.set()
            release_backend.wait(timeout=3)
            return {'status': 'complete'}

        with patch.dict(os.environ, {'PVP_SANDBOX_ENABLED': '1'}), \
             patch.dict(web.CATALOG, {'ready': True}), \
             patch.dict(web.STATUS, {'state': 'idle'}), \
             patch.object(web, 'DirectMatrixClient'), \
             patch.object(web, 'BattleService'), \
             patch.object(web.BattleStore, 'from_volume', return_value=None), \
             patch.object(web, 'sandbox_operation', side_effect=slow_sim), \
             patch.object(remote.backend, '_token', return_value=web.TOKEN), \
             patch.object(remote.backend, '_request', side_effect=forward_to_real_backend):
            def send_sandbox():
                c = http.client.HTTPConnection(*gw_srv.server_address, timeout=4)
                try:
                    c.request('POST', '/app-api/sandbox', json.dumps({'action': 'simulate', 'spec': {}}), {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + remote.API_KEY,
                    })
                    r = c.getresponse()
                    r.read()
                    return r.status
                finally:
                    c.close()

            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(send_sandbox)
                self.assertTrue(in_backend.wait(timeout=2))
                try:
                    # 2nd concurrent job acquires a Gateway APP_REQUEST_SLOT, hits real Backend, and receives 409.
                    self.assertEqual(send_sandbox(), 409)
                finally:
                    release_backend.set()
                self.assertEqual(f1.result(), 200)


class EngineSecurityTests(unittest.TestCase):
    def test_child_environment_excludes_every_secret(self):
        with patch.dict(os.environ, {'PVP_API_KEY': 'secret', 'AWS_SECRET_ACCESS_KEY': 'secret',
                                   'VISUAL_BACKUP_S3_SECRET_ACCESS_KEY': 'secret'}):
            env = child_environment()
        self.assertNotIn('PVP_API_KEY', env)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)
        self.assertNotIn('VISUAL_BACKUP_S3_SECRET_ACCESS_KEY', env)


    def test_iv_worker_environment_drops_server_secrets_and_keeps_runtime_settings(self):
        import pvpoke_web as local
        fake = {
            'PVP_API_KEY': 'FAKE_PRIVATE_ROOT_KEY_NOT_REAL',
            'AUTH0_CLIENT_SECRET': 'FAKE_PRIVATE_OAUTH_SECRET_NOT_REAL',
            'VISUAL_BACKUP_S3_SECRET_ACCESS_KEY': 'FAKE_PRIVATE_S3_KEY_NOT_REAL',
            'AWS_SECRET_ACCESS_KEY': 'FAKE_PRIVATE_AWS_KEY_NOT_REAL',
            'PVP_MCP_URL': 'https://private-gateway.invalid/mcp',
            'PVP_ENGINE': 'direct',
            'PVP_ARCHIVE_DIR': '/tmp/test-only-archives',
            'RAILWAY_VOLUME_MOUNT_PATH': '/tmp/test-only-volume',
            'PVP_CAND_CHUNK': '5',
            'PVP_RESULT_CACHE': '0',
            'PVP_CACHE_EPOCH': 'test-cache-epoch',
            'PVP_FORCE_RECALCULATE': '0',
        }
        with patch.dict(os.environ, fake):
            for force, expected in ((False, '0'), (True, '1')):
                with self.subTest(force=force):
                    env = iv_worker_environment(force=force)
                    self.assertEqual(env['PVP_FORCE_RECALCULATE'], expected)
                    self.assertEqual(env['PVP_ENGINE'], 'direct')
                    self.assertEqual(env['PVP_ARCHIVE_DIR'], '/tmp/test-only-archives')
                    self.assertEqual(env['RAILWAY_VOLUME_MOUNT_PATH'],
                                     '/tmp/test-only-volume')
                    self.assertEqual(env['PVP_RESULT_CACHE'], '0')
                    self.assertEqual(env['PVP_CAND_CHUNK'], '5')
                    self.assertEqual(env['PVP_CACHE_EPOCH'], 'test-cache-epoch')
                    for name in ('PVP_API_KEY', 'AUTH0_CLIENT_SECRET',
                                 'VISUAL_BACKUP_S3_SECRET_ACCESS_KEY',
                                 'AWS_SECRET_ACCESS_KEY', 'PVP_MCP_URL'):
                        self.assertNotIn(name, env)
                    # Exercise the exact Popen call site, not only the helper.
                    with patch.object(local, 'CANCEL_REQUESTED', False), patch.object(
                            local.subprocess, 'Popen', side_effect=OSError(
                                'fake child start failure')) as started:
                        local.background_run('all', force=force)
                    self.assertEqual(started.call_args.kwargs['env'], env)

    def test_browser_disabled_before_connecting_to_existing_debugger(self):
        import pvpoke_batch_v2 as engine
        with patch.dict(os.environ, {'PVP_ALLOW_BROWSER': '0'}), patch.object(engine, 'call_json') as call:
            with self.assertRaises(RuntimeError):
                engine.chromium_connect()
            call.assert_not_called()

    def test_direct_failure_never_falls_back_to_browser(self):
        import pvpoke_batch_v2 as engine
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'gamemaster.json').write_text('{}')
            (root / 'Pokemon.js').write_text('fixture')
            row = dict(species='quagsire', fast='MUD_SHOT', charged1='AQUA_TAIL',
                       charged2='STONE_EDGE', atk=0, hp=15, level=20, cp=1400, **{'def': 15})
            with patch.dict(os.environ, {'PVP_ENGINE': 'direct', 'PVP_MATCHUP_CACHE': '0', 'PVP_FORCE_RECALCULATE': '1'}), \
                 patch.object(engine, 'DATA', root), patch.object(engine, 'OUT', root / 'out'), \
                 patch.object(engine, 'DIR', root), patch.object(engine, 'prepare', return_value=({}, [row], [row])), \
                 patch.object(engine.direct_backend, 'DirectMatrixClient', side_effect=RuntimeError('broken')), \
                 patch.object(engine, 'chromium_connect') as browser:
                with self.assertRaisesRegex(RuntimeError, '自動切替しません'):
                    engine.run(shield_set='equal')
                browser.assert_not_called()

    def test_proxy_port_validation(self):
        from pvpoke_proxy_config import render
        self.assertIn('listen 8787;', render(8787))
        for port in ('80; include /etc/passwd', 'x', 0, 8765, 8788, 65536):
            with self.assertRaises(ValueError):
                render(port)
