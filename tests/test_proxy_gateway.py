"""Small local proxy tests; no requests are sent to the production service."""
import http.client
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pvpoke_proxy_config import render

NGINX = os.environ.get('PVP_TEST_NGINX') or shutil.which('nginx')


@unittest.skipUnless(NGINX, 'Nginx binary not installed; production image CI runs this suite')
class ProxyGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Healthy(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'ok')
            def log_message(self, *args):
                pass
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), Healthy)
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.thread.start()
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            cls.port = s.getsockname()[1]
        config = render(cls.port).replace('127.0.0.1:8788', '127.0.0.1:' + str(cls.backend.server_port))
        config = config.replace('/tmp/pokemoniv-nginx.pid', str(root / 'pid'))
        config = config.replace('/tmp/pokemoniv-nginx/', str(root) + '/')
        config = config.replace('client_header_timeout 10s', 'client_header_timeout 1s')
        config = config.replace('client_body_timeout 10s', 'client_body_timeout 1s')
        # Single process avoids unavailable privilege switching in a local sandbox.
        config = 'master_process off;\n' + config
        if os.getuid() == 0:
            config = 'user ' + pwd.getpwuid(os.getuid()).pw_name + ';\n' + config
        for part in ('body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'):
            (root / part).mkdir()
        file = root / 'nginx.conf'
        file.write_text(config)
        subprocess.run([NGINX, '-t', '-e', '/dev/stderr', '-c', str(file)], check=True, capture_output=True)
        cls.proc = subprocess.Popen([NGINX, '-e', '/dev/stderr', '-c', str(file), '-g', 'daemon off;'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=0.1):
                    break
            except OSError:
                if cls.proc.poll() is not None:
                    raise RuntimeError('Nginx exited before readiness')
                time.sleep(0.01)
        else:
            raise RuntimeError('Nginx did not become ready')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=3)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def request(self, path='/health', headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        c.request('GET', path, headers=headers or {})
        r = c.getresponse()
        result = r.status
        r.read()
        c.close()
        return result

    def test_health_proxies_normally(self):
        self.assertEqual(self.request(), 200)

    def test_slow_header_is_closed_and_healthy_request_still_succeeds(self):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as c:
            c.sendall(b'GET /health HTTP/1.1\r\nHost:')
            self.assertEqual(self.request(), 200)
            c.settimeout(2)
            try:
                response = c.recv(1000)
            except ConnectionResetError:
                response = b''  # reset_timedout_connection intentionally sends RST.
            self.assertTrue(not response or b'408' in response, response)

    def test_rate_limit_cannot_be_bypassed_by_forged_forwarded_ip(self):
        codes = [self.request('/app', {'X-Forwarded-For': f'192.0.2.{i}'}) for i in range(65)]
        self.assertIn(200, codes)
        self.assertIn(429, codes)
        self.assertEqual(self.request(), 200)

    def test_oversized_body_rejected_before_backend(self):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as c:
            c.sendall(b'POST /health HTTP/1.1\r\nHost: local\r\nContent-Length: 30000000\r\n\r\n')
            self.assertIn(b'413', c.recv(1000))
