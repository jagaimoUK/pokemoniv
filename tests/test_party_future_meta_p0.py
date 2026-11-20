"""Comprehensive P0 verification tests for Future Meta & Unified Auto-Complete (Issue #125)."""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("PVP_ENGINE", "direct")
import pvpoke_batch_v2 as engine
import pvpoke_future_meta as future_meta
import pvpoke_meta_live as meta_live
import pvpoke_party_core as core
from pvpoke_party_backend import PartyBuilder

ROOT = Path(__file__).resolve().parents[1]
GM_FIXTURE = json.loads((ROOT / "tests/fixtures/strategy_gamemaster.json").read_text())
ROWS_FIXTURE = json.loads((ROOT / "tests/fixtures/strategy_rows.json").read_text())


def _build_fixture_env(work: Path, include_mimikyu: bool = False):
    gm = json.loads(json.dumps(GM_FIXTURE))
    if include_mimikyu:
        gm["pokemon"].append({
            "dex": 778,
            "speciesId": "mimikyu",
            "speciesName": "Mimikyu",
            "baseStats": {"atk": 177, "def": 199, "hp": 146},
            "types": ["ghost", "fairy"],
            "fastMoves": ["SHADOW_CLAW", "CHARM"],
            "chargedMoves": ["SHADOW_BALL", "PLAY_ROUGH"],
        })
        gm["pokemon"].append({
            "dex": 774,
            "speciesId": "minior_meteor",
            "speciesName": "Minior (Meteor)",
            "baseStats": {"atk": 115, "def": 181, "hp": 155},
            "types": ["rock", "flying"],
            "fastMoves": ["TACKLE", "ROLLOUT"],
            "chargedMoves": ["ANCIENT_POWER", "POWER_GEM"],
        })
    (work / "gamemaster.json").write_text(json.dumps(gm))
    js = (ROOT / "vendor/pvpoke/src/js/pokemon/Pokemon.js").read_text()
    (work / "Pokemon.js").write_text(js)
    cpms = [float(x) for x in re.search(r"var\s+cpms\s*=\s*\[([^\]]+)\]", js, re.S)[1].split(",") if x.strip()]
    species = {p["speciesId"]: p for p in gm["pokemon"]}
    catalog = {
        sid: {
            "name": p["speciesName"],
            "fastMoves": list(p["fastMoves"]),
            "chargedMoves": list(p["chargedMoves"]),
            "default_moves": {
                "fast": p["fastMoves"][0],
                "charged1": p["chargedMoves"][0],
                "charged2": p["chargedMoves"][1] if len(p["chargedMoves"]) > 1 else p["chargedMoves"][0],
            },
        }
        for sid, p in species.items()
    }
    return gm, species, catalog, cpms


def _synthetic_meta_species(gm_species, count=10):
    """Build deterministic legal rows from the fixture gamemaster (unique dexes)."""
    rows = []
    seen_dex = set()
    for row in ROWS_FIXTURE:
        sid = row["species"]
        if sid in gm_species and gm_species[sid].get("dex") not in seen_dex:
            seen_dex.add(gm_species[sid].get("dex"))
            rows.append(dict(row))
    for sid, p in gm_species.items():
        if len(rows) >= count:
            break
        if p.get("dex") in seen_dex or len(p.get("fastMoves", [])) < 1 or len(p.get("chargedMoves", [])) < 2:
            continue
        if core.unverified_mechanic_reason(sid):
            continue
        seen_dex.add(p.get("dex"))
        rows.append({
            "species": sid,
            "fast": p["fastMoves"][0],
            "charged1": p["chargedMoves"][0],
            "charged2": p["chargedMoves"][1],
            "atk": 0, "def": 15, "hp": 15,
        })
    return rows


