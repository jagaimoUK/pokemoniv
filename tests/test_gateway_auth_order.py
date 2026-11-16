"""Tests for Phase D-03: Gateway authentication order and budget isolation."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.cookies import CookieError
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)
import pvpoke_mcp_remote as remote
from pvpoke_app_access import BrowserLogin, AppAccess
from pvpoke_auth_store import CredentialStore
from pvpoke_http_security import BoundedHTTPServer, RateBudget
from visual_backup import BackupTokens


class GatewayAuthOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CredentialStore(Path(self.temp.name) / 'auth.sqlite3')
        self.budget = RateBudget()
        self.patchers = [
            patch.object(remote, 'BROWSER_LOGIN', BrowserLogin(remote.API_KEY, store=self.store)),
            patch.object(remote, 'BACKUP_TOKENS', BackupTokens(remote.API_KEY, store=self.store)),
            patch.object(remote, 'RATE_BUDGET', self.budget),
            patch.object(remote, 'APP_ACCESS', AppAccess()),
        ]
        for p in self.patchers:
            p.start()
        self.server = BoundedHTTPServer(('127.0.0.1', 0), remote.Handler,
                                        socket_timeout=1.0, request_timeout=2.0, max_workers=4)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def request(self, path, token=None, payload=None, get=False, extra_headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = token
        if extra_headers:
            headers.update(extra_headers)
        data = None if get else json.dumps(payload or {}).encode('utf-8')
        conn.request('GET' if get else 'POST', path, data, headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), body

    def test_d03_01_framing_check_first_without_budget_charge(self):
        # Malformed framing: Transfer-Encoding header present
        status, _, _ = self.request('/mcp', payload={'jsonrpc': '2.0'},
                                    extra_headers={'Transfer-Encoding': 'chunked'})
        self.assertEqual(status, 400)
        # Verify no budget was charged
        with self.budget._lock:
            self.assertEqual(len(self.budget._buckets), 0)

    def test_d03_02_unauthenticated_post_charges_unauth_not_owner(self):
        # Unauthenticated POST to /mcp
        status, _, _ = self.request('/mcp', token='Bearer invalid_token', payload={'test': 1})
        self.assertEqual(status, 401)
        # Should have charged 'unauth-entry', NOT 'owner-entry'
        with self.budget._lock:
            self.assertIn('unauth-entry', self.budget._buckets)
            self.assertNotIn('owner-entry', self.budget._buckets)

    def test_d03_03_authenticated_post_charges_owner_entry(self):
        # Authenticated POST with API_KEY
        with patch.object(remote, 'call_tool', return_value={'ok': True}):
            status, _, _ = self.request('/mcp', token='Bearer ' + remote.API_KEY,
                                        payload={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        self.assertEqual(status, 200)
        with self.budget._lock:
            self.assertIn('owner-entry', self.budget._buckets)
            self.assertNotIn('unauth-entry', self.budget._buckets)

    def test_d03_04_cookie_error_does_not_raise_500(self):
        # Malformed cookie header that triggers CookieError
        login = BrowserLogin(remote.API_KEY, store=self.store)
        malformed = 'bad_cookie="unterminated'
        self.assertFalse(login.valid(malformed))

        # Sending it to /app-api/catalog returns 401, not 500
        status, _, _ = self.request('/app-api/catalog', extra_headers={'Cookie': malformed})
        self.assertEqual(status, 401)

    def test_d03_05_visual_backup_unauth_does_not_acquire_slot(self):
        # Invalid Bearer token
        status, _, _ = self.request('/visual-backup/v1/status', token='Bearer fake')
        self.assertEqual(status, 401)
        with self.budget._lock:
            self.assertIn('unauth-backup', self.budget._buckets)
            self.assertNotIn('backup-owner', self.budget._buckets)

        # Slot was not consumed and is still available
        self.assertEqual(remote.BACKUP_SLOTS._value, 1)

    def test_d03_06_visual_backup_valid_token_charges_owner(self):
        valid = remote.BACKUP_TOKENS.issue()
        with patch.object(remote.VISUAL_BACKUP, 'head', return_value={'head': 'ok'}):
            status, _, _ = self.request('/visual-backup/v1/status', token='Bearer ' + valid,
                                        extra_headers={'Origin': remote.APP_ORIGIN})
        self.assertEqual(status, 200)
        with self.budget._lock:
            self.assertIn('backup-owner', self.budget._buckets)

    def test_d03_07_public_get_uses_public_get_bucket(self):
        status, _, _ = self.request('/app', get=True)
        self.assertEqual(status, 200)
        with self.budget._lock:
            self.assertIn('public-get', self.budget._buckets)
            self.assertNotIn('owner-entry', self.budget._buckets)


if __name__ == '__main__':
    unittest.main()
