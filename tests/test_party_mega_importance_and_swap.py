import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pvpoke_party_core as core
import pvpoke_party_ui
from pvpoke_party_backend import PartyBuilder


class PartyMegaImportanceAndSwapTests(unittest.TestCase):
    def test_compare_single_swap_covers_all_shields_and_deltas(self):
        roster = ["a", "b", "c", "d", "e", "sableye"]
        opponents = ["opp1", "opp2"]
        weights = {"opp1": 0.6, "opp2": 0.4}
        matrix = {}
        for shield in core.ALL_SHIELDS:
            for member in roster:
                matrix[(member, "opp1", shield)] = 420
                matrix[(member, "opp2", shield)] = 560
            # mega_sableye flips opp1 in 2-2 and 1-1, loses opp2 in 0-0
            matrix[("sableye_mega", "opp1", shield)] = 650 if shield in ((2, 2), (1, 1)) else 440
            matrix[("sableye_mega", "opp2", shield)] = 430 if shield == (0, 0) else 560

        res = core.compare_single_swap(
            roster, 5, "sableye_mega", opponents, matrix, weights,
            display_targets=["opp1", "opp2"],
        )
        self.assertEqual(res["slot"], 5)
        self.assertEqual(res["old"], "sableye")
        self.assertEqual(res["new"], "sableye_mega")
        self.assertEqual(len(res["by_shield"]), len(core.ALL_SHIELDS))

        s22 = res["by_shield"]["2-2"]
        self.assertGreater(s22["coverage_delta"], 0)
        self.assertLess(s22["severity_delta"], 0)
        self.assertEqual(s22["benefit_count"], 1)
        self.assertEqual(s22["benefits"][0]["opponent"], "opp1")
        self.assertEqual(len(s22["before_heatmap"]), 2)
        self.assertEqual(len(s22["after_heatmap"]), 2)

        s00 = res["by_shield"]["0-0"]
        self.assertEqual(s00["coverage_delta"], 0)
        self.assertLess(s00["severity_delta"], 0)
        self.assertEqual(s00["cost_count"], 1)
        self.assertEqual(s00["costs"][0]["opponent"], "opp2")

        with self.assertRaises(ValueError):
            core.compare_single_swap(roster, 6, "sableye_mega", opponents, matrix, weights)

    def test_evaluate_mega_importance_computes_index_and_unique_wins(self):
        roster = ["a", "b", "c", "d", "e", "sableye_mega"]
        opponents = ["opp1", "opp2", "opp3"]
        weights = {"opp1": 0.5, "opp2": 0.3, "opp3": 0.2}
        matrix = {}
        for shield in ((2, 2), (1, 1), (0, 0)):
            for m in ("a", "b", "c", "d", "e"):
                for opp in opponents:
                    matrix[(m, opp, shield)] = 430
            # normal & shadow lose opp1 and opp2; mega wins both
            matrix[("sableye", "opp1", shield)] = 420
            matrix[("sableye", "opp2", shield)] = 460
            matrix[("sableye", "opp3", shield)] = 580
            matrix[("sableye_shadow", "opp1", shield)] = 440
            matrix[("sableye_shadow", "opp2", shield)] = 480
            matrix[("sableye_shadow", "opp3", shield)] = 540
            matrix[("sableye_mega", "opp1", shield)] = 640
            matrix[("sableye_mega", "opp2", shield)] = 610
            matrix[("sableye_mega", "opp3", shield)] = 600

        variants = {
            5: {
                "normal": "sableye",
                "shadow": "sableye_shadow",
                "mega": "sableye_mega",
                "active_kind": "mega",
            }
        }
        imp = core.evaluate_mega_importance(
            roster, variants, opponents, matrix, weights,
            mega_policy={"max_megas_in_three": 1},
        )
        self.assertTrue(imp["rule_allowed"])
        self.assertEqual(len(imp["items"]), 1)
        item = imp["items"][0]
        self.assertEqual(item["unique_mega_win_count"], 2)
        self.assertEqual([w["opponent"] for w in item["unique_mega_wins"]], ["opp1", "opp2"])
        self.assertGreater(item["party_contribution"]["coverage_gain"], 0)
        self.assertGreater(item["party_contribution"]["severity_reduction"], 0)
        self.assertGreaterEqual(item["importance_index"], 75.0)
        self.assertEqual(item["tier"], "必須級")

        disallowed = core.evaluate_mega_importance(
            roster, variants, opponents, matrix, weights,
            mega_policy={"max_megas_in_three": 0},
        )
        self.assertFalse(disallowed["rule_allowed"])
        self.assertFalse(disallowed["items"][0]["rule_allowed"])

    def test_backend_compare_swap_and_mega_importance_with_mock_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            store = PartyBuilder(work)
            catalog = {
                "azumarill": {"fastMoves": ["BUBBLE"], "chargedMoves": ["ICE_BEAM", "PLAY_ROUGH"], "defaultMoves": ["BUBBLE", "ICE_BEAM", "PLAY_ROUGH"]},
                "clodsire": {"fastMoves": ["POISON_STING"], "chargedMoves": ["STONE_EDGE", "EARTHQUAKE"], "defaultMoves": ["POISON_STING", "STONE_EDGE", "EARTHQUAKE"]},
                "skarmory": {"fastMoves": ["STEEL_WING"], "chargedMoves": ["SKY_ATTACK", "BRAVE_BIRD"], "defaultMoves": ["STEEL_WING", "SKY_ATTACK", "BRAVE_BIRD"]},
                "annihilape": {"fastMoves": ["COUNTER"], "chargedMoves": ["NIGHT_SLASH", "SHADOW_BALL"], "defaultMoves": ["COUNTER", "NIGHT_SLASH", "SHADOW_BALL"]},
                "lanturn": {"fastMoves": ["SPARK"], "chargedMoves": ["SURF", "THUNDERBOLT"], "defaultMoves": ["SPARK", "SURF", "THUNDERBOLT"]},
                "sableye": {"fastMoves": ["SHADOW_CLAW"], "chargedMoves": ["FOUL_PLAY", "RETURN"], "defaultMoves": ["SHADOW_CLAW", "FOUL_PLAY", "RETURN"]},
                "sableye_shadow": {"fastMoves": ["SHADOW_CLAW"], "chargedMoves": ["FOUL_PLAY", "POWER_GEM"], "defaultMoves": ["SHADOW_CLAW", "FOUL_PLAY", "POWER_GEM"]},
                "sableye_mega": {"fastMoves": ["SHADOW_CLAW"], "chargedMoves": ["FOUL_PLAY", "DAZZLING_GLEAM"], "defaultMoves": ["SHADOW_CLAW", "FOUL_PLAY", "DAZZLING_GLEAM"], "tags": ["mega"]},
            }
            species = {
                sid: {
                    "speciesId": sid,
                    "dex": 302 if sid.startswith("sableye") else idx + 1,
                    "baseStats": {"atk": 150, "def": 150, "hp": 150},
                    "defaultIVs": {"cp1500": [40, 0, 15, 15]},
                    "fastMoves": info["fastMoves"],
                    "chargedMoves": info["chargedMoves"],
                    **({"tags": info["tags"]} if "tags" in info else {}),
                }
                for idx, (sid, info) in enumerate(catalog.items())
            }
            cpms = [0.5] * 100
            meta_csv = work / "meta.csv"
            meta_csv.write_text("clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE\nazumarill,BUBBLE,ICE_BEAM,PLAY_ROUGH\n", encoding="utf-8")

            class FakeEngine:
                CP_CAP = 1500
                MAX_LEVEL = 50
                HEADER = ["species", "fast", "charged1", "charged2", "atk", "def", "hp"]
                DATA = work

                @staticmethod
                def optimize(rows, *_args):
                    out = []
                    for r in rows:
                        out.append({
                            "species": r["species"],
                            "fast": r["fast"],
                            "charged1": r["charged1"],
                            "charged2": r["charged2"],
                            "atk": int(r["atk"]),
                            "def": int(r["def"]),
                            "hp": int(r["hp"]),
                            "cp": 1498,
                            "level": 40.0,
                        })
                    return out

            class FakeClient:
                def __init__(self, **_kwargs):
                    pass

                def simulate(self, own, opp, shield):
                    table = [[None] + [q["id"] for q in opp]]
                    for p in own:
                        row = [p["id"]]
                        for q in opp:
                            if p["species"] == "sableye_mega":
                                row.append(640 if shield == (2, 2) else 560)
                            elif p["species"] == "sableye":
                                row.append(430)
                            else:
                                row.append(480)
                        table.append(row)
                    return table

                def close(self):
                    pass

            members = [
                {"species": sid, "fast": catalog[sid]["fastMoves"][0],
                 "charged1": catalog[sid]["chargedMoves"][0], "charged2": catalog[sid]["chargedMoves"][1],
                 "atk": 0, "def": 15, "hp": 15}
                for sid in ("azumarill", "clodsire", "skarmory", "annihilape", "lanturn", "sableye")
            ]
            replacement = {
                "species": "sableye_mega",
                "fast": "SHADOW_CLAW",
                "charged1": "FOUL_PLAY",
                "charged2": "DAZZLING_GLEAM",
                "atk": 0, "def": 15, "hp": 15,
            }
            args_base = {
                "members": members,
                "meta_preset_id": "legacy",
                "ruleset": "great_mega",
                "mega_rules": {"cup_id": "great_mega"},
            }
            with patch("pvpoke_party_backend.presets.snapshot", return_value=(meta_csv, {"id": "legacy", "name": "test", "sha256": "abc"})), \
                 patch("pvpoke_party_backend.calculation_version", return_value="v-test"), \
                 patch("pvpoke_party_backend.DirectMatrixClient", FakeClient):
                swap_res = store.compare_swap(
                    {**args_base, "slot": 5, "replacement": replacement},
                    catalog=catalog, species=species, cpms=cpms, engine=FakeEngine, work=work,
                )
                self.assertEqual(swap_res["kind"], "swap_comparison")
                self.assertGreater(swap_res["comparison"]["by_shield"]["2-2"]["coverage_delta"], 0)
                self.assertGreater(swap_res["comparison"]["by_shield"]["0-0"]["coverage_delta"], 0)

                imp_res = store.mega_importance(
                    args_base,
                    catalog=catalog, species=species, cpms=cpms, engine=FakeEngine, work=work,
                )
                self.assertEqual(imp_res["kind"], "mega_importance")
                self.assertEqual(len(imp_res["mega_importance"]["items"]), 1)
                self.assertEqual(imp_res["mega_importance"]["items"][0]["unique_mega_win_count"], 2)

    def test_mega_importance_shared_movesets_and_form_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            store = PartyBuilder(work)
            catalog = {
                "azumarill": {"fastMoves": ["BUBBLE"], "chargedMoves": ["ICE_BEAM", "PLAY_ROUGH"], "default_moves": {"fast": "BUBBLE", "charged1": "ICE_BEAM", "charged2": "PLAY_ROUGH"}},
                "clodsire": {"fastMoves": ["POISON_STING"], "chargedMoves": ["STONE_EDGE", "EARTHQUAKE"], "default_moves": {"fast": "POISON_STING", "charged1": "STONE_EDGE", "charged2": "EARTHQUAKE"}},
                "skarmory": {"fastMoves": ["STEEL_WING"], "chargedMoves": ["SKY_ATTACK", "BRAVE_BIRD"], "default_moves": {"fast": "STEEL_WING", "charged1": "SKY_ATTACK", "charged2": "BRAVE_BIRD"}},
                "annihilape": {"fastMoves": ["COUNTER"], "chargedMoves": ["NIGHT_SLASH", "SHADOW_BALL"], "default_moves": {"fast": "COUNTER", "charged1": "NIGHT_SLASH", "charged2": "SHADOW_BALL"}},
                "lanturn": {"fastMoves": ["SPARK"], "chargedMoves": ["SURF", "THUNDERBOLT"], "default_moves": {"fast": "SPARK", "charged1": "SURF", "charged2": "THUNDERBOLT"}},
                "sableye": {"fastMoves": ["SHADOW_CLAW", "FEINT_ATTACK"], "chargedMoves": ["FOUL_PLAY", "RETURN", "POWER_GEM"], "default_moves": {"fast": "SHADOW_CLAW", "charged1": "FOUL_PLAY", "charged2": "RETURN"}},
                "sableye_shadow": {"fastMoves": ["SHADOW_CLAW"], "chargedMoves": ["FOUL_PLAY", "POWER_GEM"], "default_moves": {"fast": "SHADOW_CLAW", "charged1": "FOUL_PLAY", "charged2": "POWER_GEM"}},
                "sableye_mega": {"fastMoves": ["SHADOW_CLAW", "FEINT_ATTACK"], "chargedMoves": ["FOUL_PLAY", "DAZZLING_GLEAM", "POWER_GEM"], "default_moves": {"fast": "SHADOW_CLAW", "charged1": "FOUL_PLAY", "charged2": "DAZZLING_GLEAM"}, "tags": ["mega"]},
            }
            species = {
                sid: {
                    "speciesId": sid,
                    "dex": 302 if sid.startswith("sableye") else idx + 1,
                    "baseStats": {"atk": 150, "def": 150, "hp": 150},
                    "defaultIVs": {"cp1500": [40, 0, 15, 15]},
                    "fastMoves": info["fastMoves"],
                    "chargedMoves": info["chargedMoves"],
                    **({"tags": info["tags"]} if "tags" in info else {}),
                }
                for idx, (sid, info) in enumerate(catalog.items())
            }
            cpms = [0.5] * 100
            meta_csv = work / "meta.csv"
            meta_csv.write_text("clodsire,POISON_STING,STONE_EDGE,EARTHQUAKE\n", encoding="utf-8")

            class FakeEngine:
                CP_CAP = 1500
                MAX_LEVEL = 50
                HEADER = ["species", "fast", "charged1", "charged2", "atk", "def", "hp"]
                DATA = work

                @staticmethod
                def optimize(rows, *_args):
                    return [{
                        "species": r["species"], "fast": r["fast"],
                        "charged1": r["charged1"], "charged2": r["charged2"],
                        "atk": int(r["atk"]), "def": int(r["def"]), "hp": int(r["hp"]),
                        "cp": 1498, "level": 40.0,
                        **({"mega_level": r["mega_level"]} if "mega_level" in r else {}),
                    } for r in rows]

            class FakeClient:
                def __init__(self, **_kwargs):
                    pass

                def simulate(self, own, opp, shield):
                    table = [[None] + [q["id"] for q in opp]]
                    for p in own:
                        rating = 650 if (p["species"] == "sableye_mega" and p["charged2"] == "POWER_GEM") else 490
                        table.append([p["id"]] + [rating for _ in opp])
                    return table

                def close(self):
                    pass

            members = [
                {"species": sid, "fast": catalog[sid]["default_moves"]["fast"],
                 "charged1": catalog[sid]["default_moves"]["charged1"], "charged2": catalog[sid]["default_moves"]["charged2"],
                 "atk": 0, "def": 15, "hp": 15}
                for sid in ("azumarill", "clodsire", "skarmory", "annihilape", "lanturn", "sableye")
            ]

            with patch("pvpoke_party_backend.presets.snapshot", return_value=(meta_csv, {"id": "legacy", "name": "test", "sha256": "abc"})), \
                 patch("pvpoke_party_backend.calculation_version", return_value="v-test"), \
                 patch("pvpoke_party_backend.DirectMatrixClient", FakeClient):
                # 1. Shared moveset for sableye_mega overrides template/catalog defaults.
                shared_res = store.mega_importance(
                    {
                        "members": members,
                        "meta_preset_id": "legacy",
                        "ruleset": "great_mega",
                        "mega_rules": {"cup_id": "great_mega"},
                        "species_movesets": {
                            "sableye_mega": {"fast": "FEINT_ATTACK", "charged1": "FOUL_PLAY", "charged2": "POWER_GEM", "mega_level": 4}
                        },
                    },
                    catalog=catalog, species=species, cpms=cpms, engine=FakeEngine, work=work,
                )
                item = shared_res["mega_importance"]["items"][0]
                mega_id = item["forms"]["mega"]["id"]
                self.assertEqual(shared_res["labels"][mega_id]["moves"], ["FEINT_ATTACK", "FOUL_PLAY", "POWER_GEM"])
                self.assertEqual(shared_res["labels"][mega_id]["mega_level"], 4)
                self.assertEqual(item["move_sources"]["normal"], "party_slot")
                self.assertEqual(item["move_sources"]["mega"], "shared_moveset")
                self.assertEqual(item["unique_mega_win_count"], 1)

                # 2. Explicit form_overrides takes highest priority even over shared_movesets and party_slot.
                ovr_res = store.mega_importance(
                    {
                        "members": members,
                        "meta_preset_id": "legacy",
                        "ruleset": "great_mega",
                        "mega_rules": {"cup_id": "great_mega"},
                        "species_movesets": {
                            "sableye_mega": {"fast": "FEINT_ATTACK", "charged1": "FOUL_PLAY", "charged2": "POWER_GEM"}
                        },
                        "form_overrides": {
                            "5": {
                                "mega": {"fast": "SHADOW_CLAW", "charged1": "DAZZLING_GLEAM", "charged2": "FOUL_PLAY", "mega_level": 2},
                                "normal": {"fast": "FEINT_ATTACK", "charged1": "FOUL_PLAY", "charged2": "POWER_GEM"},
                            }
                        },
                    },
                    catalog=catalog, species=species, cpms=cpms, engine=FakeEngine, work=work,
                )
                ovr_item = ovr_res["mega_importance"]["items"][0]
                ovr_mega = ovr_item["forms"]["mega"]["id"]
                ovr_norm = ovr_item["forms"]["normal"]["id"]
                self.assertEqual(ovr_res["labels"][ovr_mega]["moves"], ["SHADOW_CLAW", "DAZZLING_GLEAM", "FOUL_PLAY"])
                self.assertEqual(ovr_res["labels"][ovr_mega]["mega_level"], 2)
                self.assertEqual(ovr_res["labels"][ovr_norm]["moves"], ["FEINT_ATTACK", "FOUL_PLAY", "POWER_GEM"])
                self.assertEqual(ovr_item["move_sources"]["mega"], "override")
                self.assertEqual(ovr_item["move_sources"]["normal"], "override")
                self.assertEqual(ovr_item["unique_mega_win_count"], 0)

    def test_mega_importance_captures_multi_shield_d1_and_rating_dominance(self):
        roster = ["a", "b", "c", "d", "e", "charizard_mega_y"]
        opponents = ["opp1", "opp2"]
        weights = {"opp1": 0.5, "opp2": 0.5}
        matrix = {}
        for shield in ((2, 2), (1, 1), (0, 0)):
            for m in ("a", "b", "c", "d", "e"):
                # Member 'a' already covers opp1 (so d1=1 without Mega on opp1), nobody covers opp2 in 1-1/0-0
                matrix[(m, "opp1", shield)] = 560 if m == "a" else 420
                matrix[(m, "opp2", shield)] = 560 if (m == "a" and shield == (2, 2)) else 420
            # Normal Charizard wins opp1 barely in 2-2, loses opp2 in 1-1/0-0
            matrix[("charizard", "opp1", shield)] = 460
            matrix[("charizard", "opp2", shield)] = 560 if shield == (2, 2) else 440
            # Mega Charizard dominates opp1 (reducing D1!) and wins opp2 across 1-1 and 0-0
            matrix[("charizard_mega_y", "opp1", shield)] = 700
            matrix[("charizard_mega_y", "opp2", shield)] = 680 if shield != (2, 2) else 720

        variants = {
            5: {
                "normal": "charizard",
                "mega": "charizard_mega_y",
                "active_kind": "mega",
            }
        }
        imp = core.evaluate_mega_importance(
            roster, variants, opponents, matrix, weights,
            mega_policy={"max_megas_in_three": 1},
        )
        item = imp["items"][0]
        # 2-2 unique wins is 1 (opp1), multi-shield unique weight captures 1-1/0-0 opp2 as well
        self.assertGreater(item["score_breakdown"]["weighted_d1_reduction"], 0)
        self.assertGreater(item["score_breakdown"]["weighted_rating_lift"], 100.0)
        self.assertGreater(item["score_breakdown"]["party_impact"], 0)
        self.assertGreater(item["score_breakdown"]["solo_lift"], 10.0)
        self.assertGreaterEqual(item["importance_index"], 50.0)
        self.assertIn("2-2", item["party_contribution"]["by_shield"])
        self.assertIn("1-1", item["party_contribution"]["by_shield"])
        self.assertIn("0-0", item["party_contribution"]["by_shield"])

    def test_ui_contains_mega_importance_and_manual_swap_controls(self):
        import pvpoke_app_ui
        for token in (
            "megaImportanceSection",
            "manualSwapSection",
            "manualSwapMovesWrap",
            "runMegaImportance",
            "runManualSwap",
            "party/compare-swap",
            "party/mega-importance",
            "mega-moves-editor",
            "calcDock",
            "calcDockMeta",
            "calcDockBar",
            "dockStart",
            "mega-diag-list",
        ):
            self.assertIn(token, pvpoke_party_ui.HTML)
        for token in (
            "calcDock",
            "calcDockMeta",
            "calcDockBar",
            "appDockStart",
            "calcDockJump",
        ):
            self.assertIn(token, pvpoke_app_ui.HTML)


if __name__ == "__main__":
    unittest.main()

