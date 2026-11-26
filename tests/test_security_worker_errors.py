"""Synthetic backend failures must not persist secrets in user-visible status.

These unit tests use only temporary storage, patches and dummy markers.
They do not call the connected PvPoke MCP or production servers.
"""
from collections import deque
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pvpoke_party_backend import PartyBuilder
import pvpoke_web as web


class WorkerErrorDisclosureTests(unittest.TestCase):
    def test_party_worker_hides_unexpected_exception_from_persisted_status(self):
        marker = 'TEST_PRIVATE_PARTY_PATH_TOKEN_NOT_REAL'
        with tempfile.TemporaryDirectory() as root:
            party = PartyBuilder(Path(root))
            with patch.object(party, '_compute', side_effect=OSError(marker)):
                party._worker('test-party', {}, None, None, None, None,
                              Path(root), threading.RLock())
            result = party.run_status('test-party')
            self.assertEqual(result['status'], 'error')
            self.assertNotIn(marker, str(result))
            self.assertIn('再試行', result['message'])

            # Invalid user inputs still provide actionable feedback.
            with patch.object(party, '_compute', side_effect=ValueError('技構成が不正です')):
                party._worker('test-input', {}, None, None, None, None,
                              Path(root), threading.RLock())
            self.assertIn('技構成が不正です', party.run_status('test-input')['message'])

            with patch.object(party, '_compute', side_effect=RuntimeError('cancelled')):
                party._worker('test-cancel', {}, None, None, None, None,
                              Path(root), threading.RLock())
            self.assertEqual(party.run_status('test-cancel')['status'], 'cancelled')

    def test_catalog_initialization_does_not_return_internal_error_text(self):
        marker = 'TEST_PRIVATE_CATALOG_PATH_TOKEN_NOT_REAL'
        catalog = {'ready': False, 'error': None}
        with patch.object(web, 'CATALOG', catalog), patch.object(
                web, 'configure_engine', side_effect=OSError(marker)):
            web.load_catalog()
            self.assertFalse(catalog['ready'])
            self.assertNotIn(marker, str(catalog))
            self.assertIn('読み込み', catalog['error'])

    def test_iv_background_error_does_not_persist_private_exception(self):
        marker = 'TEST_PRIVATE_IV_RUNNER_PATH_TOKEN_NOT_REAL'
        status = {'state': 'idle', 'logs': deque(maxlen=120)}
        with patch.object(web, 'STATUS', status), patch.object(
                web, 'CANCEL_REQUESTED', False), patch.object(
                web.subprocess, 'Popen', side_effect=OSError(marker)):
            web.background_run('s0')
            self.assertEqual(status['state'], 'error')
            self.assertNotIn(marker, str(status))
            self.assertIn('再試行', status['message'])


if __name__ == '__main__':
    unittest.main()