class ObservationAndFutureMetaContractTests(unittest.TestCase):
    def test_observations_preserve_exact_periods_non_summable_and_unconfirmed_separation(self):
        snap = future_meta.observation_snapshot()
        self.assertTrue(snap["metadata"]["overlapping_periods"])
        self.assertTrue(snap["metadata"]["naive_summation_prohibited"])
        self.assertTrue(snap["metadata"]["outside_top12_is_not_zero"])
        self.assertEqual(snap["metadata"]["cooccurrence_status"], "unavailable_without_raw_6mon_rosters")
        self.assertEqual(len(snap["periods"]), 5)
        self.assertEqual(snap["periods"][0]["teams"], 475)
        self.assertEqual(snap["periods"][-1]["teams"], 200)
        by_sp = {s["species"]: s["rates"] for s in snap["series"]}
        self.assertEqual(by_sp["melmetal"], [50, 55, 34, 43, 46])
        self.assertEqual(by_sp["dunsparce"], [None, None, 31, 39, 36])
        machamp = snap["unconfirmed_observations"][0]
        self.assertEqual(machamp["species"], "machamp_shadow")
        self.assertIsNone(machamp["adoption_rate"])
        self.assertEqual(machamp["status"], "hypothesis_unconfirmed")

    def test_scenario_validation_blocks_duplicate_current_and_excess_chain_steps(self):
        with self.assertRaisesRegex(ValueError, "現行メタ"):
            future_meta.validate_scenario_payload({"name": "現行環境維持"})
        with self.assertRaisesRegex(ValueError, "最大3段階"):
            future_meta.validate_scenario_payload({
                "name": "独自予測テスト",
                "chain_steps": [{"title": f"s{i}", "detail": "d"} for i in range(4)],
            })
        # Effective weights replace directly without double-counting.
        sc = {"weights": {"melmetal": 4.0, "quagsire": 2.0}}
        merged = future_meta.resolve_effective_weights(sc, {"melmetal": 5.0})
        self.assertEqual(merged, {"melmetal": 5.0, "quagsire": 2.0})


class CoreAutocompleteAndTriplesTests(unittest.TestCase):
    def test_autocomplete_0_1_5_6_and_all_locked_with_zero_stay_penalty_and_3plus_swaps(self):
        # Construct 10 distinct species A..J where E,F,G,H,I,J dominate opponents O1..O4,
        # while A,B,C,D lose badly to all opponents.
        opps = ["o1", "o2", "o3", "o4"]
        weights = {o: 0.25 for o in opps}
        weak = ["a", "b", "c", "d"]
        strong = ["e", "f", "g", "h", "i", "j"]
        all_cands = weak + strong
        clause = {x: f"dex_{x}" for x in all_cands}
        matrix = {}
        for x in weak:
            for o in opps:
                for sh in core.ALL_SHIELDS:
                    matrix[(x, o, sh)] = 300
        for idx, x in enumerate(strong):
            for j, o in enumerate(opps):
                for sh in core.ALL_SHIELDS:
                    matrix[(x, o, sh)] = 650 if (idx + j) % 2 == 0 else 560

        # 0 members -> proposes 6 strong members.
        r0 = core.autocomplete_search([], all_cands, opps, matrix, weights, clause)
        self.assertEqual(len(r0["roster"]), 6)
        self.assertEqual(set(r0["roster"]), set(strong))

        # 1 locked weak member -> preserves locked member, fills 5 best remaining.
        r1 = core.autocomplete_search(["a"], all_cands, opps, matrix, weights, clause,
                                      initial_slots=["a"], locked_slots=[0])
        self.assertEqual(r1["roster"][0], "a")
        self.assertEqual(len(set(r1["roster"])), 6)
        self.assertTrue(set(r1["roster"][1:]).issubset(set(strong)))

        # 5 entered (only slot 0 locked) -> replaces all 4 unlocked weak/suboptimal freely.
        r5 = core.autocomplete_search(["a"], all_cands, opps, matrix, weights, clause,
                                      initial_slots=["a", "b", "c", "d", "e"], locked_slots=[0])
        self.assertEqual(r5["roster"][0], "a")
        self.assertTrue(all(x in strong for x in r5["roster"][1:]))

        # 6 entered with 1 locked ("a") and 5 unlocked ("b","c","d","e","f") -> replaces >= 3 unlocked ("b","c","d")!
        init6 = ["a", "b", "c", "d", "e", "f"]
        r6 = core.autocomplete_search(["a"], all_cands, opps, matrix, weights, clause,
                                      initial_slots=init6, locked_slots=[0])
        self.assertEqual(r6["status"], "improved")
        self.assertEqual(r6["roster"][0], "a")
        self.assertGreaterEqual(r6["finalists"][0]["replaced_count"], 3)
        self.assertTrue(all(x not in ("b", "c", "d") for x in r6["roster"]))

        # 6 ALL locked -> no swaps performed!
        r_locked = core.autocomplete_search(init6, all_cands, opps, matrix, weights, clause,
                                            initial_slots=init6, locked_slots=list(range(6)))
        self.assertEqual(r_locked["status"], "all_locked")
        self.assertEqual(r_locked["roster"], init6)
        self.assertEqual(r_locked["finalists"][0]["replaced_count"], 0)

    def test_evaluate_all_20_triples_and_unfavorable_explanations(self):
        roster = ["m1", "m2", "m3", "m4", "m5", "m6"]
        clause = {m: m for m in roster}
        opps = ["o1", "o2", "o3"]
        weights = {"o1": 0.5, "o2": 0.3, "o3": 0.2}
        matrix = {}
        for m in roster:
            for o in opps:
                for sh in core.ALL_SHIELDS:
                    # m1,m2,m3 beat all; m4,m5,m6 lose to o1.
                    rating = 600 if m in ("m1", "m2", "m3") else (350 if o == "o1" else 560)
                    matrix[(m, o, sh)] = rating
        triples = core.evaluate_all_triples(roster, opps, matrix, weights, clause=clause)
        self.assertEqual(len(triples), 20)
        self.assertEqual(triples[0]["rank"], 1)
        self.assertEqual(set(triples[0]["members"]), {"m1", "m2", "m3"})
        self.assertEqual(set(triples[0]["roles"].values()), {"m1", "m2", "m3"})
        worst = triples[-1]
        self.assertEqual(set(worst["members"]), {"m4", "m5", "m6"})
        self.assertTrue(worst["unfavorable"])
        self.assertTrue(any(r["kind"] == "uncovered_meta" for r in worst["avoid_reasons"]))

    def test_compare_scenarios_returns_average_and_worst_case(self):
        roster = ["m1", "m2", "m3", "m4", "m5", "m6"]
        opps = ["o1", "o2"]
        matrix = {
            **{(m, "o1", (2, 2)): 600 for m in roster},
            **{(m, "o2", (2, 2)): 350 for m in roster},
        }
        cmp = core.compare_scenarios(roster, opps, matrix, [
            {"id": "current", "name": "現行メタ", "weights": {"o1": 0.9, "o2": 0.1}},
            {"id": "future:A", "name": "未来A", "weights": {"o1": 0.2, "o2": 0.8}},
        ])
        self.assertEqual(cmp["count"], 2)
        self.assertAlmostEqual(cmp["average"]["d0"], 0.45, places=4)
        self.assertEqual(cmp["worst_case"]["scenario_id"], "future:A")
        self.assertAlmostEqual(cmp["worst_case"]["summary"]["d0"], 0.8, places=4)


