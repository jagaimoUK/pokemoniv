"""Cross-job integration: exact overlap reuse through the real batch runner."""
import csv
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pvpoke_batch_v2 as engine


class CacheRunnerIntegrationTests(unittest.TestCase):
    def test_adding_iv_only_simulates_new_pairs_and_reordering_is_browser_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            data = root / "data"
            data.mkdir()
            (data/"gamemaster.json").write_text('{"timestamp":"test"}')
            (data/"Pokemon.js").write_text("var cpms=[]")
            for name in ("candidates.csv","opponents.csv",
                         "prepared_candidates.csv","prepared_opponents.csv"):
                (work/name).write_text("fixture\n")
            cands = [dict(species="quagsire", fast="MUD_SHOT", charged1="AQUA_TAIL",
                          charged2="STONE_EDGE", atk=a, **{"def":11},
                          hp=8, level=29.5, cp=1496) for a in (0,1,2)]
            opps = [dict(species="clodsire", fast="POISON_STING", charged1="STONE_EDGE",
                         charged2="EARTHQUAKE", atk=a, **{"def":15},
                         hp=15, level=27, cp=1499) for a in (0,1)]
            config = {"selected": cands[:2]}

            class DummyPage:
                created = []
                cells_evaluated = 0
                def __init__(self):
                    self.created.append(self)
                    self.groups = {}
                def wait_ready(self, require_empty=False):
                    assert require_empty
                def reset_groups(self):
                    self.groups.clear()
                def import_group(self, idx, rows):
                    self.groups[idx] = rows
                def simulate(self, nleft, nright, shield):
                    a, b = self.groups[0], self.groups[1]
                    assert nleft==len(a) and nright==len(b)
                    self.__class__.cells_evaluated += nleft*nright
                    header = ["", *[f"opponent-{x['atk']}" for x in b],
                              "Wins", "Losses", "Draws", "Average"]
                    rows = [header]
                    for x in a:
                        ratings = [str(510 + x["atk"]*9 - y["atk"]*20 - shield[0]*2)
                                   for y in b]
                        floats = [float(v) for v in ratings]
                        wld = [sum(v>500 for v in floats),
                               sum(v<500 for v in floats),
                               sum(v==500 for v in floats)]
                        rows.append([f"Quagsire {x['atk']}/11/8", *ratings,
                                     *wld, sum(floats)/len(floats)])
                    return rows
                def close(self):
                    return None

            def prepare(refresh=False):
                return {"timestamp": "2026-test"}, config["selected"], opps

            with ExitStack() as stack:
                for c in (
                    patch.object(engine, "DIR", work),
                    patch.object(engine, "OUT", work / "results"),
                    patch.object(engine, "DATA", data),
                    patch.object(engine, "CAND", work/"candidates.csv"),
                    patch.object(engine, "OPPS", work/"opponents.csv"),
                    patch.object(engine, "CAND_CHUNK", 2),
                    patch.object(engine, "OPP_CHUNK", 2),
                    patch.object(engine, "prepare", side_effect=prepare),
                    patch.object(engine, "chromium_connect", return_value={"Browser":"mock"}),
                    patch.object(engine, "Page", DummyPage),
                    patch.dict(engine.os.environ, {"PVP_MATCHUP_CACHE":"1"}, clear=True),
                ):
                    stack.enter_context(c)

                engine.run(shield_set="equal")
                self.assertEqual(DummyPage.cells_evaluated, 12)
                self.assertEqual(len(DummyPage.created), 1)

                config["selected"] = cands
                engine.run(shield_set="equal")
                self.assertEqual(DummyPage.cells_evaluated, 18)
                self.assertEqual(len(DummyPage.created), 2)
                self.assertTrue((data.parent/"archives"/"matchups.sqlite3").is_file())

                config["selected"] = cands[::-1]
                engine.run(shield_set="equal")
                self.assertEqual(DummyPage.cells_evaluated, 18)
                self.assertEqual(len(DummyPage.created), 2)
                last = sorted((work/"results").glob("run_*/manifest.json"),
                              key=lambda p:p.stat().st_mtime)[-1]
                info = json.loads(last.read_text())
                self.assertEqual(info["matchup_cache"]["computed"], 0)
                self.assertEqual(info["matchup_cache"]["hits"], 18)
                with (last.parent/"pvpoke_s0.csv").open(encoding="utf-8-sig") as fp:
                    values = list(csv.reader(fp))
                self.assertEqual(len(values), 4)
                self.assertIn("2/11/8", values[1][0])
                self.assertEqual(values[1][1:3], ["528","508"])


if __name__=="__main__":
    unittest.main()
