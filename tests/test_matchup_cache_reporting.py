"""Result manifest carries cache stats through the existing MCP bridge."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pvpoke_24_workflow as workflow
import pvpoke_bridge_core as bridge


class CacheReportTests(unittest.TestCase):
    def test_copy_cache_counters_into_durable_batch_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"engine.json"
            result=root/"manifest.json"
            source.write_text(json.dumps({"matchup_cache":{
                "hits":1044,"misses":522,"computed":522,"bypassed":0},
                "engine":{"selected":"direct","direct_calculations":522,"browser_fallbacks":0}}))
            result.write_text(json.dumps({"batch_mode":"simple","shield_pairs":[[0,0]]}))
            workflow.record_cache_stats(source,result)
            data=json.loads(result.read_text())
            self.assertEqual(data["batch_mode"], "simple")
            self.assertEqual(data["matchup_cache"]["hits"], 1044)
            self.assertEqual(data["matchup_cache"]["computed"], 522)
            self.assertEqual(data["engine"]["direct_calculations"], 522)

    def test_old_engine_without_cache_reports_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"engine.json"
            result=root/"manifest.json"
            source.write_text("{}")
            result.write_text('{"batch_mode":"simple"}')
            workflow.record_cache_stats(source,result)
            data=json.loads(result.read_text())
            self.assertEqual(data["matchup_cache"],{"enabled":False})
            self.assertEqual(data["engine"],{"selected":"legacy"})

    def test_summary_returns_cache_stats_while_retaining_rows(self):
        mem=io.BytesIO()
        with zipfile.ZipFile(mem,"w") as z:
            z.writestr("manifest.json",json.dumps({"matchup_cache":{"hits":42,"computed":0},"engine":{"selected":"direct","browser_fallbacks":0}}))
            z.writestr("ranking_summary.csv","opponent_iv_mode,mean_rating\n"
                                              "default,478.33\n")
        with zipfile.ZipFile(io.BytesIO(mem.getvalue())) as z:
            with patch.object(bridge,"_zip",return_value=z):
                result=bridge.summary24()
        self.assertEqual(result["rows"][0]["mean_rating"],"478.33")
        self.assertEqual(result["matchup_cache"],{"hits":42,"computed":0})
        self.assertEqual(result["engine"],{"selected":"direct","browser_fallbacks":0})


if __name__=="__main__":
    unittest.main()
