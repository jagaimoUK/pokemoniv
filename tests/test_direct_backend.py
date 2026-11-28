import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pvpoke_direct_backend import (
    DirectMatrixClient,
    DirectMatrixError,
    MAX_RESPONSE_BYTES,
    linux_process_rss_mb,
    matrix_from_response,
)


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


class DirectMatrixClientLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.gm_path = Path("tests/fixtures/strategy_gamemaster.json").resolve()
        self.log_dir = Path(self.tmpdir.name)
        self.cands = [dict(atk=1, **{"def": 11}, hp=8)]
        self.opps = [dict(species="altaria"), dict(species="clodsire")]

    def tearDown(self):
        self.tmpdir.cleanup()

    def _assert_dead(self, pid: int | None):
        if pid is None:
            return
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        # Wait up to 1 second for OS reaper
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                return
        # If still exists, verify it is not an active runnable process
        status_path = Path(f"/proc/{pid}/status")
        if status_path.exists():
            for line in status_path.read_text().splitlines():
                if line.startswith("State:"):
                    self.assertNotIn("R", line.split()[1], f"Process {pid} is still running")

    def _make_client_with_worker(self, py_code: str, timeout_seconds=0.25, max_response_bytes=MAX_RESPONSE_BYTES):
        orig_popen = subprocess.Popen

        def fake_popen(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) >= 2 and cmd[1].endswith("pvpoke_node_matrix.js"):
                new_cmd = [sys.executable, "-u", "-c", py_code]
                return orig_popen(new_cmd, *args, **kwargs)
            return orig_popen(cmd, *args, **kwargs)

        with patch("subprocess.Popen", side_effect=fake_popen):
            return DirectMatrixClient(
                gamemaster=self.gm_path,
                log_dir=self.log_dir,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes
            )

    def test_init_parameter_validation(self):
        with self.assertRaises(ValueError):
            DirectMatrixClient(gamemaster=self.gm_path, log_dir=self.log_dir, timeout_seconds=0)
        with self.assertRaises(ValueError):
            DirectMatrixClient(gamemaster=self.gm_path, log_dir=self.log_dir, timeout_seconds=601)
        with self.assertRaises(ValueError):
            DirectMatrixClient(gamemaster=self.gm_path, log_dir=self.log_dir, timeout_seconds=True)
        with self.assertRaises(ValueError):
            DirectMatrixClient(gamemaster=self.gm_path, log_dir=self.log_dir, max_response_bytes=100)
        with self.assertRaises(ValueError):
            DirectMatrixClient(gamemaster=self.gm_path, log_dir=self.log_dir, max_response_bytes=100 * 1024 * 1024)

    def test_d01_01_timeout_kills_and_reaps(self):
        code = "import sys, time; sys.stdin.readline(); time.sleep(10)"
        client = self._make_client_with_worker(code, timeout_seconds=0.2)
        pid = client.proc.pid
        started = time.monotonic()
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        elapsed = time.monotonic() - started
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(elapsed, 2.5)
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_02_partial_byte_hang(self):
        code = "import sys, time; sys.stdin.readline(); sys.stdout.write('{'); sys.stdout.flush(); time.sleep(10)"
        client = self._make_client_with_worker(code, timeout_seconds=0.2)
        pid = client.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("timed out", str(ctx.exception))
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_03_slow_trickle_exceeds_total_deadline(self):
        code = "import sys, time; sys.stdin.readline()\nfor _ in range(50):\n    sys.stdout.write(' '); sys.stdout.flush(); time.sleep(0.04)"
        client = self._make_client_with_worker(code, timeout_seconds=0.2)
        pid = client.proc.pid
        started = time.monotonic()
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        elapsed = time.monotonic() - started
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(elapsed, 2.0)
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_04_max_response_bytes_exceeded(self):
        code = "import sys; sys.stdin.readline(); sys.stdout.write('a' * 5000); sys.stdout.flush()"
        client = self._make_client_with_worker(code, timeout_seconds=1.0, max_response_bytes=1024)
        pid = client.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("exceeded frame limit", str(ctx.exception))
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_05_eof_empty_and_incomplete(self):
        # Empty EOF
        code_empty = "import sys; sys.stdin.readline(); sys.exit(0)"
        client1 = self._make_client_with_worker(code_empty, timeout_seconds=1.0)
        pid1 = client1.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client1.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("without a response", str(ctx.exception))
        self.assertIsNone(client1.proc)
        self._assert_dead(pid1)

        # Incomplete EOF
        code_inc = "import sys; sys.stdin.readline(); sys.stdout.write('{\"ok\":true'); sys.stdout.flush(); sys.exit(0)"
        client2 = self._make_client_with_worker(code_inc, timeout_seconds=1.0)
        pid2 = client2.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client2.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("with incomplete response", str(ctx.exception))
        self.assertIsNone(client2.proc)
        self._assert_dead(pid2)

    def test_d01_06_malformed_json_and_nan(self):
        code_nan = "import sys; sys.stdin.readline(); sys.stdout.write('{\"ok\":true,\"result\":{\"v\":NaN}}\\n'); sys.stdout.flush()"
        client = self._make_client_with_worker(code_nan, timeout_seconds=1.0)
        pid = client.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("parsing failed", str(ctx.exception))
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_07_ok_false_sanitized_and_unreusable(self):
        code = "import sys; sys.stdin.readline(); sys.stdout.write('{\"ok\":false,\"error\":\"/etc/shadow secret leakage\"}\\n'); sys.stdout.flush()"
        client = self._make_client_with_worker(code, timeout_seconds=1.0)
        pid = client.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        self.assertEqual(str(ctx.exception), "PvPoke Node result failed")
        self.assertNotIn("/etc/shadow", str(ctx.exception))
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

        # Immediate reuse should fail without restarting
        with self.assertRaises(DirectMatrixError) as ctx2:
            client.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("process is not running", str(ctx2.exception))

    def test_d01_08_trailing_bytes_after_newline(self):
        code = "import sys; sys.stdin.readline(); sys.stdout.write('{\"ok\":true,\"result\":{\"candidates\":[]}}\\nextra_token\\n'); sys.stdout.flush()"
        client = self._make_client_with_worker(code, timeout_seconds=1.0)
        pid = client.proc.pid
        with self.assertRaises(DirectMatrixError) as ctx:
            client.simulate(self.cands, self.opps, (1, 1))
        self.assertIn("Unexpected trailing bytes", str(ctx.exception))
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_09_idempotent_close_with_broken_pipe(self):
        code = "import sys, time; sys.stdin.readline(); sys.stdout.write('{\"ok\":true}\\n'); sys.stdout.flush(); time.sleep(1)"
        client = self._make_client_with_worker(code, timeout_seconds=1.0)
        pid = client.proc.pid
        # Break stdin
        if client.proc.stdin:
            client.proc.stdin.close()
        # Closing multiple times must be safe and idempotent
        client.close()
        client.close()
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

    def test_d01_10_normal_consecutive_then_poisoned(self):
        code = (
            "import sys, json\n"
            "resp = json.dumps({'ok':True,'result':{'status':'calculated','schema':'strategy-detail-v1','terminal':[{'hp':50,'max_hp':100,'energy_points':20,'shields':1},{'hp':0,'max_hp':100,'energy_points':0,'shields':0}]}})\n"
            "for _ in range(2):\n"
            "    sys.stdin.readline()\n"
            "    sys.stdout.write(resp + '\\n')\n"
            "    sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
            "sys.stdout.write('{\"ok\":false,\"error\":\"broken\"}\\n')\n"
            "sys.stdout.flush()\n"
        )
        client = self._make_client_with_worker(code, timeout_seconds=1.0)
        pid = client.proc.pid
        payload = {"shields": [1, 1]}

        # 1st call: OK
        res1 = client.strategy("detail", payload)
        self.assertEqual(res1["status"], "calculated")

        # 2nd call: OK
        res2 = client.strategy("detail", payload)
        self.assertEqual(res2["status"], "calculated")

        # 3rd call: Fails
        with self.assertRaises(DirectMatrixError) as ctx:
            client.strategy("detail", payload)
        self.assertEqual(str(ctx.exception), "PvPoke strategy calculation failed")
        self.assertIsNone(client.proc)
        self._assert_dead(pid)

        # 4th call: Poisoned
        with self.assertRaises(DirectMatrixError):
            client.strategy("detail", payload)

    def test_d01_11_real_node_engine_identity(self):
        # Real Node execution using pinned repo sources
        try:
            client = DirectMatrixClient(
                gamemaster=self.gm_path,
                log_dir=self.log_dir,
                timeout_seconds=10.0
            )
        except DirectMatrixError as exc:
            self.skipTest(f"Node setup not available: {exc}")

        try:
            res = client.strategy("engine_identity", {})
            self.assertEqual(res["status"], "calculated")
            self.assertIn("engine_sources", res)
            self.assertGreater(len(res["engine_sources"]), 0)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()

