"""Phase D-4 regression tests for independent review findings (R-01..R-08, D-01..D-03)."""
import base64
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)

import pvpoke_mcp_remote as remote
import pvpoke_web as web
import pvpoke_meta_variants as meta_variants
from pvpoke_app_access import AppAccess, BrowserLogin
from pvpoke_auth_store import CredentialStore
from pvpoke_direct_backend import DirectMatrixClient, DirectMatrixError
from pvpoke_http_security import BoundedHTTPServer, RateBudget
from pvpoke_party_backend import PartyBuilder
from pvpoke_proxy_config import render as render_nginx
from visual_backup import BackupTokens


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _make_fake_jwt(kid: str, sig: str, *, iss='https://issuer.example/', aud='https://app.example/mcp',
                   sub='auth0|owner', scope='openid mcp:tools', exp_offset=300, alg='RS256') -> str:
    header = _b64url(json.dumps({'alg': alg, 'typ': 'JWT', 'kid': kid}).encode('utf-8'))
    payload = _b64url(json.dumps({
        'iss': iss,
        'aud': aud,
        'sub': sub,
        'scope': scope,
        'exp': int(time.time()) + exp_offset,
    }).encode('utf-8'))
    return f'{header}.{payload}.{sig}'


class _FakeInvalidTokenError(Exception):
    pass


