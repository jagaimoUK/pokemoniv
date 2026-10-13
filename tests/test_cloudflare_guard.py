"""Cloudflare verification should not hang the PvPoke automation for 90s."""
import unittest
from unittest.mock import patch

import pvpoke_batch_v2 as engine


class MatrixPageSecurityTests(unittest.TestCase):
    def test_security_interstitial_stops_without_bypass(self):
        page = engine.Page.__new__(engine.Page)
        page.eval = lambda expression: {
            'ready': 'complete', 'mode': None, 'groups': 0,
            'battle': False, 'title': 'Just a moment...', 'securityCheck': True
        }
        with patch.object(engine.time, 'sleep', lambda _: None):
            with self.assertRaisesRegex(RuntimeError, 'セキュリティ確認.*Cloudflare'):
                page.wait_ready()

    def test_regular_matrix_still_passes(self):
        page = engine.Page.__new__(engine.Page)
        page.eval = lambda expression: {
            'ready': 'complete', 'mode': 'matrix', 'groups': 2,
            'battle': True, 'title': 'PvPoke Matrix', 'securityCheck': False
        }
        page.wait_ready()


if __name__ == '__main__':
    unittest.main()
