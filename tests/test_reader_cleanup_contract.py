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
        self.assertTrue(all(item["search"].endswith("&!favorite") for item in payload["items"]))

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

    def test_response_sends_every_verified_query_not_the_tiny_quick_subset(self):
        from pvpoke_reader_cleanup import reader_cleanup_payload
        fake = {
            "source_date":"test",
            "queries":[{"query":"Alpha&!shadow&cp-1500&!favorite"},
                       {"query":"Beta&shadow&cp-1500&!favorite"}],
            "unranked_queries":[{"query":"Gothita&!shadow&cp-1500&!favorite"}],
            "unranked_review":[{"name":"Gothita","reason":"未掲載"}],
            "unranked_review_count":1,
            "source_date":"test",
            "searchable_count":2,
            "exclusion_reasons":{"evolution_protected":1},
            "quick_query":"201&cp-1500&!favorite",
        }
        with patch("pvpoke_reader_cleanup.search_low_scores",return_value=fake):
            result = reader_cleanup_payload({})
        self.assertEqual(len(result["items"]),3)
        self.assertEqual(result["verified_query_count"],2)
        self.assertNotIn(result["quick_query"] if "quick_query" in result else "201&cp-1500&!favorite",
                         [x["search"] for x in result["items"]])
        self.assertTrue(all(len(x["search"])<=2000 for x in result["items"]))


if __name__=="__main__":
    unittest.main()
