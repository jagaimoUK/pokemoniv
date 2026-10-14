"""Compact digest correctness, completeness and payload regression tests."""
import csv
import io
import json
import unittest
from zipfile import ZipFile

from pvpoke_selection_report import SHIELDS, build_selection_report
from pvpoke_selection_digest import build_selection_digest


def sample_zip(missing=None, n=2, opponents=2):
    buf = io.BytesIO()
    names = ["Corsola (Galarian) A+NSh/PG 4/15/14",
             "Tinkaton FW+Bd/GH 4/15/14"] + [
                 f"Opponent_{j} MoveSet" for j in range(2, opponents)]
    with ZipFile(buf, "w") as output:
        output.writestr("manifest.json", json.dumps({
            "batch_mode": "simple", "excluded": 0,
            "gamemaster_timestamp": "2026-10-13",
        }))
        for case, shield in enumerate(SHIELDS):
            if shield == missing:
                continue
            content = io.StringIO()
            writer = csv.writer(content)
            writer.writerow(["candidate", *names, "rating_gt500",
                             "rating_lt500", "rating_eq500", "mean_rating"])
            for i in range(n):
                if n == 2 and opponents == 2:
                    a = (510 if shield == "s1" else 600) - 30 * i
                    vals = [a, 350 - 50 * i]
                else:
                    vals = [
                        380 + (case * 23 + i * 11 + j * 17) % 245
                        for j in range(opponents)
                    ]
                writer.writerow([f"Kecleon SP+TP/DP {i}/10/8",
                                 *vals,
                                 sum(x > 500 for x in vals),
                                 sum(x < 500 for x in vals), 0,
                                 sum(vals) / len(vals)])
            output.writestr(f"default_{shield}.csv", content.getvalue())
    buf.seek(0)
    return buf


class SelectionDigestTests(unittest.TestCase):
    def test_small_fixture_dominance_and_focus(self):
        with ZipFile(sample_zip()) as archive:
            result = build_selection_digest(
                archive, "default", ["Corsola", "Tinkaton"],
                highlight_limit=3, review_limit=2, focus_limit=1)
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_ratings_checked"], 24)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["dominated_by"]["1/10/8"], ["0/10/8"])
        self.assertEqual(result["crossovers_total"], 1)
        self.assertEqual(result["crossovers_returned"], 1)
        self.assertEqual(result["priority_crossovers"][0]["shield"], "s1")
        self.assertEqual(result["priority_crossovers"][0]["best"], ["0/10/8", 510])
        self.assertEqual(result["priority_crossovers"][0]["second"], ["1/10/8", 480])
        self.assertEqual(result["focus_matchups_total"], 2)
        self.assertEqual(result["focus_matchups_returned"], 1)
        self.assertTrue(result["focus_matchups_truncated"])
        self.assertEqual(len(result["focus_matchups"][0]["by_iv"]), 2)

    def test_realistic_12x87x6_digests_less_data_than_full(self):
        with ZipFile(sample_zip(n=12, opponents=87)) as archive:
            original = build_selection_report(
                archive, "default", ["Corsola", "Tinkaton"],
                max_flips=120)
            digest = build_selection_digest(
                archive, "default", ["Corsola", "Tinkaton"],
                highlight_limit=16, review_limit=7, focus_limit=6)
        self.assertEqual(digest["total_ratings_checked"], 6264)
        self.assertEqual(digest["crossovers_total"], original["crossovers_total"])
        self.assertEqual(digest["ranking_rows"][0][0], original["rankings"][0]["ivs"])
        self.assertLessEqual(digest["crossovers_returned"], 16)
        self.assertLessEqual(digest["focus_matchups_returned"], 6)
        self.assertLessEqual(len(digest["review_ivs"]), 7)
        self.assertLess(
            len(json.dumps(digest, ensure_ascii=False)),
            0.6 * len(json.dumps(original, ensure_ascii=False))
        )

    def test_missing_condition_fails_closed(self):
        with ZipFile(sample_zip(missing="i1y2")) as archive:
            with self.assertRaisesRegex(ValueError, "Missing required condition"):
                build_selection_digest(archive)

    def test_parameter_bounds(self):
        with ZipFile(sample_zip()) as archive:
            with self.assertRaisesRegex(ValueError, "highlight_limit"):
                build_selection_digest(archive, highlight_limit=0)
            with self.assertRaisesRegex(ValueError, "review_limit"):
                build_selection_digest(archive, review_limit=13)
            with self.assertRaisesRegex(ValueError, "focus_limit"):
                build_selection_digest(archive, focus_limit=-1)


if __name__ == "__main__":
    unittest.main()
