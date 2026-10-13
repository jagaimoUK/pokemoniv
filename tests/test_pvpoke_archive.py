"""End-to-end local checks for verify -> preserve ZIP -> safe cleanup."""
import os
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pvpoke_archive as store


def make_zip(path: Path, complete=True, batch_mode="detailed"):
    modes = ("default",) if batch_mode == "simple" else store.MODES
    files = ({"manifest.json", "ranking_summary.csv"}
             | {f"{mode}_{shield}.csv" for mode in modes for shield in store.SHIELDS})
    if not complete:
        files = {"manifest.json"}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            content = json.dumps({"batch_mode": batch_mode}) if name == "manifest.json" else f"data:{name}\\n"
            z.writestr(name, content)


class ArchiveTests(unittest.TestCase):
    def test_keep_archive_and_delete_only_temporary_batch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            work = root / "work"
            batch = work / "batch24_results"
            parts = batch / "engine_job" / "results" / "parts_abc"
            parts.mkdir(parents=True)
            (parts / "partial.csv").write_text("partial")
            make_zip(batch / "pvpoke_24_conditions.zip")
            volume = root / "volume"
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": str(volume)}):
                archive = store.preserve_and_cleanup(batch, work)
                self.assertFalse(batch.exists())
                self.assertEqual(len(list((volume / "pvpoke_archives").glob("pvpoke_*.zip"))), 1)
                self.assertEqual(store.archived_latest(work).read_bytes(), archive.read_bytes())
                store.verify_zip(archive)
                store.verify_zip(store.archived_latest(work))

    def test_simple_zip_only_six_files_accepted_and_cleaned(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            work, volume = root / "work", root / "volume"
            batch = work / "batch24_results"
            batch.mkdir(parents=True)
            make_zip(batch / "pvpoke_24_conditions.zip", batch_mode="simple")
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": str(volume)}):
                saved = store.preserve_and_cleanup(batch, work)
                with zipfile.ZipFile(saved) as z:
                    self.assertEqual(len([n for n in z.namelist() if n.endswith(".csv")]), 7)
                    self.assertNotIn("rank1_s0.csv", z.namelist())
                self.assertFalse(batch.exists())

    def test_simple_archive_missing_shield_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            batch = work / "batch24_results"
            batch.mkdir(parents=True)
            dest = batch / "pvpoke_24_conditions.zip"
            with zipfile.ZipFile(dest, "w") as z:
                z.writestr("manifest.json", json.dumps({"batch_mode": "simple"}))
                z.writestr("ranking_summary.csv", "ok")
                z.writestr("default_s0.csv", "only one")
            with self.assertRaises(ValueError):
                store.preserve_and_cleanup(batch, work)
            self.assertTrue(batch.exists())

    def test_corrupted_archive_preserves_everything(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            batch = work / "batch24_results"
            batch.mkdir(parents=True)
            (batch / "pvpoke_24_conditions.zip").write_bytes(b"not a zip")
            with self.assertRaises((ValueError, zipfile.BadZipFile)):
                store.preserve_and_cleanup(batch, work)
            self.assertTrue(batch.exists())

    def test_missing_file_preserves_everything(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            batch = work / "batch24_results"
            batch.mkdir(parents=True)
            make_zip(batch / "pvpoke_24_conditions.zip", complete=False)
            with self.assertRaises(ValueError):
                store.preserve_and_cleanup(batch, work)
            self.assertTrue(batch.exists())

    def test_unwritable_storage_preserves_intermediates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            work = root / "work"
            batch = work / "batch24_results"
            batch.mkdir(parents=True)
            make_zip(batch / "pvpoke_24_conditions.zip")
            occupied = root / "not_a_dir"
            occupied.write_text("content")
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": str(occupied)}):
                with self.assertRaises((OSError, ValueError)):
                    store.preserve_and_cleanup(batch, work)
            self.assertTrue(batch.exists())

    def test_never_remove_wrong_path(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            wrong = work / "other"
            wrong.mkdir(parents=True)
            with self.assertRaises(ValueError):
                store.preserve_and_cleanup(wrong, work)
            self.assertTrue(wrong.exists())


if __name__ == "__main__":
    unittest.main()
