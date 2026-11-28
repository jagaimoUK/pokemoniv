"""TV-03: Differential vs forced full calculation parity and cache isolation for Mega forms."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from pvpoke_app_selection import recommend
from pvpoke_calculation_version import CALCULATION_FILES, calculation_version
from pvpoke_matchup_cache import MatchupCache, cache_namespace
from pvpoke_selection_matrix import SHIELDS, SelectionMatrix

SHIELD_PAIRS = {
    "s0": (0, 0),
    "s1": (1, 1),
    "s2": (2, 2),
    "i0y1": (0, 1),
    "i0y2": (0, 2),
    "i1y2": (1, 2),
}


def _mega_candidate(
    atk: int,
    defense: int,
    hp: int,
    *,
    species: str = "charizard_mega_y",
    level: float = 20.0,
    cp: int = 1495,
    mega_level: int | None = 3,
    charged3: str | None = "BLAST_BURN",
) -> dict:
    row = {
        "species": species,
        "fast": "FIRE_SPIN",
        "charged1": "DRAGON_CLAW",
        "charged2": "OVERHEAT",
        "atk": atk,
        "def": defense,
        "hp": hp,
        "level": level,
        "cp": cp,
    }
    if mega_level is not None:
        row["mega_level"] = mega_level
    if charged3 is not None:
        row["charged3"] = charged3
    return row


def _opponent(name: str, atk: int, defense: int, hp: int, level: float = 25.0, cp: int = 1498) -> dict:
    return {
        "species": name,
        "fast": "COUNTER",
        "charged1": "BODY_SLAM",
        "charged2": "SHADOW_BALL",
        "atk": atk,
        "def": defense,
        "hp": hp,
        "level": level,
        "cp": cp,
    }


def _simulate_mega_matrix(cands: list[dict], opps: list[dict], shield: tuple[int, int]) -> list[list]:
    """Deterministic PvPoke-shaped simulator sensitive to IVs, mega_level, charged3, level, and shield."""
    headers = [f"{o['species']} {o['atk']}/{o['def']}/{o['hp']}" for o in opps]
    rows = [["", *headers, "Wins", "Losses", "Draws", "Average"]]
    for c in cands:
        iv_key = f"{c['atk']}/{c['def']}/{c['hp']}"
        ml = c.get("mega_level") or 3
        c3_bonus = 10 if c.get("charged3") else 0
        pl_bonus = 6 if float(c["level"]) >= 53.0 else (3 if float(c["level"]) >= 52.0 else 0)
        ratings = []
        for idx, opp in enumerate(opps):
            # Make (0,15,15) strong generalist, (15,15,15) strictly dominated,
            # and (0,13,14) a specialist with a unique_gt500 win on opponent index 2.
            if (c["atk"], c["def"], c["hp"]) == (15, 15, 15):
                base = 420 - idx * 15
            elif (c["atk"], c["def"], c["hp"]) == (0, 13, 14):
                base = 530 if idx == 2 else 440 - idx * 5
            else:
                # (0,15,15) and equivalent (0,15,14)
                base = 460 if idx == 2 else 560 - idx * 10
            score = base + ml * 2 + c3_bonus + pl_bonus + shield[0] * 2 - shield[1] * 2
            score = max(0, min(1000, score))
            ratings.append(str(score))
        vals = [int(r) for r in ratings]
        counts = [sum(v > 500 for v in vals), sum(v < 500 for v in vals), sum(v == 500 for v in vals)]
        avg = round(sum(vals) / len(vals), 2)
        rows.append([f"{c['species']} {iv_key}", *ratings, *counts, avg])
    return rows


def _selection_matrix_from_resolved(
    resolved_by_shield: dict[str, list[list]],
    candidates: list[dict],
) -> SelectionMatrix:
    opponents = list(resolved_by_shield[SHIELDS[0]][0][1:-4])
    cand_ivs = [f"{c['atk']}/{c['def']}/{c['hp']}" for c in candidates]
    ratings: dict[str, dict[str, list[float]]] = {}
    for shield in SHIELDS:
        table = resolved_by_shield[shield]
        per_cand = {}
        for idx, row in enumerate(table[1:]):
            per_cand[cand_ivs[idx]] = [float(x) for x in row[1:-4]]
        ratings[shield] = per_cand
    return SelectionMatrix(opponents=opponents, candidates=cand_ivs, ratings=ratings, manifest={})


class MegaDifferentialCacheTV03Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "matchups.sqlite3"
        self.opponents = [
            _opponent("azumarill", 0, 15, 15),
            _opponent("medicham", 5, 15, 15),
            _opponent("registeel", 2, 13, 14),
            _opponent("altaria", 0, 14, 15),
        ]

    def _run_recommend_comparison(
        self,
        *,
        mega_level: int,
        super_max_mode: str,
        level: float,
        max_level: float,
        charged3: str | None,
    ):
        c_generalist = _mega_candidate(0, 15, 15, mega_level=mega_level, level=level, charged3=charged3)
        c_dominated = _mega_candidate(15, 15, 15, mega_level=mega_level, level=level, charged3=charged3)
        c_specialist = _mega_candidate(0, 13, 14, mega_level=mega_level, level=level, charged3=charged3)
        c_equiv = _mega_candidate(0, 15, 14, mega_level=mega_level, level=level, charged3=charged3)

        initial_cands = [c_generalist, c_dominated]
        full_cands = [c_generalist, c_dominated, c_specialist, c_equiv]

        ns = cache_namespace(
            gamemaster_hash="gm-tv03",
            pokemonjs_hash="js-tv03",
            cp_cap=1500,
            max_level=max_level,
            engine_hash="eng-tv03",
            mega_level=mega_level,
            downscaling_mode="allow_cp_downscaling",
            super_max_mode=super_max_mode,
            cup_id="mega_great",
        )

        # 1. Seed cache with initial candidates
        with MatchupCache(self.db_path, ns) as cache:
            for shield_key in SHIELDS:
                cache.resolve(initial_cands, self.opponents, SHIELD_PAIRS[shield_key], _simulate_mega_matrix)

        # 2. Differential calculation reusing valid cache for initial_cands, computing only new cands
        diff_calls = []

        def diff_sim(c, o, sh):
            diff_calls.append((len(c), len(o), sh))
            return _simulate_mega_matrix(c, o, sh)

        diff_matrices = {}
        with MatchupCache(self.db_path, ns) as cache:
            for shield_key in SHIELDS:
                diff_matrices[shield_key] = cache.resolve(
                    full_cands, self.opponents, SHIELD_PAIRS[shield_key], diff_sim
                )
            self.assertEqual(cache.stats["hits"], len(SHIELDS) * len(initial_cands) * len(self.opponents))
            self.assertEqual(
                cache.stats["computed"],
                len(SHIELDS) * (len(full_cands) - len(initial_cands)) * len(self.opponents),
            )
            self.assertEqual(len(diff_calls), len(SHIELDS))

        # 3. Forced full recalculation (bypass cache completely)
        full_matrices = {}
        with MatchupCache(self.db_path, ns) as disabled_cache:
            disabled_cache.disable()
            for shield_key in SHIELDS:
                full_matrices[shield_key] = disabled_cache.resolve(
                    full_cands, self.opponents, SHIELD_PAIRS[shield_key], _simulate_mega_matrix
                )
            self.assertEqual(disabled_cache.stats["hits"], 0)
            self.assertEqual(disabled_cache.stats["computed"], len(SHIELDS) * len(full_cands) * len(self.opponents))

        cand_meta = {
            "species": "charizard_mega_y",
            "mega_level": mega_level,
            "super_max_mode": super_max_mode,
            "charged3": charged3,
        }
        diff_rec = recommend(
            {"default": _selection_matrix_from_resolved(diff_matrices, full_cands)},
            cand_meta,
            "Charizard",
        )
        full_rec = recommend(
            {"default": _selection_matrix_from_resolved(full_matrices, full_cands)},
            cand_meta,
            "Charizard",
        )

        # Exact parity checks: recommendations, dominated_by, unique wins, moveset_summary
        self.assertEqual(diff_rec["recommendations"], full_rec["recommendations"])
        self.assertEqual(diff_rec["dominated_by"], full_rec["dominated_by"])
        self.assertEqual(diff_rec["review_candidates"], full_rec["review_candidates"])
        self.assertEqual(diff_rec["additional_candidates"], full_rec["additional_candidates"])
        self.assertEqual(diff_rec["covered_candidates"], full_rec["covered_candidates"])
        self.assertEqual(diff_rec["moveset_summary"], full_rec["moveset_summary"])

        # Sanity: dominated IV is rejected and specialist unique_gt500 is preserved
        self.assertIn("15/15/15", diff_rec["dominated_by"])
        rec_by_iv = {row["ivs"]: row for row in diff_rec["recommendations"]}
        self.assertIn("0/13/14", rec_by_iv)
        self.assertTrue(any(ev.get("kind") == "unique_gt500" for ev in rec_by_iv["0/13/14"].get("evidence", [])))

    def test_differential_vs_full_parity_across_mega_levels_and_super_max(self):
        scenarios = [
            dict(mega_level=1, super_max_mode="", level=20.0, max_level=50.0, charged3=None),
            dict(mega_level=2, super_max_mode="", level=20.0, max_level=50.0, charged3="BLAST_BURN"),
            dict(mega_level=3, super_max_mode="", level=20.0, max_level=50.0, charged3="BLAST_BURN"),
            dict(mega_level=4, super_max_mode="hypothesis_1_pl52", level=52.0, max_level=52.0, charged3="BLAST_BURN"),
            dict(mega_level=4, super_max_mode="hypothesis_2_pl53", level=53.0, max_level=53.0, charged3="BLAST_BURN"),
        ]
        for idx, params in enumerate(scenarios):
            with self.subTest(scenario=idx, **params):
                # Fresh db per scenario so each tests clean differential seeding
                self.db_path = Path(self.tmp.name) / f"matchups_{idx}.sqlite3"
                self._run_recommend_comparison(**params)

    def test_cache_key_separates_mega_levels_charged3_super_max_and_downscaling(self):
        base_ns = cache_namespace(
            gamemaster_hash="gm1",
            pokemonjs_hash="js1",
            cp_cap=1500,
            max_level=50,
            engine_hash="eng1",
            mega_level=3,
            downscaling_mode="allow_cp_downscaling",
            super_max_mode="",
            cup_id="mega_great",
        )
        c_base = _mega_candidate(0, 15, 15, mega_level=3, charged3="BLAST_BURN", level=20.0)
        with MatchupCache(self.db_path, base_ns) as cache:
            cache.resolve([c_base], self.opponents[:1], (1, 1), _simulate_mega_matrix)
            self.assertEqual(len(cache.lookup([c_base], self.opponents[:1], (1, 1))), 1)

            # Different mega_level (1, 2, 4) and charged3 must NOT hit
            for variant in [
                _mega_candidate(0, 15, 15, mega_level=1, charged3="BLAST_BURN", level=20.0),
                _mega_candidate(0, 15, 15, mega_level=2, charged3="BLAST_BURN", level=20.0),
                _mega_candidate(0, 15, 15, mega_level=4, charged3="BLAST_BURN", level=20.0),
                _mega_candidate(0, 15, 15, mega_level=3, charged3=None, level=20.0),
                _mega_candidate(0, 15, 15, mega_level=3, charged3="DRAGON_CLAW", level=20.0),
            ]:
                self.assertEqual(cache.lookup([variant], self.opponents[:1], (1, 1)), {})

        # Super MAX PL52 / PL53 and non-downscaling namespaces must NOT hit
        for other_ns in [
            cache_namespace(
                gamemaster_hash="gm1", pokemonjs_hash="js1", cp_cap=1500, max_level=52,
                engine_hash="eng1", mega_level=4, downscaling_mode="allow_cp_downscaling",
                super_max_mode="hypothesis_1_pl52", cup_id="mega_great",
            ),
            cache_namespace(
                gamemaster_hash="gm1", pokemonjs_hash="js1", cp_cap=1500, max_level=53,
                engine_hash="eng1", mega_level=4, downscaling_mode="allow_cp_downscaling",
                super_max_mode="hypothesis_2_pl53", cup_id="mega_great",
            ),
            cache_namespace(
                gamemaster_hash="gm1", pokemonjs_hash="js1", cp_cap=1500, max_level=50,
                engine_hash="eng1", mega_level=3, downscaling_mode="",
                super_max_mode="", cup_id="mega_great",
            ),
        ]:
            with MatchupCache(self.db_path, other_ns) as other_cache:
                self.assertEqual(other_cache.lookup([c_base], self.opponents[:1], (1, 1)), {})

    def test_expired_and_mega_rule_version_mismatch_reject_cache(self):
        ns = cache_namespace(gamemaster_hash="gm1", pokemonjs_hash="js1", cp_cap=1500, max_level=50)
        c = _mega_candidate(0, 15, 15, mega_level=3, charged3="BLAST_BURN")
        with MatchupCache(self.db_path, ns) as cache:
            cache.resolve([c], self.opponents[:1], (0, 0), _simulate_mega_matrix)
            self.assertEqual(len(cache.lookup([c], self.opponents[:1], (0, 0))), 1)
            cache.db.execute("UPDATE matchup SET expires = 0")
            cache.db.commit()
            self.assertEqual(cache.lookup([c], self.opponents[:1], (0, 0)), {})

        # Verify pvpoke_mega.py is tracked in calculation_version
        self.assertIn("pvpoke_mega.py", CALCULATION_FILES)
        repo_root = Path(__file__).resolve().parent.parent
        sandbox = Path(self.tmp.name) / "version_check"
        sandbox.mkdir()
        for fname in CALCULATION_FILES:
            shutil.copy2(repo_root / fname, sandbox / fname)
        data_dir = sandbox / "data"
        data_dir.mkdir()
        (data_dir / "gamemaster.json").write_text("{}", encoding="utf-8")
        (data_dir / "Pokemon.js").write_text("// js", encoding="utf-8")

        import os
        old_engine = os.environ.get("PVP_ENGINE")
        old_epoch = os.environ.get("PVP_BROWSER_CACHE_EPOCH")
        try:
            os.environ["PVP_ENGINE"] = "browser"
            os.environ["PVP_BROWSER_CACHE_EPOCH"] = "tv03-test"
            v1 = calculation_version(data_dir, root=sandbox)
            self.assertIsNotNone(v1)
            (sandbox / "pvpoke_mega.py").write_text(
                (sandbox / "pvpoke_mega.py").read_text(encoding="utf-8") + "\n# tv03-change\n",
                encoding="utf-8",
            )
            v2 = calculation_version(data_dir, root=sandbox)
            self.assertIsNotNone(v2)
            self.assertNotEqual(v1, v2)
        finally:
            if old_engine is None:
                os.environ.pop("PVP_ENGINE", None)
            else:
                os.environ["PVP_ENGINE"] = old_engine
            if old_epoch is None:
                os.environ.pop("PVP_BROWSER_CACHE_EPOCH", None)
            else:
                os.environ["PVP_BROWSER_CACHE_EPOCH"] = old_epoch


if __name__ == "__main__":
    unittest.main()
