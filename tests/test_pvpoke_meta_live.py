"""Project snapshot synchronization is atomic, validated, and persistent."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pvpoke_meta_live as live


SPECIES = {
    "quagsire": {
        "fastMoves": ["MUD_SHOT"],
        "chargedMoves": ["AQUA_TAIL", "STONE_EDGE", "MUD_BOMB"],
    },
    "altaria": {
        "fastMoves": ["DRAGON_BREATH"],
        "chargedMoves": ["SKY_ATTACK", "FLAMETHROWER"],
    },
}


class LiveMetaTests(unittest.TestCase):
    def test_atomic_persist_and_same_content_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                source = ("quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                          "altaria,DRAGON_BREATH,SKY_ATTACK,FLAMETHROWER\n")
                first = live.sync(work, source, SPECIES)
                self.assertTrue(first["changed"])
                self.assertEqual(first["rows"], 2)
                self.assertEqual(first["source"], "project_synced")
                self.assertEqual(live.active_path(work).read_text(), source)
                again = live.sync(work, source, SPECIES)
                self.assertFalse(again["changed"])
                self.assertEqual(first["sha256"], again["sha256"])

    def test_invalid_replacement_preserves_prior_source(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                good = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                live.sync(work, good, SPECIES)
                old = live.get_status(work)["sha256"]
                with self.assertRaises(ValueError):
                    live.sync(work, "quagsire,MUD_SHOT,AQUA_TAIL,INVALID\n", SPECIES)
                self.assertEqual(live.get_status(work)["sha256"], old)
                self.assertEqual(live.active_path(work).read_text(), good)

    def test_duplicate_and_malformed_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                row = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                with self.assertRaises(ValueError):
                    live.sync(work, row + row, SPECIES)
                with self.assertRaises(ValueError):
                    live.sync(work, "quagsire,MUD_SHOT,STONE_EDGE\n", SPECIES)

    def test_preview_only_then_exact_apply_with_optimistic_lock(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                original = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                replacement = ("quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n"
                               "altaria,DRAGON_BREATH,SKY_ATTACK,FLAMETHROWER\n")
                live.sync(work, original, SPECIES)
                old = live.get_status(work)
                proposal = live.preview(work, replacement, SPECIES)
                self.assertEqual(proposal["current_rows"], 1)
                self.assertEqual(proposal["rows"], 2)
                self.assertEqual(proposal["added_count"], 2)
                self.assertEqual(proposal["removed_count"], 1)
                self.assertTrue(proposal["changed"])
                self.assertEqual(live.get_status(work), old)
                with self.assertRaisesRegex(ValueError, "プレビュー"):
                    live.sync(work, replacement, SPECIES,
                              expected_previous_sha256="0" * 64,
                              expected_sha256=proposal["sha256"])
                with self.assertRaisesRegex(ValueError, "プレビュー"):
                    live.sync(work, original, SPECIES,
                              expected_previous_sha256=old["sha256"],
                              expected_sha256=proposal["sha256"])
                self.assertEqual(live.active_path(work).read_text(), original)
                saved = live.sync(work, replacement, SPECIES,
                                  expected_previous_sha256=old["sha256"],
                                  expected_sha256=proposal["sha256"])
                self.assertTrue(saved["changed"])
                self.assertEqual(saved["rows"], 2)
                self.assertEqual(live.active_path(work).read_text(), replacement)
                with self.assertRaisesRegex(ValueError, "プレビュー"):
                    live.sync(work, original, SPECIES,
                              expected_previous_sha256=old["sha256"])

    def test_preview_rejects_invalid_data_without_changing_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ, {"PVP_ARCHIVE_DIR": d}):
                work = Path(d) / "work"
                old = live.get_status(work)
                for content in (
                    "quagsire,MUD_SHOT,BOGUS,STONE_EDGE\n",
                    "missingno,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n",
                    "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n" * 2,
                    "quagsire,MUD_SHOT,AQUA_TAIL\n",
                ):
                    with self.assertRaises(ValueError):
                        live.preview(work, content, SPECIES)
                self.assertEqual(live.get_status(work), old)
                self.assertFalse(live.uploaded_path(work).exists())

    def test_normalization_and_sha_match(self):
        a = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
        b = "quagsire, MUD_SHOT, AQUA_TAIL, STONE_EDGE\r\n"
        self.assertEqual(live.digest(a), live.digest(b))


if __name__ == "__main__":
    unittest.main()