class BackendIntegrationP0Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.gm, self.species, self.catalog, self.cpms = _build_fixture_env(self.work, include_mimikyu=True)
        self.prev_data = engine.DATA
        engine.DATA = self.work
        self.rows = _synthetic_meta_species(self.species, count=9)
        self.assertGreaterEqual(len(self.rows), 7)
        meta_csv = "".join(
            ",".join([r["species"], r["fast"], r["charged1"], r["charged2"]]) + "\n"
            for r in self.rows
        )
        meta_live.sync(self.work, meta_csv, self.species)
        self.builder = PartyBuilder(self.work)

    def tearDown(self):
        engine.DATA = self.prev_data
        self.tmp.cleanup()

    def test_isolated_scenario_weights_never_bleed_and_survive_restart(self):
        s_a = self.builder.save_scenario({
            "name": "未来A（鋼重視）",
            "base_meta_id": "legacy",
            "weights": {"quagsire": 5.0},
            "chain_steps": [{"stage": 1, "kind": "increase", "title": "仮説1", "detail": "詳細"}],
        })
        s_b = self.builder.save_scenario({
            "name": "未来B（ゴースト重視）",
            "base_meta_id": "legacy",
            "weights": {"quagsire": 2.0},
        })
        # Edit Future A scoped weights ONLY.
        self.builder.scoped_weights("scenario:" + s_a["id"], {"quagsire": 10.0})
        # Verify Future B, Current Meta, and legacy meta_weights are completely untouched!
        self.assertEqual(self.builder.get_scenario(s_a["id"])["weights"]["quagsire"], 10.0)
        self.assertEqual(self.builder.get_scenario(s_b["id"])["weights"]["quagsire"], 2.0)
        self.assertEqual(self.builder.scoped_weights("meta:legacy")["weights"], {})
        self.assertEqual(self.builder.meta_weights()["weights"], {})

        # Simulate restart by creating a new PartyBuilder pointing at the same work dir.
        restarted = PartyBuilder(self.work)
        self.assertEqual(restarted.get_scenario(s_a["id"])["weights"]["quagsire"], 10.0)
        self.assertEqual(restarted.get_scenario(s_b["id"])["weights"]["quagsire"], 2.0)

        # Revision conflict protection on scenario update & delete.
        updated = restarted.save_scenario({
            "id": s_a["id"], "revision": s_a["revision"],
            "name": "未来A（更新）", "base_meta_id": "legacy", "weights": {"quagsire": 8.0},
        })
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(RuntimeError):
            restarted.save_scenario({
                "id": s_a["id"], "revision": 1,
                "name": "未来A（競合）", "base_meta_id": "legacy", "weights": {"quagsire": 1.0},
            })
        with self.assertRaises(RuntimeError):
            restarted.delete_scenario(s_a["id"], revision=1)
        deleted = restarted.delete_scenario(s_a["id"], revision=2)
        self.assertTrue(deleted["deleted"])

    def test_owner_isolation_and_party_rename_and_conflict(self):
        p_a = self.builder.save_party({"name": "OwnerA Party", "members": self.rows[:6]}, owner_scope="owner_a")
        p_b = self.builder.save_party({"name": "OwnerB Party", "members": self.rows[:6]}, owner_scope="owner_b")
        self.assertEqual([x["id"] for x in self.builder.list_parties(owner_scope="owner_a")["items"]], [p_a["id"]])
        self.assertEqual([x["id"] for x in self.builder.list_parties(owner_scope="owner_b")["items"]], [p_b["id"]])
        with self.assertRaises(ValueError):
            self.builder.get_party(p_a["id"], owner_scope="owner_b")
        with self.assertRaises(ValueError):
            self.builder.save_party({"id": p_a["id"], "revision": p_a["revision"], "name": "Hijack", "members": []}, owner_scope="owner_b")
        # Rename + revision conflict check.
        renamed = self.builder.rename_party(p_a["id"], "OwnerA Renamed", p_a["revision"], owner_scope="owner_a")
        self.assertEqual(renamed["revision"], 2)
        self.assertEqual(self.builder.get_party(p_a["id"], owner_scope="owner_a")["name"], "OwnerA Renamed")
        with self.assertRaises(RuntimeError):
            self.builder.rename_party(p_a["id"], "Stale", 1, owner_scope="owner_a")
        # Scenario owner isolation.
        sc_a = self.builder.save_scenario({"name": "Private Future", "base_meta_id": "legacy"}, owner_scope="owner_a")
        with self.assertRaises(ValueError):
            self.builder.get_scenario(sc_a["id"], owner_scope="owner_b")

    def test_autocomplete_0_1_5_6_all_locked_cache_reuse_and_mimikyu_unknown(self):
        def fake_sim(self_client, own_chunk, opp_chunk, shield):
            # Deterministic ratings; fail loudly if Mimikyu or Minior is ever sent to simulate!
            for p in own_chunk + opp_chunk:
                if core.unverified_mechanic_reason(p["species"]):
                    raise AssertionError(f"Unverified mechanic species must never be simulated: {p['species']}")
            grid = [[""] + [q["species"] for q in opp_chunk]]
            for p in own_chunk:
                row = [p["species"]]
                for q in opp_chunk:
                    h = int(hashlib.sha256(f"{p['id']}|{q['id']}|{shield}".encode()).hexdigest()[:4], 16)
                    row.append(350 + (h % 350))
                grid.append(row)
            return grid

        with patch("pvpoke_party_backend.DirectMatrixClient.simulate", new=fake_sim), \
             patch("pvpoke_party_backend.DirectMatrixClient.close", return_value=None):
            # 1) 0 members -> 6 new provisional proposals, Mimikyu scenario -> unknown_weight > 0, no crash!
            res0 = self.builder._compute(
                "job0",
                {"mode": "autocomplete", "members": [], "locked_slots": [],
                 "meta_preset_id": "legacy", "scenario_id": "builtin:mimikyu_rise",
                 "compare_scenario_ids": ["current", "builtin:mimikyu_rise", "builtin:mimikyu_counters"]},
                self.catalog, self.species, self.cpms, engine, self.work,
            )
            self.assertEqual(len(res0["roster"]), 6)
            self.assertEqual(len(res0["triples"]), 20)
            self.assertEqual(len(res0["recommended_three"]), 3)
            self.assertGreater(res0["team"]["unknown_weight"], 0)
            self.assertTrue(any(u["species"] == "mimikyu" and u["status"] == "unknown" for u in res0["unverified_mechanics"]))
            self.assertIsNotNone(res0["scenario_comparison"])
            self.assertIn("worst_case", res0["scenario_comparison"])
            self.assertIsNone(res0["refinement"])  # Extra detail is OFF by default!

            # Verify Mimikyu was NEVER written to cells cache.
            with sqlite3.connect(self.builder.path) as db:
                cached_count = db.execute("SELECT count(*) FROM cells").fetchone()[0]
                self.assertGreater(cached_count, 0)

            # 2) 1 member locked with custom IVs -> exact moves & IVs strictly preserved!
            custom_locked = dict(self.rows[0], atk=3, def_=11, hp=14)
            custom_locked = {
                "species": self.rows[0]["species"],
                "fast": self.rows[0]["fast"],
                "charged1": self.rows[0]["charged1"],
                "charged2": self.rows[0]["charged2"],
                "atk": 3, "def": 11, "hp": 14,
            }
            res1 = self.builder._compute(
                "job1",
                {"mode": "autocomplete", "members": [custom_locked], "locked_slots": [0],
                 "meta_preset_id": "legacy"},
                self.catalog, self.species, self.cpms, engine, self.work,
            )
            kept = res1["labels"][res1["roster"][0]]
            self.assertEqual(kept["species"], custom_locked["species"])
            self.assertEqual(kept["moves"], [custom_locked["fast"], custom_locked["charged1"], custom_locked["charged2"]])
            self.assertEqual(kept["ivs"], [3, 11, 14])

            # 3) Locking an empty slot must be rejected!
            with self.assertRaisesRegex(ValueError, "空の枠は固定できません"):
                self.builder._compute(
                    "job_bad_lock",
                    {"mode": "autocomplete", "members": [custom_locked, {}], "locked_slots": [1],
                     "meta_preset_id": "legacy"},
                    self.catalog, self.species, self.cpms, engine, self.work,
                )

            # 4) 6 members ALL locked -> zero replacements.
            res_all_locked = self.builder._compute(
                "job_locked6",
                {"mode": "autocomplete", "members": self.rows[:6], "locked_slots": [0, 1, 2, 3, 4, 5],
                 "meta_preset_id": "legacy"},
                self.catalog, self.species, self.cpms, engine, self.work,
            )
            self.assertEqual(res_all_locked["autocomplete"]["status"], "all_locked")
            self.assertEqual(res_all_locked["autocomplete"]["finalists"][0]["replaced_count"], 0)

            # 5) Weight-only change reuses 100% of cached matchup cells (computed == 0)!
            res_reweight = self.builder._compute(
                "job_reweight",
                {"mode": "analyze", "members": self.rows[:6],
                 "meta_preset_id": "legacy",
                 "group_weights": {self.rows[0]["species"]: 10.0}},
                self.catalog, self.species, self.cpms, engine, self.work,
            )
            self.assertEqual(res_reweight["cache"]["computed"], 0)
            self.assertGreater(res_reweight["cache"]["hits"], 0)

    def test_real_engine_autocomplete_zero_to_six_and_mimikyu_unknown(self):
        """Real DirectMatrixClient Node engine end-to-end check (no mocks)."""
        res = self.builder._compute(
            "job_real_engine",
            {
                "mode": "autocomplete",
                "members": [],
                "locked_slots": [],
                "meta_preset_id": "legacy",
                "scenario_id": "builtin:mimikyu_rise",
                "compare_scenario_ids": ["current", "builtin:mimikyu_rise"],
            },
            self.catalog, self.species, self.cpms, engine, self.work,
        )
        self.assertEqual(len(res["roster"]), 6)
        self.assertEqual(len({self.species[res["labels"][x]["species"]]["dex"] for x in res["roster"]}), 6)
        self.assertEqual(len(res["triples"]), 20)
        self.assertEqual(len(res["recommended_three"]), 3)
        self.assertGreater(res["team"]["unknown_weight"], 0)
        self.assertTrue(any(u["species"] == "mimikyu" for u in res["unverified_mechanics"]))
        self.assertIsNotNone(res["scenario_comparison"])

    def test_http_backend_ignores_payload_owner_scope_and_enforces_header_isolation(self):
        import http.client
        from http.server import ThreadingHTTPServer
        import pvpoke_web as web

        prev_party = web.PARTY
        web.PARTY = self.builder
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            def post(path, body, owner_header=None):
                c = http.client.HTTPConnection(*srv.server_address)
                h = {"Content-Type": "application/json", "X-PvPoke-Token": web.TOKEN}
                if owner_header is not None:
                    h["X-PvPoke-Owner"] = owner_header
                c.request("POST", path, json.dumps(body), h)
                r = c.getresponse()
                data = json.loads(r.read().decode())
                c.close()
                return r.status, data

            code, saved = post(
                "/api/party/save",
                {"name": "A Secret", "members": self.rows[:6], "owner_scope": "spoofed_owner"},
                owner_header="owner_alpha",
            )
            self.assertEqual(code, 200)
            # Owner beta cannot list or read owner alpha's party even if passing owner_scope in payload!
            code_b, list_b = post("/api/party/list", {"owner_scope": "owner_alpha"}, owner_header="owner_beta")
            self.assertEqual(code_b, 200)
            self.assertEqual(list_b["items"], [])
            code_get_b, _ = post("/api/party/get", {"id": saved["id"], "owner_scope": "owner_alpha"}, owner_header="owner_beta")
            self.assertEqual(code_get_b, 400)
            # Revision conflict returns HTTP 409.
            code_c, _ = post(
                "/api/party/rename",
                {"id": saved["id"], "name": "Renamed", "revision": 99},
                owner_header="owner_alpha",
            )
            self.assertEqual(code_c, 409)
        finally:
            srv.shutdown()
            srv.server_close()
            t.join()
            web.PARTY = prev_party

    def test_generic_3phase_meta_evolution_handles_multi_focus_and_unknowns(self):
        # Generic 5-species rock-paper-scissors meta (no Mimikyu hardcoding):
        # A & B are user-weighted multi-focus picks; C beats A & B; D beats C; U is unverified (None).
        meta_rows = [
            {"id": "A", "species": "azumarill"},
            {"id": "B", "species": "clodsire"},
            {"id": "C", "species": "feraligatr"},
            {"id": "D", "species": "serperior"},
            {"id": "U", "species": "mimikyu"},
        ]
        base_weights = {"A": 0.35, "B": 0.35, "C": 0.10, "D": 0.10, "U": 0.10}
        sh = core.STANDARD
        matrix = {
            # C counters both A and B strongly
            ("C", "A", sh): 720, ("A", "C", sh): 280,
            ("C", "B", sh): 700, ("B", "C", sh): 300,
            # D counters C strongly, loses mildly to B
            ("D", "C", sh): 740, ("C", "D", sh): 260,
            ("D", "A", sh): 560, ("A", "D", sh): 440,
            ("D", "B", sh): 420, ("B", "D", sh): 580,
            # A vs B neutral
            ("A", "B", sh): 500, ("B", "A", sh): 500,
            # U (unverified) has no entries -> None
        }
        evo = core.evolve_meta_phases(meta_rows, base_weights, matrix)
        self.assertIsNotNone(evo)
        self.assertEqual(len(evo["phases"]), 3)
        self.assertAlmostEqual(sum(evo["combined_weights"].values()), 1.0, places=5)

        p1, p2, p3 = evo["phases"]
        # Phase 1 keeps user multi-focus weights
        self.assertAlmostEqual(p1["weights"]["A"], 0.35, places=5)
        self.assertAlmostEqual(p1["weights"]["B"], 0.35, places=5)
        # Phase 2 automatically discovers C as the top counter rising against A & B
        self.assertTrue(p2["rising"])
        self.assertEqual(p2["rising"][0]["id"], "C")
        beat_ids = {b["id"] for b in p2["rising"][0]["beats"]}
        self.assertTrue("A" in beat_ids or "B" in beat_ids)
        self.assertGreater(p2["weights"]["C"], p1["weights"]["C"])
        # Phase 3 promotes D (counter to C) and keeps unverified U without crashing
        self.assertGreater(p3["weights"]["D"], p2["weights"]["D"])
        self.assertGreater(p3["weights"]["U"], 0.0)


if __name__ == "__main__":
    unittest.main()

