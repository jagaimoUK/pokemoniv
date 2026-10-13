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

    def test_normalization_and_sha_match(self):
        a = "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
        b = "quagsire, MUD_SHOT, AQUA_TAIL, STONE_EDGE\r\n"
        self.assertEqual(live.digest(a), live.digest(b))


if __name__ == "__main__":
    unittest.main()
