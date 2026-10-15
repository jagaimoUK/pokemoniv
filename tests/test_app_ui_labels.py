import subprocess
from pathlib import Path
import unittest

class AppUILabelTests(unittest.TestCase):
    def test_localized_matchups_nicknames_and_export(self):
        p = subprocess.run(['node', 'tests/test_app_ui_labels.js'], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
