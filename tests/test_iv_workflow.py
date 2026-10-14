"""No-live-battle regression tests for the one-call IV workflow."""
import csv
import io
import json
import unittest
from zipfile import ZipFile

from pvpoke_iv_workflow import IVWorkflow

CANDIDATE = {
    "species": "quagsire", "fast": "MUD_SHOT",
    "charged1": "AQUA_TAIL", "charged2": "STONE_EDGE",
}
IVS = "0,11,12\n2,15,13"
SHIELDS = ("s0", "s1", "s2", "i0y1", "i0y2", "i1y2")
HASH = "a" * 64


def fixture_zip(*, batch_mode="simple", bad_species=False, bad_ivs=False):
    modes = ("default",) if batch_mode == "simple" else (
        "default", "rank1", "attack", "defense")
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "batch_mode": batch_mode, "candidates": 2,
            "excluded": 0, "gamemaster_timestamp": "test",
        }))
        summary = io.StringIO()
        writer = csv.DictWriter(summary, fieldnames=[
            "species", "fast", "charged1", "charged2",
            "atk", "def", "hp", "opponent_iv_mode",
            "matchups", "mean_rating", "min_rating",
        ])
        writer.writeheader()
        for mode in modes:
            for index, triple in enumerate(((0, 11, 12), (2, 15, 13))):
                if bad_ivs and index == 1:
                    triple = (1, 15, 13)
                writer.writerow({
                    **CANDIDATE,
                    "species": "kecleon" if bad_species else "quagsire",
                    "atk": triple[0], "def": triple[1], "hp": triple[2],
                    "opponent_iv_mode": mode, "matchups": 12,
                    "mean_rating": 450, "min_rating": 300,
                })
            for shield in SHIELDS:
                table = io.StringIO()
                rows = csv.writer(table)
                rows.writerow([
                    "candidate", "Corsola (Galarian) A+NSh/PG 4/15/14",
                    "Tinkaton FW+Bd/GH 4/15/14",
                    "rating_gt500", "rating_lt500", "rating_eq500", "mean_rating",
                ])
                rows.writerow(["Quagsire MS+AT/SE 0/11/12",
                               550 if shield == "s0" else 510, 400,
                               1, 1, 0, 475])
                rows.writerow(["Quagsire MS+AT/SE 2/15/13",
                               490 if shield == "s0" else 505, 390,
                               1, 1, 0, 440])
                archive.writestr(f"{mode}_{shield}.csv", table.getvalue())
        archive.writestr("ranking_summary.csv", summary.getvalue())
    output.seek(0)
    return output


class FakeBackend:
    def __init__(self, zip_kwargs=None):
        self.state = "idle"
        self.time = "2026-10-14T15:59:01"
        self.run_count = 0
        self.inputs = []
        self.sha = HASH
        self.zip_kwargs = zip_kwargs or {}

    def meta_status(self):
        return {"sha256": self.sha, "rows": 87}

    def start24(self, candidate, ivs, batch_mode):
        self.run_count += 1
        self.inputs.append((candidate, ivs, batch_mode))
        self.state = "running"
        self.time = f"2026-10-14T15:59:{self.run_count:02}"
        return {"started": True, "preview": {
            "batch24": True, "batch_mode": batch_mode,
            "candidate_count": 2, "opponent_count": 87, "shield_cases": 6,
        }}

    def status(self):
        return {"state": self.state, "started_at": self.time,
                "batch24": self.state != "idle",
                "message": "calculation " + self.state,
                "exit_code": 4 if self.state == "error" else None}

    def _zip(self):
        return ZipFile(fixture_zip(**self.zip_kwargs))


class IVWorkflowTests(unittest.TestCase):
    def test_launch_and_resume_with_exact_ticket(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        start = workflow.run(CANDIDATE, IVS, "simple", ["Corsola"],
                             wait_seconds=0, expected_meta_sha256=HASH)
        self.assertEqual(start["state"], "running")
        self.assertEqual(start["preview"]["candidate_count"], 2)
        self.assertEqual(backend.run_count, 1)
        self.assertEqual(backend.inputs[0][1], IVS)
        backend.state = "done"
        report = workflow.result(start["run_ref"])
        self.assertEqual(report["state"], "done")
        self.assertTrue(report["complete"])
        self.assertEqual(report["total_ratings_checked"], 24)
        self.assertEqual(set(report["reports"]), {"default"})
        self.assertTrue(report["meta_verified_against_project"])
        self.assertEqual(backend.run_count, 1)

    def test_wrong_token_and_wrong_job_are_rejected(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        start = workflow.run(CANDIDATE, IVS, wait_seconds=0)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            workflow.result("fake-ref")
        backend.state = "done"
        backend.time = "2026-10-14T15:59:59"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            workflow.result(start["run_ref"])

    def test_previous_zip_species_and_ivs_are_rejected(self):
        for zip_kwargs in ({"bad_species": True}, {"bad_ivs": True}):
            with self.subTest(zip_kwargs=zip_kwargs):
                backend = FakeBackend(zip_kwargs)
                workflow = IVWorkflow(backend)
                start = workflow.run(CANDIDATE, IVS, wait_seconds=0)
                backend.state = "done"
                with self.assertRaisesRegex(ValueError, "different|differ"):
                    workflow.result(start["run_ref"])

    def test_project_hash_mismatch_must_not_start(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        with self.assertRaisesRegex(ValueError, "meta SHA256"):
            workflow.run(CANDIDATE, IVS, expected_meta_sha256="b" * 64)
        self.assertEqual(backend.run_count, 0)

    def test_validation_before_job_start(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        with self.assertRaisesRegex(ValueError, "Invalid IV"):
            workflow.run(CANDIDATE, "99,11,12", wait_seconds=0)
        with self.assertRaisesRegex(ValueError, "highlight_limit"):
            workflow.run(CANDIDATE, IVS, highlight_limit=0, wait_seconds=0)
        self.assertEqual(backend.run_count, 0)

    def test_error_and_busy_states(self):
        backend = FakeBackend()
        workflow = IVWorkflow(backend)
        start = workflow.run(CANDIDATE, IVS, wait_seconds=0)
        with self.assertRaisesRegex(ValueError, "already running"):
            workflow.run(CANDIDATE, IVS, wait_seconds=0)
        backend.state = "error"
        result = workflow.result(start["run_ref"])
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["exit_code"], 4)

    def test_detailed_all_four_modes_are_complete(self):
        backend = FakeBackend({"batch_mode": "detailed"})
        workflow = IVWorkflow(backend)
        started = workflow.run(CANDIDATE, IVS, batch_mode="detailed",
                               wait_seconds=0)
        backend.state = "done"
        result = workflow.result(started["run_ref"])
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["reports"]), 4)
        self.assertEqual(result["total_ratings_checked"], 96)

    def test_backend_tool_discovery(self):
        from pathlib import Path
        remote = (Path(__file__).resolve().parents[1] / "pvpoke_mcp_remote.py").read_text()
        self.assertIn("'run_iv_selection'", remote)
        self.assertIn("'get_iv_selection_result'", remote)
        self.assertIn("'get_selection_digest'", remote)


if __name__ == "__main__":
    unittest.main()
