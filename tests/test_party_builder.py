import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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



class PartyMetaShadowIdTests(unittest.TestCase):
    """PvPoke export spellings must become valid internal battle IDs."""

    def setUp(self):
        self.catalog = {
            "feraligatr": {"fastMoves": ["SHADOW_CLAW"],
                           "chargedMoves": ["HYDRO_CANNON", "ICE_BEAM"]},
            "feraligatr_shadow": {"fastMoves": ["SHADOW_CLAW"],
                                  "chargedMoves": ["HYDRO_CANNON", "ICE_BEAM"]},
            "corsola_galarian": {"fastMoves": ["ASTONISH"],
                                 "chargedMoves": ["NIGHT_SHADE", "POWER_GEM"]},
        }
        self.species = {
            "feraligatr": {"dex": 160},
            "feraligatr_shadow": {"dex": 160},
            "corsola_galarian": {"dex": 222},
        }
        self.engine = SimpleNamespace(
            HEADER=["species", "fast", "charged1", "charged2", "atk", "def", "hp"],
            CP_CAP=1500, MAX_LEVEL=50,
            optimize=lambda rows, species, cpms, label: [
                {**row, "level": 20.0, "cp": 1481} for row in rows],
        )

    def normalize(self, sid, fast="SHADOW_CLAW",
                  charged1="HYDRO_CANNON", charged2="ICE_BEAM"):
        return PartyBuilder._normalize(
            [{"species": sid, "fast": fast, "charged1": charged1,
              "charged2": charged2}],
            self.catalog, self.species, [], self.engine, "メタ")[0]

    def test_pvpoke_export_shadow_suffix_uses_internal_species_id(self):
        with patch("pvpoke_party_backend.iv_modes.select_opponent_ivs",
                   return_value=(0, 15, 15, 1)):
            exported = self.normalize("FERALIGATR_SHADOW-shadow")
            native = self.normalize("feraligatr_shadow")
            normal = self.normalize("feraligatr")

        self.assertEqual(exported["species"], "feraligatr_shadow")
        self.assertEqual(exported["meta_group_id"], "feraligatr_shadow")
        self.assertEqual(exported["roster_clause_id"], "160")
        self.assertEqual(exported["id"], native["id"])
        self.assertNotEqual(exported["id"], normal["id"])

    def test_other_forms_and_unknown_ids_remain_strictly_validated(self):
        with patch("pvpoke_party_backend.iv_modes.select_opponent_ivs",
                   return_value=(0, 15, 15, 1)):
            galar = self.normalize("corsola_galarian", "ASTONISH",
                                   "NIGHT_SHADE", "POWER_GEM")
            self.assertEqual(galar["species"], "corsola_galarian")
            for bad in ("feraligatr-shadow",
                        "feraligatr_shadow-shadow-shadow",
                        "unknown_shadow-shadow"):
                with self.subTest(species=bad), self.assertRaisesRegex(
                        ValueError, "未登録ポケモン"):
                    self.normalize(bad)



    def test_recommendations_respect_locks_and_species_and_improvement(self):
        roster = list("abcdef")
        meta = ["x", "y"]
        matrix = {(a, x, (2, 2)): 420 for a in roster + ["g", "h"] for x in meta}
        matrix[("a", "x", (2, 2))] = 600
        matrix[("b", "y", (2, 2))] = 600
        matrix[("g", "x", (2, 2))] = 630
        matrix[("g", "y", (2, 2))] = 630
        # h is the same species as a, so it can only replace a, not another slot.
        matrix[("h", "x", (2, 2))] = 610
        matrix[("h", "y", (2, 2))] = 610
        clause = {a: a for a in roster + ["g"]}
        clause["h"] = "a"
        result = core.recommend_single_swaps(roster, ["g", "h"], meta, matrix,
                    {"x": .5, "y": .5}, clause, locked_slots=[2])
        self.assertEqual(result["status"], "improved")
        self.assertTrue(result["items"])
        self.assertTrue(all(x["slot"] != 2 for x in result["items"]))
        self.assertTrue(all(x["in"] != "h" or x["out"] == "a" for x in result["items"]))
        self.assertTrue(all(x["after"]["d1"] <= result["baseline"]["d1"]
                            for x in result["items"]))

    def test_recommendations_do_not_promote_missing_cells_or_worse_teams(self):
        roster = list("abcdef")
        meta = ["x"]
        matrix = {(a, "x", (2, 2)): 600 for a in roster}
        matrix[("g", "x", (2, 2))] = 100
        clause = {a: a for a in roster + ["g", "h"]}
        no_change = core.recommend_single_swaps(roster, ["g"], meta, matrix,
                                                 {"x": 1}, clause)
        self.assertEqual(no_change["status"], "no_improvement")
        self.assertEqual(no_change["items"], [])
        # h's missing cell is unknown, not treated as a defeat or a success.
        missing = core.recommend_single_swaps(roster, ["h"], meta, matrix,
                                               {"x": 1}, clause)
        self.assertEqual(missing["items"], [])
        incomplete = core.recommend_single_swaps(roster, ["h"], meta, {},
                                                  {"x": 1}, clause)
        self.assertEqual(incomplete["status"], "unknown")

