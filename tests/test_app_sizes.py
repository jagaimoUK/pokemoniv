"""Size-specific regression checks for the two pumpkin evolution stages."""
import unittest

from pvpoke_app_catalog import enrich_catalog
from pvpoke_app_input import parse_import
from pvpoke_app_selection import search_string

FORMS = ("small", "average", "large", "super")
NAMES = {"pumpkaboo": ("バケッチャ", 710), "gourgeist": ("パンプジン", 711)}
MOVES = {"fast": "HEX", "charged1": "SEED_BOMB", "charged2": "SHADOW_BALL"}


def sample_catalog():
    species = {}
    raw = {}
    for base, (_, dex) in NAMES.items():
        for form in FORMS:
            sid = base + "_" + form
            raw[sid] = {"dex": dex}
            species[sid] = {
                "name": base.capitalize() + " (" + form.capitalize() + ")",
                "fastMoves": ["HEX"], "chargedMoves": ["SEED_BOMB", "SHADOW_BALL"],
            }
    enrich_catalog(species, raw)
    for row in species.values():
        row["default_moves"] = MOVES.copy()
    return {"species": species, "presets": []}


def imported(text, cat):
    return parse_import("個体値厳選\n# " + text + "\n0,11,12", cat)["candidate"]["species"]


class PumpkinSizeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = sample_catalog()

    def test_both_species_4_forms_are_independent_and_visible(self):
        for base, (ja, _) in NAMES.items():
            for form in FORMS:
                with self.subTest(base=base, form=form):
                    sid = base + "_" + form
                    row = self.catalog["species"][sid]
                    self.assertIn(ja, row["name_ja"])
                    self.assertIn(form.upper() if form != "average" else "通常", row["name_ja"].upper() if form == "average" else sid.upper() + row["name_ja"])
        codes = [p["nickname_code"] for p in self.catalog["species"].values()]
        self.assertEqual(len(set(c.casefold() for c in codes)), 8)
        self.assertEqual(set(self.catalog["species"]["gourgeist_" + f]["nickname_code"][-1] for f in FORMS), set("XMLZ"))

    def test_japanese_and_english_aliases(self):
        words = {"small": ("こだましゅ", "Small Size", "XS"),
                 "average": ("ちゅうだましゅ", "Average", "Medium"),
                 "large": ("おおだましゅ", "Large", "XL"),
                 "super": ("ぎがだましゅ", "Super", "XXL")}
        for base, (ja, _) in NAMES.items():
            for form, terms in words.items():
                for jp in (ja + "の" + terms[0], ja + "(" + terms[0] + ")", ja + " " + terms[0]):
                    with self.subTest(jp=jp):
                        self.assertEqual(imported(jp, self.catalog), base + "_" + form)
                for en in terms[1:]:
                    with self.subTest(en=en):
                        self.assertEqual(imported(base.capitalize() + " " + en, self.catalog), base + "_" + form)
                        self.assertEqual(imported(base.capitalize() + "(" + en + ")", self.catalog), base + "_" + form)
                self.assertEqual(imported(base + "_" + form, self.catalog), base + "_" + form)
        self.assertEqual(imported("パンプジンのギガだましゅ", self.catalog), "gourgeist_super")
        self.assertEqual(imported("Gourgeist Jumbo", self.catalog), "gourgeist_super")
        self.assertEqual(imported("Gourgeist XXL", self.catalog), "gourgeist_super")

    def test_different_forms_do_not_merge_same_ivs(self):
        parsed = parse_import(
            "個体値厳選\n# パンプジンのこだましゅ\n0,11,12\n"
            "# パンプジンのギガだましゅ\n0,11,12\n"
            "# バケッチャのちゅうだましゅ\n0,11,12", self.catalog)
        self.assertEqual(parsed["group_count"], 3)
        self.assertEqual([x["candidate"]["species"] for x in parsed["jobs"]],
                         ["gourgeist_small", "gourgeist_super", "pumpkaboo_average"])
        self.assertTrue(all(x["candidate_count"] == 1 for x in parsed["jobs"]))

    def test_missing_size_is_rejected_instead_of_guessing(self):
        for base, (ja, _) in NAMES.items():
            for word in (base, base.capitalize(), ja):
                with self.subTest(word=word), self.assertRaisesRegex(ValueError, "サイズを指定"):
                    imported(word, self.catalog)
        with self.assertRaises(ValueError):
            imported("パンプジンの知らないサイズ", self.catalog)

    def test_search_copy_is_go_name_plus_size_and_keeps_iv_buckets(self):
        suffix = {"small": "&xs", "average": "&!xxs&!xs&!xl&!xxl",
                  "large": "&xl", "super": "&xxl"}
        for base in NAMES:
            for form in FORMS:
                with self.subTest(base=base, form=form):
                    result = search_string("Any display name", "0/11/12", False, base + "_" + form)
                    self.assertEqual(result, base.capitalize() + "&0attack&3defense&3hp" + suffix[form])
        self.assertEqual(search_string("Gourgeist (Super)", "5/15/10", True, "gourgeist_super"),
                         "Gourgeist&1attack&4defense&2hp&xxl&shadow")
        self.assertEqual(search_string("Quagsire", "0/11/12", False, "quagsire"),
                         "Quagsire&0attack&3defense&3hp")


if __name__ == "__main__":
    unittest.main()
