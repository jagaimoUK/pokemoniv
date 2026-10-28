"""Persistent, per-matchup PvPoke Matrix cache.

Only reuses results with identical prepared species/moves/IVs/level/CP,
shield counts and GameMaster/Pokemon.js hashes. It is deliberately bounded,
expires within seven days for unversioned upstream website changes, and
never guesses PvPoke's official W/L/D counters.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

VERSION = 2
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_ENTRIES = 150_000
FIELDS = ("species", "fast", "charged1", "charged2", "atk", "def",
          "hp", "level", "cp", "level_override")


def cache_namespace(*, gamemaster_hash, pokemonjs_hash, cp_cap, max_level, epoch="", engine_hash=""):
    """Do not share results across different Pokémon data or operator epochs."""
    data = [VERSION, gamemaster_hash, pokemonjs_hash, cp_cap, max_level, epoch, engine_hash]
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


def _prepared(row):
    return [row.get(k) for k in FIELDS]


def _winner_counts(ratings):
    result = [0, 0, 0]
    for value in ratings:
        rating = float(value)
        if not 0 <= rating <= 1000:
            raise ValueError("Invalid Battle Rating")
        result[0 if rating > 500 else 1 if rating < 500 else 2] += 1
    return result


class MatchupCache:
    """A single-process SQLite cache; the surrounding batch worker stays single."""

    def __init__(self, path: Path, namespace: str, *, ttl_seconds=CACHE_TTL_SECONDS):
        self.path = Path(path)
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self.enabled = True
        self.stats = {"hits": 0, "misses": 0, "computed": 0, "bypassed": 0}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=5)
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS matchup (
             cache_key TEXT PRIMARY KEY,
             candidate_label TEXT NOT NULL,
             opponent_label TEXT NOT NULL,
             rating TEXT NOT NULL,
             created INTEGER NOT NULL,
             expires INTEGER NOT NULL
         )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS matchup_expiry ON matchup(expires)")
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self.db is None:
            return
        try:
            # Delete expired entries and oldest overflow, not unrelated ZIPs.
            now = int(time.time())
            self.db.execute("DELETE FROM matchup WHERE expires < ?", (now,))
            count = self.db.execute("SELECT COUNT(*) FROM matchup").fetchone()[0]
            if count > MAX_ENTRIES:
                self.db.execute(
                    "DELETE FROM matchup WHERE cache_key IN "
                    "(SELECT cache_key FROM matchup ORDER BY created LIMIT ?)",
                    (count - MAX_ENTRIES,))
            self.db.commit()
        finally:
            self.db.close()
            self.db = None

    def disable(self):
        """A backend fallback must never populate the pinned-engine namespace."""
        self.enabled = False

    def _key(self, candidate, opponent, shield):
        body = [self.namespace, _prepared(candidate), _prepared(opponent), list(shield)]
        return hashlib.sha256(json.dumps(
            body, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()

    def lookup(self, candidates, opponents, shield):
        keys = {}
        for i, candidate in enumerate(candidates):
            for j, opponent in enumerate(opponents):
                k = self._key(candidate, opponent, shield)
                keys.setdefault(k, []).append((i, j))
        if not keys:
            return {}
        found = {}
        now = int(time.time())
        key_list = list(keys)
        # SQLite versions can have a 999-variable query limit.
        for start in range(0, len(key_list), 500):
            block = key_list[start:start + 500]
            placeholders = ",".join("?" for _ in block)
            sql = ("SELECT cache_key,candidate_label,opponent_label,rating "
                   "FROM matchup WHERE expires >= ? AND cache_key IN (" + placeholders + ")")
            for key, own_label, opp_label, rating in self.db.execute(sql, [now, *block]):
                try:
                    _winner_counts([rating])
                    if not own_label or not opp_label:
                        continue
                except (ValueError, TypeError):
                    continue
                for pos in keys[key]:
                    found[pos] = (own_label, opp_label, rating)
        return found

    def store_matrix(self, candidates, opponents, shield, matrix):
        """Store only if per-cell rating classification equals official row W/L/D.

        None means PvPoke's CSV has an outcome that can't be reconstructed
        safely from Battle Rating alone. Caller must use a fresh full matrix.
        """
        nleft, nright = len(candidates), len(opponents)
        if len(matrix) != nleft + 1 or len(matrix[0]) != nright + 5:
            raise ValueError("Incorrect matrix shape for caching")
        headers = matrix[0][1:1+nright]
        if any(not name for name in headers):
            raise ValueError("Empty opponent label")
        records, found = [], {}
        now = int(time.time())
        for i, row in enumerate(matrix[1:]):
            if len(row) != nright + 5:
                raise ValueError("Incomplete matrix row")
            cand_label = row[0]
            ivs = "/".join(str(candidates[i][k]) for k in ("atk", "def", "hp"))
            if ivs not in cand_label:
                raise ValueError("Incorrect cached candidate IV label")
            rates = row[1:1+nright]
            if _winner_counts(rates) != [int(x) for x in row[1+nright:4+nright]]:
                return None
            for j, rating in enumerate(rates):
                entry = (cand_label, headers[j], str(rating))
                found[(i, j)] = entry
                records.append((self._key(candidates[i], opponents[j], shield),
                                *entry, now, now + self.ttl_seconds))
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO matchup "
                "(cache_key,candidate_label,opponent_label,rating,created,expires) "
                "VALUES (?,?,?,?,?,?)", records)
        return found

    @staticmethod
    def assemble(candidates, opponents, cells):
        """Reconstruct the exact Matrix shape and real W/L/D classification."""
        nleft, nright = len(candidates), len(opponents)
        if len(cells) != nleft*nright:
            raise ValueError("Incomplete cached Matrix")
        headers = []
        for j in range(nright):
            labels = {cells[(i, j)][1] for i in range(nleft)}
            if len(labels) != 1:
                raise ValueError("Opponent labels disagree across rows")
            headers.append(labels.pop())
        output = [["", *headers, "Wins", "Losses", "Draws", "Average"]]
        for i in range(nleft):
            labels = {cells[(i, j)][0] for j in range(nright)}
            if len(labels) != 1:
                raise ValueError("Candidate labels disagree across columns")
            label = labels.pop()
            ratings = [cells[(i,j)][2] for j in range(nright)]
            counts = _winner_counts(ratings)
            output.append([label, *ratings, *counts,
                           math.floor(sum(map(float, ratings)) * 100 / nright + 0.5) / 100])
        return output

    def resolve(self, candidates, opponents, shield, simulate, *,
                cand_chunk=8, opp_chunk=12):
        """Calculate just missing candidate/opponent pairs and recombine.

        'simulate' performs a normal PvPoke Matrix run with subsets and
        returns the usual verified CSV rows. On doubtful outcome semantics,
        conservatively execute the original full matrix without caching it.
        """
        if not self.enabled:
            total = len(candidates) * len(opponents)
            self.stats["computed"] += total
            self.stats["bypassed"] += total
            return simulate(candidates, opponents, shield)
        cells = self.lookup(candidates, opponents, shield)
        total = len(candidates)*len(opponents)
        self.stats["hits"] += len(cells)
        self.stats["misses"] += total - len(cells)
        if len(cells) == total:
            try:
                return self.assemble(candidates, opponents, cells)
            except ValueError:
                self.stats["bypassed"] += total
                cells = {}
        if not cells:
            matrix = simulate(candidates, opponents, shield)
            self.stats["computed"] += total
            if self.enabled and self.store_matrix(candidates, opponents, shield, matrix) is None:
                self.stats["bypassed"] += total
            return matrix

        grouped = defaultdict(list)
        for i in range(len(candidates)):
            missing = tuple(j for j in range(len(opponents)) if (i,j) not in cells)
            if missing:
                grouped[missing].append(i)
        for missing, c_indices in grouped.items():
            for ci in range(0, len(c_indices), cand_chunk):
                selected_c = c_indices[ci:ci+cand_chunk]
                for oj in range(0, len(missing), opp_chunk):
                    selected_o = missing[oj:oj+opp_chunk]
                    crows = [candidates[i] for i in selected_c]
                    orows = [opponents[j] for j in selected_o]
                    matrix = simulate(crows, orows, shield)
                    self.stats["computed"] += len(crows)*len(orows)
                    if not self.enabled:
                        # Do not combine old direct-engine hits with browser fallback cells.
                        self.stats["bypassed"] += total
                        self.stats["computed"] += total
                        return simulate(candidates, opponents, shield)
                    new = self.store_matrix(crows, orows, shield, matrix)
                    if new is None:
                        self.stats["bypassed"] += total
                        full = simulate(candidates, opponents, shield)
                        self.stats["computed"] += total
                        return full
                    for (i, j), entry in new.items():
                        cells[(selected_c[i], selected_o[j])] = entry
        try:
            return self.assemble(candidates, opponents, cells)
        except ValueError:
            self.stats["bypassed"] += total
            full = simulate(candidates, opponents, shield)
            self.stats["computed"] += total
            self.store_matrix(candidates, opponents, shield, full)
            return full