class PhaseD4OAuthAndGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CredentialStore(Path(self.temp.name) / 'auth.sqlite3')
        self.budget = RateBudget()
        self.valid_sigs = {'good-sig-1', 'good-sig-rotated'}
        self.decode_calls = []
        self.jwks_fetch_calls = []
        self.active_keys = [types.SimpleNamespace(key_id='kid-1', key='pub-kid-1')]

        fake_jwks = MagicMock()
        def get_signing_keys(refresh=False):
            self.jwks_fetch_calls.append(refresh)
            return list(self.active_keys)
        fake_jwks.get_signing_keys.side_effect = get_signing_keys
        fake_jwks.get_signing_key_from_jwt.side_effect = lambda tok: next(
            (k for k in self.active_keys if k.key_id == self._extract_kid(tok)), None
        )

        fake_jwt_mod = types.SimpleNamespace(
            get_unverified_header=self._fake_header,
            decode=self._fake_decode,
            InvalidTokenError=_FakeInvalidTokenError,
        )

        self.patchers = [
            patch.object(remote, 'BROWSER_LOGIN', BrowserLogin(remote.API_KEY, store=self.store)),
            patch.object(remote, 'BACKUP_TOKENS', BackupTokens(remote.API_KEY, store=self.store)),
            patch.object(remote, 'RATE_BUDGET', self.budget),
            patch.object(remote, 'APP_ACCESS', AppAccess()),
            patch.object(remote, 'AUTH0_ENABLED', True),
            patch.object(remote, 'AUTH0_ISSUER', 'https://issuer.example/'),
            patch.object(remote, 'JWT_AUDIENCE', 'https://app.example/mcp'),
            patch.object(remote, 'AUTH0_ALLOWED_SUB', 'auth0|owner'),
            patch.object(remote, 'OAUTH_SCOPE', 'openid'),
            patch.object(remote, 'JWKS', fake_jwks, create=True),
            patch.object(remote, 'jwt', fake_jwt_mod),
            patch.object(remote, 'InvalidTokenError', _FakeInvalidTokenError),
        ]
        self._clear_oauth_caches()
        for p in self.patchers:
            p.start()

        self.server = BoundedHTTPServer(('127.0.0.1', 0), remote.Handler,
                                        socket_timeout=1.5, request_timeout=3.0, max_workers=8)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for p in reversed(self.patchers):
            p.stop()
        self._clear_oauth_caches()
        self.temp.cleanup()

    @staticmethod
    def _clear_oauth_caches():
        with remote._JWKS_CACHE_LOCK:
            remote._JWKS_KEY_CACHE.clear()
            remote._JWKS_NEG_CACHE.clear()
            remote._JWT_BAD_SIG_CACHE.clear()
            remote._JWT_GOOD_SIG_CACHE.clear()
            remote._LAST_JWKS_REFRESH_AT = 0.0
            remote._JWKS_FULL_SET_FRESH_UNTIL = 0.0

    @staticmethod
    def _extract_kid(token: str) -> str:
        hdr = token.split('.')[0]
        padded = hdr + '=' * (-len(hdr) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')).get('kid', '')

    @staticmethod
    def _fake_header(token: str):
        parts = token.split('.')
        if len(parts) != 3:
            raise _FakeInvalidTokenError('bad token')
        padded = parts[0] + '=' * (-len(parts[0]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))

    def _fake_decode(self, token, key, algorithms=None, audience=None, issuer=None, options=None, leeway=0):
        self.decode_calls.append((key, token.split('.')[2]))
        sig = token.split('.')[2]
        expected_key = f'pub-{self._extract_kid(token)}'
        if key != expected_key or sig not in self.valid_sigs:
            raise _FakeInvalidTokenError('bad signature')
        return {
            'iss': issuer,
            'aud': audience,
            'sub': 'auth0|owner',
            'scope': 'openid mcp:tools',
            'exp': int(time.time()) + 300,
        }

    def _raw_post(self, path: str, body: bytes = b'{"jsonrpc":"2.0","id":1,"method":"ping"}', headers=None) -> bytes:
        host, port = self.server.server_address
        hdrs = {
            'Host': f'{host}:{port}',
            'Content-Type': 'application/json',
            'Content-Length': str(len(body)),
            'Connection': 'close',
        }
        if headers:
            hdrs.update(headers)
        raw_req = f'POST {path} HTTP/1.1\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in hdrs.items()) + '\r\n'
        with socket.create_connection((host, port), timeout=3.0) as sock:
            sock.sendall(raw_req.encode('ascii') + body)
            chunks = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        return b''.join(chunks)

    def _post(self, path: str, token: str | None = None, payload=None, extra_headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3.0)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = token
        if extra_headers:
            headers.update(extra_headers)
        conn.request('POST', path, json.dumps(payload or {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}).encode('utf-8'), headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), body

    def _get(self, path: str):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3.0)
        conn.request('GET', path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_r01_unknown_kid_flood_does_not_lock_out_valid_or_rotated_jwt(self):
        # Exhaust unauth-jwks completely with attacker's unknown kids.
        for i in range(15):
            bad_tok = _make_fake_jwt(f'unknown-{i}', 'forged')
            status, _, _ = self._post('/mcp', token='Bearer ' + bad_tok)
            self.assertIn(status, (401, 429))

        # Cold/cached valid kid-1 succeeds even while unauth-jwks is exhausted.
        good_tok = _make_fake_jwt('kid-1', 'good-sig-1')
        status, _, _ = self._post('/mcp', token='Bearer ' + good_tok)
        self.assertEqual(status, 200)

        # Simulate key rotation on Auth0 when unauth-jwks is exhausted & cooldown passed.
        self.active_keys.append(types.SimpleNamespace(key_id='kid-2', key='pub-kid-2'))
        with remote._JWKS_CACHE_LOCK:
            remote._LAST_JWKS_REFRESH_AT = time.monotonic() - 20.0
            remote._JWKS_FULL_SET_FRESH_UNTIL = 0.0
        rotated_tok = _make_fake_jwt('kid-2', 'good-sig-rotated')
        status, _, _ = self._post('/mcp', token='Bearer ' + rotated_tok)
        self.assertEqual(status, 200)

        # Unknown kid NOT in JWKS must still be rejected (never skips verification).
        unknown_tok = _make_fake_jwt('never-exists-kid', 'good-sig-1')
        status, _, _ = self._post('/mcp', token='Bearer ' + unknown_tok)
        self.assertIn(status, (401, 429))

    def test_r01_expired_cache_removes_stale_rotated_out_kid(self):
        good_tok = _make_fake_jwt('kid-1', 'good-sig-1')
        status, _, _ = self._post('/mcp', token='Bearer ' + good_tok)
        self.assertEqual(status, 200)

        # Expire kid-1 in cache and rotate it out of JWKS.
        with remote._JWKS_CACHE_LOCK:
            key_obj, _ = remote._JWKS_KEY_CACHE['kid-1']
            remote._JWKS_KEY_CACHE['kid-1'] = (key_obj, time.monotonic() - 1.0)
        self.active_keys[:] = [types.SimpleNamespace(key_id='kid-2', key='pub-kid-2')]

        status, _, _ = self._post('/mcp', token='Bearer ' + good_tok)
        self.assertEqual(status, 401)
        with remote._JWKS_CACHE_LOCK:
            self.assertNotIn('kid-1', remote._JWKS_KEY_CACHE)
            self.assertIn('kid-1', remote._JWKS_NEG_CACHE)

    def test_r03_cached_kid_invalid_sig_cpu_bounded_and_never_skips_valid_verify(self):
        # Prime cache with kid-1 via a valid token, also populating known-good helper.
        good_tok = _make_fake_jwt('kid-1', 'good-sig-1')
        status, _, _ = self._post('/mcp', token='Bearer ' + good_tok)
        self.assertEqual(status, 200)
        initial_decodes = len(self.decode_calls)

        # Replay exact same bad token 10 times -> jwt.decode called at most once.
        replay_bad = _make_fake_jwt('kid-1', 'bad-replay')
        for _ in range(10):
            status, _, _ = self._post('/mcp', token='Bearer ' + replay_bad)
            self.assertEqual(status, 401)
        self.assertEqual(len(self.decode_calls), initial_decodes + 1)

        # Flood distinct invalid signatures until unauth-oauth-sig (60/60s) is exhausted.
        got_429 = False
        for i in range(70):
            distinct_bad = _make_fake_jwt('kid-1', f'forged-sig-{i}')
            status, _, _ = self._post('/mcp', token='Bearer ' + distinct_bad)
            if status == 429:
                got_429 = True
                break
            self.assertEqual(status, 401)
        self.assertTrue(got_429)
        decodes_at_cap = len(self.decode_calls)

        # Further distinct forged JWTs must NOT execute jwt.decode while rate-limited.
        for i in range(10):
            status, _, _ = self._post('/mcp', token='Bearer ' + _make_fake_jwt('kid-1', f'overflow-{i}'))
            self.assertEqual(status, 429)
        self.assertEqual(len(self.decode_calls), decodes_at_cap)

        # Legitimate token still succeeds AND still performs real jwt.decode verification.
        status, _, _ = self._post('/mcp', token='Bearer ' + good_tok)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.decode_calls), decodes_at_cap + 1)

        # API key also remains completely unaffected.
        status, _, _ = self._post('/mcp', token='Bearer ' + remote.API_KEY)
        self.assertEqual(status, 200)

    def test_r04_rate_limited_oauth_sends_single_429_never_followed_by_401(self):
        # Exhaust unauth-oauth-sig so next forged cached-kid token hits rate_limited.
        for _ in range(60):
            self.budget.allow('unauth-oauth-sig', 60, 60)
        # Ensure kid-1 is cached.
        with remote._JWKS_CACHE_LOCK:
            remote._JWKS_KEY_CACHE['kid-1'] = (self.active_keys[0], time.monotonic() + 300)

        tok = _make_fake_jwt('kid-1', 'bad-after-cap')
        raw_resp = self._raw_post('/mcp', headers={'Authorization': 'Bearer ' + tok})
        self.assertEqual(raw_resp.count(b'HTTP/1.'), 1, f'Double HTTP response detected: {raw_resp!r}')
        self.assertTrue(raw_resp.startswith(b'HTTP/1.0 429') or raw_resp.startswith(b'HTTP/1.1 429'), raw_resp)
        self.assertNotIn(b'401 Unauthorized', raw_resp)

    def test_r02_gateway_reader_flood_does_not_block_app_shell_and_boundaries_hold(self):
        # Exhaust public-reader-get via /reader-api/v1/flashcards.
        for _ in range(120):
            self.budget.allow('public-reader-get', 120, 60)
        status, _ = self._get('/reader-api/v1/flashcards')
        self.assertEqual(status, 429)

        # /app shell remains reachable (200) on separate 'public-get' bucket.
        status, _ = self._get('/app')
        self.assertEqual(status, 200)

        # Auth boundaries:
        # 1) Browser cookie cannot mint a new session (/app-api/session requires strong_auth).
        cookie_tok = remote.BROWSER_LOGIN.issue().split(';', 1)[0]
        status, _, _ = self._post('/app-api/session', extra_headers={'Cookie': cookie_tok})
        self.assertEqual(status, 401)
        # 2) AppAccess token cannot access /mcp.
        app_tok = remote.APP_ACCESS.issue(remote.APP_ORIGIN)['url'].split('#access=', 1)[1]
        status, _, _ = self._post('/mcp', token='Bearer ' + app_tok)
        self.assertEqual(status, 401)

    def test_new01_unsupported_post_routes_rejected_before_auth_work(self):
        forged = 'Bearer ' + _make_fake_jwt('kid-1', 'forged')
        with patch.object(remote, 'oauth_token_valid',
                          side_effect=AssertionError('OAuth must not run')) as oauth_check:
            with patch.object(remote.BROWSER_LOGIN, 'valid',
                              side_effect=AssertionError('Cookie auth must not run')) as cookie_check:
                for path in ('/health', '/app', '/api/status', '/reader-api/v1/cleanup'):
                    with self.subTest(path=path):
                        status, _, _ = self._post(path, token=forged)
                        self.assertEqual(status, 404)
            oauth_check.assert_not_called()
            cookie_check.assert_not_called()
        self.assertNotIn('unauth-entry', self.budget._buckets)

    def test_new03_malformed_claims_are_invalid_not_auth_outage(self):
        forged = 'Bearer ' + _make_fake_jwt('kid-1', 'forged')
        for exception_type in (TypeError, RecursionError):
            with self.subTest(exception=exception_type.__name__):
                with patch.object(remote, '_unverified_claims_match',
                                  side_effect=exception_type('malformed claims')):
                    status, _, _ = self._post('/mcp', token=forged)
                self.assertEqual(status, 401)

        # Also exercise the real deeply nested JSON parsing path.
        header = _b64url(json.dumps({'alg': 'RS256', 'kid': 'kid-1'}).encode('utf-8'))
        nested = _b64url(b'[' * 1200 + b'0' + b']' * 1200)
        malformed = f'Bearer {header}.{nested}.forged'
        self.assertLess(len(malformed), 4096)
        status, _, _ = self._post('/mcp', token=malformed)
        self.assertEqual(status, 401)
        self.assertIn('unauth-entry', self.budget._buckets)
        self.assertLess(self.budget._buckets['unauth-entry'][0], 180)

    def test_nginx_template_enforces_limits_independent_of_untrusted_credentials(self):
        conf = render_nginx(8787)
        self.assertNotIn('$http_authorization', conf)
        self.assertNotIn('$http_cookie', conf)
        self.assertIn('limit_conn api_connections 24;', conf)
        self.assertIn('limit_req zone=api_requests burst=20 nodelay;', conf)
        self.assertIn('limit_req zone=api_global_requests burst=40 nodelay;', conf)
        self.assertIn('limit_req_zone $binary_remote_addr zone=api_requests:64k rate=5r/s;', conf)
        self.assertIn('limit_req_zone $server_name zone=api_global_requests:64k rate=10r/s;', conf)
        self.assertIn('limit_req_zone $binary_remote_addr zone=app_page_requests:64k rate=10r/s;', conf)
        self.assertIn('location = /app', conf)
        self.assertIn('location ^~ /app/', conf)
        self.assertIn('limit_conn app_connections 8;', conf)
        self.assertIn('limit_conn public_connections 8;', conf)
        health = conf.split('location = /health {', 1)[1].split('}', 1)[0]
        self.assertIn('limit_conn public_connections 8;', health)
        self.assertIn('limit_req zone=peer_requests burst=40 nodelay;', health)


