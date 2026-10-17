"""S-led limited box selection: preserve full matchup evidence, hide weak niches."""
import unittest
from pvpoke_app_selection import recommend
from pvpoke_selection_matrix import SelectionMatrix, SHIELDS


CANDIDATE = {
    "species": "quagsire", "fast": "MUD_SHOT",
    "charged1": "AQUA_TAIL", "charged2": "STONE_EDGE"
}


def matrix(rows, opponents):
    return SelectionMatrix(opponents, list(rows), {
        shield: {iv: list(values) for iv, values in rows.items()}
        for shield in SHIELDS
    }, {})


class ClassicBoxTests(unittest.TestCase):
    def test_mainstay_without_single_best_event_is_promoted_to_s(self):
        m = matrix({
            "0/11/12": [525, 525, 525],
            "3/13/8": [535, 500, 500],
            "2/15/13": [500, 535, 500],
        }, ["Corviknight", "Quagsire", "Feraligatr"])
        r = recommend({"default": m}, CANDIDATE, "Quagsire")
        self.assertEqual(r["recommendations"][0]["ivs"], "0/11/12")
        self.assertEqual(r["recommendations"][0]["grade"], "Sランク")
        self.assertEqual(r["recommendations"][0]["role"], "総合本命（保存最優先）")
        self.assertEqual(r["recommendations"][0]["evidence"][0]["kind"], "mainstay")

    def test_disadvantaged_single_matchup_is_worth_keeping(self):
        m = matrix({"0/11/12": [540, 540], "3/13/8": [490, 490]},
                   ["Corviknight", "Quagsire"])
        m.ratings["i0y1"]["3/13/8"] = [550, 490]
        m.ratings["i0y1"]["0/11/12"] = [490, 540]
        r = recommend({"default": m}, CANDIDATE, "Quagsire")
        self.assertEqual([x["ivs"] for x in r["recommendations"]],
                         ["0/11/12", "3/13/8"])
        self.assertEqual(r["recommendations"][1]["grade"], "Aランク")

    def test_isolated_nonfocus_s0_specialist_is_reference_not_copy(self):
        m = matrix({"0/11/12": [520, 540], "3/13/8": [490, 490]},
                   ["Corviknight", "Quagsire"])
        m.ratings["s0"]["3/13/8"] = [560, 490]
        m.ratings["s0"]["0/11/12"] = [490, 540]
        r = recommend({"default": m}, CANDIDATE, "Quagsire")
        self.assertEqual([x["ivs"] for x in r["recommendations"]], ["0/11/12"])
        self.assertEqual(r["additional_candidates"][0]["ivs"], "3/13/8")
        focused = recommend({"default": m}, CANDIDATE, "Quagsire",
                            focus_opponents=["Corviknight"])
        self.assertEqual(len(focused["recommendations"]), 2)

    def test_four_copy_rows_without_discarding_other_evaluations(self):
        ivs = {f"{i}/10/8": [550 if j == i else 470 for j in range(12)]
               for i in range(12)}
        r = recommend({"default": matrix(ivs, [f"Opponent {j}" for j in range(12)])},
                      CANDIDATE, "Quagsire")
        self.assertEqual(len(r["recommendations"]), 4)
        self.assertEqual(len(r["additional_candidates"]), 8)
        self.assertEqual(r["total_ratings_checked"], 12 * 12 * 6)
        all_ivs = {x["ivs"] for x in
                   r["recommendations"] + r["additional_candidates"]}
        self.assertEqual(all_ivs, set(ivs))


if __name__ == "__main__":
    unittest.main()
