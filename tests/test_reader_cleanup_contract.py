"""Reader button response is a complete multi-query batch, not quick_query."""
import unittest
from unittest.mock import patch

from pvpoke_reader_cleanup import reader_cleanup_payload
from pvpoke_score_search import search_low_scores


class ReaderCleanupContractTests(unittest.TestCase):
    def test_gothita_missing_from_snapshot_is_review_only(self):
        # 574 is absent in the pinned ranking while its whole evolution line is present.
        catalog = {
            "gothita": {"dex":574, "name":"Gothita"},
            "gothorita": {"dex":575, "name":"Gothorita"},
            "gothitelle": {"dex":576, "name":"Gothitelle"},
            "unown": {"dex":201, "name":"Unown"},
        }
        data = search_low_scores(species_catalog=catalog)
        self.assertTrue(any(x["name"]=="Gothita" and "未掲載" in x["reason"]
                            for x in data["unranked_review"]))
        self.assertFalse(any("Gothita" in q["query"] for q in data["queries"]))
        self.assertTrue(any("Gothita" in q["query"] for q in data["unranked_queries"]))
        payload = reader_cleanup_payload(catalog)
        self.assertEqual(payload["format"], "pokemoniv-search-queue-v1")
        self.assertGreaterEqual(payload["verified_query_count"], 1)
        self.assertGreaterEqual(payload["review_query_count"], 1)
        self.assertEqual(payload["review_species_count"], 1)
        self.assertEqual(payload["items"][-1]["confidence"], "unranked_review")
        self.assertTrue(any("Gothita" in item["search"] for item in payload["items"]))
        self.assertTrue(all("nickname" not in item for item in payload["items"]))
        self.assertTrue(all("!favorite" not in item["search"] for item in payload["items"]))

    def test_strong_or_unknown_descendants_do_not_enter_unranked_queries(self):
        rows = [
            {"name":"高評価進化", "dex":575,
             **{role:80 for role in ("overall","leads","closers","switches","chargers","attackers","consistency")}},
            {"name":"低評価進化", "dex":576,
             **{role:20 for role in ("overall","leads","closers","switches","chargers","attackers","consistency")}},
        ]
        cat = {"gothita":{"dex":574,"name":"Gothita"}}
        with patch("pvpoke_score_search.load_snapshot",return_value=("test",rows)), \
             patch("pvpoke_score_search.evolution_descendants",
                   return_value={574:(575,576),575:(576,),576:()}):
            result = search_low_scores(species_catalog=cat)
        self.assertFalse(result["unranked_queries"])
        self.assertFalse(result["unranked_review"])

    def test_prioritizes_high_coverage_and_gothita_review_before_cp_exceptions(self):
        data = {
            "source_date": "test",
            "queries": [
                {"query": "RareOne&!shadow&cp1000-1500", "species_count": 1},
                {"query": ",".join("ManySpecies" + str(i) for i in range(60)) + "&!shadow&cp-1500", "species_count": 60},
                {"query": ",".join("ShadowGroup" + str(i) for i in range(20)) + "&shadow&cp-1500", "species_count": 20},
                {"query": "RareTwo&!shadow&cp1100-1500", "species_count": 1},
            ],
            "unranked_queries": [{"query": "Gothita&!shadow&cp-1500"}],
            "unranked_review": [{"name": "Gothita", "reason": "未掲載"}],
            "unranked_review_count": 1,
            "searchable_count": 82,
            "exclusion_reasons": {},
        }
        with patch("pvpoke_reader_cleanup.search_low_scores", return_value=data):
            result = reader_cleanup_payload({})
        self.assertEqual(
            set(result["items"][0]["search"].split("&")[0].split(",")),
            set(data["queries"][1]["query"].split("&")[0].split(",")),
        )
        self.assertEqual(
            result["items"][0]["search"].split("&")[1:],
            data["queries"][1]["query"].split("&")[1:],
        )
        self.assertFalse(result["excluded_favorites"])
        self.assertFalse(result["single_query_complete"])
        self.assertEqual(result["original_query_count"], 5)
        self.assertTrue(all("!favorite" not in x["search"] for x in result["items"]))
        self.assertEqual(
            set(result["items"][1]["search"].split("&")[0].split(",")),
            set(data["queries"][2]["query"].split("&")[0].split(",")),
        )
        self.assertEqual(
            result["items"][1]["search"].split("&")[1:],
            data["queries"][2]["query"].split("&")[1:],
        )
        self.assertEqual(result["items"][2]["search"], "Gothita&!shadow&cp-1500")
        self.assertEqual(result["items"][2]["confidence"], "unranked_review")
        self.assertEqual(len(result["items"]), 5)

    def test_response_sends_every_verified_query_not_the_tiny_quick_subset(self):
        from pvpoke_reader_cleanup import reader_cleanup_payload
        fake = {
            "source_date":"test",
            "queries":[{"query":"Alpha&!shadow&cp-1500"},
                       {"query":"Beta&shadow&cp-1500"}],
            "unranked_queries":[{"query":"Gothita&!shadow&cp-1500"}],
            "unranked_review":[{"name":"Gothita","reason":"未掲載"}],
            "unranked_review_count":1,
            "source_date":"test",
            "searchable_count":2,
            "exclusion_reasons":{"evolution_protected":1},
            "quick_query":"201&cp-1500",
        }
        with patch("pvpoke_reader_cleanup.search_low_scores",return_value=fake):
            result = reader_cleanup_payload({})
        self.assertEqual(len(result["items"]),3)
        self.assertEqual(result["verified_query_count"],2)
        self.assertNotIn(result["quick_query"] if "quick_query" in result else "201&cp-1500",
                         [x["search"] for x in result["items"]])
        self.assertTrue(all(len(x["search"])<=2000 for x in result["items"]))


    def test_excludes_entire_cp_sensitive_species_from_android_search(self):
        # Spritzee is below 70, but Aromatisse has a strong PvP score.
        # This fixture yields a genuine CP-dependent threshold in the old mode.
        catalog = {
            "spritzee": {"name": "Spritzee", "dex": 682,
                         "baseStats": {"atk": 100, "def": 100, "hp": 100}},
            "aromatisse": {"name": "Aromatisse", "dex": 683,
                           "baseStats": {"atk": 240, "def": 240, "hp": 240}},
            "unown": {"name": "Unown", "dex": 201},
        }
        original = search_low_scores(
            {"mode": "practical", "exclude_favorites": False}, catalog
        )
        self.assertTrue(any(
            "Spritzee" in row["query"] for row in original["queries"]
        ))
        self.assertTrue(any(
            row["name"] == "シュシュプ"
            for row in original["evolution_high_cp_exceptions"]
        ))

        safe = search_low_scores(
            {"mode": "practical", "exclude_favorites": False,
             "exclude_cp_dependent": True}, catalog
        )
        self.assertFalse(any(
            "Spritzee" in row["query"] for row in safe["queries"]
        ))
        self.assertEqual(safe["evolution_high_cp_count"], 0)
        self.assertTrue(any(
            row["name"] == "シュシュプ" and row["minimum_cp"] > 1
            for row in safe["cp_dependent_excluded"]
        ))
        self.assertEqual(
            safe["selected_count"],
            safe["searchable_count"] + safe["manual_review_count"]
            + safe["evolution_protected_count"] + safe["cp_dependent_excluded_count"],
        )

        exported = reader_cleanup_payload(catalog)
        self.assertTrue(exported["cp_dependent_excluded_count"] >= 1)
        self.assertTrue(exported["cp_dependent_excluded_species_count"] >= 1)
        self.assertFalse(any(
            "Spritzee" in item["search"] for item in exported["items"]
        ))
        self.assertTrue(all(
            "&cp-1500" in item["search"]
            for item in exported["items"]
        ))
        self.assertFalse(any(
            "!favorite" in item["search"] for item in exported["items"]
        ))

    def test_invalid_cp_dependent_flag_and_default_behavior(self):
        with self.assertRaises(ValueError):
            search_low_scores({"exclude_cp_dependent": "true"})
        # Diagnostic mode stays unchanged unless the reader explicitly opts in.
        standard = search_low_scores()
        self.assertEqual(standard["cp_dependent_excluded_count"], 0)
        # Tests with a complete species/stat catalog above cover the actual
        # CP exception; an empty catalog cannot prove any CP lower bound.

