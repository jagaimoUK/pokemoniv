"""Test optional meta UI without browser credentials or a running server."""
from pathlib import Path
import shutil
import subprocess
import unittest


class AppMetaUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    def test_optional_meta_preview_then_save(self):
        root = Path(__file__).resolve().parents[1]
        p = subprocess.run(['node', 'tests/test_app_meta_ui.js'], cwd=root,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
