"""Retention never removes newest five or the verified latest pointer."""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pvpoke_archive as archives


def small_zip(path):
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"batch_mode": "simple"}))
        bundle.writestr("ranking_summary.csv", "test")
        for shield in archives.SHIELDS:
            bundle.writestr(f"default_{shield}.csv", "a,b")


class RetentionTests(unittest.TestCase):
    def test_old_runs_removed_after_verified_latest(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                store = archives.archive_dir(work)
                store.mkdir(parents=True)
                for i in range(9):
                    small_zip(store / f"pvpoke_{i:04d}.zip")
                small_zip(store / "latest.zip")
                result = archives.prune_archives(work, keep_count=5, max_bytes=200000)
                self.assertEqual(result["removed"], 4)
                self.assertEqual(archives.archive_stats(work)["archive_count"], 5)
                self.assertTrue((store / "pvpoke_0008.zip").exists())
                self.assertFalse((store / "pvpoke_0000.zip").exists())
                archives.verify_zip(store / "latest.zip")

    def test_corrupted_latest_never_prunes(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                store = archives.archive_dir(work)
                store.mkdir(parents=True)
                for i in range(7):
                    small_zip(store / f"pvpoke_{i:04d}.zip")
                (store / "latest.zip").write_bytes(b"corrupt")
                with self.assertRaises(zipfile.BadZipFile):
                    archives.prune_archives(work, keep_count=5)
                self.assertEqual(archives.archive_stats(work)["archive_count"], 7)

    def test_preserves_symlinks_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                store = archives.archive_dir(work)
                store.mkdir(parents=True)
                for i in range(8):
                    small_zip(store / f"pvpoke_{i:04d}.zip")
                small_zip(store / "latest.zip")
                foreign = Path(d) / "outside.zip"
                small_zip(foreign)
                (store / "pvpoke_extra.zip").symlink_to(foreign)
                (store / "settings.txt").write_text("keep")
                archives.prune_archives(work, keep_count=5)
                self.assertTrue((store / "pvpoke_extra.zip").is_symlink())
                self.assertTrue(foreign.exists())
                self.assertEqual((store / "settings.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