if __name__=="__main__":
    unittest.main()



class BooleanCompactionTests(unittest.TestCase):
    def test_shadow_and_region_partition_merge_without_other_species(self):
        from pvpoke_go_query_compact import compact_search_groups
        rows = [
            {"query": "A,B&!shadow&!alola&cp-1500"},
            {"query": "A&shadow&!alola&cp-1500"},
            {"query": "A&!shadow&alola&cp-1500"},
            {"query": "A&shadow&alola&cp-1500"},
        ]
        out = compact_search_groups(rows)
        self.assertEqual({x["query"] for x in out},
            {"A&cp-1500", "B&!alola&!shadow&cp-1500"})
        self.assertEqual(sum(x["species_count"] for x in out), 2)

    def test_different_cp_bounds_never_merge(self):
        from pvpoke_go_query_compact import compact_search_groups
        rows = [
            {"query": "A&!shadow&cp1000-1500"},
            {"query": "A&shadow&cp1100-1500"},
            {"query": "B&!shadow&cp-1500"},
            {"query": "B&shadow&cp-1500"},
        ]
        actual = {r["query"] for r in compact_search_groups(rows)}
        self.assertEqual(actual, {"A&!shadow&cp1000-1500",
                                  "A&shadow&cp1100-1500", "B&cp-1500"})

    def test_long_groups_split_below_go_input_limit(self):
        from pvpoke_go_query_compact import compact_search_groups
        query = ",".join("Candidate" + str(i) for i in range(250)) + "&!shadow&cp-1500"
        result = compact_search_groups([{"query": query}])
        self.assertGreater(len(result), 1)
        self.assertEqual(sum(x["species_count"] for x in result), 250)
        self.assertTrue(all(len(x["query"]) <= 950 for x in result))

    def test_boolean_union_equivalent_on_status_region_and_cp_boundaries(self):
        from pvpoke_go_query_compact import compact_search_groups
        rows = [
            {"query": "A,C&!shadow&!alola&cp-1500"},
            {"query": "A&shadow&!alola&cp-1500"},
            {"query": "A&!shadow&alola&cp-1500"},
            {"query": "A&shadow&alola&cp-1500"},
            {"query": "B&shadow&cp1000-1500"},
            {"query": "B&!shadow&cp1250-1500"},
        ]
        result = compact_search_groups(rows)
        def matched(q, name, shadow, alola, cp):
            names, *conditions = q.split("&")
            if name not in names.split(","):
                return False
            for term in conditions:
                if term == "shadow" and not shadow: return False
                if term == "!shadow" and shadow: return False
                if term == "alola" and not alola: return False
                if term == "!alola" and alola: return False
                if term.startswith("cp"):
                    lo, hi = term[2:].split("-")
                    if not (int(lo) if lo else 0) <= cp <= (int(hi) if hi else 999999):
                        return False
            return True
        for name in ("A","B","C","D"):
            for shadow in (False,True):
                for alola in (False,True):
                    for cp in (1,999,1000,1249,1250,1500,1501):
                        before = any(matched(r["query"],name,shadow,alola,cp) for r in rows)
                        after = any(matched(r["query"],name,shadow,alola,cp) for r in result)
                        self.assertEqual(before, after, (name, shadow, alola, cp))
