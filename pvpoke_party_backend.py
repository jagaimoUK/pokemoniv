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
        db.execute("CREATE TABLE IF NOT EXISTS meta_weights(species TEXT PRIMARY KEY, weight REAL NOT NULL)")
        return db

    def meta_weights(self, changes=None):
        """Owner-wide defaults; atomic per-species patches preserve unrelated edits."""
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
            "group_weights", "ruleset", "mega_rules", "opponents", "candidate_pool", "strategy", "strategy_refinement",
            "opponent_uncertainty", "opponent_hypotheses")}
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
            # PvPoke CSV export adds -shadow to the actual _shadow species ID.
            # Canonicalize before catalog/legality checks; never change the source CSV.
            if sid.endswith("_shadow-shadow"):
                sid = sid.removesuffix("-shadow")
            if not sid:
                raise ValueError(f"{label}: {i + 1}枠目のポケモンが未選択です")
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
            raw_ml = raw.get("mega_level")
            raw_c3 = raw.get("charged3")
            if (raw_ml is not None and raw_ml != "") or (raw_c3 is not None and str(raw_c3).strip()):
                from pvpoke_mega import is_mega_form
                sp_tags = set(p.get("tags") or ()) | set(species[sid].get("tags") or ())
                mega_capable = is_mega_form(sid) or ("mega" in sp_tags)
                if raw_ml is not None and raw_ml != "":
                    if type(raw_ml) is not int or not 1 <= raw_ml <= 4:
                        raise ValueError(label + ": mega_levelは1〜4の整数で指定してください")
                    if not mega_capable:
                        raise ValueError(label + ": メガレベルはメガ・ゲンシ形態のみ指定できます")
                    source["mega_level"] = raw_ml
                if raw_c3 is not None and str(raw_c3).strip():
                    c3 = str(raw_c3).strip().upper()
                    if not mega_capable:
                        raise ValueError(label + ": 追加ゲージ技はメガ・ゲンシ形態のみ指定できます")
                    has_extra_key = ("extraChargedMoves" in p) or ("extraChargedMoves" in species[sid])
                    extra = set(p.get("extraChargedMoves") or species[sid].get("extraChargedMoves") or ())
                    if has_extra_key and c3 not in extra:
                        raise ValueError(label + ": 未対応の追加ゲージ技です " + sid)
                    if c3 in moves[1:]:
                        raise ValueError(label + ": 追加ゲージ技が通常ゲージ技と重複しています " + sid)
                    source["charged3"] = c3
            p0 = engine.optimize([source], species, cpms, label)[0]
            if "mega_level" in source and "mega_level" not in p0:
                p0["mega_level"] = source["mega_level"]
            if "charged3" in source and "charged3" not in p0:
                p0["charged3"] = source["charged3"]
            p0["id"] = core.combatant_id(p0)
            p0["meta_group_id"] = str(raw.get("meta_group_id") or sid)
            # Species clause intentionally separate from battle identity.
            p0["roster_clause_id"] = str(species[sid].get("dex") or sid.replace("_shadow", ""))
            prepared.append(p0)
        return prepared

    @staticmethod
    def _unique(rows):
        return list({r["id"]: r for r in reversed(rows)}.values())[::-1]

    def start(self, args, *, catalog, species, cpms, engine, work, global_lock, global_status, release_owner=None):
        if not isinstance(args, dict) or args.get("mode") not in ("analyze", "select", "build", "strategy"):
            raise ValueError("modeはanalyze/select/build/strategyのいずれかです")
        self._mega_policy_from_args(args, engine_cp_cap=getattr(engine, "CP_CAP", 1500))
        if os.environ.get("PVP_ENGINE", "browser").lower() not in ("direct", "node"):
            raise ValueError("パーティ計算はDirectエンジンが必要です")
        with global_lock, self._lock:
            if self._active is not None or global_status.get("state") in ("running", "cancelling"):
                raise RuntimeError("他の計算中です。完了後に開始してください")
            jid = uuid.uuid4().hex
            prev_global = (global_status, global_lock, dict(global_status))
            self._active = jid
            self._cancel = False
            self._previous_global = prev_global
            try:
                self._record(jid, "queued", {"message": "準備しています", "progress": 0})
                global_status["state"] = "running"
                global_status["message"] = "パーティ作成の計算中"
                task = threading.Thread(target=self._worker, args=(
                    jid, args, catalog, species, cpms, engine, work, global_lock, release_owner), daemon=True)
                task.start()
            except Exception:
                self._active = None
                self._previous_global = None
                global_status["state"] = prev_global[2].get("state", "idle")
                global_status["message"] = prev_global[2].get("message", "")
                raise
        return {"job_id": jid, "status": "queued"}

    def cancel(self, jid):
        with self._lock:
            if jid != self._active:
                return {"cancel_requested": False}
            self._cancel = True
            return {"cancel_requested": True}

    def _worker(self, jid, args, catalog, species, cpms, engine, work, global_lock, release_owner=None):
        started = time.monotonic()
        try:
            result = self._compute(jid, args, catalog, species, cpms, engine, work)
            result["elapsed_seconds"] = round(time.monotonic() - started, 2)
            self._record(jid, "done", {"progress": 100, "result": result})
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
            self._record(jid, status, {"message": message, "progress": 0})
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
                    if release_owner is not None:
                        try:
                            release_owner()
                        except Exception:
                            pass

    @staticmethod
    def _mega_policy_from_args(args, *, engine_cp_cap=None):
        from pvpoke_mega import resolve_battle_rules, resolve_party_mega_rules
        ruleset = args.get("ruleset", "cp1500-lv50")
        raw_mega = args.get("mega_rules")
        if raw_mega is not None:
            if not isinstance(raw_mega, dict):
                raise ValueError("メガルール設定はオブジェクトで指定してください")
            rule_input = {"ruleset": ruleset, **raw_mega}
        else:
            rule_input = ruleset
        policy = resolve_party_mega_rules(rule_input)
        if engine_cp_cap is not None:
            meta_rules = raw_mega if isinstance(raw_mega, dict) else {}
            battle_rule = resolve_battle_rules({
                "league": meta_rules.get("league"),
                "cup_id": policy["effective_cup"],
                "cp_cap": meta_rules.get("cp_cap"),
            })
            if battle_rule["cp_cap"] not in (None, engine_cp_cap) or policy["effective_cup"] in (
                "ultra", "open_ultra", "ultra_mega", "master", "open_master"
            ) and engine_cp_cap == 1500:
                raise ValueError(f"現在はCP{engine_cp_cap}（スーパーリーグ系）のみ対応しています")
        if not policy["rule_verified"] or policy["max_megas_in_three"] is None:
            raise ValueError("大会・カップのメガ許可数が未確認のため、一律1体と仮定して計算できません")
        return policy

    @staticmethod
    def _mega_policy_from_args(args, *, engine_cp_cap=None):
        from pvpoke_mega import resolve_battle_rules, resolve_party_mega_rules
        ruleset = args.get("ruleset", "cp1500-lv50")
        raw_mega = args.get("mega_rules")
        if raw_mega is not None:
            if not isinstance(raw_mega, dict):
                raise ValueError("メガルール設定はオブジェクトで指定してください")
            rule_input = {"ruleset": ruleset, **raw_mega}
        else:
            rule_input = ruleset
        policy = resolve_party_mega_rules(rule_input)
        if engine_cp_cap is not None:
            meta_rules = raw_mega if isinstance(raw_mega, dict) else {}
            battle_rule = resolve_battle_rules({
                "league": meta_rules.get("league"),
                "cup_id": policy["effective_cup"],
                "cp_cap": meta_rules.get("cp_cap"),
            })
            if battle_rule["cp_cap"] not in (None, engine_cp_cap) or policy["effective_cup"] in (
                "ultra", "open_ultra", "ultra_mega", "master", "open_master"
            ) and engine_cp_cap == 1500:
                raise ValueError(f"現在はCP{engine_cp_cap}（スーパーリーグ系）のみ対応しています")
        if not policy["rule_verified"] or policy["max_megas_in_three"] is None:
            raise ValueError("大会・カップのメガ許可数が未確認のため、一律1体と仮定して計算できません")
        return policy

    def _compute(self, jid, args, catalog, species, cpms, engine, work):
        mega_policy = self._mega_policy_from_args(args, engine_cp_cap=getattr(engine, "CP_CAP", 1500))
        if args["mode"] == "strategy":
            return self._strategy(jid, args, catalog, species, cpms, engine, work)
        own_raw = args.get("members")
        locked_raw = []
        auto_complete = args["mode"] in ("analyze", "select") and args.get("auto_complete") is True
        refine = args.get("strategy_refinement", args["mode"] == "build" or auto_complete)
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
        seek_swaps = args["mode"] in ("analyze", "select") and (
            args.get("auto_replacements") is True or auto_complete)
        if (args.get("auto_replacements") not in (None, True, False) or
                args.get("auto_complete") not in (None, True, False)):
            raise ValueError("入れ替え探索の指定が不正です")
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
        if any(p["species"].startswith("minior") for p in pool):
            raise ValueError("メテノの対面ごとの最良戦略は単一の実行可能戦略ではないため、パーティ計算では未対応です")
        if len(pool) < 6 and args["mode"] == "build":
            raise ValueError("異なる候補が6体必要です")
        if args["mode"] != "build" and len(pool) != 6:
            raise ValueError("同じポケモン・技・個体値の重複があります")
        clauses = [p["roster_clause_id"] for p in pool]
        if args["mode"] != "build" and len(set(clauses)) != 6:
            raise ValueError("同種のポケモンは6体へ重複登録できません")
        from pvpoke_mega import is_mega_form
        if args["mode"] != "build" and sum(1 for p in pool if is_mega_form(p["species"])) > mega_policy["max_megas_in_six"]:
            raise ValueError(f"6体登録のメガ候補上限（最大{mega_policy['max_megas_in_six']}体）を超えています")
        preset_id = args.get("meta_preset_id") or "legacy"
        meta_file, preset = presets.snapshot(work, preset_id, catalog,
                                              args.get("meta_sha256"))
        with meta_file.open(encoding="utf-8-sig", newline="") as stream:
            meta_raw = [dict(zip(engine.HEADER[:4], row))
                        for row in csv.reader(stream) if row]
        if len(meta_raw) > MAX_META:
            raise ValueError(f"メタは最大{MAX_META}技構成です。プリセットを絞ってください")
        meta = self._unique(self._normalize(meta_raw, catalog, species, cpms, engine, "メタ"))
        weights = core.weight_rows(meta, args.get("group_weights"))
        # Excluded groups need neither simulation nor search evaluation.
        meta = [row for row in meta if weights[row["id"]] > 0]
        base_roster = [p["id"] for p in pool] if seek_swaps else []
        replacement_pool = []
        swap_source = "none"
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
                # Explore only a bounded number of meta hypotheses, not every species.
                used = {p["roster_clause_id"] for p in pool}
                for p in meta:
                    if p["roster_clause_id"] in used:
                        continue
                    used.add(p["roster_clause_id"])
                    replacement_pool.append(p)
                    if len(replacement_pool) == (24 if auto_complete else 12):
                        break
                swap_source = "meta_provisional"
            pool = self._unique(pool + replacement_pool)
        enemy_raw = args.get("opponents") or []
        if args["mode"] == "select" and len(enemy_raw) != 6:
            raise ValueError("選出計算には相手6体が必要です")
        if enemy_raw and len(enemy_raw) != 6:
            raise ValueError("相手を指定する場合は6体にしてください")
        enemy = self._normalize(enemy_raw, catalog, species, cpms, engine, "相手6体") if enemy_raw else []
        if enemy and len({r["roster_clause_id"] for r in enemy}) != 6:
            raise ValueError("相手の6体に同種重複があります")
        if enemy and sum(1 for r in enemy if is_mega_form(r["species"])) > mega_policy["max_megas_in_six"]:
            raise ValueError(f"相手6体登録のメガ候補上限（最大{mega_policy['max_megas_in_six']}体）を超えています")
        self._record(jid, "running", {"progress": 2, "message": "対面を準備しています"})
        version = calculation_version(engine.DATA)
        if version is None:
            raise ValueError("エンジンの計算版を検証できません。キャッシュを使わず中止しました")
        recommendation_ids = {p["id"] for p in replacement_pool} - set(base_roster)
        matrix, stats = self._matrix(
            jid, pool, self._unique(meta + enemy), version, engine, work,
            enemy_ids={p["id"] for p in enemy},
            recommendation_only_ids=recommendation_ids)
        ids = base_roster if seek_swaps else [p["id"] for p in pool]
        opponents = [p["id"] for p in meta]
        clause = {p["id"]: p["roster_clause_id"] for p in pool}
        if args["mode"] == "build":
            from pvpoke_mega import is_mega_form
            locked = [p["id"] for p in self._normalize(
                locked_raw, catalog, species, cpms, engine, "固定枠")] if locked_raw else []
            # Search cannot put the same species in two slots.
            groups = {}
            for p in pool:
                groups.setdefault(p["roster_clause_id"], []).append(p["id"])
            # Check species and Mega legality constraints in the search output as well.
            build_mega_ids = {p["id"] for p in pool if is_mega_form(p["species"])}
            result = self._build_legal(
                ids, opponents, matrix, weights, locked, clause, args,
                mega_ids=build_mega_ids, mega_policy=mega_policy)
            ids = result["roster"]
        else:
            result = {"roster": ids}
        whole = core.team_summary(ids, opponents, matrix, weights)
        swaps = None
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
        optimization = None
        if auto_complete:
            self._record(jid, "running", {"progress": 96,
                "message": "最終パーティと弱点表を組み立てています", "cache": stats})
            choice_ids = list(dict.fromkeys([*ids, *recommendation_ids]))
            optimization = core.iterative_party_optimization(
                ids, choice_ids, opponents, matrix, weights, clause,
                locked_slots=locked_slots, max_steps=10, beam_width=8,
                max_finalists=3)
            optimization["source"] = swap_source
            optimization["candidate_count"] = len(recommendation_ids)
            if optimization["finalists"]:
                # Expand only the original roster and the final proposals, not the search pool.
                compare_ids = set(ids)
                for proposed in optimization["finalists"]:
                    compare_ids.update(proposed["roster"])
                matrix, extra = self._matrix(
                    jid, [p for p in pool if p["id"] in compare_ids],
                    self._unique(meta + enemy), version, engine, work,
                    enemy_ids={p["id"] for p in enemy}, full_conditions=True, known=matrix)
                stats = {k: stats[k] + extra[k] for k in stats}
                optimization["shields"] = [list(s) for s in core.ALL_SHIELDS]
                optimization["baseline_roster"] = list(ids)
                # Show requested opposing six first, then the important and
                # poorly-covered meta opponents. Never mix unknown with losses.
                selected = []
                group_ids = set()
                for target in enemy:
                    key = target["roster_clause_id"]
                    if key not in group_ids:
                        selected.append(target)
                        group_ids.add(key)
                def risk_key(target):
                    ratings = [max((matrix.get((p, target["id"], shield), 500) for p in ids), default=500)
                               for shield in core.ALL_SHIELDS]
                    best = min((x for x in ratings if x is not None), default=500)
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
            finalists = (result["finalists"] if args["mode"] == "build" else
                         optimization["finalists"] if optimization and optimization["finalists"]
                         else [{"roster": ids}])
            refinement = StrategyAnalysis(self, jid, version, engine, work).refine(
                ids, finalists, {p["id"]: p for p in self._unique(pool + meta + enemy)},
                meta, matrix, weights)
            if args["mode"] == "build":
                result["finalists"] = refinement["finalists"]
                ids = result["roster"] = refinement["finalists"][0]["roster"]
                whole = core.team_summary(ids, opponents, matrix, weights)
            elif optimization:
                optimization["finalists"] = refinement["finalists"]
        uncertainty = None
        if uncertainty_enabled:
            from pvpoke_party_uncertainty import analyze as analyze_uncertainty
            finalists = (result['finalists'] if args['mode'] == 'build' else
                         optimization['finalists'] if optimization and optimization['finalists']
                         else [{'roster': ids}])
            uncertainty = analyze_uncertainty(self, jid, version, engine, work, ids, finalists,
                {p['id']: p for p in self._unique(pool + meta + enemy)}, meta, matrix, weights,
                hypotheses, catalog, species, cpms)
            if args['mode'] == 'build':
                result['finalists'] = uncertainty['finalists']
                ids = result['roster'] = uncertainty['finalists'][0]['roster']
                whole = core.team_summary(ids, opponents, matrix, weights)
            elif optimization:
                optimization['finalists'] = uncertainty['finalists']
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
        from pvpoke_mega import is_mega_form
        own_mega_ids = {p["id"] for p in pool if is_mega_form(p["species"])}
        enemy_mega_ids = {p["id"] for p in enemy if is_mega_form(p["species"])}
        max_megas_3 = mega_policy["max_megas_in_three"]
        triples = [{"members": list(group),
                    "summary": core.team_summary(group, opponents, matrix, weights)}
                   for group in core.legal_triples(
                       ids, clause=clause, mega_ids=own_mega_ids, max_megas=max_megas_3)]
        triples.sort(key=lambda r: (r["summary"]["unknown_weight"], r["summary"]["d0"],
                                    r["summary"]["severity0"]))
        threats = core.dangerous_pairs(
            [row["members"] for row in triples[:3]], opponents, matrix, weights,
            {p["id"]: p["roster_clause_id"] for p in meta})
        chosen = (core.choose_three(
            ids, [p["id"] for p in enemy], matrix,
            clause=clause, mega_ids=own_mega_ids, max_megas=max_megas_3,
            enemy_clause={p["id"]: p["roster_clause_id"] for p in enemy},
            enemy_mega_ids=enemy_mega_ids, enemy_max_megas=max_megas_3)
                  if enemy else {"status": "相手6体が未指定"})
        labels = {p["id"]: {"species": p["species"],
                  "moves": [p["fast"], p["charged1"], p["charged2"]],
                  "ivs": [p["atk"], p["def"], p["hp"]],
                  "cp": p["cp"], "level": p["level"],
                  **({"mega_level": p["mega_level"]} if p.get("mega_level") is not None else {}),
                  **({"charged3": p["charged3"]} if p.get("charged3") else {})}
                  for p in self._unique(pool + meta + enemy)}
        not_calculated = list(refinement["unknown"]) if refinement else [
            "通常技限定の圧力", "受け後の仕事", "観測ベースのシールド温存",
            "交代後の状態引継ぎ", "実戦3対3の勝率"]
        if uncertainty:
            not_calculated = [x for x in not_calculated if x != "相手IVの感度分析"]
            not_calculated.append("技・IV感度の未評価条件（標本外を含む）")
        return {"roster": ids, "meta": {"id": preset_id, "sha256": preset["sha256"],
                "hypotheses": len(meta), "assumption": "仮説等分は使用率ではありません"},
                "labels": labels, "team": whole, "scenarios": scenarios,
                "condition_weights": {"2-2": .50, "1-1": .20, "0-0": .10,
                    "0-1": .20 / 3, "0-2": .20 / 3, "1-2": .20 / 3},
                "pairs": pairs,
                "triples": triples, "danger_pairs": threats, "selection": chosen, "search": result if args["mode"] == "build" else None,
                "recommendations": swaps, "optimization": optimization, "refinement": refinement,
                "uncertainty": uncertainty, "mega_policy": mega_policy,
                "calculation_version": version, "evaluation_version": core.EVALUATION_VERSION,
                "cache": stats, "not_calculated": not_calculated}

    def _strategy(self, jid, args, catalog, species, cpms, engine, work):
        from pvpoke_mega import is_mega_form
        from pvpoke_party_strategy import StrategyAnalysis, normalize_config
        mega_policy = self._mega_policy_from_args(args)
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
            if sum(1 for p in roster if is_mega_form(p["species"])) > mega_policy["max_megas_in_six"]:
                raise ValueError(f"6体登録のメガ候補上限（最大{mega_policy['max_megas_in_six']}体）を超えています")
        if any(p["species"].startswith("minior") for p in own + enemy):
            raise ValueError("メテノの固定方針による詳細分析は未対応です")
        config = normalize_config(args.get("strategy", {}), own, enemy)
        version = calculation_version(engine.DATA)
        if version is None:
            raise ValueError("詳細計算のエンジン版を確認できません")
        return StrategyAnalysis(self, jid, version, engine, work).compute(own, enemy, config)

    @staticmethod
    def _build_legal(ids, opponents, matrix, weights, locked, clause, args,
                     *, mega_ids=None, mega_policy=None):
        if len({clause[x] for x in locked}) != len(locked):
            raise ValueError("固定枠に同種が含まれています")
        megas = set(mega_ids or ())
        if mega_policy is not None:
            max_in_six = mega_policy["max_megas_in_six"]
            max_in_three = mega_policy["max_megas_in_three"]
            effective_six_mega_cap = min(max_in_six, 3 + max_in_three) if max_in_three is not None else max_in_six
        else:
            effective_six_mega_cap = None
        if effective_six_mega_cap is not None and sum(1 for x in locked if x in megas) > effective_six_mega_cap:
            raise ValueError("固定枠のメガ候補数が大会・カップの許可上限を超えています")
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
                mega_used = sum(1 for x in partial if x in megas)
                choices = [
                    x for x in candidates
                    if x not in partial and clause[x] not in existing
                    and (effective_six_mega_cap is None or x not in megas or mega_used < effective_six_mega_cap)
                ]
                choices.sort(key=lambda x: core.rank_partial((*partial, x), opponents, matrix, weights))
                for x in choices[:24]:
                    roster = tuple(sorted((*partial, x)))
                    pool[roster] = core.rank_partial(roster, opponents, matrix, weights)
            beam = sorted(pool, key=lambda x: (pool[x], x))[:width]
            if not beam:
                raise ValueError("種族重複・メガ枠制限を満たして6体を組めません")
        best = beam[0]
        for _ in range(2):
            options = [(core.rank_partial(best, opponents, matrix, weights), best)]
            for old in best:
                if old in locked:
                    continue
                keep = [x for x in best if x != old]
                used = {clause[x] for x in keep}
                mega_used = sum(1 for x in keep if x in megas)
                for replacement in candidates:
                    if clause[replacement] in used:
                        continue
                    if effective_six_mega_cap is not None and replacement in megas and mega_used >= effective_six_mega_cap:
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
                recommendation_only_ids=frozenset(), full_conditions=False, known=None):
        # Cache namespaced by exact prepared inputs, engine/data version and direction.
        # Standard Matrix results are never confused with detailed policy outcomes.
        matrix, stats = dict(known or {}), {"hits": 0, "computed": 0}
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
                                if client is None:
                                    client = DirectMatrixClient(
                                        gamemaster=engine.DATA / "gamemaster.json", log_dir=work)
                                values = client.simulate(own_chunk, opp_chunk, shield)
                                for a, p in enumerate(own_chunk):
                                    for b, q in enumerate(opp_chunk):
                                        pair = (p["id"], q["id"])
                                        if not full_conditions and ((p["id"] in recommendation_only_ids and shield != core.STANDARD) or (shield not in SHIELDS_META and q["id"] not in enemy_ids)):
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
                                "message": "比較用の全シールド条件を計算しています" if full_conditions else "対面を計算しています", "cache": stats})
                # Bound storage size; never delete parties or saved analyses.
                db.execute("""DELETE FROM cells WHERE key IN
                           (SELECT key FROM cells ORDER BY created DESC LIMIT -1 OFFSET 120000)""")
                db.commit()
            finally:
                if client is not None:
                    client.close()
        return matrix, stats


