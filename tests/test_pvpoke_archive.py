"""End-to-end local checks for verify -> preserve ZIP -> safe cleanup."""
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pvpoke_archive as store


def make_zip(path: Path, complete=True):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        files = sorted(store.REQUIRED) if complete else ["manifest.json"]
        for name in files:
            z.writestr(name, f"data:{name}\\n")


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
