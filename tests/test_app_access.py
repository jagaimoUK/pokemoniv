import unittest
from unittest.mock import patch
from pvpoke_app_access import AppAccess


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
