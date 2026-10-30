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
from pvpoke_child_env import child_environment
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


class EngineSecurityTests(unittest.TestCase):
    def test_child_environment_excludes_every_secret(self):
        with patch.dict(os.environ, {'PVP_API_KEY': 'secret', 'AWS_SECRET_ACCESS_KEY': 'secret',
                                   'VISUAL_BACKUP_S3_SECRET_ACCESS_KEY': 'secret'}):
            env = child_environment()
        self.assertNotIn('PVP_API_KEY', env)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)
        self.assertNotIn('VISUAL_BACKUP_S3_SECRET_ACCESS_KEY', env)

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
