"""Party Builder worker and isolated SQLite storage.

Runs only inside the local PvPoke Web server, never through the MCP endpoint.
The public gateway already owns authentication, origin and body-size checks.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pvpoke_party_core as core
import pvpoke_archive as archives
import pvpoke_meta_presets as presets
import pvpoke_meta_live as meta_live
import pvpoke_iv_modes as iv_modes
from pvpoke_calculation_version import calculation_version
from pvpoke_direct_backend import DirectMatrixClient

MAX_POOL = 48
MAX_META = 100
SHIELDS_META = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))
MAX_PARTIES = 32


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class PartyBuilder:
    def __init__(self, work):
        self.path = archives.archive_dir(work) / "team_builder.sqlite3"
        self._lock = threading.RLock()
        self._active = None
        self._cancel = False
        self._previous_global = None

    @property
    def running(self):
        with self._lock:
            return self._active is not None

    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("""CREATE TABLE IF NOT EXISTS parties(
                   id TEXT PRIMARY KEY, revision INTEGER NOT NULL, name TEXT NOT NULL,
                   content TEXT NOT NULL, updated INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS runs(
                   id TEXT PRIMARY KEY, status TEXT NOT NULL, details TEXT NOT NULL,
                   updated INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS cells(
                   key TEXT PRIMARY KEY, rating INTEGER NOT NULL,
                   created INTEGER NOT NULL)""")
        return db

    def list_parties(self):
        with self._db() as db:
            return {"items": [{"id": x[0], "revision": x[1], "name": x[2]}
                              for x in db.execute(
                                  "SELECT id,revision,name FROM parties ORDER BY updated DESC LIMIT ?",
                                  (MAX_PARTIES,))]}

    def get_party(self, pid):
        if not isinstance(pid, str) or len(pid) > 64:
            raise ValueError("パーティIDが不正です")
        with self._db() as db:
            row = db.execute("SELECT revision,name,content FROM parties WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise ValueError("保存したパーティが見つかりません")
        return {"id": pid, "revision": row[0], "name": row[1], **json.loads(row[2])}

    def save_party(self, payload):
        name, members = payload.get("name"), payload.get("members")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError("パーティ名は1〜60文字で入力してください")
        if not isinstance(members, list) or len(members) > 6 or any(not isinstance(x, dict) for x in members):
            raise ValueError("パーティは最大6体の配列で指定してください")
        pid = payload.get("id") or uuid.uuid4().hex
        rev = payload.get("revision", 0)
        if not isinstance(pid, str) or len(pid) > 64 or type(rev) is not int or rev < 0:
            raise ValueError("保存のrevisionが不正です")
        content = {k: payload.get(k) for k in (
            "members", "locked_slots", "manual_pair_tags", "meta_preset_id", "meta_sha256",
            "group_weights", "ruleset", "opponents", "candidate_pool")}
        serialized = _json(content)
        if len(serialized.encode("utf-8")) > 100_000:
            raise ValueError("保存データが大きすぎます")
        with self._lock, self._db() as db:
            current = db.execute("SELECT revision FROM parties WHERE id=?", (pid,)).fetchone()
            if current is None:
                if rev != 0:
                    raise ValueError("保存先が存在しません。新規作成してください")
                if db.execute("SELECT count(*) FROM parties").fetchone()[0] >= MAX_PARTIES:
                    raise ValueError("保存できるパーティは最大32件です")
                db.execute("INSERT INTO parties VALUES(?,?,?,?,?)",
                           (pid, 1, name.strip(), serialized, int(time.time())))
                rev = 1
            else:
                if current[0] != rev:
                    raise RuntimeError("保存競合: 別のタブで編集されています")
                result = db.execute(
                    "UPDATE parties SET revision=?,name=?,content=?,updated=? WHERE id=? AND revision=?",
                    (rev + 1, name.strip(), serialized, int(time.time()), pid, rev))
                if result.rowcount != 1:
                    raise RuntimeError("保存競合: 別のタブで編集されています")
                rev += 1
        return {"id": pid, "revision": rev, "saved": True}

    def run_status(self, job_id):
        if not isinstance(job_id, str) or len(job_id) > 64:
            raise ValueError("ジョブIDが不正です")
        with self._db() as db:
            row = db.execute("SELECT status,details FROM runs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("ジョブIDが見つかりません")
        return {"job_id": job_id, "status": row[0], **json.loads(row[1])}

    def _record(self, jid, status, data):
        with self._lock, self._db() as db:
            db.execute("""INSERT INTO runs(id,status,details,updated) VALUES(?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                       details=excluded.details,updated=excluded.updated""",
                       (jid, status, _json(data), int(time.time())))
            # Keep stored results bounded, without touching IV jobs/ZIPs.
            stale = db.execute("SELECT id FROM runs ORDER BY updated DESC LIMIT -1 OFFSET 32").fetchall()
            if stale:
                db.executemany("DELETE FROM runs WHERE id=?", stale)

    @staticmethod
    def _normalize(rows, catalog, species, cpms, engine, label):
        if not isinstance(rows, list) or not rows:
            raise ValueError(label + "を登録してください")
        prepared = []
        for i, raw in enumerate(rows):
            if not isinstance(raw, dict):
                raise ValueError(label + "の形式が不正です")
            sid = str(raw.get("species") or "").strip().lower()
            p = catalog.get(sid)
            if p is None:
                raise ValueError(label + ": 未登録ポケモン " + sid)
            moves = [str(raw.get(k) or "").strip().upper() for k in
                     ("fast", "charged1", "charged2")]
            if (moves[0] not in p["fastMoves"] or
                any(m not in p["chargedMoves"] for m in moves[1:]) or
                moves[1] == moves[2]):
                raise ValueError(label + ": 技構成が不正です " + sid)
            ivs = [raw.get(k) for k in ("atk", "def", "hp")]
            if all(x is None for x in ivs):
                atk, defense, hp, _ = iv_modes.select_opponent_ivs(
                    species[sid], cpms, "default", moves=moves,
                    cp_cap=engine.CP_CAP, level_cap=engine.MAX_LEVEL)
                ivs = [atk, defense, hp]
            if any(type(v) is not int or not 0 <= v <= 15 for v in ivs):
                raise ValueError(label + ": 個体値は0〜15の整数を3つ指定してください")
            source = dict(zip(engine.HEADER, [sid, *moves, *ivs]))
            if raw.get("level_override") is not None:
                source["level_override"] = raw["level_override"]
            p0 = engine.optimize([source], species, cpms, label)[0]
            p0["id"] = core.combatant_id(p0)
            p0["meta_group_id"] = str(raw.get("meta_group_id") or sid)
            # Species clause intentionally separate from battle identity.
            p0["roster_clause_id"] = str(raw.get("roster_clause_id") or sid.replace("_shadow", ""))
            prepared.append(p0)
        return prepared

    @staticmethod
    def _unique(rows):
        return list({r["id"]: r for r in reversed(rows)}.values())[::-1]

    def start(self, args, *, catalog, species, cpms, engine, work, global_lock, global_status):
        if not isinstance(args, dict) or args.get("mode") not in ("analyze", "select", "build"):
            raise ValueError("modeはanalyze/select/buildのいずれかです")
        if args.get("ruleset", "cp1500-lv50") != "cp1500-lv50":
            raise ValueError("現在はCP1500/Lv50のみ対応しています")
        if os.environ.get("PVP_ENGINE", "browser").lower() not in ("direct", "node"):
            raise ValueError("パーティ計算はDirectエンジンが必要です")
        with global_lock, self._lock:
            if self._active is not None or global_status.get("state") == "running":
                raise RuntimeError("他の計算中です。完了後に開始してください")
            jid = uuid.uuid4().hex
            self._active = jid
            self._cancel = False
            self._record(jid, "queued", {"message": "準備しています", "progress": 0})
            self._previous_global = (global_status, global_lock, dict(global_status))
            global_status["state"] = "running"
            global_status["message"] = "パーティ作成の計算中"
            task = threading.Thread(target=self._worker, args=(
                jid, args, catalog, species, cpms, engine, work, global_lock), daemon=True)
            task.start()
        return {"job_id": jid, "status": "queued"}

    def cancel(self, jid):
        with self._lock:
            if jid != self._active:
                return {"cancel_requested": False}
            self._cancel = True
            return {"cancel_requested": True}

    def _worker(self, jid, args, catalog, species, cpms, engine, work, global_lock):
        started = time.monotonic()
        try:
            result = self._compute(jid, args, catalog, species, cpms, engine, work)
            result["elapsed_seconds"] = round(time.monotonic() - started, 2)
            self._record(jid, "done", {"progress": 100, "result": result})
        except Exception as exc:
            status = "cancelled" if str(exc) == "cancelled" else "error"
            self._record(jid, status, {"message": str(exc)[:400], "progress": 0})
        finally:
            # Always acquire the shared web lock before this worker lock.
            # The reverse order could deadlock with a concurrent start request.
            with global_lock, self._lock:
                if self._active == jid:
                    self._active = None
                    if self._previous_global:
                        status, _, previous = self._previous_global
                        status.clear()
                        status.update(previous)
                        self._previous_global = None

    def _compute(self, jid, args, catalog, species, cpms, engine, work):
        own_raw = args.get("members")
        locked_raw = []
        if not isinstance(own_raw, list):
            raise ValueError("自分のパーティ入力が必要です")
        if args["mode"] == "build":
            indices = args.get("locked_slots") or []
            if (not isinstance(indices, list) or
                any(type(i) is not int or i < 0 or i >= len(own_raw) for i in indices)):
                raise ValueError("固定枠の指定が正しくありません")
            locked_raw = [own_raw[i] for i in dict.fromkeys(indices)]
            pool_raw = locked_raw + (args.get("candidate_pool") or [])
        else:
            pool_raw = own_raw
        if not isinstance(pool_raw, list) or not 1 <= len(pool_raw) <= MAX_POOL:
            raise ValueError("固定枠を含む候補は1〜48体までです")
        if args["mode"] != "build" and len(own_raw) != 6:
            raise ValueError("分析するパーティは6体必要です")
        if args["mode"] == "build" and len(pool_raw) < 6:
            raise ValueError("自動構築は6体以上の候補が必要です")
        pool = self._unique(self._normalize(pool_raw, catalog, species, cpms, engine, "自分の候補"))
        if args["mode"] == "build" and any(p["species"].startswith("minior") for p in pool):
            raise ValueError("メテノの対面ごとに方針を変える試験モデルは自動構築に使えません")
        if len(pool) < 6 and args["mode"] == "build":
            raise ValueError("異なる候補が6体必要です")
        if args["mode"] != "build" and len(pool) != 6:
            raise ValueError("同じポケモン・技・個体値の重複があります")
        clauses = [p["roster_clause_id"] for p in pool]
        if args["mode"] != "build" and len(set(clauses)) != 6:
            raise ValueError("同種のポケモンは6体へ重複登録できません")
        preset_id = args.get("meta_preset_id") or "legacy"
        meta_file, preset = presets.snapshot(work, preset_id, catalog,
                                              args.get("meta_sha256"))
        with meta_file.open(encoding="utf-8-sig", newline="") as stream:
            meta_raw = [dict(zip(engine.HEADER[:4], row))
                        for row in csv.reader(stream) if row]
        if len(meta_raw) > MAX_META:
            raise ValueError("現在のプレビューはメタ最大100技構成です。プリセットを絞ってください")
        meta = self._unique(self._normalize(meta_raw, catalog, species, cpms, engine, "メタ"))
        weights = core.weight_rows(meta, args.get("group_weights"))
        enemy_raw = args.get("opponents") or []
        if args["mode"] == "select" and len(enemy_raw) != 6:
            raise ValueError("選出計算には相手6体が必要です")
        if enemy_raw and len(enemy_raw) != 6:
            raise ValueError("相手を指定する場合は6体にしてください")
        enemy = self._normalize(enemy_raw, catalog, species, cpms, engine, "相手6体") if enemy_raw else []
        if enemy and len({r["roster_clause_id"] for r in enemy}) != 6:
            raise ValueError("相手の6体に同種重複があります")
        self._record(jid, "running", {"progress": 2, "message": "対面を準備しています"})
        version = calculation_version(engine.DATA)
        if version is None:
            raise ValueError("エンジンの計算版を検証できません。キャッシュを使わず中止しました")
        matrix, stats = self._matrix(
            jid, pool, self._unique(meta + enemy), version, engine, work,
            enemy_ids={p["id"] for p in enemy})
        ids = [p["id"] for p in pool]
        opponents = [p["id"] for p in meta]
        clause = {p["id"]: p["roster_clause_id"] for p in pool}
        if args["mode"] == "build":
            locked = [p["id"] for p in self._normalize(
                locked_raw, catalog, species, cpms, engine, "固定枠")] if locked_raw else []
            # Search cannot put the same species in two slots.
            groups = {}
            for p in pool:
                groups.setdefault(p["roster_clause_id"], []).append(p["id"])
            # Check species constraints in the search output as well.
            result = self._build_legal(ids, opponents, matrix, weights, locked, clause, args)
            ids = result["roster"]
        else:
            result = {"roster": ids}
        whole = core.team_summary(ids, opponents, matrix, weights)
        pairs = [core.pair_summary(a, b, opponents, matrix, weights) for a, b in __import__("itertools").combinations(ids, 2)]
        pairs.sort(key=lambda r: -r["balance"])
        triples = [{"members": list(group),
                    "summary": core.team_summary(group, opponents, matrix, weights)}
                   for group in core.legal_triples(ids, clause=clause)]
        triples.sort(key=lambda r: (r["summary"]["unknown_weight"], r["summary"]["d0"],
                                    r["summary"]["severity0"]))
        threats = core.dangerous_pairs(
            [row["members"] for row in triples[:3]], opponents, matrix, weights,
            {p["id"]: p["roster_clause_id"] for p in meta})
        chosen = (core.choose_three(ids, [p["id"] for p in enemy], matrix)
                  if enemy else {"status": "相手6体が未指定"})
        labels = {p["id"]: {"species": p["species"],
                  "moves": [p["fast"], p["charged1"], p["charged2"]],
                  "ivs": [p["atk"], p["def"], p["hp"]],
                  "cp": p["cp"], "level": p["level"]}
                  for p in self._unique(pool + meta + enemy)}
        return {"roster": ids, "meta": {"id": preset_id, "sha256": preset["sha256"],
                "hypotheses": len(meta), "assumption": "仮説等分は使用率ではありません"},
                "labels": labels, "team": whole, "pairs": pairs,
                "triples": triples, "danger_pairs": threats, "selection": chosen, "search": result if args["mode"] == "build" else None,
                "calculation_version": version, "evaluation_version": core.EVALUATION_VERSION,
                "cache": stats, "not_calculated": [
                    "通常技限定の圧力", "受け後の仕事", "観測ベースのシールド温存",
                    "交代後の状態引継ぎ", "実戦3対3の勝率"]}

    @staticmethod
    def _build_legal(ids, opponents, matrix, weights, locked, clause, args):
        if len({clause[x] for x in locked}) != len(locked):
            raise ValueError("固定枠に同種が含まれています")
        # Only choose one variant of each species for each final six.
        # Wrap rank with explicit legality rather than silently accepting duplicates.
        legal = []
        for value in ids:
            if value in locked or clause[value] not in {clause[x] for x in locked}:
                legal.append(value)
        candidates = legal
        # Use independent beam expansion with clause filtering.
        width = min(32, max(1, int(args.get("beam_width", 16))))
        beam = [tuple(sorted(locked))]
        for _ in range(len(locked), 6):
            pool = {}
            for partial in beam:
                existing = {clause[x] for x in partial}
                choices = [x for x in candidates if x not in partial and clause[x] not in existing]
                choices.sort(key=lambda x: core.rank_partial((*partial, x), opponents, matrix, weights))
                for x in choices[:24]:
                    roster = tuple(sorted((*partial, x)))
                    pool[roster] = core.rank_partial(roster, opponents, matrix, weights)
            beam = sorted(pool, key=lambda x: (pool[x], x))[:width]
            if not beam:
                raise ValueError("種族重複なしで6体を組めません")
        best = beam[0]
        for _ in range(2):
            options = [(core.rank_partial(best, opponents, matrix, weights), best)]
            for old in best:
                if old in locked:
                    continue
                keep = [x for x in best if x != old]
                used = {clause[x] for x in keep}
                for replacement in candidates:
                    if clause[replacement] in used:
                        continue
                    value = tuple(sorted(keep + [replacement]))
                    options.append((core.rank_partial(value, opponents, matrix, weights), value))
            next_best = min(options)[1]
            if next_best == best:
                break
            best = next_best
        return {"roster": list(best), "locked": locked, "beam_width": width,
                "candidate_count": len(candidates), "scope": "候補内の暫定結果。全探索ではありません"}

    def _matrix(self, jid, pool, opponents, version, engine, work, *, enemy_ids):
        # Cache namespaced by exact prepared inputs, engine/data version and direction.
        # Standard Matrix results are never confused with detailed policy outcomes.
        matrix, stats = {}, {"hits": 0, "computed": 0}
        total = len(pool) * len(opponents) * 9
        done = 0
        with self._db() as db:
            client = None
            try:
                for shield in core.ALL_SHIELDS:
                    for start in range(0, len(pool), 6):
                        own_chunk = pool[start:start + 6]
                        for col in range(0, len(opponents), 10):
                            opp_chunk = opponents[col:col + 10]
                            keys = {(p["id"], q["id"]): core.digest(
                                ["party-cell-v1", version, p["id"], q["id"], shield])
                                for p in own_chunk for q in opp_chunk}
                            missing = []
                            for p in own_chunk:
                                for q in opp_chunk:
                                    pair = (p["id"], q["id"])
                                    # All nine conditions for the 6v6; only six for meta.
                                    if shield not in SHIELDS_META and q["id"] not in enemy_ids:
                                        continue
                                    row = db.execute("SELECT rating FROM cells WHERE key=?",
                                                     (keys[pair],)).fetchone()
                                    if row is None:
                                        missing.append(pair)
                                    else:
                                        matrix[pair + (shield,)] = row[0]
                                        stats["hits"] += 1
                            if missing:
                                missing_set = set(missing)
                                if client is None:
                                    client = DirectMatrixClient(
                                        gamemaster=engine.DATA / "gamemaster.json", log_dir=work)
                                values = client.simulate(own_chunk, opp_chunk, shield)
                                for a, p in enumerate(own_chunk):
                                    for b, q in enumerate(opp_chunk):
                                        pair = (p["id"], q["id"])
                                        if shield not in SHIELDS_META and q["id"] not in enemy_ids:
                                            continue
                                        if pair not in missing_set:
                                            continue  # Valid cached cell wins; do not count as new.
                                        rating = values[a + 1][b + 1]
                                        matrix[pair + (shield,)] = rating
                                        # Minior's per-opponent policy max is not a fixed strategy.
                                        if not p["species"].startswith("minior"):
                                            db.execute("INSERT OR REPLACE INTO cells VALUES(?,?,?)",
                                                       (keys[pair], rating, int(time.time())))
                                        stats["computed"] += 1
                                db.commit()
                            done += len(own_chunk) * len(opp_chunk)
                            with self._lock:
                                if self._cancel:
                                    raise ValueError("cancelled")
                            self._record(jid, "running", {"progress": min(95, 2 + int(91 * done / total)),
                                "message": "対面を計算しています", "cache": stats})
                # Bound storage size; never delete parties or saved analyses.
                db.execute("""DELETE FROM cells WHERE key IN
                           (SELECT key FROM cells ORDER BY created DESC LIMIT -1 OFFSET 120000)""")
                db.commit()
            finally:
                if client is not None:
                    client.close()
        return matrix, stats
