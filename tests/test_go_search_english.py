"""Regression: every newly generated species query is an English GO name."""
import unittest

from pvpoke_go_search import search_string, species_search_term


class EnglishGoSearchTests(unittest.TestCase):
    def test_flabebe_uses_english_species_not_669(self):
        for name in ("Flabébé", "Flabebe", "Flabe\u0301be\u0301", "フラベベ"):
            with self.subTest(name=name):
                query = search_string(name, "0/11/15", True, "flabebe_blue")
                self.assertEqual(query, "Flabébé&0attack&3defense&4hp&shadow")
                self.assertNotIn("669", query)

    def test_names_with_gender_forms_stay_searchable(self):
        self.assertEqual(
            search_string("Nidoran (Female)", "0/11/15", False, "nidoran_female"),
            "Nidoran&female&0attack&3defense&4hp")
        self.assertEqual(
            search_string("Wooper (Paldean)", "0/11/15", True, "wooper_paldean_shadow"),
            "Wooper&paldea&0attack&3defense&4hp&shadow")

    def test_no_new_bare_dex_query_is_created(self):
        with self.assertRaisesRegex(ValueError, "English species name"):
            search_string("669", "0/11/15", species_id="not_flabebe")
        self.assertEqual(species_search_term("Quagsire"), "Quagsire")


if __name__ == "__main__":
    unittest.main()
