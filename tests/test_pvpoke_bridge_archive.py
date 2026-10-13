"""Check bridge uses a persisted ZIP after process restart."""
import io
import unittest
import zipfile
from unittest.mock import patch

import pvpoke_bridge_core as bridge


def make_zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr("ranking_summary.csv", "atk,def,hp,opponent_iv_mode,mean_rating\n0,11,12,default,375\n")
    return buffer.getvalue()


class RestartArchiveTests(unittest.TestCase):
    def test_idle_with_persisted_archive_returns_zip(self):
        b = make_zip_bytes()
        with patch.object(bridge, "status", return_value={
            "state": "idle", "has_previous_archive": True
        }), patch.object(bridge, "_request", return_value=b):
            with bridge._zip() as z:
                self.assertIn("ranking_summary.csv", z.namelist())

    def test_idle_without_archive_rejects(self):
        with patch.object(bridge, "status", return_value={
            "state": "idle", "has_previous_archive": False
        }):
            with self.assertRaises(bridge.BridgeError):
                bridge._zip()

    def test_running_rejects_even_with_old_archive(self):
        with patch.object(bridge, "status", return_value={
            "state": "running", "has_previous_archive": True
        }):
            with self.assertRaises(bridge.BridgeError):
                bridge._zip()


if __name__ == "__main__":
    unittest.main()
