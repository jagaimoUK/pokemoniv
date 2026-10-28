"""Persistent batch reuse and invalidation; no remote worker or production data."""
import copy
import http.client
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import types
import time
import unittest
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from unittest.mock import patch, Mock
from zipfile import ZipFile

import pvpoke_web as web
from pvpoke_calculation_version import CALCULATION_FILES, calculation_version
from pvpoke_result_cache import ResultCache, context
from test_iv_workflow import CANDIDATE, IVS, fixture_zip


def make_archive(path, ctx, *, fallback=0):
    with ZipFile(fixture_zip()) as original, ZipFile(path, "w") as out:
        for name in original.namelist():
            data = original.read(name)
            if name == "manifest.json":
                obj = json.loads(data)
                obj.update({k: ctx["request"][k] for k in (
                    "meta_sha256", "calculation_version", "cp_cap", "max_level")})
                obj["engine"] = {"selected":"direct", "browser_fallbacks":fallback}
                data = json.dumps(obj).encode()
            out.writestr(name, data)


class VersionTests(unittest.TestCase):
    def test_every_installed_engine_dependency_and_dataset_invalidates_by_content(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"PVP_ENGINE":"direct", "PVP_CACHE_EPOCH":"", "PVP_PVPOKE_SOURCE":""}):
            root = Path(tmp)
            for name in CALCULATION_FILES:
                (root / name).write_text("original")
            data = root / "data"; data.mkdir()
            for name in ("gamemaster.json", "Pokemon.js"):
                (data / name).write_text("original")
            js = root / "vendor/pvpoke/src/js"
            for name in ("battle/Battle.js", "battle/DamageCalculator.js", "pokemon/Pokemon.js", "battle/actions/NewRule.js"):
                file = js / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text("original")
            first = calculation_version(data, root=root)
            self.assertIsNotNone(first)
            # Even preserved size/mtime cannot hide a changed move, stat or damage rule.
            for file in [data / "gamemaster.json", data / "Pokemon.js", js / "battle/DamageCalculator.js", root / "pvpoke_iv_modes.py", js / "battle/actions/NewRule.js"]:
                before = file.stat(); file.write_text("modified")
                os.utime(file, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.assertNotEqual(first, calculation_version(data, root=root))
                file.write_text("original")
            with patch.dict(os.environ, {"PVP_CACHE_EPOCH":"rules-2"}):
                self.assertNotEqual(first, calculation_version(data, root=root))
            (js / "battle/Battle.js").unlink()
            self.assertIsNone(calculation_version(data, root=root))

    def test_unversioned_browser_never_reuses_results(self):
        with patch.dict(os.environ, {"PVP_ENGINE":"browser", "PVP_BROWSER_CACHE_EPOCH":""}):
            self.assertIsNone(calculation_version(Path("missing")))


class ResultCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"PVP_ARCHIVE_DIR":str(self.root)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.ctx = context(CANDIDATE, [[0,11,12],[2,15,13]], "simple", "a"*64, "b"*64, 1500, 50)
        self.source = self.root / "source.zip"; make_archive(self.source, self.ctx)
        self.cache = ResultCache(self.root)

    def test_reopen_restores_exact_complete_archive_without_recalculation(self):
        self.assertTrue(self.cache.store(self.ctx, self.source))
        output = self.root / "output.zip"
        self.assertTrue(ResultCache(self.root).restore(self.ctx, output)["reused"])
        self.assertEqual(self.source.read_bytes(), output.read_bytes())

    def test_meta_moves_ivs_shields_mode_and_rules_changes_are_separate(self):
        self.cache.store(self.ctx, self.source)
        for changed in (dict(meta_sha256="c"*64), dict(calculation_version="c"*64),
                        dict(batch_mode="detailed"), dict(cp_cap=2500), dict(max_level=51),
                        dict(ivs=[[1,11,12],[2,15,13]]),
                        dict(candidate={**CANDIDATE,"charged1":"MUD_BOMB"})):
            params = {k:v for k,v in self.ctx["request"].items() if k != "schema"}
            params.update(changed)
            other = context(**params)
            self.assertIsNone(self.cache.restore(other, self.root / "out.zip"))

    def test_expiry_corruption_and_wrong_archive_are_misses(self):
        self.cache.store(self.ctx, self.source)
        meta = self.cache.root / (self.ctx["key"] + ".json")
        data = json.loads(meta.read_text()); data["created_at"] -= 8*86400; meta.write_text(json.dumps(data))
        self.assertIsNone(self.cache.restore(self.ctx, self.root / "out.zip"))
        self.cache.store(self.ctx, self.source)
        (self.cache.root / (self.ctx["key"] + ".zip")).write_bytes(b"broken")
        self.assertIsNone(self.cache.restore(self.ctx, self.root / "out.zip"))
        wrong = copy.deepcopy(self.ctx); wrong["request"]["ivs"] = [[1,11,12],[2,15,13]]
        with self.assertRaises(ValueError):
            self.cache.store(wrong, self.source)
        make_archive(self.source, self.ctx, fallback=1)
        with self.assertRaises(ValueError):
            self.cache.store(self.ctx, self.source)

    def test_retention_never_touches_existing_history_or_latest(self):
        self.cache.max_entries = 1
        history = self.cache.root.parent; history.mkdir(parents=True, exist_ok=True)
        (history / "latest.zip").write_text("history")
        (history / "pvpoke_saved.zip").write_text("history")
        self.cache.store(self.ctx, self.source)
        other = copy.deepcopy(self.ctx); other["key"] = "d"*64
        self.cache.store(other, self.source)
        self.assertEqual(len(list(self.cache.root.glob("*.zip"))),1)
        self.assertEqual((history / "latest.zip").read_text(),"history")
        self.assertEqual((history / "pvpoke_saved.zip").read_text(),"history")


class CacheHTTPTests(unittest.TestCase):
    def test_same_conditions_skip_worker_force_and_updates_start_it(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root=Path(tmp); meta=root/"meta.csv"
            meta.write_text("quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n")
            stack.enter_context(patch.dict(os.environ,{"PVP_ARCHIVE_DIR":str(root), "PVP_RESULT_CACHE":"1", "PVP_FORCE_RECALCULATE":"0"}))
            stack.enter_context(patch.object(web,"WORK",root))
            stack.enter_context(patch.object(web,"BATCH_CONFIG",root/"batch.json"))
            stack.enter_context(patch.object(web.meta_live,"active_path",return_value=meta))
            stack.enter_context(patch.object(web,"calculation_version",return_value="b"*64))
            stack.enter_context(patch.object(web,"CATALOG",{"ready":True,"species":{"quagsire":{"fastMoves":["MUD_SHOT"],"chargedMoves":["AQUA_TAIL","STONE_EDGE"]}}}))
            stack.enter_context(patch.object(web,"STATUS",{"state":"idle"}))
            from pvpoke_calculation_version import content_hash
            ctx=context(CANDIDATE, [[0,11,12],[2,15,13]],"simple",content_hash(meta),"b"*64,1500,50)
            archive=root/"ready.zip"; make_archive(archive,ctx)
            ResultCache(root).store(ctx,archive)
            server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                def request(**extra):
                    web.STATUS["state"]="idle"
                    conn=http.client.HTTPConnection(*server.server_address)
                    conn.request("POST","/api/run24",json.dumps(dict(candidate=CANDIDATE,ivs=IVS,**extra)),
                                 {"Content-Type":"application/json","X-PvPoke-Token":web.TOKEN})
                    response=conn.getresponse(); body=json.loads(response.read()); conn.close()
                    self.assertEqual(response.status,200,body)
                    return body
                worker = Mock()
                with patch.object(web,"threading",types.SimpleNamespace(Thread=worker)):
                    first=request()
                    self.assertTrue(first["preview"]["result_cache"]["reused"])
                    self.assertEqual(web.STATUS["state"],"done"); worker.assert_not_called()
                    request(force_recalculate=True)
                    self.assertTrue(worker.call_args.kwargs["args"][-1])
                    worker.reset_mock()
                    meta.write_text(meta.read_text()+"quagsire,MUD_SHOT,STONE_EDGE,AQUA_TAIL\n")
                    self.assertFalse(request()["preview"]["result_cache"]["reused"])
                    worker.assert_called_once()
            finally:
                server.shutdown(); server.server_close(); thread.join()


class FreshAnalysisTests(unittest.TestCase):
    def test_reused_battles_are_reanalyzed_for_current_recommendation_policy(self):
        from pvpoke_iv_workflow import IVWorkflow
        from test_iv_workflow import FakeBackend
        class ReusedBackend(FakeBackend):
            zip_reads=0
            def candidate_name(self,species): return 'Quagsire'
            def start24(self,*args,**kwargs):
                started=super().start24(*args)
                self.state='done'
                started['preview']['result_cache']={'reused':True}
                return started
            def _zip(self):
                self.zip_reads+=1
                return super()._zip()
        backend=ReusedBackend(); workflow=IVWorkflow(backend)
        first=workflow.run(CANDIDATE,IVS,report_format='app',selection_policy={'meaningful_win_lead':20})
        second=workflow.run(CANDIDATE,IVS,report_format='app',selection_policy={'meaningful_win_lead':100})
        self.assertTrue(first['result_cache']['reused']);self.assertTrue(second['result_cache']['reused'])
        self.assertEqual(first['selection']['policy']['meaningful_win_lead'],20)
        self.assertEqual(second['selection']['policy']['meaningful_win_lead'],100)
        self.assertNotEqual(first['run_ref'],second['run_ref'])
        self.assertEqual(backend.zip_reads,2)
        with self.assertRaises(ValueError):workflow.run(CANDIDATE,IVS,force_recalculate='yes')
