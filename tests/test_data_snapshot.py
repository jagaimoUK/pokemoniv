import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pvpoke_data_snapshot as snapshot


class DataSnapshotTests(unittest.TestCase):
    def test_cached_approved_data_and_bundled_seed_work_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / 'seed'
            seed.mkdir()
            content = b'approved fixture'
            expected = hashlib.sha256(content).hexdigest()
            (seed / 'fixture').write_bytes(content)
            fetch = Mock(side_effect=AssertionError('Network must not be needed'))
            with patch.dict(snapshot.FILES, {'fixture': ('data/fixture', expected)}, clear=True):
                target = root / 'runtime'
                snapshot.install_snapshot(target, fetch, seed=seed)
                snapshot.install_snapshot(target, fetch, seed=root / 'missing')
                self.assertEqual((target / 'fixture').read_bytes(), content)
            fetch.assert_not_called()

    def test_corrupt_data_cannot_replace_a_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'fixture'
            file.write_bytes(b'old file preserved')
            fetch = Mock(return_value=b'unapproved data')
            with patch.dict(snapshot.FILES, {'fixture': ('data/fixture', hashlib.sha256(b'approved').hexdigest())}, clear=True):
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    snapshot.install_snapshot(root, fetch, seed=root / 'missing')
                self.assertEqual(file.read_bytes(), b'old file preserved')
                self.assertEqual(list(root.glob('*.tmp')), [])
            self.assertIn('/' + snapshot.COMMIT + '/', fetch.call_args.args[0])
            self.assertNotIn('/master/', fetch.call_args.args[0])

    def test_corrupt_seed_is_replaced_only_by_verified_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / 'seed'
            seed.mkdir()
            (seed / 'fixture').write_bytes(b'bad')
            content = b'approved'
            fetch = Mock(return_value=content)
            with patch.dict(snapshot.FILES, {'fixture': ('data/fixture', hashlib.sha256(content).hexdigest())}, clear=True):
                snapshot.install_snapshot(root / 'runtime', fetch, seed=seed)
                self.assertEqual((root / 'runtime' / 'fixture').read_bytes(), content)
                self.assertEqual(list((root / 'runtime').glob('*.tmp')), [])

    def test_refresh_reuses_the_approved_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = b'approved'
            (root / 'fixture').write_bytes(content)
            fetch = Mock(return_value=content)
            with patch.dict(snapshot.FILES, {'fixture': ('data/fixture', hashlib.sha256(content).hexdigest())}, clear=True):
                snapshot.install_snapshot(root, fetch, refresh=True, seed=root / 'missing')
            fetch.assert_called_once()

