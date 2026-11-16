"""Synthetic benchmarks for Phase D P1 fixes.
BM-1: /api/status response delay while evaluate() runs simulate outside LOCK.
BM-2: DirectMatrixClient timeout overrun measurement on hanging worker.
BM-3: Admin request survival after unauthenticated/anonymous request flood.
"""
import os
os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)

import http.client
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pvpoke_web as web
import pvpoke_mcp_remote as remote
from pvpoke_direct_backend import DirectMatrixClient, DirectMatrixError
from pvpoke_http_security import BoundedHTTPServer, RateBudget
from pvpoke_auth_store import CredentialStore
from visual_backup import BackupTokens
from pvpoke_app_access import BrowserLogin, AppAccess


class PhaseDBenchmarks(unittest.TestCase):
    def test_bm1_api_status_delay_under_evaluate(self):
        """BM-1: /api/status latency must remain <50ms even while meta_variants.evaluate runs."""
        # Set up a test server for pvpoke_web
        tmp = tempfile.TemporaryDirectory()
        work = Path(tmp.name)
        web.COMPUTE_OWNER = None
        web.BATTLE_RUNNING = False
        web.STATUS['state'] = 'idle'
        server = BoundedHTTPServer(('127.0.0.1', 0), web.Handler, max_workers=8)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            # Simulate a long evaluate running client.simulate outside LOCK
            token = web.try_reserve_compute('meta_variants')
            self.assertIsNotNone(token)

            # Measure /api/status request latency while reservation is held
            latencies = []
            for _ in range(10):
                t0 = time.perf_counter()
                conn = http.client.HTTPConnection(*server.server_address, timeout=2)
                conn.request('GET', '/api/status', headers={'X-PvPoke-Token': web.TOKEN})
                resp = conn.getresponse()
                body = resp.read()
                conn.close()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self.assertEqual(resp.status, 200)
                latencies.append(elapsed_ms)

            web.release_compute(token)
            p50 = sorted(latencies)[len(latencies) // 2]
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            print(f'\n[BM-1] /api/status under meta compute: median={p50:.2f}ms, p95={p95:.2f}ms')
            # Astra baseline was ~303ms before fix; must be < 50ms now
            self.assertLess(p50, 50.0)
            self.assertLess(p95, 50.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            tmp.cleanup()

    def test_bm2_direct_timeout_overrun(self):
        """BM-2: DirectMatrixClient timeout overrun must be tightly bounded."""
        import sys
        tmp = tempfile.TemporaryDirectory()
        gm = Path('tests/fixtures/strategy_gamemaster.json').resolve()
        code = 'import sys, time; sys.stdin.readline(); time.sleep(10)'
        orig_popen = subprocess.Popen
        def fake_popen(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1].endswith('pvpoke_node_matrix.js'):
                return orig_popen([sys.executable, '-u', '-c', code], *args, **kwargs)
            return orig_popen(cmd, *args, **kwargs)

        with patch('subprocess.Popen', side_effect=fake_popen):
            client = DirectMatrixClient(gamemaster=gm, log_dir=Path(tmp.name), timeout_seconds=0.1)

        t0 = time.perf_counter()
        with self.assertRaises(DirectMatrixError):
            client._exchange_frame({'action': 'hang'}, timeout_message='PvPoke Matrix timeout')

        duration_ms = (time.perf_counter() - t0) * 1000.0
        overrun_ms = duration_ms - 100.0
        print(f'[BM-2] Direct IPC deadline=100ms: total={duration_ms:.2f}ms, overrun={overrun_ms:.2f}ms')
        tmp.cleanup()
        # Overrun must not exceed 60ms (Astra previously recorded 252ms overrun)
        self.assertLess(overrun_ms, 60.0)

    def test_bm3_admin_post_survival_after_anonymous_flood(self):
        """BM-3: Admin requests succeed even when anonymous attackers exhaust unauth budget."""
        temp = tempfile.TemporaryDirectory()
        store = CredentialStore(Path(temp.name) / 'auth.sqlite3')
        budget = RateBudget()
        patchers = [
            patch.object(remote, 'BROWSER_LOGIN', BrowserLogin(remote.API_KEY, store=store)),
            patch.object(remote, 'BACKUP_TOKENS', BackupTokens(remote.API_KEY, store=store)),
            patch.object(remote, 'RATE_BUDGET', budget),
            patch.object(remote, 'APP_ACCESS', AppAccess()),
        ]
        for p in patchers:
            p.start()
        server = BoundedHTTPServer(('127.0.0.1', 0), remote.Handler, max_workers=8)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            # 1. Simulate 200 anonymous requests (depleting unauth-entry bucket)
            for _ in range(200):
                conn = http.client.HTTPConnection(*server.server_address, timeout=2)
                conn.request('POST', '/mcp', json.dumps({'test': 1}), {'Content-Type': 'application/json', 'Authorization': 'Bearer fake'})
                resp = conn.getresponse()
                resp.read()
                conn.close()

            # Confirm unauth-entry is now rejecting
            conn = http.client.HTTPConnection(*server.server_address, timeout=2)
            conn.request('POST', '/mcp', json.dumps({'test': 1}), {'Content-Type': 'application/json', 'Authorization': 'Bearer fake'})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            self.assertEqual(resp.status, 429)

            # 2. Authenticated Admin request MUST still succeed (owner-entry unaffected)
            conn = http.client.HTTPConnection(*server.server_address, timeout=2)
            conn.request('POST', '/mcp', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}),
                         {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + remote.API_KEY})
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            self.assertEqual(resp.status, 200)
            result = json.loads(body)
            self.assertIn('tools', result.get('result', {}))
            print('[BM-3] Admin POST survival after 200 anonymous flood: SUCCESS (Admin got HTTP 200)')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            for p in reversed(patchers):
                p.stop()
            temp.cleanup()


if __name__ == '__main__':
    unittest.main()
