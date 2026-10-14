"""Offline regression tests for the one-call IV comparison report."""
import ast
import csv
import io
import json
import unittest
from pathlib import Path
from zipfile import ZipFile

from pvpoke_selection_report import SHIELDS, build_selection_report


def fixture_zip(missing=None, swapped=False):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "batch_mode": "simple", "excluded": 0,
            "gamemaster_timestamp": "test",
        }))
        for shield in SHIELDS:
            if shield == missing:
                continue
            table = io.StringIO()
            writer = csv.writer(table)
            names = ["Corsola (Galarian) A+NSh/PG 4/15/14",
                     "Tinkaton FW+Bd/GH 4/15/14"]
            if swapped and shield == "s2":
                names.reverse()
            writer.writerow(["candidate", *names,
                             "rating_gt500", "rating_lt500", "rating_eq500",
                             "mean_rating"])
            high = 510 if shield == "s1" else 600
            low = 480 if shield == "s1" else 550
            writer.writerow(["Kecleon SP+TP/DP 0/10/8", high, 350, 1, 1, 0, 430])
            writer.writerow(["Kecleon SP+TP/DP 13/7/5", low, 300, 1, 1, 0, 390])
            z.writestr(f"default_{shield}.csv", table.getvalue())
    stream.seek(0)
    return stream


class SelectionReportTests(unittest.TestCase):
    def test_report_is_complete_and_crossover_is_exact(self):
        with ZipFile(fixture_zip()) as archive:
            report = build_selection_report(
                archive, focus_opponents=["Corsola"], max_flips=100)
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["opponent_count"], 2)
        self.assertEqual(report["condition_count"], 6)
        self.assertEqual(report["total_ratings_checked"], 24)
        self.assertTrue(report["complete"])
        self.assertEqual(len(report["rankings"]), 2)
        self.assertEqual(report["rankings"][0]["ivs"], "0/10/8")
        self.assertEqual(report["crossovers_total"], 1)
        flip = report["crossovers"][0]
        self.assertEqual(flip["shield"], "s1")
        self.assertEqual(flip["above500_ivs"], ["0/10/8"])
        self.assertEqual(flip["best"][0]["rating"], 510)
        focus = report["focus_matchups"][0]
        self.assertEqual(focus["by_iv"]["13/7/5"][1], 480)

    def test_missing_condition_is_not_silently_ignored(self):
        with ZipFile(fixture_zip(missing="i1y2")) as archive:
            with self.assertRaisesRegex(ValueError, "Missing required condition"):
                build_selection_report(archive)

    def test_opponent_order_mismatch_is_rejected(self):
        with ZipFile(fixture_zip(swapped=True)) as archive:
            with self.assertRaisesRegex(ValueError, "Opponent order differs"):
                build_selection_report(archive)

    def test_validation_and_no_crossovers_limit(self):
        with ZipFile(fixture_zip()) as archive:
            result = build_selection_report(archive, max_flips=0)
            self.assertEqual(result["crossovers_total"], 1)
            self.assertEqual(result["crossovers_returned"], 0)
            with self.assertRaises(ValueError):
                build_selection_report(archive, mode="bad")
            with self.assertRaises(ValueError):
                build_selection_report(archive, focus_opponents=[""] * 16)

    def test_mcp_tool_exposed_and_existing_apis_preserved(self):
        src = (Path(__file__).resolve().parents[1] / "pvpoke_mcp_remote.py").read_text()
        ast.parse(src)
        self.assertIn("'get_selection_report'", src)
        self.assertIn("'get_results'", src)
        self.assertIn("'get_24_summary'", src)


if __name__ == "__main__":
    unittest.main()
