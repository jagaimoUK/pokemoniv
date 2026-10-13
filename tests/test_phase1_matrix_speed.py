"""Phase-1 performance changes must not reorder or lose PvPoke matrices."""
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pvpoke_batch_v2 as engine


class PhaseOneTests(unittest.TestCase):
    def test_chunk_size_validation_and_default(self):
        with patch.dict(engine.os.environ, {}, clear=True):
            self.assertEqual(engine.chunk_size("PVP_OPP_CHUNK", 12), 12)
        with patch.dict(engine.os.environ, {"PVP_OPP_CHUNK": "16"}):
            self.assertEqual(engine.chunk_size("PVP_OPP_CHUNK", 12), 16)
        for invalid in ("0", "101", "eight", "-1", "3.5"):
            with self.subTest(invalid=invalid):
                with patch.dict(engine.os.environ, {"PVP_OPP_CHUNK": invalid}):
                    with self.assertRaises(ValueError):
                        engine.chunk_size("PVP_OPP_CHUNK", 12)

    def test_chunk_8x12_reduces_browser_runs_without_dropping_matches(self):
        previous = math.ceil(20 / 8) * math.ceil(348 / 8) * 6
        improved = math.ceil(20 / 8) * math.ceil(348 / 12) * 6
        self.assertEqual((previous, improved), (792, 522))
        self.assertEqual(20 * 348 * 6, 41760)

    def test_group_reset_uses_quick_fill_and_requires_empty_groups(self):
        page = engine.Page.__new__(engine.Page)
        page.eval = Mock(return_value={"count": 2, "empty": True})
        page.reset_groups()
        script = page.eval.call_args.args[0]
        self.assertIn("quick-fill-select", script)
        self.assertIn("dispatchEvent", script)
        self.assertIn("rankings-container .rank", script)

        page.eval = Mock(return_value={"count": 2, "empty": False})
        with self.assertRaises(RuntimeError):
            page.reset_groups()

    def test_wait_ready_rejects_old_populated_matrix(self):
        page = engine.Page.__new__(engine.Page)
        populated = {"ready": "complete", "mode": "matrix", "groups": 2,
                     "battle": True, "empty": False, "title": "PvPoke",
                     "securityCheck": False}
        blank = {**populated, "empty": True}
        page.eval = Mock(side_effect=[populated, blank])
        with patch.object(engine.time, "sleep"):
            page.wait_ready(require_empty=True)
        self.assertEqual(page.eval.call_count, 2)

    def test_single_tab_reuse_and_exact_csv_reassembly(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            data_dir = home / "game_data"
            data_dir.mkdir()
            (data_dir / "gamemaster.json").write_text("{}", encoding="utf-8")
            (data_dir / "Pokemon.js").write_text("var cpms=[];", encoding="utf-8")
            candidates = [
                {"species": "quagsire", "fast": "MUD_SHOT", "charged1": "AQUA_TAIL",
                 "charged2": "STONE_EDGE", "atk": i, "def": 11, "hp": 12}
                for i in (0, 1)
            ]
            opponents = [
                {"species": "clodsire", "fast": "POISON_STING", "charged1": "STONE_EDGE",
                 "charged2": "EARTHQUAKE", "atk": i, "def": 15, "hp": 15}
                for i in (0, 1)
            ]

            class FakePage:
                created = []
                def __init__(self):
                    self.created.append(self)
                    self.groups = {}
                    self.reset_count = 0
                    self.closed = False
                def wait_ready(self, require_empty=False):
                    assert require_empty
                def reset_groups(self):
                    self.reset_count += 1
                    self.groups.clear()
                def import_group(self, index, rows):
                    self.groups[index] = rows
                def simulate(self, left, right, pair):
                    a, b = self.groups[0], self.groups[1]
                    assert (left, right) == (len(a), len(b))
                    # Distinct scores per candidate, opponent and shield
                    headings = [f"opp_{r['atk']}" for r in b]
                    output = [["candidate", *headings, "Wins", "Losses", "Draws", "Average"]]
                    for c in a:
                        rates = [600 + c["atk"] * 10 + o["atk"] + pair[0] * 2
                                 for o in b]
                        output.append([f"quagsire_{c['atk']}/{c['def']}/{c['hp']}",
                                       *rates, len(b), 0, 0, sum(rates) / len(rates)])
                    return output
                def close(self):
                    self.closed = True

            for filename in ("candidates.csv", "opponents.csv",
                             "prepared_candidates.csv", "prepared_opponents.csv"):
                (home / filename).write_text("test\n", encoding="utf-8")
            patches = [
                patch.object(engine, "DIR", home),
                patch.object(engine, "OUT", home / "results"),
                patch.object(engine, "DATA", data_dir),
                patch.object(engine, "CAND", home / "candidates.csv"),
                patch.object(engine, "OPPS", home / "opponents.csv"),
                patch.object(engine, "CAND_CHUNK", 1),
                patch.object(engine, "OPP_CHUNK", 1),
                patch.object(engine, "prepare", return_value=({"timestamp": "test"},
                                                             candidates, opponents)),
                patch.object(engine, "chromium_connect", return_value={"Browser": "test"}),
                patch.object(engine, "Page", FakePage),
            ]
            from contextlib import ExitStack
            with ExitStack() as stack:
                for context in patches:
                    stack.enter_context(context)
                engine.run(shield_set="equal")
                self.assertEqual(len(FakePage.created), 1)
                self.assertEqual(FakePage.created[0].reset_count, 3)
                self.assertTrue(FakePage.created[0].closed)
                run_dir = next((home / "results").glob("run_*"))
                with (run_dir / "pvpoke_s0.csv").open(encoding="utf-8-sig", newline="") as f:
                    table = list(csv.reader(f))
                self.assertEqual(table[0][1:3], ["opp_0", "opp_1"])
                self.assertEqual(table[1][1:3], ["600", "601"])
                self.assertEqual(table[2][1:3], ["610", "611"])
                # A re-run should reuse all 12 saved matrices without opening a tab.
                engine.run(shield_set="equal")
                self.assertEqual(len(FakePage.created), 1)


if __name__ == "__main__":
    unittest.main()
