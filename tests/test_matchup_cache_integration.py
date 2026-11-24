"""Cross-job integration: exact overlap reuse through the real batch runner."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pvpoke_batch_v2 as engine
from pvpoke_24_workflow import split_matrix
from pvpoke_app_selection import recommendations_from_zip


class CacheRunnerIntegrationTests(unittest.TestCase):
    def test_added_iv_reuses_only_valid_pairs_and_rebuilds_the_same_recommendation(self):
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
                        scores = ((540, 470), (480, 560), (570, 530))
                        ratings = [str(scores[x["atk"]][y["atk"]] - shield[0]*2) for y in b]
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
                    patch.dict(engine.os.environ, {"PVP_MATCHUP_CACHE":"1", "PVP_BROWSER_CACHE_EPOCH":"fixture-v1"}, clear=True),
                ):
                    stack.enter_context(c)

                def calculate(name):
                    engine.run(shield_set="all")
                    raw = root / (name + "-raw")
                    raw.mkdir()
                    report_dir = root / (name + "-report")
                    report_dir.mkdir()
                    with ZipFile(work / "pvpoke_results_latest.zip") as archive:
                        info = json.loads(archive.read("manifest.json"))
                        for pair in engine.SCENARIOS["all"]:
                            csv_name = engine.result_filename(pair)
                            (raw / csv_name).write_bytes(archive.read(csv_name))
                    report_files = split_matrix(raw, report_dir, [{"mode": "default"} for _ in opps],
                                                config["selected"], full_modes=("default",))
                    zip_path = report_dir / "selection.zip"
                    with ZipFile(zip_path, "w") as archive:
                        for path in report_files:
                            archive.write(path, arcname=path.name)
                    with ZipFile(zip_path) as archive:
                        result = recommendations_from_zip(archive, cands[0], "Quagsire", "simple")
                    return info, result

                _, old = calculate("saved")
                self.assertEqual(DummyPage.cells_evaluated, 24)
                self.assertEqual(len(DummyPage.created), 1)
                self.assertTrue(any(e["kind"] == "unique_gt500" for row in old["recommendations"]
                                    for e in row["evidence"]))
                self.assertFalse(old["dominated_by"])

                config["selected"] = cands
                info, incremental = calculate("incremental")
                self.assertEqual(DummyPage.cells_evaluated, 36)
                self.assertEqual(len(DummyPage.created), 2)
                self.assertTrue((data.parent/"archives"/"matchups.sqlite3").is_file())
                self.assertEqual(info["matchup_cache"], {"hits": 24, "misses": 12, "computed": 12, "bypassed": 0})
                self.assertEqual(incremental["dominated_by"], {"0/11/8": ["2/11/8"]})
                self.assertFalse(any(e["kind"] == "unique_gt500" for row in incremental["recommendations"]
                                     for e in row["evidence"]))
                self.assertNotEqual([row["ivs"] for row in old["recommendations"]],
                                    [row["ivs"] for row in incremental["recommendations"]])

                with patch.dict(engine.os.environ, {"PVP_FORCE_RECALCULATE": "1"}):
                    info, full = calculate("forced")
                self.assertEqual(DummyPage.cells_evaluated, 72)
                self.assertEqual(info["matchup_cache"], {"enabled": False})
                self.assertEqual(full, incremental)

                config["selected"] = cands[::-1]
                info, _ = calculate("reordered")
                self.assertEqual(DummyPage.cells_evaluated, 72)
                self.assertEqual(info["matchup_cache"]["computed"], 0)
                self.assertEqual(info["matchup_cache"]["hits"], 36)

                # A new calculation version must not reuse the previous cells.
                config["selected"] = cands
                (data/"gamemaster.json").write_text('{"timestamp":"updated"}')
                info, updated = calculate("new-version")
                self.assertEqual(DummyPage.cells_evaluated, 108)
                self.assertEqual(info["matchup_cache"]["hits"], 0)
                self.assertEqual(info["matchup_cache"]["computed"], 36)
                self.assertEqual(updated, incremental)
