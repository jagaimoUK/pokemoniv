"""Authenticated gateway boundary for the Party Builder API."""
import http.client
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

os.environ.setdefault("PVP_API_KEY", "test-" + "x" * 32)
import pvpoke_mcp_remote as gateway


class PartyHTTPTests(unittest.TestCase):
    def setUp(self):
        self.s = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
        self.t = threading.Thread(target=self.s.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.s.shutdown()
        self.s.server_close()
        self.t.join()

    def request(self, path, payload=None, authorized=True, origin=None):
        c = http.client.HTTPConnection(*self.s.server_address)
        h = {"Content-Type": "application/json"}
        if authorized:
            h["Authorization"] = "Bearer " + gateway.API_KEY
        if origin:
            h["Origin"] = origin
        c.request("GET" if payload is None else "POST", path,
                  None if payload is None else json.dumps(payload), h)
        r = c.getresponse()
        result = (r.status, r.read().decode())
        c.close()
        return result

    def test_public_page_contains_no_root_token(self):
        code, text = self.request("/app/party", authorized=False)
        self.assertEqual(code, 200)
        self.assertIn("見せ合い6体", text)
        self.assertNotIn(gateway.API_KEY, text)

    def test_all_mutation_and_read_operations_require_login(self):
        for action in ("list", "get", "save", "start", "status", "cancel", "meta-weights"):
            code, _ = self.request("/app-api/party/" + action, {}, authorized=False)
            self.assertEqual(code, 401)

    def test_same_origin_proxy_is_restricted(self):
        with patch.object(gateway.backend, "_token", return_value="local-token"), patch.object(
             gateway.backend, "_request", return_value={"items": []}) as req:
            code, text = self.request("/app-api/party/list", {})
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(text)["items"], [])
            req.assert_called_once_with("/api/party/list", {},
                                        headers={"X-PvPoke-Token": "local-token"}, timeout=75)
            self.assertEqual(self.request("/app-api/party/list", {},
                             origin="https://attacker.example")[0], 403)
            self.assertEqual(self.request("/app-api/party/delete", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
