"""Exercise actual browser-script control flow with a small DOM/API fixture."""
from pathlib import Path
import shutil
import subprocess
import unittest


class AppUIQueueTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    def test_sequential_jobs_resume_partial_failure_and_copy(self):
        root = Path(__file__).resolve().parents[1]
        p = subprocess.run(['node', 'tests/test_app_ui_queue.js'], cwd=root,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