class PhaseD4ProcessAndConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.gm = Path('tests/fixtures/strategy_gamemaster.json').resolve()

    def tearDown(self):
        web.COMPUTE_OWNER = None
        web.BATTLE_RUNNING = False
        web.STATUS['state'] = 'idle'
        self.tmp.cleanup()

    @unittest.skipUnless(os.name == 'posix', 'POSIX process group reaping test')
    def test_d01_reaps_grandchild_when_node_leader_exits_abnormally(self):
        pid_file = self.work / 'grandchild.pid'
        # Spawn a worker that spawns a grandchild in same PGID, reports grandchild PID, and exits abnormally.
        worker_code = (
            'import json, os, subprocess, sys, time\n'
            f'pf = {str(pid_file)!r}\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
            'open(pf, "w").write(str(child.pid))\n'
            'sys.stdin.readline()\n'
            'os._exit(1)\n'
        )
        orig_popen = subprocess.Popen
        def fake_popen(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1].endswith('pvpoke_node_matrix.js'):
                return orig_popen([sys.executable, '-u', '-c', worker_code], *args, **kwargs)
            return orig_popen(cmd, *args, **kwargs)

        with patch('subprocess.Popen', side_effect=fake_popen):
            client = DirectMatrixClient(gamemaster=self.gm, log_dir=self.work, timeout_seconds=1.0)
        # Wait briefly until grandchild PID file exists
        for _ in range(40):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            time.sleep(0.05)
        grandchild_pid = int(pid_file.read_text().strip())

        with self.assertRaises(DirectMatrixError):
            client.simulate([{'atk': 1, 'def': 11, 'hp': 8}], [{'species': 'altaria'}], (1, 1))

        # Both leader (already exited) and orphaned grandchild must be terminated (gone or zombie awaiting init wait).
        deadline = time.monotonic() + 2.0
        dead = False
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild_pid, 0)
            except ProcessLookupError:
                dead = True
                break
            status_path = Path(f'/proc/{grandchild_pid}/status')
            if status_path.exists() and any(
                l.startswith('State:') and 'Z' in l.split()[1]
                for l in status_path.read_text().splitlines()
            ):
                dead = True
                break
            time.sleep(0.05)
        self.assertTrue(dead, f'Grandchild {grandchild_pid} still alive after close()')

    def test_d01_error_messages_are_constant_without_exception_text(self):
        worker_code = 'import sys; sys.stdin.readline(); sys.stdout.write("not-json-secret-/etc/passwd\\n"); sys.stdout.flush()'
        orig_popen = subprocess.Popen
        def fake_popen(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1].endswith('pvpoke_node_matrix.js'):
                return orig_popen([sys.executable, '-u', '-c', worker_code], *args, **kwargs)
            return orig_popen(cmd, *args, **kwargs)

        with patch('subprocess.Popen', side_effect=fake_popen):
            client = DirectMatrixClient(gamemaster=self.gm, log_dir=self.work, timeout_seconds=1.0)
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate([{'atk': 1, 'def': 11, 'hp': 8}], [{'species': 'altaria'}], (1, 1))
        self.assertEqual(str(ctx.exception), 'PvPoke Node response parsing failed')
        self.assertNotIn('/etc/passwd', str(ctx.exception))

    def test_d02_party_start_rolls_back_active_and_global_status_on_thread_error(self):
        party = PartyBuilder(self.work / 'party.sqlite3')
        global_status = {'state': 'idle', 'message': 'ok'}
        lock = threading.RLock()
        fake_species = {'quagsire': {'speciesName': 'Quagsire', 'dex': 195, 'fastMoves': ['MUD_SHOT'], 'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE']}}
        with patch.dict(os.environ, {'PVP_ENGINE': 'direct'}):
            with patch.object(threading.Thread, 'start', side_effect=RuntimeError('cannot allocate thread')):
                with self.assertRaises(RuntimeError):
                    party.start(
                        {'mode': 'analyze', 'party': [{'species': 'quagsire', 'fast': 'MUD_SHOT', 'charged1': 'AQUA_TAIL', 'charged2': 'STONE_EDGE'}]},
                        catalog=fake_species, species=fake_species, cpms={50: 0.84},
                        engine=web.engine, work=self.work, global_lock=lock, global_status=global_status,
                    )
        self.assertIsNone(party._active)
        self.assertEqual(global_status['state'], 'idle')
        self.assertEqual(global_status['message'], 'ok')

    def test_d02_meta_variants_deadline_enforced_between_shields_and_gm_occ_and_cap(self):
        gm_file = self.work / 'gamemaster.json'
        gm_file.write_text('{"moves":[{"moveId":"MUD_SHOT","type":"ground","power":3,"energyGain":9,"cooldown":2},{"moveId":"AQUA_TAIL","type":"water","power":50,"energy":35},{"moveId":"STONE_EDGE","type":"rock","power":100,"energy":55}],"timestamp":"2026-10-13"}')
        gm_sha = hashlib.sha256(gm_file.read_bytes()).hexdigest()

        # 1) Deadline enforced mid-shield loop inside evaluate()
        lock = threading.RLock()
        status = {'state': 'idle'}
        fake_client = MagicMock()
        def slow_sim(*args, **kwargs):
            time.sleep(0.06)
            return [[0, 0], [0, 500]]
        fake_client.simulate.side_effect = slow_sim
        job = {'id': 'p1', 'gm_sha256': gm_sha, 'source_sha256': 's1', 'source_csv': 'quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n', 'attempts': 0}
        species = {'quagsire': {'fastMoves': ['MUD_SHOT'], 'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE']}}
        with patch.object(meta_variants.engine, 'DATA', self.work):
            with patch('pvpoke_meta_variants.shortlist', return_value=[('quagsire', 'MUD_SHOT', 'AQUA_TAIL', 'STONE_EDGE')]):
                with patch('pvpoke_meta_variants.prepared_rows', return_value=[['row']]):
                    with self.assertRaises(TimeoutError):
                        meta_variants.evaluate(job, fake_client, species, {50: 0.84}, lock, status, MagicMock(),
                                               max_job_wall_seconds=0.10)
        self.assertLess(fake_client.simulate.call_count, len(meta_variants.SHIELDS))

        # 2) apply() rejects if GameMaster changed before apply (R-06)
        gm_file.write_text('{"moves":[],"timestamp":"changed"}')
        self.assertFalse(meta_variants.apply(self.work, job, []))

        # 3) start() startup recovery caps _queued at MAX_PENDING_JOBS (R-05)
        import queue as _q
        local_q = _q.Queue()
        local_queued = set()
        new_sha = hashlib.sha256(gm_file.read_bytes()).hexdigest()
        job_dir = meta_variants.directory(self.work)
        job_dir.mkdir(parents=True, exist_ok=True)
        for i in range(meta_variants.MAX_PENDING_JOBS + 5):
            (job_dir / f'j_{i:02d}.json').write_text(json.dumps({
                'id': f'p_{i}', 'state': 'queued', 'minimal_policy': 1,
                'attempts': 0, 'gm_sha256': new_sha, 'source_sha256': 'src', 'created': float(i),
            }))
        with patch.object(meta_variants, '_runtime', None), \
                patch.object(meta_variants, '_queue', local_q), \
                patch.object(meta_variants, '_queued', local_queued), \
                patch.object(meta_variants.engine, 'DATA', self.work), \
                patch.object(meta_variants.presets, 'resolve', return_value={'manual_only': False, 'sha256': 'src'}), \
                patch.object(threading.Thread, 'start'):
            meta_variants.start(self.work, lock, status)
            self.assertEqual(len(local_queued), meta_variants.MAX_PENDING_JOBS)
        deferred_count = sum(1 for p in job_dir.glob('*.json') if json.loads(p.read_text()).get('state') == 'deferred')
        self.assertEqual(deferred_count, 5)

    def test_r08_load_catalog_preserves_gamemaster_timestamp(self):
        species = {'quagsire': {'speciesName': 'Quagsire', 'dex': 195, 'fastMoves': ['MUD_SHOT'], 'chargedMoves': ['AQUA_TAIL', 'STONE_EDGE']}}
        with patch.dict(web.CATALOG), patch.object(web, 'configure_engine'), \
                patch.object(web.engine, 'game_data', return_value=({'timestamp': '2026-10-13 01:07:13', 'moves': []}, [], species)), \
                patch.object(web.meta_variants, 'start'):
            web.load_catalog()
            self.assertEqual(web.CATALOG['timestamp'], '2026-10-13 01:07:13')

    @unittest.skipUnless(os.name == 'posix', 'POSIX process group test')
    def test_d01_web_stop_process_group_kills_orphaned_descendant(self):
        pid_file = self.work / 'web_gc.pid'
        code = (
            f'import subprocess, sys, os\n'
            f'c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
            f'open({str(pid_file)!r}, "w").write(str(c.pid))\n'
            f'os._exit(0)\n'
        )
        proc = subprocess.Popen([sys.executable, '-c', code], start_new_session=True)
        proc.wait(timeout=3.0)
        self.assertIsNotNone(proc.poll())
        gc_pid = int(pid_file.read_text().strip())
        web.stop_process_group(proc)

        deadline = time.monotonic() + 2.0
        dead = False
        while time.monotonic() < deadline:
            try:
                os.kill(gc_pid, 0)
            except ProcessLookupError:
                dead = True
                break
            status_path = Path(f'/proc/{gc_pid}/status')
            if status_path.exists() and any(
                l.startswith('State:') and 'Z' in l.split()[1]
                for l in status_path.read_text().splitlines()
            ):
                dead = True
                break
            time.sleep(0.05)
        self.assertTrue(dead, f'Web descendant {gc_pid} still alive')

    def test_d02_web_api_run_releases_compute_and_resets_status_on_thread_start_error(self):
        from email.message import Message
        from io import BytesIO
        body = json.dumps({
            'candidate': {'species': 'quagsire', 'fast': 'MUD_SHOT', 'charged1': 'AQUA_TAIL', 'charged2': 'STONE_EDGE'},
            'ivs': '0,15,15',
            'opponents': [{'species': 'quagsire', 'fast': 'MUD_SHOT', 'charged1': 'AQUA_TAIL', 'charged2': 'STONE_EDGE'}],
            'shields': 'all',
        }).encode('utf-8')
        hdrs = Message()
        hdrs['Content-Length'] = str(len(body))
        hdrs['Content-Type'] = 'application/json'
        hdrs['Host'] = f'127.0.0.1:{web.PORT}'
        hdrs['X-PvPoke-Token'] = web.TOKEN
        handler = web.Handler.__new__(web.Handler)
        handler.server = types.SimpleNamespace(server_address=('127.0.0.1', web.PORT))
        handler.path = '/api/run'
        handler.headers = hdrs
        handler.rfile = BytesIO(body)
        responses = []
        handler.respond = lambda code, obj=None, *a, **kw: responses.append((code, obj))

        preview = {'candidate_count': 1}
        with patch.object(web, 'prepare_payload', return_value=({'shields': 'all'}, [], [], preview)), \
                patch.object(web, 'save_input'), \
                patch.object(threading.Thread, 'start', side_effect=RuntimeError('thread limit')):
            handler.do_POST()

        self.assertEqual(responses[-1][0], 500)
        self.assertEqual(web.STATUS['state'], 'error')
        self.assertIsNotNone(web.STATUS['finished_at'])
        self.assertIsNone(web.COMPUTE_OWNER)
        self.assertFalse(web._compute_busy_locked())


if __name__ == '__main__':
    unittest.main()

