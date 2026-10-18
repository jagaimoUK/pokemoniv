"""Regression checks for low-score box searches and ranking snapshots."""
import unittest
from pathlib import Path

from pvpoke_score_search import load_snapshot, search_low_scores


class LowScoreSearchTests(unittest.TestCase):
    def test_snapshot_is_packaged_in_runtime_docker_image(self):
        project_root = Path(__file__).resolve().parent.parent
        dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
        asset = "data/cp1500_role_scores_20261015.json"
        self.assertTrue((project_root / asset).is_file())
        self.assertIn(
            f"COPY {asset} /app/{asset}", dockerfile,
            "Ranking scores must be installed into the runtime Docker image",
        )
        self.assertIn(
            "from pvpoke_score_search import load_snapshot", dockerfile,
            "Validate the packaged scores during the Docker build",
        )

    def test_snapshot_alignment_and_expected_counts(self):
        date, rows = load_snapshot()
        self.assertEqual(date, "2026-10-15")
        self.assertEqual(len(rows), 1153)
        self.assertEqual(len({r["name"] for r in rows}), 1153)
        self.assertEqual(sum(r["overall"] < 70 for r in rows), 431)

    def test_presets_protect_specialists(self):
        self.assertEqual(search_low_scores()["selected_count"], 211)
        self.assertEqual(search_low_scores({"mode": "overall"})["selected_count"], 431)
        self.assertEqual(search_low_scores({"mode": "battle"})["selected_count"], 422)
        self.assertEqual(search_low_scores({"mode": "strict"})["selected_count"], 3)
        self.assertEqual(search_low_scores()["preserved_by_other_roles"], 220)

    def test_search_chunks_are_bounded_and_conservative(self):
        for mode in ("practical", "overall", "battle", "strict"):
            result = search_low_scores({"mode": mode})
            self.assertEqual(result["selected_count"],
                             result["searchable_count"] + result["manual_review_count"])
            self.assertEqual(len(result["queries"]), len({q["query"] for q in result["queries"]}))
            for q in result["queries"]:
                self.assertLessEqual(len(q["query"]), 420)
                self.assertLessEqual(q["species_count"], 18)
                self.assertTrue(q["query"].endswith("&cp-1500&!favorite"))
                self.assertEqual(q["query"].count("&cp-1500"), 1)
                self.assertEqual(q["query"].count("&!shadow") + q["query"].count("&shadow"), 1)
                self.assertTrue(q["query"].split("&")[0])
            for item in result["manual_review"]:
                self.assertTrue(item["reason"])

    def test_safety_and_validation(self):
        result = search_low_scores({"exclude_favorites": False})
        self.assertTrue(all("!favorite" not in q["query"] for q in result["queries"]))
        for invalid in (0, 101, float("nan"), "70", True):
            with self.assertRaises(ValueError):
                search_low_scores({"threshold": invalid})
        with self.assertRaises(ValueError):
            search_low_scores({"mode": "bad"})
        with self.assertRaises(ValueError):
            search_low_scores({"exclude_favorites": "false"})


if __name__ == "__main__":
    unittest.main()
