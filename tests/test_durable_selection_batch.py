"""Synthetic tests: no network, no live battles, no database deletion."""
import tempfile
import threading
import unittest
from pathlib import Path

from pvpoke_app_batch import DurableSelectionBatch

SHA = "a" * 64
CAND = {"species": "quagsire", "fast": "MUD_SHOT", "charged1": "AQUA_TAIL", "charged2": "STONE_EDGE"}


def plan(count=2, request="request-0123456789"):
    return {
        "request_id": request, "batch_mode": "simple", "report_format": "app",
        "meta_sha256": SHA, "meta_preset_id": "legacy",
        "policy": {"meaningful_win_lead": 20},
        "jobs": [
            {"candidate": CAND, "ivs": "0,11,12", "name": "ヌオー",
             "batch_mode": "simple", "moveset_group": str(i)}
            for i in range(count)
        ],
    }


class Runner:
    def __init__(self, gate=None, failures=0):
        self.calls = []
        self.gate = gate
        self.failures = failures

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.gate is not None:
            self.gate.wait(2)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary engine failure")
        return {"run_ref": kwargs["request_id"], "state": "done", "complete": True,
                "meta_sha256": SHA, "calculation_version": "b" * 64,
                "candidate": kwargs["candidate"], "selection": {"complete": True},
                "reports": {}, "total_ratings_checked": 6}

    def result(self, ref, wait_seconds=0):
        raise AssertionError("Immediate fake jobs never require polling")

    def cancel(self, ref):
        return {"cancelled": True}


class DurableBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "batches.sqlite3"

    def settled(self, app, batch_id, state):
        worker = app._workers.get(batch_id)
        if worker:
            worker.join(5)
        result = app.status(batch_id, include_results=True)
        self.assertEqual(result["state"], state, result)
        return result

    def test_batch_runs_to_completion_without_browser_polling(self):
        worker = Runner()
        app = DurableSelectionBatch(worker, self.path, retry_delay=0)
        bid = app.start(plan(3))["batch_id"]
        done = self.settled(app, bid, "done")
        self.assertEqual((done["index"], done["total"], len(done["results"])), (3, 3, 3))
        self.assertEqual(len(worker.calls), 3)
        self.assertEqual(done["results"][1]["display_name"], "ヌオー")
        self.assertEqual(done["results"][1]["moveset_group"], "1")
        self.assertTrue(self.path.is_file())

    def test_idempotent_start_and_no_unrelated_replay(self):
        gate = threading.Event()
        worker = Runner(gate)
        app = DurableSelectionBatch(worker, self.path, retry_delay=0)
        first = plan()
        bid = app.start(first)["batch_id"]
        self.assertEqual(app.start(first)["batch_id"], bid)
        altered = plan()
        altered["jobs"][0]["ivs"] = "2,15,13"
        with self.assertRaisesRegex(ValueError, "異なる計算条件"):
            app.start(altered)
        with self.assertRaisesRegex(ValueError, "前の計算"):
            app.start(plan(request="request-9876543210"))
        gate.set()
        self.settled(app, bid, "done")
        self.assertEqual(len(worker.calls), 2)

    def test_recover_completed_checkpoint_without_recalculating_prior_results(self):
        first = DurableSelectionBatch(Runner(), self.path, retry_delay=0)
        bid = first.start(plan(2))["batch_id"]
        self.settled(first, bid, "done")
        with first._db() as db:
            db.execute("""UPDATE batches SET state='running',idx=1,
                lease_owner=NULL,lease_until=0 WHERE id=?""", (bid,))
            db.execute("DELETE FROM batch_results WHERE batch_id=? AND idx=1", (bid,))
        recovered_worker = Runner()
        recovered = DurableSelectionBatch(recovered_worker, self.path, retry_delay=0)
        recovered.recover()
        state = self.settled(recovered, bid, "done")
        self.assertEqual(state["index"], 2)
        self.assertEqual(len(recovered_worker.calls), 1)
        self.assertEqual(len(state["results"]), 2)

    def test_bounded_failures_pause_and_explicit_resume(self):
        worker = Runner(failures=4)
        app = DurableSelectionBatch(worker, self.path, retry_delay=0)
        bid = app.start(plan(2))["batch_id"]
        paused = self.settled(app, bid, "paused")
        self.assertEqual(paused["index"], 0)
        worker.failures = 0
        app.resume(bid)
        done = self.settled(app, bid, "done")
        self.assertEqual(done["index"], 2)
        self.assertEqual(len(done["results"]), 2)

    def test_cancel_while_running_does_not_start_following_jobs(self):
        gate = threading.Event()
        worker = Runner(gate)
        app = DurableSelectionBatch(worker, self.path, retry_delay=0)
        bid = app.start(plan(3))["batch_id"]
        app.cancel(bid)
        gate.set()
        done = self.settled(app, bid, "cancelled")
        self.assertLessEqual(done["index"], 1)
        self.assertLessEqual(len(worker.calls), 1)

    def test_mismatched_meta_pauses_without_checkpoint(self):
        class WrongMeta(Runner):
            def run(self, **kwargs):
                response = super().run(**kwargs)
                response["meta_sha256"] = "c" * 64
                return response
        app = DurableSelectionBatch(WrongMeta(), self.path, retry_delay=0)
        bid = app.start(plan(2))["batch_id"]
        state = self.settled(app, bid, "paused")
        self.assertEqual(state["index"], 0)
        self.assertEqual(state["results"], [])

    def test_requires_frozen_meta_before_creating_job(self):
        app = DurableSelectionBatch(Runner(), self.path, retry_delay=0)
        missing = plan()
        del missing["meta_sha256"]
        with self.assertRaisesRegex(ValueError, "SHA256"):
            app.start(missing)
        self.assertIsNone(app.latest()["batch_id"])

    def test_reject_invalid_inputs_without_overwriting_saved_data(self):
        app = DurableSelectionBatch(Runner(), self.path, retry_delay=0)
        bid = app.start(plan())["batch_id"]
        self.settled(app, bid, "done")
        bad = plan(request="request-9876543210")
        bad["jobs"][0]["ivs"] = "15,15,16"
        with self.assertRaises(ValueError):
            app.start(bad)
        with self.assertRaises(ValueError):
            app.status("not-our-id")
        self.assertEqual(app.status(bid)["state"], "done")
        self.assertEqual(app.latest()["batch_id"], bid)


if __name__ == "__main__":
    unittest.main()
