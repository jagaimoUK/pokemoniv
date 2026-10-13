"""Check Railway volume bootstrap remains compatible with non-root runtime."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VolumeBootstrapTests(unittest.TestCase):
    def test_shell_syntax(self):
        result = subprocess.run(["/bin/sh", "-n", str(ROOT / "volume_bootstrap.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_drop_privileges_after_chown(self):
        entry = (ROOT / "volume_bootstrap.sh").read_text(encoding="utf-8")
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("chown appuser:appuser", entry)
        self.assertIn("exec gosu appuser /app/start.sh", entry)
        self.assertLess(entry.index("chown appuser:appuser"),
                        entry.index("exec gosu appuser /app/start.sh"))
        self.assertIn("COPY volume_bootstrap.sh", docker)
        self.assertIn('CMD ["/app/volume_bootstrap.sh"]', docker)


if __name__ == "__main__":
    unittest.main()
