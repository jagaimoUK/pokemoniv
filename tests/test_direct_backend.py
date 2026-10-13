"""Safety tests for the experimental Node PvPoke IPC adapter."""
import os
import unittest

from pvpoke_direct_backend import DirectMatrixError, matrix_from_response, linux_process_rss_mb


class DirectMatrixTests(unittest.TestCase):
    def setUp(self):
        self.cands=[dict(atk=1, **{"def":11}, hp=8)]
        self.opps=[dict(species="altaria"), dict(species="clodsire")]

    def test_convert_full_js_matrix_to_identical_csv_shape(self):
        row={"label":"Quagsire MS+AT/SE 1/11/8",
             "opponents":["Altaria DB+SA/Ft 4/12/13","Clodsire PSt+SE/Eq 4/14/10"],
             "ratings":[416,645]}
        data=matrix_from_response({"ok":True,"result":{"candidates":[row]}},self.cands,self.opps)
        self.assertEqual(data[0],["",*row["opponents"],"Wins","Losses","Draws","Average"])
        self.assertEqual(data[1],[row["label"],416,645,1,1,0,530.5])

    def test_rejects_wrong_iv_or_missing_columns(self):
        row={"label":"Quagsire 5/11/8","opponents":["a","b"],"ratings":[400,650]}
        with self.assertRaises(DirectMatrixError):
            matrix_from_response({"ok":True,"result":{"candidates":[row]}},self.cands,self.opps)
        row["label"]="Quagsire 1/11/8"
        row["ratings"]=[400]
        with self.assertRaises(DirectMatrixError):
            matrix_from_response({"ok":True,"result":{"candidates":[row]}},self.cands,self.opps)

    def test_rejects_corrupt_rating_and_inconsistent_opponents(self):
        data={"ok":True,"result":{"candidates":[{
             "label":"Quagsire 1/11/8","opponents":["a","b"],"ratings":[400,1001]}]}}
        with self.assertRaises(DirectMatrixError):
            matrix_from_response(data,self.cands,self.opps)
        data["result"]["candidates"][0]["ratings"]=[400,500.5]
        with self.assertRaises(DirectMatrixError):
            matrix_from_response(data,self.cands,self.opps)

    def test_rounding_follows_js_not_python_bankers(self):
        data={"ok":True,"result":{"candidates":[{
          "label":"Quagsire 1/11/8","opponents":["a","b","c","d","e","f","g","h"],
          "ratings":[500,500,500,500,500,500,500,501]}]}}
        result=matrix_from_response(data,self.cands,[{}]*8)
        self.assertEqual(result[1][-1],500.13)

    def test_node_protocol_error_is_not_treated_as_success(self):
        with self.assertRaisesRegex(DirectMatrixError,"failed"):
            matrix_from_response({"ok":False,"error":"simulation failed"},self.cands,self.opps)


if __name__=="__main__":
    unittest.main()

class DirectMemoryTelemetryTests(unittest.TestCase):
    def test_proc_rss_peak_is_not_below_current_rss(self):
        result = linux_process_rss_mb(os.getpid())
        if result is None:
            self.skipTest('Linux /proc not present')
        self.assertGreater(result['rss_mb'], 0)
        self.assertGreaterEqual(result['peak_rss_mb'], result['rss_mb'])

    def test_dead_process_returns_none(self):
        self.assertIsNone(linux_process_rss_mb(999999999))

    def test_chunk_size_supports_hundred_but_not_more(self):
        import pvpoke_batch_v2
        from unittest.mock import patch
        with patch.dict(os.environ, {'PVP_CAND_CHUNK':'100'}):
            self.assertEqual(pvpoke_batch_v2.chunk_size('PVP_CAND_CHUNK', 8), 100)
        with patch.dict(os.environ, {'PVP_CAND_CHUNK':'101'}):
            with self.assertRaises(ValueError):
                pvpoke_batch_v2.chunk_size('PVP_CAND_CHUNK', 8)
