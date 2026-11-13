"""Actual Nginx -> authenticated gateway regression on a disposable local replica.

Only synthetic credentials, loopback network and disposable SQLite state.
Never connects to production, a real user account, or the ChatGPT PvPoke MCP.
Run in the production Docker image, where nginx is installed.
"""
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('PVP_API_KEY', 'test-edge-' + 'x' * 40)
import pvpoke_mcp_remote as gateway
from pvpoke_app_access import BrowserLogin
from pvpoke_auth_store import CredentialStore
from pvpoke_http_security import BoundedHTTPServer, RateBudget
from pvpoke_proxy_config import render

NGINX = shutil.which('nginx')


@unittest.skipUnless(NGINX, 'Requires nginx from the production image')
class RealProxyAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        for name, value in (
            ('BROWSER_LOGIN', BrowserLogin(
                gateway.API_KEY, store=CredentialStore(cls.root / 'browser-auth.sqlite3'))),
            ('RATE_BUDGET', RateBudget()),
        ):
            p = patch.object(gateway, name, value)
            p.start()
            cls.addClassCleanup(p.stop)

        cls.backend = BoundedHTTPServer(('127.0.0.1', 0), gateway.Handler,
                                        socket_timeout=3, request_timeout=8, max_workers=4)
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.thread.start()

        def stop_backend():
            cls.backend.shutdown()
            cls.backend.server_close()
            cls.thread.join(timeout=3)

        cls.addClassCleanup(stop_backend)

        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        conf = render(cls.port).replace(
            '127.0.0.1:8788', '127.0.0.1:' + str(cls.backend.server_port))
        conf = conf.replace('/tmp/pokemoniv-nginx.pid', str(cls.root / 'nginx.pid'))
        conf = conf.replace('/tmp/pokemoniv-nginx/', str(cls.root) + '/')
        conf = 'master_process off;\n' + conf
        for directory in ('body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'):
            (cls.root / directory).mkdir()
        path = cls.root / 'nginx.conf'
        path.write_text(conf)
        safe_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG')
                    if key in os.environ}
        subprocess.run([NGINX, '-t', '-e', '/dev/stderr', '-c', str(path)],
                       check=True, timeout=5, capture_output=True, env=safe_env)
        cls.proc = subprocess.Popen(
            [NGINX, '-e', '/dev/stderr', '-c', str(path), '-g', 'daemon off;'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=safe_env)

        def stop_proxy():
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait(timeout=3)

        cls.addClassCleanup(stop_proxy)
        for _ in range(120):
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=0.1):
                    break
            except OSError:
                if cls.proc.poll() is not None:
                    raise RuntimeError('Nginx exited during local replica setup')
                time.sleep(0.025)
        else:
            raise RuntimeError('Nginx failed to start on disposable test port')

    def request(self, path, payload=None, *, token=None, cookie=None, origin=None,
                method='POST', extra_headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        headers.update(extra_headers or {})
        body = None if method == 'GET' else (
            payload if isinstance(payload, bytes) else json.dumps(payload or {}).encode())
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_public_html_and_health_never_include_credentials(self):
        for path in ('/app', '/app/party', '/reader-backup', '/app/migration',
                     '/health'):
            with self.subTest(path=path):
                status, headers, body = self.request(path, method='GET')
                self.assertEqual(status, 200, body)
                self.assertNotIn(gateway.API_KEY.encode(), body)
                self.assertNotIn(b'FAKE_PRIVATE_S3_KEY', body)
                self.assertNotIn('Set-Cookie', headers)

        # The internal local computation API must never be served by
        # the public reverse-proxy routing table.
        status, _, body = self.request('/api/status', method='GET')
        self.assertNotEqual(status, 200, body)

    def test_authentication_origin_cookie_revocation_at_actual_proxy(self):
        marker = 'SYNTHETIC_PRIVATE_DATA_NOT_REAL'
        with patch.object(gateway.backend, 'meta_status',
                          return_value={'private': marker}) as backend:
            # Anonymous clients, including ones forging a forwarded IP,
            # never cause private app API dispatch.
            for path in ('/app-api/meta-status', '/app-api/catalog',
                         '/app-api/party/list', '/app-api/sandbox',
                         '/app-api/missing-analysis', '/app-api/battles/simulate',
                         '/app-api/visual-backup-connections', '/mcp'):
                with self.subTest(path=path):
                    status, _, raw = self.request(path, extra_headers={
                        'X-Forwarded-For': '192.0.2.25'})
                    self.assertEqual(status, 401, raw)
                    self.assertNotIn(marker.encode(), raw)
            backend.assert_not_called()

            status, _, raw = self.request('/app-api/meta-status',
                                          token=gateway.API_KEY,
                                          origin='https://attacker.invalid')
            self.assertEqual(status, 403, raw)
            backend.assert_not_called()

            status, _, raw = self.request('/app-api/meta-status',
                                          token=gateway.API_KEY)
            self.assertEqual(status, 200, raw)
            self.assertEqual(json.loads(raw)['private'], marker)

            status, headers, raw = self.request('/app-api/session',
                                                 token=gateway.API_KEY)
            self.assertEqual(status, 200, raw)
            cookie_header = headers['Set-Cookie']
            self.assertIn('HttpOnly', cookie_header)
            self.assertIn('SameSite=Strict', cookie_header)
            cookie = cookie_header.split(';', 1)[0]

            self.assertEqual(self.request('/app-api/meta-status', cookie=cookie)[0], 200)
            self.assertEqual(self.request('/mcp', cookie=cookie)[0], 401)
            self.assertEqual(self.request('/app-api/meta-status', cookie=cookie,
                                          origin='https://attacker.invalid')[0], 403)
            self.assertEqual(self.request('/app-api/logout', cookie=cookie)[0], 200)
            self.assertEqual(self.request('/app-api/meta-status', cookie=cookie)[0], 401)

    def test_malformed_and_ambiguous_json_is_rejected_at_proxy(self):
        with patch.object(gateway.backend, 'meta_status') as backend:
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
                status, _, body = self.request('/app-api/meta-status', raw,
                                               token=gateway.API_KEY)
                self.assertEqual(status, 400, body)
            status, _, body = self.request('/app-api/meta-status',
                                           b'{"x":1}', token=gateway.API_KEY,
                                           extra_headers={'Content-Type': 'text/plain'})
            self.assertEqual(status, 415, body)
            backend.assert_not_called()


if __name__ == '__main__':
    unittest.main()