class PartyStoreTests(unittest.TestCase):
    def test_saved_parties_keep_own_enemy_and_strategy_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PartyBuilder(Path(tmp))
            own_a = [{"species": "azumarill", "fast": "BUBBLE",
                      "charged1": "ICE_BEAM", "charged2": "PLAY_ROUGH",
                      "atk": 0, "def": 15, "hp": 15}]
            own_b = [{"species": "clodsire", "fast": "POISON_STING",
                      "charged1": "STONE_EDGE", "charged2": "EARTHQUAKE",
                      "atk": 2, "def": 15, "hp": 12}]
            opp_a = [{"species": "corsola_galarian", "fast": "ASTONISH",
                      "charged1": "NIGHT_SHADE", "charged2": "POWER_GEM",
                      "atk": 5, "def": 10, "hp": 11}]
            opp_b = [{"species": "quagsire", "fast": "MUD_SHOT",
                      "charged1": "AQUA_TAIL", "charged2": "STONE_EDGE",
                      "atk": 3, "def": 14, "hp": 14}]
            a = store.save_party({"name": "大会A", "members": own_a,
                "opponents": opp_a, "strategy": {"enemy_csv": "corsola_galarian,ASTONISH,NIGHT_SHADE,POWER_GEM", "lead_index": 1}})
            b = store.save_party({"name": "大会B", "members": own_b,
                "opponents": opp_b, "strategy": {"enemy_csv": "quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE", "lead_index": 2}})
            self.assertNotEqual(a["id"], b["id"])
            self.assertEqual(len(store.list_parties()["items"]), 2)
            for id_, own, opp, lead in ((a["id"], own_a, opp_a, 1),
                                         (b["id"], own_b, opp_b, 2)):
                with self.subTest(party=id_):
                    saved = PartyBuilder(Path(tmp)).get_party(id_)
                    self.assertEqual(saved["members"], own)
                    self.assertEqual(saved["opponents"], opp)
                    self.assertEqual(saved["strategy"]["lead_index"], lead)
            updated = store.save_party({"id": b["id"], "revision": 1,
                "name": "大会B改", "members": own_b, "opponents": opp_a})
            self.assertEqual(updated["revision"], 2)
            self.assertEqual(store.get_party(a["id"])["opponents"], opp_a)
            self.assertEqual(store.get_party(b["id"])["opponents"], opp_a)

    def test_legacy_party_without_opponents_is_still_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PartyBuilder(Path(tmp))
            created = store.save_party({"name": "旧保存", "members": []})
            party = store.get_party(created["id"])
            self.assertIsNone(party["opponents"])
            self.assertIsNone(party["strategy"])

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
