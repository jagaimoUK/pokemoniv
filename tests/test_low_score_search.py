"""Regression checks for low-score box searches and ranking snapshots."""
import unittest
import re
from pathlib import Path

from pvpoke_score_search import english_names_by_dex, evolution_descendants, load_snapshot, search_low_scores


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
        evolutions = "data/pokemon_species_evolutions_20261019.json"
        self.assertTrue((project_root / evolutions).is_file())
        self.assertIn(f"COPY {evolutions} /app/{evolutions}", dockerfile)
        self.assertIn("evolution_descendants", dockerfile)
        self.assertEqual(len(evolution_descendants()), 1025)
        self.assertIn(683, evolution_descendants()[682])
        self.assertIn(681, evolution_descendants()[679])

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
                             result["searchable_count"] + result["manual_review_count"] +
                             result["evolution_protected_count"])
            self.assertEqual(len(result["queries"]), len({q["query"] for q in result["queries"]}))
            for q in result["queries"]:
                self.assertLessEqual(len(q["query"]), 1200)
                self.assertLessEqual(q["species_count"], 90)
                self.assertNotIn("+", q["query"], "進化系統を含む検索は禁止")
                self.assertRegex(q["query"], r"&cp(?:-1500|[1-9][0-9]*-1500)&!favorite$")
                self.assertEqual(q["query"].count("&cp"), 1)
                self.assertEqual(q["query"].count("&!shadow") + q["query"].count("&shadow"), 1)
                self.assertTrue(q["query"].split("&")[0])
            for item in result["manual_review"]:
                self.assertTrue(item["reason"])

    def test_english_names_and_status_are_preserved(self):
        game_master = {
            "spritzee": {"dex": 682, "name": "Spritzee", "baseStats": {"atk": 100, "def": 100, "hp": 100}},
            "aromatisse": {"dex": 683, "name": "Aromatisse", "baseStats": {"atk": 240, "def": 240, "hp": 240}},
            "entei": {"dex": 244, "name": "Entei"},
            "entei_shadow": {"dex": 244, "name": "Entei (Shadow)"},
            "ho_oh_shadow": {"dex": 250, "name": "Ho-Oh (Shadow)"},
            "darumaka_galarian": {"dex": 554, "name": "Darumaka (Galarian)"},
        }
        result = search_low_scores({"mode": "practical"}, game_master)
        searches = [q["query"] for q in result["queries"]]
        def matching(name, *terms):
            return any(
                name in q.split("&")[0].split(",")
                and all(term in q.split("&")[1:] for term in terms)
                for q in searches
            )
        self.assertTrue(any(
            "Spritzee" in q.split("&")[0].split(",")
            and re.search(r"&cp[0-9]+-1500&", q) for q in searches))
        self.assertTrue(any(x["name"] == "シュシュプ" for x in result["evolution_high_cp_exceptions"]))
        # Galar Darumaka is protected: its evolved CP cannot be bounded here.
        self.assertFalse(matching("Darumaka", "galar", "!shadow"))
        self.assertTrue(any(x["name"] == "ダルマッカ (ガラル)" for x in result["evolution_protected"]))
        self.assertTrue(matching("Entei", "shadow"))
        self.assertTrue(matching("Entei", "!shadow"))
        self.assertTrue(matching("Ho-Oh", "shadow"))
        self.assertTrue(all(not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", q) for q in searches))
        self.assertEqual(
            result["selected_count"],
            result["searchable_count"] + result["manual_review_count"] +
            result["evolution_protected_count"])
        self.assertTrue(any(x["name"] == "ゴチルゼル" and "英語名" in x["reason"]
                            for x in result["manual_review"]))

    def test_ambiguous_and_unverified_english_names_are_not_guessed(self):
        cases = {
            "spritzee": {"dex": 682, "name": "Spritzee"},
            "broken": {"dex": 682, "name": "AnotherSpecies"},
            "non_english": {"dex": 244, "name": "エンテイ"},
            "no_dex": {"name": "Spritzee"},
        }
        self.assertNotIn(682, english_names_by_dex(cases))
        self.assertNotIn(244, english_names_by_dex(cases))
        result = search_low_scores({"mode": "practical"}, cases)
        self.assertEqual(result["searchable_count"], 0)
        self.assertTrue(any(x["name"] == "シュシュプ" for x in result["evolution_protected"]))

    def test_protects_gl_ranked_descendants_when_source_cp_is_unknown(self):
        catalog = {"spritzee": {"dex": 682, "name": "Spritzee"}}
        result = search_low_scores({"mode": "practical"}, catalog)
        self.assertFalse(any("Spritzee" in item["query"] for item in result["queries"]))
        self.assertTrue(any(x["name"] == "シュシュプ" for x in result["evolution_protected"]))

    def test_high_cp_exception_is_only_for_guaranteed_evolution_over_cap(self):
        stats = {"atk": 100, "def": 100, "hp": 100}
        evolved = {"atk": 240, "def": 240, "hp": 240}
        catalog = {
            "spritzee": {"name": "Spritzee", "dex": 682, "baseStats": stats},
            "aromatisse": {"name": "Aromatisse", "dex": 683, "baseStats": evolved},
        }
        result = search_low_scores({"mode": "practical"}, catalog)
        exceptions = [x for x in result["evolution_high_cp_exceptions"] if x["name"] == "シュシュプ"]
        self.assertEqual(len(exceptions), 1)
        cutoff = exceptions[0]["minimum_cp"]
        self.assertGreater(cutoff, 1)
        self.assertLessEqual(cutoff, 1500)
        matching = [q["query"] for q in result["queries"] if
                    "Spritzee" in q["query"].split("&")[0].split(",")]
        self.assertTrue(any(f"cp{cutoff}-1500" in q for q in matching))
        lower_ratio = (240 / 115) ** 2
        self.assertGreaterEqual(int(cutoff * lower_ratio), 1501)
        self.assertLess(int((cutoff - 2) * lower_ratio), 1501)

    def test_compacts_species_with_identical_filters_into_one_query(self):
        # The previous 18-species limit unnecessarily required 4 separate
        # copy-paste steps for 60 otherwise identical search terms.
        from unittest.mock import patch
        mock_rows = [
            {"name": f"test_{n}", "dex": 20000 + n,
             **{role: 1 for role in ("overall", "leads", "closers", "switches",
                                    "chargers", "attackers", "consistency")}}
            for n in range(60)
        ]
        mock_catalog = {
            f"species_{n}": {"dex": 20000 + n, "name": f"Testmon{n:03d}"}
            for n in range(60)
        }
        with patch("pvpoke_score_search.load_snapshot", return_value=("2026-10-15", mock_rows)), \\
             patch("pvpoke_score_search.evolution_descendants",
                   return_value={20000 + n: () for n in range(60)}):
            result = search_low_scores(species_catalog=mock_catalog)
        self.assertEqual(len(result["queries"]), 1)
        self.assertEqual(result["queries"][0]["species_count"], 60)
        self.assertEqual(result["searchable_count"], 60)
        self.assertEqual(result["queries"][0]["query"].count(","), 59)
        self.assertTrue(result["queries"][0]["query"].endswith("&!shadow&cp-1500&!favorite"))

    def test_does_not_combine_different_cp_or_shadow_status_conditions(self):
        from unittest.mock import patch
        rows = [
            {"name": label, "dex": 50000 + i,
             **{role: 1 for role in ("overall", "leads", "closers", "switches",
                                    "chargers", "attackers", "consistency")}}
            for i, label in enumerate(("イー", "イー (シャドウ)", "アー"))
        ]
        rows[1]["dex"] = rows[0]["dex"]
        cat = {
            "alpha": {"dex": 50000, "name": "Alpha"},
            "alpha_shadow": {"dex": 50000, "name": "Alpha (Shadow)"},
            "beta": {"dex": 50002, "name": "Beta"},
        }
        with patch("pvpoke_score_search.load_snapshot", return_value=("2026-10-15", rows)), \\
             patch("pvpoke_score_search.evolution_descendants",
                   return_value={50000: (), 50002: ()}):
            result = search_low_scores(species_catalog=cat)
        self.assertEqual(len(result["queries"]), 2)
        self.assertTrue(any("&shadow&" in x["query"] for x in result["queries"]))
        self.assertTrue(any("&!shadow&" in x["query"] for x in result["queries"]))

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
