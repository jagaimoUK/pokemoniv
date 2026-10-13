"""No-network tests for Project meta snapshot comparison and controlled update."""
import tempfile
import unittest
from pathlib import Path

import pvpoke_meta_sync as meta


class MetaSyncTests(unittest.TestCase):
    def test_equal_files_pass_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            s, t = p / "source.txt", p / "snapshot.csv"
            content = ("quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                       "quagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n")
            s.write_text(content, encoding="utf-8")
            t.write_text(content, encoding="utf-8")
            self.assertTrue(meta.sync(s, t))
            self.assertEqual(t.read_text(), content)

    def test_mismatch_does_not_write_unless_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            s, t = p / "source.txt", p / "snapshot.csv"
            s.write_text("quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n", encoding="utf-8")
            t.write_text("quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n", encoding="utf-8")
            self.assertFalse(meta.sync(s, t))
            self.assertIn("MUD_BOMB", t.read_text())
            self.assertTrue(meta.sync(s, t, apply=True))
            self.assertEqual(meta.read_rows(s), meta.read_rows(t))

    def test_preserves_duplicates_shadow_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            s, t = p / "source.txt", p / "snapshot.csv"
            rows = ("quagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n"
                    "quagsire,MUD_SHOT,AQUA_TAIL,MUD_BOMB\n"
                    "quagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n")
            s.write_text(rows, encoding="utf-8")
            self.assertTrue(meta.sync(s, t, apply=True))
            self.assertEqual(t.read_text(encoding="utf-8"), rows)

    def test_reject_invalid_rows_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            s, t = p / "source.txt", p / "snapshot.csv"
            s.write_text("quagsire,MUD_SHOT,AQUA_TAIL\n", encoding="utf-8")
            t.write_text("quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                meta.sync(s, t, apply=True)
            self.assertIn("STONE_EDGE", t.read_text())


if __name__ == "__main__":
    unittest.main()
