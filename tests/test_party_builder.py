import tempfile
import unittest
from pathlib import Path

import pvpoke_party_core as core
from pvpoke_party_backend import PartyBuilder


class PartyCoreTests(unittest.TestCase):
    def test_ids_include_species_and_moves(self):
        base = dict(species="azumarill", fast="BUBBLE", charged1="ICE_BEAM",
                    charged2="PLAY_ROUGH", atk=0, def_=15, hp=15, level=50, cp=1499)
        base["def"] = base.pop("def_")
        other = dict(base, species="clodsire")
        self.assertNotEqual(core.combatant_id(base), core.combatant_id(other))
        self.assertNotEqual(core.combatant_id(base),
                            core.combatant_id(dict(base, fast="TACKLE")))

    def test_weight_per_species_and_duplicate_hypothesis(self):
        a = {"id": "a", "species": "one"}
        b = {"id": "b", "species": "one"}
        c = {"id": "c", "species": "two"}
        result = core.weight_rows([a, a, b, c], {"one": 3, "two": 1})
        self.assertAlmostEqual(result["a"], .375)
        self.assertAlmostEqual(result["b"], .375)
        self.assertAlmostEqual(result["c"], .25)
        self.assertAlmostEqual(sum(result.values()), 1)

    def test_unknown_is_not_defeat(self):
        mat = {("a", "x", (2, 2)): 620, ("b", "x", (2, 2)): 400}
        r = core.team_summary(["a", "b"], ["x", "y"], mat,
                              {"x": .5, "y": .5})
        self.assertEqual(r["d0"], 0)
        self.assertEqual(r["d1"], .5)
        self.assertEqual(r["unknown_weight"], .5)
        self.assertFalse(r["complete"])

    def test_6_coverage_does_not_mean_each_triple_covers(self):
        matrix = {}
        for i in range(6):
            for j in range(6):
                matrix[(str(i), str(j), (2, 2))] = 650 if i == j else 250
        weights = {str(j): 1/6 for j in range(6)}
        team = core.team_summary([str(i) for i in range(6)],
                                  list(weights), matrix, weights)
        self.assertEqual(team["d0"], 0)
        triples = [core.team_summary(t, list(weights), matrix, weights)
                   for t in core.legal_triples([str(i) for i in range(6)])]
        self.assertEqual(len(triples), 20)
        self.assertTrue(all(x["d0"] > 0 for x in triples))

    def test_roster_orders_and_shield_budget(self):
        members = list("abcdef")
        self.assertEqual(len(list(core.legal_triples(members))), 20)
        self.assertEqual(len(list(core.role_orders(members))), 60)
        self.assertEqual(len(list(core.ALLOCATIONS)), 10)
        self.assertEqual(len(core.ALL_SHIELDS), 9)
        self.assertTrue(all(sum(x) <= 2 for x in core.ALLOCATIONS))

    def test_matching_one_answer_cannot_answer_two_separately(self):
        m = {("a", "x", (2, 2)): 700, ("a", "y", (2, 2)): 700,
             ("b", "x", (2, 2)): 100, ("b", "y", (2, 2)): 100}
        self.assertEqual(core.max_matching(["a", "b"], ["x", "y"], m), 1)
        self.assertEqual(core.assignment_report(["a", "b"], ["x", "y"], m)["deficit"], .5)

    def test_danger_pair_avoids_same_species_move_variants(self):
        own = ["a", "b", "c"]
        opp = ["x1", "x2", "y"]
        m = {(a, b, (2, 2)): 400 for a in own for b in opp}
        for enemy in opp:
            m[("a", enemy, (2, 2))] = 700
        clauses = {"x1": "x", "x2": "x", "y": "y"}
        threats = core.dangerous_pairs([own], opp, m,
                                       {a: 1 / 3 for a in opp}, clauses)
        self.assertTrue(all(set(x["opponents"]) != {"x1", "x2"} for x in threats))
        self.assertTrue(threats)

    def test_selection_bounds_do_not_claim_probability(self):
        own, enemy = list("abc"), list("xyz")
        m = {(a, b, shields): 600 for a in own for b in enemy
             for shields in core.ALL_SHIELDS}
        self.assertEqual(core.static_bounds(own, enemy, m), (.2, .2))
        m.pop(("a", "x", (1, 0)))
        self.assertIsNone(core.static_bounds(own, enemy, m))
        self.assertNotIn("probability", core.EVALUATION_VERSION)

    def test_build_respects_locks_and_clause(self):
        own = list("abcdefg")
        opponents = ["x"]
        mat = {(a, "x", (2, 2)): 550 for a in own}
        clause = {a: a for a in own}
        clause["g"] = "a"
        r = PartyBuilder._build_legal(own, opponents, mat, {"x": 1},
                                      ["a"], clause, {"beam_width": 8})
        self.assertIn("a", r["roster"])
        self.assertNotIn("g", r["roster"])
        self.assertEqual(len(set(clause[x] for x in r["roster"])), 6)


class PartyStoreTests(unittest.TestCase):
    def test_revision_and_separate_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PartyBuilder(Path(tmp))
            result = store.save_party({"name": "Sample", "members": []})
            self.assertEqual(result["revision"], 1)
            saved = store.get_party(result["id"])
            self.assertEqual(saved["name"], "Sample")
            self.assertEqual(len(store.list_parties()["items"]), 1)
            with self.assertRaisesRegex(RuntimeError, "保存競合"):
                store.save_party({"id": result["id"], "revision": 0,
                                  "name": "Older", "members": []})
            result2 = store.save_party({"id": result["id"], "revision": 1,
                                        "name": "Updated", "members": []})
            self.assertEqual(result2["revision"], 2)
            self.assertEqual(store.get_party(result["id"])["name"], "Updated")


if __name__ == "__main__":
    unittest.main()
