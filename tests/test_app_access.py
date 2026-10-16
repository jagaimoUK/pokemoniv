import unittest
from unittest.mock import patch
from pvpoke_app_access import AppAccess, BrowserLogin


class AppAccessTests(unittest.TestCase):
    def test_token_expires_and_url_has_fragment_only(self):
        a = AppAccess(ttl=60)
        with patch('pvpoke_app_access.time.monotonic', return_value=100):
            link = a.issue('https://example.test')
            token = link['url'].split('#access=')[1]
            self.assertTrue(a.valid('Bearer ' + token))
        self.assertEqual(link['url'].split('#')[0], 'https://example.test/app')
        with patch('pvpoke_app_access.time.monotonic', return_value=160):
            self.assertFalse(a.valid('Bearer ' + token))
        self.assertFalse(a.valid('Bearer wrong'))

    def test_bound_storage(self):
        a = AppAccess(capacity=2)
        links = [a.issue('https://example.test') for _ in range(3)]
        tokens = ['Bearer ' + x['url'].split('#access=')[1] for x in links]
        self.assertFalse(a.valid(tokens[0]))
        self.assertTrue(a.valid(tokens[-1]))


class BrowserLoginTests(unittest.TestCase):
    def test_persistent_cookie_does_not_reveal_root_key(self):
        key = 'this-key-must-never-be-in-a-cookie-' + 'x' * 32
        login = BrowserLogin(key)
        with patch('pvpoke_app_access.time.time', return_value=1000):
            header = login.issue()
            cookie = header.split(';', 1)[0]
            self.assertTrue(login.valid(cookie))
        self.assertIn('Path=/app-api', header)
        self.assertIn('HttpOnly', header)
        self.assertIn('Secure', header)
        self.assertIn('SameSite=Strict', header)
        self.assertNotIn(key, header)
        self.assertFalse(BrowserLogin('wrong-' + key).valid(cookie))
        self.assertFalse(login.valid(cookie[:-1] + ('a' if cookie[-1] != 'a' else 'b')))
        with patch('pvpoke_app_access.time.time', return_value=1000 + 30 * 24 * 60 * 60):
            self.assertFalse(login.valid(cookie))
        self.assertIn('Max-Age=0', login.clear())

    def test_invalid_cookie_is_rejected(self):
        login = BrowserLogin('x' * 40)
        for cookie in ('', 'pvpoke_app_login=bogus', 'a=b', 'x' * 5000,
                       'pvpoke_app_login=v1.invalid.abc.def'):
            self.assertFalse(login.valid(cookie))
