"""Offline safety checks for per-matchup persisted PvPoke results."""
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pvpoke_matchup_cache import MatchupCache, cache_namespace


def candidate(iv, *, move="AQUA_TAIL"):
    return dict(species="quagsire", fast="MUD_SHOT", charged1=move,
                charged2="STONE_EDGE", atk=iv, hp=8, level=29.5, cp=1496, **{'def': 11})


def opponent(iv):
    return dict(species="clodsire", fast="POISON_STING", charged1="STONE_EDGE",
                charged2="EARTHQUAKE", atk=iv, hp=15, level=27, cp=1499, **{'def': 15})


def pvpmatrix(cands, opps, shield):
    """PvPoke-like result with exact labels and official W/L/D counts."""
    header = ["", *[f"Clodsire {o['atk']}/15/15" for o in opps],
              "Wins", "Losses", "Draws", "Average"]
    rows = [header]
    for c in cands:
        rates = [str(500 + 20*c["atk"] - 15*o["atk"] + shield[0]*2 - shield[1]*4)
                 for o in opps]
        v = [float(x) for x in rates]
        counts = [sum(x > 500 for x in v), sum(x < 500 for x in v),
                  sum(x == 500 for x in v)]
        rows.append([f"Quagsire MS+AT/SE {c['atk']}/11/8", *rates, *counts,
                     sum(v)/len(v)])
    return rows


class PersistentMatchupCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"pvpoke_archives"/"matchups.sqlite3"
        self.namespace = cache_namespace(gamemaster_hash="gm1", pokemonjs_hash="js1",
                                         cp_cap=1500, max_level=50)

    def cache(self, namespace=None):
        return MatchupCache(self.path, namespace or self.namespace)

    def test_exact_csv_and_counts_persist_after_database_reopen(self):
        cands, opps, shield = [candidate(0), candidate(1)], [opponent(0), opponent(1)], (0, 0)
        requested = []
        def sim(c, o, s):
            requested.append((len(c),len(o)))
            return pvpmatrix(c, o, s)
        with self.cache() as db:
            result = db.resolve(cands, opps, shield, sim)
            self.assertEqual(result, pvpmatrix(cands, opps, shield))
            self.assertEqual(requested, [(2,2)])
        with self.cache() as db:
            recovered = db.resolve(cands, opps, shield, sim)
            self.assertEqual(recovered[1][:-1], result[1][:-1])
            self.assertEqual(db.stats['hits'], 4)
            self.assertEqual(db.stats['computed'], 0)
            self.assertEqual(requested, [(2,2)])

    def test_partial_cache_computes_only_new_candidate(self):
        calls = []
        def sim(c, o, sh):
            calls.append((len(c),len(o),sh))
            return pvpmatrix(c, o, sh)
        with self.cache() as db:
            cands, opps, shield = [candidate(0), candidate(1)], [opponent(0), opponent(1)], (0,0)
            expected = db.resolve(cands, opps, shield, sim)
            self.assertEqual(calls, [(2,2,shield)])
            original = db.resolve(cands[::-1], opps[::-1], shield, sim)
            self.assertEqual(len(calls), 1, "reordering must not rerun any matchup")
            self.assertEqual(original[1][1], expected[2][2])
            mixed = db.resolve([candidate(2), *cands], opps, shield, sim)
            self.assertEqual(calls[-1], (1,2,shield))
            self.assertEqual(len(calls), 2)
            self.assertEqual(mixed[2][1:3], expected[1][1:3])
            self.assertEqual(db.stats["computed"], 6)
            self.assertEqual(db.stats["hits"], 8)

    def test_invalidation_on_moves_ivs_level_shields_and_dataset(self):
        c, o, shield = candidate(0), opponent(0), (1,1)
        with self.cache() as db:
            db.resolve([c], [o], shield, pvpmatrix)
            self.assertEqual(len(db.lookup([c],[o],shield)), 1)
            for changed, other, sh in [
                ({**c, "charged1":"MUD_BOMB"}, o, shield),
                ({**c, "level": 30.0}, o, shield),
                ({**c, "cp": 1490}, o, shield),
                ({**c, "atk": 2}, o, shield),
                (c, {**o, "charged2": "SLUDGE_BOMB"}, shield),
                (c, o, (0,1)),
            ]:
                self.assertFalse(db.lookup([changed],[other],sh))
        other_ns = cache_namespace(gamemaster_hash="gm2", pokemonjs_hash="js1",
                                   cp_cap=1500, max_level=50)
        with self.cache(other_ns) as db:
            self.assertFalse(db.lookup([c],[o],shield))

    def test_reject_outcome_counts_that_do_not_match_ratings(self):
        with self.cache() as db:
            cands, opps = [candidate(0)], [opponent(0)]
            rows = pvpmatrix(cands, opps, (0,0))
            rows[1][-4:-1] = [1,0,0]  # 500 rating must be a tie
            self.assertIsNone(db.store_matrix(cands,opps,(0,0),rows))
            self.assertFalse(db.lookup(cands,opps,(0,0)))

    def test_expired_entries_are_ignored(self):
        with self.cache() as db:
            cands, opps = [candidate(0)], [opponent(0)]
            db.resolve(cands,opps,(1,1),pvpmatrix)
            db.db.execute("UPDATE matchup SET expires=0")
            db.db.commit()
            self.assertFalse(db.lookup(cands,opps,(1,1)))


class BackendFallbackCacheTests(unittest.TestCase):
    def test_fallback_does_not_mix_or_store_results_under_direct_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"cache.sqlite3"
            with MatchupCache(path,"direct-fixture") as cache:
                own=[candidate(0),candidate(1)]; other=[opponent(0)]
                cache.resolve(own[:1],other,(0,0),pvpmatrix)
                calls=[]
                def fallback(c,o,sh):
                    calls.append(len(c))
                    cache.disable()
                    return pvpmatrix(c,o,sh)
                self.assertEqual(cache.resolve(own,other,(0,0),fallback),pvpmatrix(own,other,(0,0)))
                self.assertEqual(calls,[1,2])
            with MatchupCache(path,"direct-fixture") as cache:
                self.assertEqual(len(cache.lookup(own,other,(0,0))),1)
                self.assertFalse(cache.lookup(own[1:],other,(0,0)))


class MatrixRoundingCacheTests(unittest.TestCase):
    def test_cache_rounding_matches_pvpoke_javascript_half_up(self):
        with tempfile.TemporaryDirectory() as folder:
            own=[candidate(0)]; others=[opponent(i) for i in range(8)]
            matrix=[["",*["opponent-"+str(i) for i in range(8)],"Wins","Losses","Draws","Average"],
                    ["Quagsire 0/11/8",*[500]*7,501,1,0,7,500.13]]
            with MatchupCache(Path(folder)/"cache.sqlite3","rounding") as cache:
                cache.resolve(own,others,(0,0),lambda *args:matrix)
                restored=cache.resolve(own,others,(0,0),lambda *args:self.fail("cached battle"))
                self.assertEqual(restored[1][-1],500.13)
                def as_csv(rows):
                    stream=io.StringIO();csv.writer(stream).writerows(rows);return stream.getvalue()
                self.assertEqual(as_csv(restored),as_csv(matrix))
