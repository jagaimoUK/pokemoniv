"""HTTP integration: app uses existing authentication and exact workflow ticket.
No network simulation or production credentials are required.
"""
import http.client
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

os.environ.setdefault('PVP_API_KEY', 'test-' + 'x' * 32)
import pvpoke_mcp_remote as remote
from pvpoke_iv_workflow import IVWorkflow
from test_iv_workflow import CANDIDATE, IVS, FakeBackend


class AppGatewayTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.backend.candidate_name = lambda sid: 'Quagsire'
        self.patchers = [patch.object(remote, 'IV_RUNNER', IVWorkflow(self.backend)),
                         patch.object(remote.backend, 'meta_status', self.backend.meta_status)]
        for p in self.patchers:
            p.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), remote.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for p in reversed(self.patchers):
            p.stop()

    def request(self, path, payload=None, token=True, origin=None):
        c = http.client.HTTPConnection(*self.server.server_address)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + remote.API_KEY
        if origin:
            headers['Origin'] = origin
        c.request('GET' if payload is None else 'POST', path,
                  None if payload is None else json.dumps(payload), headers)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def test_public_ui_has_no_credentials_or_data(self):
        status, page = self.request('/app', token=False)
        self.assertEqual(status, 200)
        self.assertIn('アプリで自動推薦', page)
        self.assertNotIn(remote.API_KEY, page)

    def test_app_data_requires_current_mcp_authentication(self):
        for path in ['/app-api/catalog', '/app-api/import', '/app-api/run', '/app-api/result']:
            status, _ = self.request(path, {}, token=False)
            self.assertEqual(status, 401)
        self.assertEqual(self.backend.run_count, 0)

    def test_import_validates_without_starting_a_battle(self):
        from test_app_input import CATALOG
        with patch.object(remote.backend, '_request', return_value=CATALOG):
            status, body = self.request('/app-api/import', {
                'text': 'quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n0,11,12\n3,13,8'})
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertEqual(result['candidate_count'], 2)
            self.assertEqual(result['ivs'], '0,11,12\n3,13,8')
            self.assertEqual(self.backend.run_count, 0)

    def test_cross_origin_and_unknown_operations_are_rejected(self):
        self.assertEqual(self.request('/app-api/run', {}, origin='https://invalid.example')[0], 403)
        self.assertEqual(self.request('/app-api/arbitrary', {})[0], 404)
        self.assertEqual(self.backend.run_count, 0)

    def test_short_lived_app_access_cannot_authenticate_mcp(self):
        token = remote.APP_ACCESS.issue(remote.APP_ORIGIN)['url'].split('#access=')[1]
        catalog = {'ready': True, 'species': {}, 'presets': []}
        with patch.object(remote.backend, '_request', return_value=catalog):
            c = http.client.HTTPConnection(*self.server.server_address)
            headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
            c.request('POST', '/app-api/catalog', '{}', headers)
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            r.read()
            c.request('POST', '/mcp', '{}', headers)
            r = c.getresponse()
            self.assertEqual(r.status, 401)
            r.read()
            c.close()

    def test_remembered_login_only_unlocks_app(self):
        c = http.client.HTTPConnection(*self.server.server_address)
        api_headers = {
            'Content-Type': 'application/json',
            'Origin': remote.APP_ORIGIN,
            'Authorization': 'Bearer ' + remote.API_KEY,
        }
        c.request('POST', '/app-api/session', '{}', api_headers)
        response = c.getresponse()
        self.assertEqual(response.status, 200)
        saved_cookie = response.getheader('Set-Cookie')
        response.read()
        self.assertIn('HttpOnly', saved_cookie)
        self.assertIn('SameSite=Strict', saved_cookie)
        self.assertIn('Max-Age=2592000', saved_cookie)
        self.assertNotIn(remote.API_KEY, saved_cookie)

        cookie_only = {
            'Content-Type': 'application/json',
            'Cookie': saved_cookie.split(';', 1)[0],
            'Origin': remote.APP_ORIGIN,
        }
        with patch.object(remote.backend, '_request', return_value={'ready': True, 'species': {}}):
            c.request('POST', '/app-api/catalog', '{}', cookie_only)
            response = c.getresponse()
            self.assertEqual(response.status, 200)
            response.read()

        c.request('POST', '/app-api/session', '{}', cookie_only)
        response = c.getresponse()
        self.assertEqual(response.status, 401)
        response.read()

        c.request('POST', '/mcp', '{}', cookie_only)
        response = c.getresponse()
        self.assertEqual(response.status, 401)
        response.read()

        c.request('POST', '/app-api/catalog', '{}',
                  {**cookie_only, 'Origin': 'https://attacker.example'})
        response = c.getresponse()
        self.assertEqual(response.status, 403)
        response.read()

        c.request('POST', '/app-api/logout', '{}', cookie_only)
        response = c.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn('Max-Age=0', response.getheader('Set-Cookie'))
        response.read()
        c.close()

    def test_launch_poll_recommendations_and_gpt_mode(self):
        args = {'candidate': CANDIDATE, 'ivs': IVS, 'wait_seconds': 0}
        status, body = self.request('/app-api/run', args, origin=remote.APP_ORIGIN)
        self.assertEqual(status, 200)
        ref = json.loads(body)['run_ref']
        self.backend.state = 'done'
        status, body = self.request('/app-api/result', {'run_ref': ref, 'wait_seconds': 0})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(result['complete'])
        self.assertEqual(result['selection']['format'], 'app-recommendations-v1')
        self.assertFalse(result['meta_verified_against_project'])
        self.assertEqual(self.backend.run_count, 1)
        args['report_format'] = 'decision'
        status, body = self.request('/app-api/run', args)
        ref = json.loads(body)['run_ref']
        self.backend.state = 'done'
        _, body = self.request('/app-api/result', {'run_ref': ref, 'wait_seconds': 0})
        result = json.loads(body)
        self.assertEqual(result['reports']['default']['format'], 'decision-v2')
        self.assertNotIn('selection', result)


if __name__ == '__main__':
    unittest.main()