def owned_candidates_for_party(ownership_store, catalog: dict, *, limit: int = 128) -> dict:
    """Export confirmed-owned inventory records into validated Party Builder candidate rows."""
    from pvpoke_mega import is_mega_form

    snap = ownership_store.list_snapshot(state="confirmed_owned", limit=limit, include_scopes=False)
    items = []
    skipped = 0
    for record in snap.get("items") or ():
        sid = str(record.get("species_id") or "").strip().lower()
        entry = catalog.get(sid) if isinstance(catalog, dict) else None
        if not entry:
            skipped += 1
            continue
        fast_pool = list(entry.get("fastMoves") or ())
        charged_pool = list(entry.get("chargedMoves") or ())
        if not fast_pool or len(charged_pool) < 2:
            skipped += 1
            continue
        default_moves = entry.get("default_moves") if isinstance(entry.get("default_moves"), dict) else {}
        obs_moves = record.get("current_moves") if isinstance(record.get("current_moves"), dict) else {}
        obs_fast = str(obs_moves.get("fast") or "").strip().upper()
        fast = obs_fast if obs_fast in fast_pool else (
            default_moves.get("fast") if default_moves.get("fast") in fast_pool else fast_pool[0]
        )
        obs_charged = [str(m or "").strip().upper() for m in (obs_moves.get("charged") or ()) if str(m or "").strip()]
        c1 = obs_charged[0] if len(obs_charged) >= 1 and obs_charged[0] in charged_pool else None
        c2 = obs_charged[1] if len(obs_charged) >= 2 and obs_charged[1] in charged_pool and obs_charged[1] != c1 else None
        if not c1:
            def_c1 = default_moves.get("charged1")
            c1 = def_c1 if def_c1 in charged_pool and def_c1 != c2 else next((m for m in charged_pool if m != c2), None)
        if not c2:
            def_c2 = default_moves.get("charged2")
            c2 = def_c2 if def_c2 in charged_pool and def_c2 != c1 else next((m for m in charged_pool if m != c1), None)
        if not c1 or not c2 or c1 == c2:
            skipped += 1
            continue

        ivs = record.get("ivs") if isinstance(record.get("ivs"), dict) else {}
        try:
            raw_atk = ivs["attack"] if "attack" in ivs else ivs["atk"]
            raw_def = ivs["defense"] if "defense" in ivs else ivs["def"]
            atk = int(raw_atk)
            defense = int(raw_def)
            hp = int(ivs["hp"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if not all(0 <= v <= 15 for v in (atk, defense, hp)):
            skipped += 1
            continue

        row = {
            "species": sid,
            "fast": fast,
            "charged1": c1,
            "charged2": c2,
            "atk": atk,
            "def": defense,
            "hp": hp,
            "instance_id": record.get("instance_id"),
            "current_cp": record.get("current_cp"),
        }
        cur_lv = record.get("current_level")
        if isinstance(cur_lv, (int, float)) and 1 <= cur_lv <= 50:
            row["level_override"] = cur_lv
        tags = set(entry.get("tags") or ())
        mega_capable = is_mega_form(sid) or ("mega" in tags)
        raw_ml = record.get("mega_level")
        if mega_capable and type(raw_ml) is int and 1 <= raw_ml <= 4:
            row["mega_level"] = raw_ml
        extra_pool = list(entry.get("extraChargedMoves") or ())
        raw_c3 = record.get("charged3") or (obs_charged[2] if len(obs_charged) >= 3 else None)
        if mega_capable and isinstance(raw_c3, str):
            c3 = raw_c3.strip().upper()
            if c3 and c3 in extra_pool and c3 not in (c1, c2):
                row["charged3"] = c3
        items.append(row)

    return {
        "ledger_revision": snap.get("ledger_revision", 0),
        "items": items,
        "has_more": bool(snap.get("has_more", False)),
        "skipped_count": skipped,
    }
