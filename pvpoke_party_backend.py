"""Party Builder worker and isolated SQLite storage.

Runs only inside the local PvPoke Web server, never through the MCP endpoint.
The public gateway already owns authentication, origin and body-size checks.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import re
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pvpoke_party_core as core
import pvpoke_future_meta as future_meta
import pvpoke_archive as archives
import pvpoke_meta_presets as presets
import pvpoke_meta_live as meta_live
import pvpoke_iv_modes as iv_modes
from pvpoke_calculation_version import calculation_version
from pvpoke_direct_backend import DirectMatrixClient

MAX_POOL = 48
MAX_META = meta_live.MAX_ROWS
SHIELDS_META = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))
MAX_PARTIES = 32
DEFAULT_OWNER = "owner"
OWNER_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
SCOPE_KEY_RE = re.compile(r"^(meta|scenario):[a-zA-Z0-9_:-]{1,90}$")


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _owner(owner_scope):
    value = DEFAULT_OWNER if owner_scope is None else owner_scope
    if not isinstance(value, str) or not OWNER_RE.fullmatch(value):
        raise ValueError("所有者スコープが不正です")
    return value


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
                   content TEXT NOT NULL, updated INTEGER NOT NULL,
                   owner_scope TEXT NOT NULL DEFAULT 'owner')""")
        # Safe additive migration for pre-existing databases without owner_scope.
        party_cols = {row[1] for row in db.execute("PRAGMA table_info(parties)").fetchall()}
        if "owner_scope" not in party_cols:
            db.execute("ALTER TABLE parties ADD COLUMN owner_scope TEXT NOT NULL DEFAULT 'owner'")
        db.execute("""CREATE TABLE IF NOT EXISTS runs(
                   id TEXT PRIMARY KEY, status TEXT NOT NULL, details TEXT NOT NULL,
                   updated INTEGER NOT NULL,
                   owner_scope TEXT NOT NULL DEFAULT 'owner')""")
        run_cols = {row[1] for row in db.execute("PRAGMA table_info(runs)").fetchall()}
        if "owner_scope" not in run_cols:
            db.execute("ALTER TABLE runs ADD COLUMN owner_scope TEXT NOT NULL DEFAULT 'owner'")
        db.execute("""CREATE TABLE IF NOT EXISTS cells(
                   key TEXT PRIMARY KEY, rating INTEGER NOT NULL,
                   created INTEGER NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS meta_weights(species TEXT PRIMARY KEY, weight REAL NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS scoped_meta_weights(
                   owner_scope TEXT NOT NULL, scope_key TEXT NOT NULL,
                   species TEXT NOT NULL, weight REAL NOT NULL,
                   PRIMARY KEY (owner_scope, scope_key, species))""")
        db.execute("""CREATE TABLE IF NOT EXISTS meta_scenarios(
                   owner_scope TEXT NOT NULL, id TEXT NOT NULL,
                   revision INTEGER NOT NULL, name TEXT NOT NULL,
                   base_meta_id TEXT NOT NULL, base_meta_sha256 TEXT NOT NULL,
                   kind TEXT NOT NULL, content TEXT NOT NULL,
                   updated INTEGER NOT NULL,
                   PRIMARY KEY (owner_scope, id))""")
        return db

    def meta_weights(self, changes=None, *, scope_key=None, owner_scope=DEFAULT_OWNER):
        """Legacy owner-wide defaults when scope_key is None; isolated per-scope weights when scope_key is set."""
        if scope_key is not None:
            return self.scoped_weights(scope_key, changes, owner_scope=owner_scope)
        if changes is not None:
            if not isinstance(changes, dict) or len(changes) > MAX_META:
                raise ValueError("重要度の更新は最大500種のオブジェクトです")
            for sid, value in changes.items():
                if (not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", sid)
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                    raise ValueError("重要度はポケモンIDと0以上の有限数で指定してください")
        with self._lock, self._db() as db:
            if changes:
                db.executemany("""INSERT INTO meta_weights VALUES(?,?)
                    ON CONFLICT(species) DO UPDATE SET weight=excluded.weight""", changes.items())
            return {"weights": dict(db.execute("SELECT species,weight FROM meta_weights"))}

    def scoped_weights(self, scope_key, changes=None, *, owner_scope=DEFAULT_OWNER):
        """Strictly isolated weight boundary per (owner_scope, scope_key).

        Editing Future A (scenario:future:A) never mutates Future B or Current Meta.
        """
        owner = _owner(owner_scope)
        if not isinstance(scope_key, str) or not SCOPE_KEY_RE.fullmatch(scope_key):
            raise ValueError("重要度の保存スコープが不正です")
        clean = None
        if changes is not None:
            clean = future_meta.validate_weights(changes)
        with self._lock, self._db() as db:
            if clean:
                db.executemany(
                    """INSERT INTO scoped_meta_weights(owner_scope,scope_key,species,weight)
                       VALUES(?,?,?,?)
                       ON CONFLICT(owner_scope,scope_key,species)
                       DO UPDATE SET weight=excluded.weight""",
                    [(owner, scope_key, sid, val) for sid, val in clean.items()],
                )
            rows = db.execute(
                "SELECT species,weight FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                (owner, scope_key),
            ).fetchall()
            return {"scope_key": scope_key, "weights": dict(rows)}

    def list_scenarios(self, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        items = []
        with self._db() as db:
            for builtin in future_meta.builtin_scenarios():
                overrides = dict(db.execute(
                    "SELECT species,weight FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                    (owner, "scenario:" + builtin["id"]),
                ).fetchall())
                if overrides:
                    builtin["weights"] = future_meta.resolve_effective_weights(builtin, overrides)
                items.append(builtin)
            rows = db.execute(
                """SELECT id,revision,name,base_meta_id,base_meta_sha256,kind,content,updated
                   FROM meta_scenarios WHERE owner_scope=? ORDER BY updated DESC LIMIT ?""",
                (owner, future_meta.MAX_SCENARIOS),
            ).fetchall()
            for sid, rev, name, base_id, base_sha, kind, content, updated in rows:
                data = json.loads(content)
                overrides = dict(db.execute(
                    "SELECT species,weight FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                    (owner, "scenario:" + sid),
                ).fetchall())
                weights = future_meta.resolve_effective_weights(data, overrides) if overrides else data.get("weights", {})
                items.append({
                    "id": sid, "revision": rev, "name": name,
                    "base_meta_id": base_id, "base_meta_sha256": base_sha,
                    "kind": kind, "builtin": False, "updated": updated,
                    **data, "weights": weights,
                })
        return {"items": items, "observations": future_meta.observation_snapshot()}

    def get_scenario(self, sid, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        if not isinstance(sid, str) or not 1 <= len(sid) <= 64:
            raise ValueError("シナリオIDが不正です")
        if sid in future_meta.BUILTIN_SCENARIO_MAP:
            item = json.loads(_json(future_meta.BUILTIN_SCENARIO_MAP[sid]))
            with self._db() as db:
                overrides = dict(db.execute(
                    "SELECT species,weight FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                    (owner, "scenario:" + sid),
                ).fetchall())
            if overrides:
                item["weights"] = future_meta.resolve_effective_weights(item, overrides)
            return item
        with self._db() as db:
            row = db.execute(
                """SELECT revision,name,base_meta_id,base_meta_sha256,kind,content,updated
                   FROM meta_scenarios WHERE owner_scope=? AND id=?""",
                (owner, sid),
            ).fetchone()
            if row is None:
                raise ValueError("指定された未来メタシナリオが見つかりません")
            overrides = dict(db.execute(
                "SELECT species,weight FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                (owner, "scenario:" + sid),
            ).fetchall())
        data = json.loads(row[5])
        weights = future_meta.resolve_effective_weights(data, overrides) if overrides else data.get("weights", {})
        return {
            "id": sid, "revision": row[0], "name": row[1],
            "base_meta_id": row[2], "base_meta_sha256": row[3],
            "kind": row[4], "builtin": False, "updated": row[6],
            **data, "weights": weights,
        }

    def save_scenario(self, payload, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        normalized = future_meta.validate_scenario_payload(payload)
        sid = normalized["id"]
        rev = normalized["revision"]
        name = normalized["name"]
        content = {
            "summary": normalized["summary"],
            "weights": normalized["weights"],
            "chain_steps": normalized["chain_steps"],
            "assumptions": normalized["assumptions"],
            "custom_entries": normalized["custom_entries"],
        }
        serialized = _json(content)
        if len(serialized.encode("utf-8")) > 100_000:
            raise ValueError("シナリオの保存データが大きすぎます")
        with self._lock, self._db() as db:
            # Enforce unique scenario name within owner scope (including built-ins).
            builtin_names = {b["name"].casefold() for b in future_meta.BUILTIN_SCENARIOS}
            if name.casefold() in builtin_names:
                raise ValueError("組み込みシナリオと同じ名前は使えません。別の名前を指定してください")
            dup = db.execute(
                "SELECT id FROM meta_scenarios WHERE owner_scope=? AND lower(name)=lower(?) AND id!=?",
                (owner, name, sid),
            ).fetchone()
            if dup is not None:
                raise ValueError("同じ名前のシナリオが既にあります。別の名前を指定してください")
            current = db.execute(
                "SELECT revision FROM meta_scenarios WHERE owner_scope=? AND id=?",
                (owner, sid),
            ).fetchone()
            now = int(time.time())
            if current is None:
                if rev != 0:
                    raise ValueError("保存先のシナリオが存在しません。新規作成してください")
                count = db.execute(
                    "SELECT count(*) FROM meta_scenarios WHERE owner_scope=?",
                    (owner,),
                ).fetchone()[0]
                if count >= future_meta.MAX_SCENARIOS:
                    raise ValueError(f"保存できる未来メタシナリオは最大{future_meta.MAX_SCENARIOS}件です")
                db.execute(
                    """INSERT INTO meta_scenarios(owner_scope,id,revision,name,base_meta_id,base_meta_sha256,kind,content,updated)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (owner, sid, 1, name, normalized["base_meta_id"],
                     normalized["base_meta_sha256"], normalized["kind"], serialized, now),
                )
                rev = 1
            else:
                if current[0] != rev:
                    raise RuntimeError("保存競合: シナリオが別のタブで編集されています")
                res = db.execute(
                    """UPDATE meta_scenarios
                       SET revision=?,name=?,base_meta_id=?,base_meta_sha256=?,content=?,updated=?
                       WHERE owner_scope=? AND id=? AND revision=?""",
                    (rev + 1, name, normalized["base_meta_id"], normalized["base_meta_sha256"],
                     serialized, now, owner, sid, rev),
                )
                if res.rowcount != 1:
                    raise RuntimeError("保存競合: シナリオが別のタブで編集されています")
                rev += 1
            # Replace scoped_meta_weights for this scenario atomically so stale edits cannot leak.
            db.execute(
                "DELETE FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                (owner, "scenario:" + sid),
            )
            if normalized["weights"]:
                db.executemany(
                    "INSERT INTO scoped_meta_weights(owner_scope,scope_key,species,weight) VALUES(?,?,?,?)",
                    [(owner, "scenario:" + sid, sp, w) for sp, w in normalized["weights"].items()],
                )
        return {"id": sid, "revision": rev, "name": name, "saved": True}

    def delete_scenario(self, sid, revision, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        if not isinstance(sid, str) or sid.startswith("builtin:") or len(sid) > 64:
            raise ValueError("組み込みシナリオは削除できません")
        if type(revision) is not int or revision < 1:
            raise ValueError("削除のrevisionが不正です")
        with self._lock, self._db() as db:
            current = db.execute(
                "SELECT revision FROM meta_scenarios WHERE owner_scope=? AND id=?",
                (owner, sid),
            ).fetchone()
            if current is None:
                raise ValueError("削除対象のシナリオが見つかりません")
            if current[0] != revision:
                raise RuntimeError("保存競合: シナリオが別のタブで更新されています")
            res = db.execute(
                "DELETE FROM meta_scenarios WHERE owner_scope=? AND id=? AND revision=?",
                (owner, sid, revision),
            )
            if res.rowcount != 1:
                raise RuntimeError("保存競合: シナリオが別のタブで更新されています")
            db.execute(
                "DELETE FROM scoped_meta_weights WHERE owner_scope=? AND scope_key=?",
                (owner, "scenario:" + sid),
            )
        return {"id": sid, "deleted": True}

    def list_parties(self, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        with self._db() as db:
            return {"items": [{"id": x[0], "revision": x[1], "name": x[2]}
                              for x in db.execute(
                                  "SELECT id,revision,name FROM parties WHERE owner_scope=? ORDER BY updated DESC LIMIT ?",
                                  (owner, MAX_PARTIES))]}

    def get_party(self, pid, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        if not isinstance(pid, str) or len(pid) > 64:
            raise ValueError("パーティIDが不正です")
        with self._db() as db:
            row = db.execute(
                "SELECT revision,name,content FROM parties WHERE id=? AND owner_scope=?",
                (pid, owner),
            ).fetchone()
        if row is None:
            raise ValueError("保存したパーティが見つかりません")
        return {"id": pid, "revision": row[0], "name": row[1], **json.loads(row[2])}

    def rename_party(self, pid, name, revision, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        if not isinstance(pid, str) or len(pid) > 64:
            raise ValueError("パーティIDが不正です")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError("パーティ名は1〜60文字で入力してください")
        if type(revision) is not int or revision < 1:
            raise ValueError("名前変更のrevisionが不正です")
        with self._lock, self._db() as db:
            current = db.execute(
                "SELECT revision FROM parties WHERE id=? AND owner_scope=?",
                (pid, owner),
            ).fetchone()
            if current is None:
                raise ValueError("保存したパーティが見つかりません")
            if current[0] != revision:
                raise RuntimeError("保存競合: 別のタブで編集されています")
            res = db.execute(
                "UPDATE parties SET revision=?,name=?,updated=? WHERE id=? AND owner_scope=? AND revision=?",
                (revision + 1, name.strip(), int(time.time()), pid, owner, revision),
            )
            if res.rowcount != 1:
                raise RuntimeError("保存競合: 別のタブで編集されています")
        return {"id": pid, "revision": revision + 1, "name": name.strip(), "renamed": True}

    def save_party(self, payload, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
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
            "scenario_id", "compare_scenario_ids",
            "group_weights", "ruleset", "opponents", "candidate_pool", "strategy", "strategy_refinement",
            "opponent_uncertainty", "opponent_hypotheses")}
        serialized = _json(content)
        if len(serialized.encode("utf-8")) > 100_000:
            raise ValueError("保存データが大きすぎます")
        with self._lock, self._db() as db:
            current = db.execute("SELECT revision,owner_scope FROM parties WHERE id=?", (pid,)).fetchone()
            if current is None:
                if rev != 0:
                    raise ValueError("保存先が存在しません。新規作成してください")
                if db.execute("SELECT count(*) FROM parties WHERE owner_scope=?", (owner,)).fetchone()[0] >= MAX_PARTIES:
                    raise ValueError("保存できるパーティは最大32件です")
                db.execute("INSERT INTO parties(id,revision,name,content,updated,owner_scope) VALUES(?,?,?,?,?,?)",
                           (pid, 1, name.strip(), serialized, int(time.time()), owner))
                rev = 1
            else:
                if current[1] != owner:
                    raise ValueError("保存したパーティが見つかりません")
                if current[0] != rev:
                    raise RuntimeError("保存競合: 別のタブで編集されています")
                result = db.execute(
                    "UPDATE parties SET revision=?,name=?,content=?,updated=? WHERE id=? AND owner_scope=? AND revision=?",
                    (rev + 1, name.strip(), serialized, int(time.time()), pid, owner, rev))
                if result.rowcount != 1:
                    raise RuntimeError("保存競合: 別のタブで編集されています")
                rev += 1
        return {"id": pid, "revision": rev, "name": name.strip(), "saved": True}

    def run_status(self, job_id, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        if not isinstance(job_id, str) or len(job_id) > 64:
            raise ValueError("ジョブIDが不正です")
        with self._db() as db:
            row = db.execute(
                "SELECT status,details FROM runs WHERE id=? AND owner_scope=?",
                (job_id, owner),
            ).fetchone()
        if row is None:
            raise ValueError("ジョブIDが見つかりません")
        return {"job_id": job_id, "status": row[0], **json.loads(row[1])}

    def _record(self, jid, status, data, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        with self._lock, self._db() as db:
            db.execute("""INSERT INTO runs(id,status,details,updated,owner_scope) VALUES(?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                       details=excluded.details,updated=excluded.updated""",
                       (jid, status, _json(data), int(time.time()), owner))
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
            # PvPoke CSV export adds -shadow to the actual _shadow species ID.
            # Canonicalize before catalog/legality checks; never change the source CSV.
            if sid.endswith("_shadow-shadow"):
                sid = sid.removesuffix("-shadow")
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
            p0["roster_clause_id"] = str(species[sid].get("dex") or sid.replace("_shadow", ""))
            prepared.append(p0)
        return prepared

    @staticmethod
    def _unique(rows):
        return list({r["id"]: r for r in reversed(rows)}.values())[::-1]

    def start(self, args, *, catalog, species, cpms, engine, work, global_lock, global_status, release_owner=None, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        if not isinstance(args, dict) or args.get("mode") not in ("analyze", "select", "build", "strategy", "autocomplete"):
            raise ValueError("modeはanalyze/select/build/strategy/autocompleteのいずれかです")
        if args.get("ruleset", "cp1500-lv50") != "cp1500-lv50":
            raise ValueError("現在はCP1500/Lv50のみ対応しています")
        if os.environ.get("PVP_ENGINE", "browser").lower() not in ("direct", "node"):
            raise ValueError("パーティ計算はDirectエンジンが必要です")
        with global_lock, self._lock:
            if self._active is not None or global_status.get("state") in ("running", "cancelling"):
                raise RuntimeError("他の計算中です。完了後に開始してください")
            jid = uuid.uuid4().hex
            prev_global = (global_status, global_lock, dict(global_status))
            self._active = jid
            self._active_owner = owner
            self._cancel = False
            self._previous_global = prev_global
            try:
                self._record(jid, "queued", {"message": "準備しています", "progress": 0}, owner_scope=owner)
                global_status["state"] = "running"
                global_status["message"] = "パーティ作成の計算中"
                task = threading.Thread(target=self._worker, args=(
                    jid, args, catalog, species, cpms, engine, work, global_lock, release_owner, owner), daemon=True)
                task.start()
            except Exception:
                self._active = None
                self._active_owner = None
                self._previous_global = None
                global_status["state"] = prev_global[2].get("state", "idle")
                global_status["message"] = prev_global[2].get("message", "")
                raise
        return {"job_id": jid, "status": "queued"}

    def cancel(self, jid, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        with self._lock:
            if jid != self._active or getattr(self, "_active_owner", DEFAULT_OWNER) != owner:
                return {"cancel_requested": False}
            self._cancel = True
            return {"cancel_requested": True}

    def _worker(self, jid, args, catalog, species, cpms, engine, work, global_lock, release_owner=None, owner_scope=DEFAULT_OWNER):
        started = time.monotonic()
        try:
            result = self._compute(jid, args, catalog, species, cpms, engine, work, owner_scope=owner_scope)
            result["elapsed_seconds"] = round(time.monotonic() - started, 2)
            self._record(jid, "done", {"progress": 100, "result": result}, owner_scope=owner_scope)
        except Exception as exc:
            status = "cancelled" if str(exc) == "cancelled" else "error"
            # Background exceptions can contain internal file paths, SQL
            # details or subprocess output. Do not persist them in a status
            # record readable through the authenticated browser API.
            if status == "cancelled":
                message = "cancelled"
            elif isinstance(exc, ValueError):
                # Keep established, actionable input-validation feedback.
                message = str(exc)[:400]
            else:
                logging.warning("Party worker failed: %s", type(exc).__name__)
                message = "パーティ計算に失敗しました。再試行してください"
            self._record(jid, status, {"message": message, "progress": 0}, owner_scope=owner_scope)
        finally:
            # Always acquire the shared web lock before this worker lock.
            # The reverse order could deadlock with a concurrent start request.
            with global_lock, self._lock:
                if self._active == jid:
                    self._active = None
                    self._active_owner = None
                    if self._previous_global:
                        status, _, previous = self._previous_global
                        status.clear()
                        status.update(previous)
                        self._previous_global = None
                    if release_owner is not None:
                        try:
                            release_owner()
                        except Exception:
                            pass

    @staticmethod
    def _default_row_for_species(sid, catalog, species=None):
        p = catalog.get(sid)
        if not p:
            return None
        rec = p.get("default_moves") or {}
        fast = rec.get("fast") if rec.get("fast") in p["fastMoves"] else (p["fastMoves"][0] if p["fastMoves"] else "")
        c1 = rec.get("charged1") if rec.get("charged1") in p["chargedMoves"] else (p["chargedMoves"][0] if p["chargedMoves"] else "")
        c2 = rec.get("charged2") if rec.get("charged2") in p["chargedMoves"] and rec.get("charged2") != c1 else next(
            (m for m in p["chargedMoves"] if m != c1), "")
        if not (fast and c1 and c2 and c1 != c2):
            return None
        row = {"species": sid, "fast": fast, "charged1": c1, "charged2": c2}
        sp = (species or {}).get(sid) or {}
        if not (sp.get("defaultIVs") or {}).get("cp1500"):
            row.update({"atk": 0, "def": 15, "hp": 15})
        return row

    def _collect_unverified(self, rows, scenario=None, catalog=None):
        seen = {}
        for p in rows:
            sid = p["species"]
            reason = core.unverified_mechanic_reason(sid)
            if reason and sid not in seen:
                seen[sid] = {"species": sid, "status": "unknown", "reason": reason}
        if scenario:
            for sid, w in (scenario.get("weights") or {}).items():
                if w > 0:
                    reason = core.unverified_mechanic_reason(sid)
                    if reason and sid not in seen:
                        in_cat = bool(catalog and sid in catalog)
                        seen[sid] = {
                            "species": sid,
                            "status": "unknown" if in_cat else "not_in_gamemaster_unknown",
                            "reason": reason if in_cat else (reason + "（現在のGameMasterに未登録のため数値計算対象外）"),
                        }
        return list(seen.values())

    def _compute(self, jid, args, catalog, species, cpms, engine, work, *, owner_scope=DEFAULT_OWNER):
        owner = _owner(owner_scope)
        mode = args["mode"]
        if mode == "strategy":
            return self._strategy(jid, args, catalog, species, cpms, engine, work)
        own_raw = args.get("members")
        locked_raw = []
        is_autocomplete = mode == "autocomplete"
        auto_complete = mode in ("analyze", "select") and args.get("auto_complete") is True
        # Extra detailed calculation is opt-in (default OFF) for unified autocomplete.
        default_refine = False if is_autocomplete else (mode == "build" or auto_complete)
        refine = args.get("strategy_refinement", default_refine)
        if type(refine) is not bool:
            raise ValueError("詳細戦略の統合は真偽値で指定してください")
        uncertainty_enabled = args.get('opponent_uncertainty', False)
        if type(uncertainty_enabled) is not bool:
            raise ValueError('技・IV感度比較は真偽値で指定してください')
        hypotheses = []
        if uncertainty_enabled:
            raw_hypotheses = args.get('opponent_hypotheses', [])
            if not isinstance(raw_hypotheses, list) or len(raw_hypotheses) > 8:
                raise ValueError('相手の追加技仮説は最大8件です')
            if raw_hypotheses:
                hypotheses = self._unique(self._normalize(raw_hypotheses, catalog, species, cpms, engine, '相手の追加技仮説'))
        seek_swaps = mode in ("analyze", "select") and (
            args.get("auto_replacements") is True or auto_complete)
        if (args.get("auto_replacements") not in (None, True, False) or
                args.get("auto_complete") not in (None, True, False)):
            raise ValueError("入れ替え探索の指定が不正です")
        if not isinstance(own_raw, list):
            raise ValueError("自分のパーティ入力が必要です")

        # Resolve base meta preset and optional isolated future scenario.
        preset_id = args.get("meta_preset_id") or "legacy"
        meta_file, preset = presets.snapshot(work, preset_id, catalog, args.get("meta_sha256"))
        with meta_file.open(encoding="utf-8-sig", newline="") as stream:
            meta_raw = [dict(zip(engine.HEADER[:4], row)) for row in csv.reader(stream) if row]
        if len(meta_raw) > MAX_META:
            raise ValueError(f"メタは最大{MAX_META}技構成です。プリセットを絞ってください")

        scenario_id = args.get("scenario_id")
        if scenario_id in ("", "current"):
            scenario_id = None
        active_scenario = self.get_scenario(scenario_id, owner_scope=owner) if scenario_id else None

        # Append validated scenario custom entries or catalog-present scenario targets (e.g. Mimikyu).
        meta_species_present = {str(r.get("species") or "").strip().lower() for r in meta_raw}
        extra_meta_raw = []
        if active_scenario:
            for entry in active_scenario.get("custom_entries") or []:
                extra_meta_raw.append(entry)
            for sid, w in (active_scenario.get("weights") or {}).items():
                if w > 0 and sid not in meta_species_present and sid in catalog:
                    default_row = self._default_row_for_species(sid, catalog, species)
                    if default_row:
                        extra_meta_raw.append(default_row)
                        meta_species_present.add(sid)
        meta_all_raw = meta_raw + extra_meta_raw
        if len(meta_all_raw) > MAX_META:
            raise ValueError(f"メタは最大{MAX_META}技構成です。プリセットを絞ってください")
        meta_all = self._unique(self._normalize(meta_all_raw, catalog, species, cpms, engine, "メタ"))

        # Resolve effective weights strictly within the active scenario boundary (no double counting).
        explicit_weights = args.get("group_weights")
        if active_scenario is not None:
            effective_group_weights = future_meta.resolve_effective_weights(active_scenario, explicit_weights)
        else:
            effective_group_weights = future_meta.validate_weights(explicit_weights)
        weights = core.weight_rows(meta_all, effective_group_weights)
        # Excluded groups need neither simulation nor search evaluation (unless needed for comparison).
        compare_ids_raw = args.get("compare_scenario_ids") or []
        if not isinstance(compare_ids_raw, list) or len(compare_ids_raw) > 4:
            raise ValueError("比較するシナリオは最大4件です")
        compare_specs = []
        if compare_ids_raw:
            seen_cmp = set()
            for cid in compare_ids_raw:
                if not isinstance(cid, str) or cid in seen_cmp:
                    continue
                seen_cmp.add(cid)
                if cid in ("", "current"):
                    curr_w = self.scoped_weights("meta:" + preset_id, owner_scope=owner)["weights"]
                    compare_specs.append({
                        "id": "current",
                        "name": f"現行メタ（{preset.get('name', preset_id)}）",
                        "revision": 0,
                        "kind": "current",
                        "weights": core.weight_rows(meta_all, curr_w),
                    })
                else:
                    sc = self.get_scenario(cid, owner_scope=owner)
                    compare_specs.append({
                        "id": sc["id"],
                        "name": sc["name"],
                        "revision": sc.get("revision"),
                        "kind": sc.get("kind", "future"),
                        "weights": core.weight_rows(meta_all, sc.get("weights")),
                    })
        needed_meta_ids = {row["id"] for row in meta_all if weights[row["id"]] > 0}
        for spec in compare_specs:
            needed_meta_ids.update(mid for mid, w in spec["weights"].items() if w > 0)
        meta = [row for row in meta_all if row["id"] in needed_meta_ids]

        provisional_ids = set()
        initial_slot_ids = []
        mapped_locked_slots = []
        locked_ids_unified = []
        swap_source = "none"
        replacement_pool = []
        base_roster = []

        if is_autocomplete:
            if len(own_raw) > 6:
                raise ValueError("自分のパーティは最大6体までです")
            raw_locks = args.get("locked_slots") or []
            if not isinstance(raw_locks, list) or any(type(i) is not int or i < 0 or i >= 6 for i in raw_locks):
                raise ValueError("固定枠の指定が正しくありません")
            raw_locks = list(dict.fromkeys(raw_locks))

            # Separate filled slots from empty slots while preserving exact slot indices.
            filled_entries = []
            slot_to_norm = {}
            for idx, entry in enumerate(own_raw):
                if not isinstance(entry, dict):
                    raise ValueError("自分のパーティ入力形式が不正です")
                if not str(entry.get("species") or "").strip():
                    continue
                norm = self._normalize([entry], catalog, species, cpms, engine, "自分のパーティ")[0]
                slot_to_norm[idx] = norm
                filled_entries.append((idx, norm))
            for idx in raw_locks:
                if idx not in slot_to_norm:
                    raise ValueError("空の枠は固定できません。ポケモンを選択してから固定してください")

            locked_norms = [slot_to_norm[idx] for idx in raw_locks]
            if len({p["roster_clause_id"] for p in locked_norms}) != len(locked_norms):
                raise ValueError("固定枠に同種のポケモンが重複しています")
            locked_ids_unified = [p["id"] for p in locked_norms]

            if len(filled_entries) == 6 and len({p["roster_clause_id"] for _, p in filled_entries}) == 6 and len({p["id"] for _, p in filled_entries}) == 6:
                initial_slot_ids = [p["id"] for _, p in filled_entries]
                mapped_locked_slots = list(raw_locks)
            else:
                # Preserve exact slot positions for entered members (using a 6-slot sparse list).
                initial_slot_ids = [slot_to_norm[i]["id"] if i in slot_to_norm else None for i in range(6)]
                initial_slot_ids = [x for x in initial_slot_ids if x is not None]
                id_to_pos = {pid: i for i, pid in enumerate(initial_slot_ids)}
                mapped_locked_slots = [id_to_pos[p["id"]] for p in locked_norms]

            entered_norms = [p for _, p in filled_entries]
            raw_candidates = args.get("candidate_pool") or []
            if not isinstance(raw_candidates, list):
                raise ValueError("候補プールの形式が不正です")
            registered_norms = (
                self._unique(self._normalize(raw_candidates, catalog, species, cpms, engine, "候補プール"))
                if raw_candidates else []
            )
            pool = self._unique(entered_norms + registered_norms)
            include_meta_provisional = args.get("include_meta_provisional")
            if include_meta_provisional not in (None, True, False):
                raise ValueError("メタ仮候補の指定が不正です")
            need_provisional = (
                include_meta_provisional is True
                or (include_meta_provisional is None and (not registered_norms or len({p["roster_clause_id"] for p in pool}) < 6))
            )
            if len(locked_norms) < 6 and need_provisional:
                used_clauses = {p["roster_clause_id"] for p in pool}
                meta_provisional = []
                for p in sorted(meta, key=lambda r: (-weights.get(r["id"], 0), r["species"])):
                    if p["roster_clause_id"] in used_clauses:
                        continue
                    if core.unverified_mechanic_reason(p["species"]):
                        continue
                    used_clauses.add(p["roster_clause_id"])
                    meta_provisional.append(p)
                    provisional_ids.add(p["id"])
                    if len(meta_provisional) >= 24 or len(pool) + len(meta_provisional) >= MAX_POOL:
                        break
                pool = self._unique(pool + meta_provisional)
                swap_source = "mixed" if registered_norms else "meta_provisional"
            else:
                swap_source = "registered" if registered_norms else ("all_locked" if len(locked_norms) == 6 else "entered")
            if len(pool) > MAX_POOL:
                pool = pool[:MAX_POOL]
            if len({p["roster_clause_id"] for p in pool}) < 6:
                raise ValueError("同種重複なしで6体を組める候補が不足しています。候補を追加するかメタ仮候補を有効にしてください")
        else:
            if mode == "build":
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
            if mode != "build" and len(own_raw) != 6:
                raise ValueError("分析するパーティは6体必要です")
            if mode == "build" and len(pool_raw) < 6:
                raise ValueError("自動構築は6体以上の候補が必要です")
            pool = self._unique(self._normalize(pool_raw, catalog, species, cpms, engine, "自分の候補"))
            if len(pool) < 6 and mode == "build":
                raise ValueError("異なる候補が6体必要です")
            if mode != "build" and len(pool) != 6:
                raise ValueError("同じポケモン・技・個体値の重複があります")
            clauses = [p["roster_clause_id"] for p in pool]
            if mode != "build" and len(set(clauses)) != 6:
                raise ValueError("同種のポケモンは6体へ重複登録できません")
            base_roster = [p["id"] for p in pool] if seek_swaps else []
            if seek_swaps:
                raw_candidates = args.get("candidate_pool") or []
                if not isinstance(raw_candidates, list):
                    raise ValueError("入れ替え候補の形式が不正です")
                if raw_candidates:
                    if len(raw_candidates) > MAX_POOL - len(base_roster):
                        raise ValueError("入れ替え候補は自分の6体と合わせて最大48体です")
                    replacement_pool = self._unique(self._normalize(
                        raw_candidates, catalog, species, cpms, engine, "入れ替え候補"))
                    swap_source = "registered"
                else:
                    used = {p["roster_clause_id"] for p in pool}
                    for p in meta:
                        if p["roster_clause_id"] in used or core.unverified_mechanic_reason(p["species"]):
                            continue
                        used.add(p["roster_clause_id"])
                        replacement_pool.append(p)
                        provisional_ids.add(p["id"])
                        if len(replacement_pool) == (24 if auto_complete else 12):
                            break
                    swap_source = "meta_provisional"
                pool = self._unique(pool + replacement_pool)

        enemy_raw = args.get("opponents") or []
        if mode == "select" and len(enemy_raw) != 6:
            raise ValueError("選出計算には相手6体が必要です")
        if enemy_raw and len(enemy_raw) != 6:
            raise ValueError("相手を指定する場合は6体にしてください")
        enemy = self._normalize(enemy_raw, catalog, species, cpms, engine, "相手6体") if enemy_raw else []
        if enemy and len({r["roster_clause_id"] for r in enemy}) != 6:
            raise ValueError("相手の6体に同種重複があります")

        self._record(jid, "running", {"progress": 2, "message": "対面を準備しています"}, owner_scope=owner)
        version = calculation_version(engine.DATA)
        if version is None:
            raise ValueError("エンジンの計算版を検証できません。キャッシュを使わず中止しました")

        recommendation_ids = {p["id"] for p in replacement_pool} - set(base_roster)
        if is_autocomplete:
            # Fast 2-2 screening for non-locked candidates first, then full 6/9-shield expansion for finalists.
            initial_set_ids = set(initial_slot_ids)
            screen_only_ids = {p["id"] for p in pool if p["id"] not in initial_set_ids and p["id"] not in set(locked_ids_unified)}
            matrix, stats = self._matrix(
                jid, pool, self._unique(meta + enemy), version, engine, work,
                enemy_ids={p["id"] for p in enemy},
                recommendation_only_ids=screen_only_ids, owner_scope=owner)
        else:
            matrix, stats = self._matrix(
                jid, pool, self._unique(meta + enemy), version, engine, work,
                enemy_ids={p["id"] for p in enemy},
                recommendation_only_ids=recommendation_ids, owner_scope=owner)

        # Compute 2-2 matchups among top meta species to drive generic Phase 1->2->3 meta evolution.
        evo_meta = [
            p for p in sorted(meta, key=lambda r: (-weights.get(r["id"], 0), r["species"]))
            if not core.unverified_mechanic_reason(p["species"])
        ][:20]
        evo_matrix = self._meta_evolution_matrix(evo_meta, version, engine, work, known=matrix)
        evolution_plan = core.evolve_meta_phases(meta, weights, evo_matrix)
        search_weights = evolution_plan["combined_weights"] if evolution_plan else weights

        ids = base_roster if seek_swaps else [p["id"] for p in pool]
        opponents = [p["id"] for p in meta]
        clause = {p["id"]: p["roster_clause_id"] for p in pool}
        autocomplete_result = None
        optimization = None
        swaps = None

        if is_autocomplete:
            self._record(jid, "running", {"progress": 90, "message": "時系列メタ変化（Phase 1→2→3）を踏まえ最適な6体を探索しています", "cache": stats}, owner_scope=owner)
            autocomplete_result = core.autocomplete_search(
                locked_ids_unified, [p["id"] for p in pool], opponents, matrix, search_weights, clause,
                initial_slots=initial_slot_ids, locked_slots=mapped_locked_slots,
                beam_width=min(32, max(1, int(args.get("beam_width", 16)))), max_finalists=3,
            )
            autocomplete_result["source"] = swap_source
            autocomplete_result["provisional_ids"] = sorted(provisional_ids)
            autocomplete_result["locked"] = list(locked_ids_unified)
            ids = list(autocomplete_result["roster"])
            # Expand full shield conditions for baseline (if 6) and all finalist rosters.
            compare_ids = set(ids)
            for proposed in autocomplete_result["finalists"]:
                compare_ids.update(proposed["roster"])
            if len(initial_slot_ids) == 6:
                compare_ids.update(initial_slot_ids)
            matrix, extra = self._matrix(
                jid, [p for p in pool if p["id"] in compare_ids],
                self._unique(meta + enemy), version, engine, work,
                enemy_ids={p["id"] for p in enemy}, full_conditions=True, known=matrix, owner_scope=owner)
            stats = {k: stats[k] + extra[k] for k in stats}
            # Attach unified visual comparison heatmaps for finalists.
            baseline_for_heat = list(initial_slot_ids) if len(initial_slot_ids) == 6 else list(ids)
            selected = []
            group_ids = set()
            for target in enemy:
                key = target["roster_clause_id"]
                if key not in group_ids:
                    selected.append(target)
                    group_ids.add(key)
            def risk_key_ac(target):
                ratings = [max((matrix.get((p, target["id"], shield), 500) for p in baseline_for_heat if matrix.get((p, target["id"], shield)) is not None), default=500)
                           for shield in core.ALL_SHIELDS]
                best = min(ratings, default=500)
                return (-int(best <= 500), -weights.get(target["id"], 0), best, target["species"])
            for target in sorted(meta, key=risk_key_ac):
                key = target["roster_clause_id"]
                if key not in group_ids:
                    selected.append(target)
                    group_ids.add(key)
                if len(selected) >= 20:
                    break
            display_ids = [p["id"] for p in selected[:20]]
            autocomplete_result["shields"] = [list(s) for s in core.ALL_SHIELDS]
            autocomplete_result["baseline_roster"] = baseline_for_heat
            autocomplete_result["heatmap_targets"] = display_ids
            autocomplete_result["enemy_targets"] = [p["id"] for p in enemy]
            autocomplete_result["baseline_by_shield"] = {
                f"{a}-{b}": core.party_matchup_heatmap(baseline_for_heat, display_ids, matrix, (a, b))
                for a, b in core.ALL_SHIELDS}
            autocomplete_result["baseline_heatmap"] = autocomplete_result["baseline_by_shield"]["2-2"]
            for proposed in autocomplete_result["finalists"]:
                proposed["by_shield"] = {
                    f"{a}-{b}": core.party_matchup_heatmap(proposed["roster"], display_ids, matrix, (a, b))
                    for a, b in core.ALL_SHIELDS}
                proposed["heatmap"] = proposed["by_shield"]["2-2"]
            optimization = autocomplete_result
            result = {"roster": ids}
        elif mode == "build":
            locked = [p["id"] for p in self._normalize(
                locked_raw, catalog, species, cpms, engine, "固定枠")] if locked_raw else []
            result = self._build_legal(ids, opponents, matrix, weights, locked, clause, args)
            ids = result["roster"]
        else:
            result = {"roster": ids}

        whole = core.team_summary(ids, opponents, matrix, weights)
        if seek_swaps:
            locked_slots = args.get("locked_slots") or []
            if (not isinstance(locked_slots, list) or
                    any(type(i) is not int or i < 0 or i >= len(ids)
                        for i in locked_slots)):
                raise ValueError("固定枠の指定が不正です")
            swaps = core.recommend_single_swaps(
                ids, list(recommendation_ids), opponents, matrix, weights,
                {p["id"]: p["roster_clause_id"] for p in pool},
                locked_slots=locked_slots)
            swaps["source"] = swap_source
            swaps["candidate_count"] = len(recommendation_ids)
        if auto_complete:
            self._record(jid, "running", {"progress": 96,
                "message": "最終パーティと弱点表を組み立てています", "cache": stats}, owner_scope=owner)
            choice_ids = list(dict.fromkeys([*ids, *recommendation_ids]))
            optimization = core.iterative_party_optimization(
                ids, choice_ids, opponents, matrix, weights, clause,
                locked_slots=locked_slots, max_steps=10, beam_width=8,
                max_finalists=3)
            optimization["source"] = swap_source
            optimization["candidate_count"] = len(recommendation_ids)
            if optimization["finalists"]:
                compare_ids = set(ids)
                for proposed in optimization["finalists"]:
                    compare_ids.update(proposed["roster"])
                matrix, extra = self._matrix(
                    jid, [p for p in pool if p["id"] in compare_ids],
                    self._unique(meta + enemy), version, engine, work,
                    enemy_ids={p["id"] for p in enemy}, full_conditions=True, known=matrix, owner_scope=owner)
                stats = {k: stats[k] + extra[k] for k in stats}
                optimization["shields"] = [list(s) for s in core.ALL_SHIELDS]
                optimization["baseline_roster"] = list(ids)
                selected = []
                group_ids = set()
                for target in enemy:
                    key = target["roster_clause_id"]
                    if key not in group_ids:
                        selected.append(target)
                        group_ids.add(key)
                def risk_key(target):
                    ratings = [max((matrix.get((p, target["id"], shield), 500) for p in ids if matrix.get((p, target["id"], shield)) is not None), default=500)
                               for shield in core.ALL_SHIELDS]
                    best = min(ratings, default=500)
                    return (-int(best <= 500), -weights.get(target["id"], 0),
                            best, target["species"])
                for target in sorted(meta, key=risk_key):
                    key = target["roster_clause_id"]
                    if key not in group_ids:
                        selected.append(target)
                        group_ids.add(key)
                    if len(selected) >= 20:
                        break
                display_ids = [p["id"] for p in selected[:20]]
                optimization["heatmap_targets"] = display_ids
                optimization["enemy_targets"] = [p["id"] for p in enemy]
                optimization["baseline_by_shield"] = {
                    f"{a}-{b}": core.party_matchup_heatmap(ids, display_ids, matrix, (a, b))
                    for a, b in core.ALL_SHIELDS}
                optimization["baseline_heatmap"] = optimization["baseline_by_shield"]["2-2"]
                for proposed in optimization["finalists"]:
                    proposed["by_shield"] = {
                        f"{a}-{b}": core.party_matchup_heatmap(proposed["roster"], display_ids, matrix, (a, b))
                        for a, b in core.ALL_SHIELDS}
                    proposed["heatmap"] = proposed["by_shield"]["2-2"]

        refinement = None
        if refine:
            from pvpoke_party_strategy import StrategyAnalysis
            finalists = (result["finalists"] if mode == "build" else
                         optimization["finalists"] if optimization and optimization["finalists"]
                         else [{"roster": ids}])
            refinement = StrategyAnalysis(self, jid, version, engine, work).refine(
                ids, finalists, {p["id"]: p for p in self._unique(pool + meta + enemy)},
                meta, matrix, weights)
            if mode == "build":
                result["finalists"] = refinement["finalists"]
                ids = result["roster"] = refinement["finalists"][0]["roster"]
                whole = core.team_summary(ids, opponents, matrix, weights)
            elif optimization:
                optimization["finalists"] = refinement["finalists"]
                if is_autocomplete:
                    ids = optimization["roster"] = refinement["finalists"][0]["roster"]
                    whole = core.team_summary(ids, opponents, matrix, weights)

        uncertainty = None
        if uncertainty_enabled:
            from pvpoke_party_uncertainty import analyze as analyze_uncertainty
            finalists = (result['finalists'] if mode == 'build' else
                         optimization['finalists'] if optimization and optimization['finalists']
                         else [{'roster': ids}])
            uncertainty = analyze_uncertainty(self, jid, version, engine, work, ids, finalists,
                {p['id']: p for p in self._unique(pool + meta + enemy)}, meta, matrix, weights,
                hypotheses, catalog, species, cpms)
            if mode == 'build':
                result['finalists'] = uncertainty['finalists']
                ids = result['roster'] = uncertainty['finalists'][0]['roster']
                whole = core.team_summary(ids, opponents, matrix, weights)
            elif optimization:
                optimization['finalists'] = uncertainty['finalists']
                if is_autocomplete:
                    ids = optimization['roster'] = uncertainty['finalists'][0]['roster']
                    whole = core.team_summary(ids, opponents, matrix, weights)

        # Standard six conditions are diagnostic weights, not battle frequencies.
        condition_weights = {(2, 2): .50, (1, 1): .20, (0, 0): .10,
                             (0, 1): .20 / 3, (0, 2): .20 / 3, (1, 2): .20 / 3}
        scenarios = {str(a) + "-" + str(b): core.team_summary(
            ids, opponents, matrix, weights, (a, b)) for a, b in SHIELDS_META}
        if refinement:
            from pvpoke_party_strategy import classify_pair
            detail_cells = {(c['member'], c['opponent']): c for c in refinement['cells']}
            selected_targets = [p for p in meta if p['id'] in refinement['targets']]
        pairs = []
        for a, b in __import__("itertools").combinations(ids, 2):
            by_condition = [(shields, core.pair_summary(a, b, opponents, matrix, weights, shields))
                            for shields in SHIELDS_META]
            main = core.pair_summary(a, b, opponents, matrix, weights)
            for metric in ("balance", "coverage", "hole"):
                main[metric] = round(sum(condition_weights[s] * v[metric]
                                         for s, v in by_condition), 6)
            main["standard_balance"] = next(v["balance"] for s, v in by_condition
                                             if s == (2, 2))
            main["conditions"] = {str(s[0]) + "-" + str(s[1]): {
                "balance": v["balance"], "hole": v["hole"]}
                for s, v in by_condition}
            if refinement:
                roles = classify_pair(a, b, selected_targets, detail_cells, matrix)
                main.update(roles)
                main['detail_status'] = ('標本内を評価済み' if all(
                    r['status'] == 'calculated' for r in roles.values()) else '一部未評価')
            pairs.append(main)
        pairs.sort(key=lambda r: -r["balance"])

        all_triples = core.evaluate_all_triples(
            ids, opponents, matrix, weights, clause=clause,
            enemy=[p["id"] for p in enemy] if enemy else None,
        )
        recommended_three = all_triples[:3]
        threats = core.dangerous_pairs(
            [row["members"] for row in all_triples[:3]], opponents, matrix, weights,
            {p["id"]: p["roster_clause_id"] for p in meta})
        chosen = (core.choose_three(ids, [p["id"] for p in enemy], matrix)
                  if enemy else {"status": "相手6体が未指定"})
        scenario_comparison = core.compare_scenarios(ids, opponents, matrix, compare_specs) if compare_specs else None
        meta_evolution = None
        if evolution_plan:
            evo_cmp = core.compare_scenarios(ids, opponents, matrix, evolution_plan["phases"])
            if evo_cmp:
                phase_by_id = {ph["id"]: ph for ph in evolution_plan["phases"]}
                for item in evo_cmp["scenarios"]:
                    ph = phase_by_id.get(item["id"], {})
                    item["stage"] = ph.get("stage")
                    item["short_name"] = ph.get("short_name", item["name"])
                    item["description"] = ph.get("description", "")
                    item["focus"] = ph.get("focus", [])
                    item["rising"] = ph.get("rising", [])
                    item["falling"] = ph.get("falling", [])
                evo_cmp["note"] = evolution_plan["note"]
                meta_evolution = evo_cmp
        unverified_mechanics = self._collect_unverified(self._unique(pool + meta + enemy), active_scenario, catalog)

        labels = {p["id"]: {"species": p["species"],
                  "moves": [p["fast"], p["charged1"], p["charged2"]],
                  "ivs": [p["atk"], p["def"], p["hp"]],
                  "cp": p["cp"], "level": p["level"],
                  "provisional": p["id"] in provisional_ids,
                  "unverified_mechanic": core.unverified_mechanic_reason(p["species"])}
                  for p in self._unique(pool + meta + enemy)}
        not_calculated = list(refinement["unknown"]) if refinement else [
            "通常技限定の圧力", "受け後の仕事", "観測ベースのシールド温存",
            "交代後の状態引継ぎ", "実戦3対3の勝率"]
        if uncertainty:
            not_calculated = [x for x in not_calculated if x != "相手IVの感度分析"]
            not_calculated.append("技・IV感度の未評価条件（標本外を含む）")
        scenario_meta = (
            {
                "id": active_scenario["id"],
                "name": active_scenario["name"],
                "revision": active_scenario.get("revision"),
                "kind": active_scenario.get("kind", "future"),
                "base_meta_id": preset_id,
                "base_meta_sha256": preset["sha256"],
                "assumptions": active_scenario.get("assumptions") or [],
                "chain_steps": active_scenario.get("chain_steps") or [],
            }
            if active_scenario else {
                "id": "current",
                "name": preset.get("name", preset_id),
                "revision": 0,
                "kind": "current",
                "base_meta_id": preset_id,
                "base_meta_sha256": preset["sha256"],
                "assumptions": [],
                "chain_steps": [],
            }
        )
        return {"roster": ids, "meta": {"id": preset_id, "sha256": preset["sha256"],
                "hypotheses": len(meta), "assumption": "仮説等分は使用率ではありません"},
                "scenario": scenario_meta,
                "scenario_comparison": scenario_comparison,
                "meta_evolution": meta_evolution,
                "unverified_mechanics": unverified_mechanics,
                "labels": labels, "team": whole, "scenarios": scenarios,
                "condition_weights": {"2-2": .50, "1-1": .20, "0-0": .10,
                    "0-1": .20 / 3, "0-2": .20 / 3, "1-2": .20 / 3},
                "pairs": pairs,
                "triples": all_triples,
                "recommended_three": recommended_three,
                "danger_pairs": threats, "selection": chosen,
                "search": result if mode == "build" else None,
                "autocomplete": autocomplete_result,
                "recommendations": swaps, "optimization": optimization, "refinement": refinement,
                "uncertainty": uncertainty,
                "calculation_version": version, "evaluation_version": core.EVALUATION_VERSION,
                "cache": stats, "not_calculated": not_calculated}

    def _strategy(self, jid, args, catalog, species, cpms, engine, work):
        from pvpoke_party_strategy import StrategyAnalysis, normalize_config
        own_raw, enemy_raw = args.get("members"), args.get("opponents")
        if not isinstance(own_raw, list) or len(own_raw) != 6:
            raise ValueError("詳細分析には自分の6体が必要です")
        if not isinstance(enemy_raw, list) or len(enemy_raw) not in (1, 6):
            raise ValueError("詳細分析には相手1体または6体が必要です")
        own = self._normalize(own_raw, catalog, species, cpms, engine, "自分6体")
        enemy = self._normalize(enemy_raw, catalog, species, cpms, engine, "相手")
        for roster in (own, enemy):
            if len({p["roster_clause_id"] for p in roster}) != len(roster):
                raise ValueError("大会の同種重複制限により同じ種族枠を複数選べません")
        for p in own + enemy:
            reason = core.unverified_mechanic_reason(p["species"])
            if reason:
                raise ValueError(reason)
        config = normalize_config(args.get("strategy", {}), own, enemy)
        version = calculation_version(engine.DATA)
        if version is None:
            raise ValueError("詳細計算のエンジン版を確認できません")
        return StrategyAnalysis(self, jid, version, engine, work).compute(own, enemy, config)

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
        finalists = sorted(set([best, *beam]),
                           key=lambda r: (core.rank_partial(r, opponents, matrix, weights), r))[:3]
        return {"roster": list(best), "finalists": [{"roster": list(r)} for r in finalists],
                "locked": locked, "beam_width": width,
                "candidate_count": len(candidates), "scope": "候補内の暫定結果。全探索ではありません"}

    def _matrix(self, jid, pool, opponents, version, engine, work, *, enemy_ids,
                recommendation_only_ids=frozenset(), full_conditions=False, known=None,
                owner_scope=DEFAULT_OWNER):
        # Cache namespaced by exact prepared inputs, engine/data version and direction.
        # Standard Matrix results are never confused with detailed policy outcomes.
        # Unverified mechanics (Mimikyu Disguise, Minior Limit Shield) stay unknown (None)
        # and are NEVER simulated or persisted into the cells cache.
        matrix, stats = dict(known or {}), {"hits": 0, "computed": 0}
        total = max(1, len(pool) * len(opponents) * 9)
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
                                    if (core.unverified_mechanic_reason(p["species"])
                                            or core.unverified_mechanic_reason(q["species"])):
                                        continue
                                    pair = (p["id"], q["id"])
                                    # All nine conditions for the 6v6; only six for meta.
                                    if not full_conditions and ((p["id"] in recommendation_only_ids and shield != core.STANDARD) or (shield not in SHIELDS_META and q["id"] not in enemy_ids)):
                                        continue
                                    if pair + (shield,) in matrix:
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
                                sim_own = [p for p in own_chunk if any(p["id"] == a for a, _ in missing_set)]
                                sim_opp = [q for q in opp_chunk if any(q["id"] == b for _, b in missing_set)]
                                if client is None:
                                    client = DirectMatrixClient(
                                        gamemaster=engine.DATA / "gamemaster.json", log_dir=work)
                                values = client.simulate(sim_own, sim_opp, shield)
                                for a, p in enumerate(sim_own):
                                    for b, q in enumerate(sim_opp):
                                        pair = (p["id"], q["id"])
                                        if pair not in missing_set:
                                            continue  # Valid cached cell wins; do not count as new.
                                        rating = values[a + 1][b + 1]
                                        matrix[pair + (shield,)] = rating
                                        db.execute("INSERT OR REPLACE INTO cells VALUES(?,?,?)",
                                                   (keys[pair], rating, int(time.time())))
                                        stats["computed"] += 1
                                db.commit()
                            done += len(own_chunk) * len(opp_chunk)
                            with self._lock:
                                if self._cancel:
                                    raise ValueError("cancelled")
                            self._record(jid, "running", {"progress": min(95, 2 + int(91 * done / total)),
                                "message": "比較用の全シールド条件を計算しています" if full_conditions else "対面を計算しています", "cache": stats}, owner_scope=owner_scope)
                # Bound storage size; never delete parties or saved analyses.
                db.execute("""DELETE FROM cells WHERE key IN
                           (SELECT key FROM cells ORDER BY created DESC LIMIT -1 OFFSET 120000)""")
                db.commit()
            finally:
                if client is not None:
                    client.close()
        return matrix, stats

    def _meta_evolution_matrix(self, evo_meta, version, engine, work, *, known=None):
        """Return a 2-2 matchup dict among top meta species using SQLite cache."""
        evo_matrix = dict(known or {})
        if len(evo_meta) < 2:
            return evo_matrix
        gamemaster = getattr(engine, "DATA", None)
        has_gm = bool(gamemaster and (Path(gamemaster) / "gamemaster.json").is_file())
        shield = core.STANDARD
        with self._db() as db:
            client = None
            try:
                for start in range(0, len(evo_meta), 6):
                    own_chunk = evo_meta[start:start + 6]
                    for col in range(0, len(evo_meta), 10):
                        opp_chunk = evo_meta[col:col + 10]
                        keys = {
                            (p["id"], q["id"]): core.digest(["party-cell-v1", version, p["id"], q["id"], shield])
                            for p in own_chunk for q in opp_chunk
                        }
                        missing = []
                        for p in own_chunk:
                            for q in opp_chunk:
                                pair = (p["id"], q["id"])
                                if pair + (shield,) in evo_matrix:
                                    continue
                                row = db.execute("SELECT rating FROM cells WHERE key=?", (keys[pair],)).fetchone()
                                if row is not None:
                                    evo_matrix[pair + (shield,)] = row[0]
                                elif has_gm:
                                    missing.append(pair)
                        if missing and has_gm:
                            missing_set = set(missing)
                            sim_own = [p for p in own_chunk if any(p["id"] == a for a, _ in missing_set)]
                            sim_opp = [q for q in opp_chunk if any(q["id"] == b for _, b in missing_set)]
                            if client is None:
                                client = DirectMatrixClient(
                                    gamemaster=Path(gamemaster) / "gamemaster.json", log_dir=work)
                            values = client.simulate(sim_own, sim_opp, shield)
                            for a, p in enumerate(sim_own):
                                for b, q in enumerate(sim_opp):
                                    pair = (p["id"], q["id"])
                                    if pair not in missing_set:
                                        continue
                                    rating = values[a + 1][b + 1]
                                    evo_matrix[pair + (shield,)] = rating
                                    db.execute("INSERT OR REPLACE INTO cells VALUES(?,?,?)",
                                               (keys[pair], rating, int(time.time())))
                            db.commit()
            finally:
                if client is not None:
                    client.close()
        return evo_matrix

