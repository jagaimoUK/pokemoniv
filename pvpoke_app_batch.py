"""Durable, authenticated-app-only sequential IV batch controller.

The browser may disappear; the server owns the queue. Every completed result
and next index commit in one SQLite transaction. An interrupted in-flight
calculation is re-evaluated with the existing exact-input verification.
No PvPoke ChatGPT connector or external notification service is involved.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import zlib

from pvpoke_input_limits import MAX_APP_REQUEST_BYTES
from pvpoke_iv_workflow import _canonical, SHA256
from pvpoke_app_selection import validate_policy

MAX_JOBS = 128
MAX_RESULT_BYTES = 20 * 1024 * 1024
MAX_DB_BYTES = 300 * 1024 * 1024
LEASE_SECONDS = 75
REF_RE = re.compile(r"^[0-9a-f]{32}$")
REQUEST_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


class DurableSelectionBatch:
    def __init__(self, runner, path: Path, *, retry_delay: float = 3.0):
        self.runner = runner
        self.path = Path(path)
        self.retry_delay = retry_delay
        self._lock = threading.RLock()
        self._workers = {}
        self._owner = uuid.uuid4().hex
        with self._db():
            pass

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=8)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=8000")
            db.execute("""CREATE TABLE IF NOT EXISTS batches(
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL, idx INTEGER NOT NULL DEFAULT 0,
            attempt INTEGER NOT NULL DEFAULT 0, revision TEXT,
            error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0,
            created INTEGER NOT NULL, updated INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS batch_results(
            batch_id TEXT NOT NULL, idx INTEGER NOT NULL, content BLOB NOT NULL,
            PRIMARY KEY(batch_id,idx),
            FOREIGN KEY(batch_id) REFERENCES batches(id))""")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _validate(payload):
        if not isinstance(payload, dict):
            raise ValueError("計算の入力形式が不正です")
        jobs = payload.get("jobs")
        if not isinstance(jobs, list) or not 1 <= len(jobs) <= MAX_JOBS:
            raise ValueError(f"計算対象は1〜{MAX_JOBS}構成で指定してください")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_RE.fullmatch(request_id):
            raise ValueError("計算の再試行IDが不正です")
        mode = payload.get("batch_mode", "simple")
        if mode not in ("simple", "detailed"):
            raise ValueError("計算モードが不正です")
        if payload.get("report_format", "app") != "app":
            raise ValueError("Web厳選はapp形式のみ使用できます")
        if type(payload.get("force_recalculate", False)) is not bool:
            raise ValueError("再計算設定が不正です")
        focus = payload.get("focus", [])
        if not isinstance(focus, list) or len(focus) > 15 or any(
            not isinstance(x, str) or not 1 <= len(x.strip()) <= 100 for x in focus
        ):
            raise ValueError("重要な相手の設定が不正です")
        validate_policy(payload.get("policy"))
        meta = payload.get("meta_sha256")
        if meta is not None and (not isinstance(meta, str) or not SHA256.fullmatch(meta)):
            raise ValueError("メタのハッシュが不正です")
        preset = payload.get("meta_preset_id")
        if preset is not None and (not isinstance(preset, str) or len(preset) > 100):
            raise ValueError("メタプリセット指定が不正です")
        # Never persist client-supplied results, progress or authentication fields.
        allowed = ("jobs", "batch_mode", "report_format", "focus", "policy",
                   "force_recalculate", "meta_sha256", "meta_preset_id", "auto_moves",
                   "compare_moves", "move_strategy", "move_threshold",
                   "move_threshold_setting", "reader_automation_digest")
        data = {key: payload[key] for key in allowed if key in payload}
        for job in jobs:
            if not isinstance(job, dict):
                raise ValueError("計算対象が不正です")
            _canonical(job.get("candidate"), job.get("ivs"), job.get("batch_mode", mode))
            if not isinstance(job.get("name", ""), str) or len(job.get("name", "")) > 120:
                raise ValueError("ポケモン名が不正です")
        encoded = _json(data).encode("utf-8")
        if len(encoded) > MAX_APP_REQUEST_BYTES - 1024:
            raise ValueError("一度に計算するデータが大きすぎます")
        digest = hashlib.sha256(encoded).hexdigest()
        return request_id, encoded.decode("utf-8"), digest

    def start(self, payload):
        request_id, content, digest = self._validate(payload)
        if self.path.stat().st_size > MAX_DB_BYTES:
            raise ValueError("保存容量の上限に達しました。既存データを保護するため新規計算は開始しません")
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id,request_hash FROM batches WHERE request_id=?",
                                  (request_id,)).fetchone()
            if existing:
                if existing["request_hash"] != digest:
                    raise ValueError("同じ再試行IDで異なる計算条件は開始できません")
                bid = existing["id"]
            else:
                busy = db.execute("SELECT id FROM batches WHERE state IN ('running','paused') LIMIT 1").fetchone()
                if busy:
                    raise ValueError("前の計算が残っています。進捗を確認するか再開・中止してください")
                bid = uuid.uuid4().hex
                now = int(time.time())
                db.execute("""INSERT INTO batches(id,request_id,request_hash,payload,state,idx,
                    created,updated) VALUES(?,?,?,?,'running',0,?,?)""",
                           (bid, request_id, digest, content, now, now))
        self._spawn(bid)
        return self.status(bid)

    def recover(self):
        with self._db() as db:
            ids = [row["id"] for row in db.execute(
                "SELECT id FROM batches WHERE state='running'")]
        for bid in ids:
            self._spawn(bid)

    def _spawn(self, bid):
        with self._lock:
            old = self._workers.get(bid)
            if old is not None and old.is_alive():
                return
            task = threading.Thread(target=self._worker, args=(bid,), daemon=True,
                                    name="iv-selection-batch")
            self._workers[bid] = task
            task.start()

    @staticmethod
    def _valid_id(batch_id):
        if not isinstance(batch_id, str) or not REF_RE.fullmatch(batch_id):
            raise ValueError("計算IDが不正です")
        return batch_id

    def status(self, batch_id, *, include_results=False, include_plan=False):
        bid = self._valid_id(batch_id)
        if type(include_results) is not bool or type(include_plan) is not bool:
            raise ValueError("結果取得の指定が不正です")
        with self._db() as db:
            row = db.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
            if not row:
                raise ValueError("保存された計算が見つかりません")
            plan = json.loads(row["payload"])
            result = {"batch_id": bid, "state": row["state"], "index": row["idx"],
                      "total": len(plan["jobs"]), "error": row["error"],
                      "cancel_requested": bool(row["cancel_requested"]),
                      "updated_at": row["updated"]}
            if include_plan:
                result["plan"] = plan
            if include_results:
                results = list(db.execute(
                    "SELECT idx,content FROM batch_results WHERE batch_id=? ORDER BY idx", (bid,)))
                if len(results) != row["idx"] or any(i != item["idx"] for i, item in enumerate(results)):
                    raise ValueError("保存された結果の順序を検証できません")
                result["results"] = [json.loads(zlib.decompress(x["content"])) for x in results]
            return result

    def cancel(self, batch_id):
        bid = self._valid_id(batch_id)
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
            if row is None:
                raise ValueError("保存された計算が見つかりません")
            if row["state"] in ("done", "cancelled"):
                return self.status(bid)
            state = "cancelled" if row["state"] == "paused" else row["state"]
            db.execute("UPDATE batches SET cancel_requested=1,state=?,updated=? WHERE id=?",
                       (state, int(time.time()), bid))
        return self.status(bid)

    def resume(self, batch_id):
        bid = self._valid_id(batch_id)
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM batches WHERE id=?", (bid,)).fetchone()
            if row is None or row["state"] != "paused":
                raise ValueError("再開できる一時停止中の計算ではありません")
            db.execute("""UPDATE batches SET state='running',error=NULL,
                cancel_requested=0,lease_owner=NULL,lease_until=0,updated=? WHERE id=?""",
                       (int(time.time()), bid))
        self._spawn(bid)
        return self.status(bid)

    def _claim(self, bid):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,lease_owner,lease_until FROM batches WHERE id=?",
                             (bid,)).fetchone()
            if row is None or row["state"] != "running":
                return False
            now = time.time()
            if row["lease_owner"] not in (None, self._owner) and row["lease_until"] > now:
                return None
            db.execute("UPDATE batches SET lease_owner=?,lease_until=? WHERE id=?",
                       (self._owner, now + LEASE_SECONDS, bid))
        return True

    def _renew(self, bid):
        with self._db() as db:
            cursor = db.execute("""UPDATE batches SET lease_until=? WHERE id=?
                AND lease_owner=? AND state='running'""",
                (time.time() + LEASE_SECONDS, bid, self._owner))
            return cursor.rowcount == 1

    def _mark(self, bid, state, error=None):
        with self._db() as db:
            db.execute("""UPDATE batches SET state=?,error=?,lease_owner=NULL,
                lease_until=0,updated=? WHERE id=? AND lease_owner=?""",
                (state, error, int(time.time()), bid, self._owner))

    def _failed_attempt(self, bid):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT attempt FROM batches WHERE id=? AND lease_owner=?",
                             (bid, self._owner)).fetchone()
            if row is None:
                return 100
            attempts = row["attempt"] + 1
            db.execute("UPDATE batches SET attempt=?,updated=? WHERE id=?",
                       (attempts, int(time.time()), bid))
            return attempts

    def _store(self, bid, index, result):
        raw = _json(result).encode("utf-8")
        compressed = zlib.compress(raw, level=6)
        if len(raw) > MAX_RESULT_BYTES or len(compressed) > MAX_RESULT_BYTES:
            raise ValueError("計算結果が保存可能な上限を超えました")
        revision = result.get("calculation_version")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT idx,revision,state,lease_owner FROM batches
                WHERE id=?""", (bid,)).fetchone()
            if (row is None or row["idx"] != index or row["state"] != "running"
                    or row["lease_owner"] != self._owner):
                raise RuntimeError("計算の進行状態が変わりました")
            if row["revision"] is not None and row["revision"] != revision:
                raise ValueError("計算版が途中で変わりました。異なる結果を混ぜず一時停止しました")
            db.execute("INSERT INTO batch_results(batch_id,idx,content) VALUES(?,?,?)",
                       (bid, index, compressed))
            db.execute("""UPDATE batches SET idx=idx+1,attempt=0,revision=?,updated=?
                WHERE id=?""", (revision, int(time.time()), bid))

    def _one(self, bid, row, plan):
        index = row["idx"]
        job = plan["jobs"][index]
        mode = job.get("batch_mode", plan.get("batch_mode", "simple"))
        opts = {
            "candidate": job["candidate"], "ivs": job["ivs"], "batch_mode": mode,
            "focus_opponents": plan.get("focus", []), "report_format": "app",
            "selection_policy": plan.get("policy"),
            "meta_preset_id": plan.get("meta_preset_id"),
            "expected_meta_sha256": plan.get("meta_sha256"),
            "force_recalculate": plan.get("force_recalculate", False),
            "request_id": "batch" + bid + "-" + str(index) + "-" + str(row["attempt"]),
            "wait_seconds": 0,
        }
        response = self.runner.run(**opts)
        ref = response.get("run_ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("計算の識別情報を取得できません")
        while response.get("state") in ("running", "cancelling"):
            if not self._renew(bid):
                raise RuntimeError("計算処理の実行権を失いました")
            with self._db() as db:
                cancelled = db.execute("SELECT cancel_requested FROM batches WHERE id=?",
                                       (bid,)).fetchone()["cancel_requested"]
            if cancelled:
                self.runner.cancel(ref)
            response = self.runner.result(ref, wait_seconds=8)
        if response.get("state") == "cancelled":
            self._mark(bid, "cancelled")
            return
        if response.get("state") != "done" or not response.get("complete"):
            raise RuntimeError("計算エンジンが完了できませんでした")
        for key, source in (("display_name", "name"), ("source_sections", "source_sections"),
                            ("source_records", "source_records"), ("pokemon_status", "pokemon_status"),
                            ("moveset_group", "moveset_group"), ("moveset_plan", "moveset_plan")):
            if source in job:
                response[key] = job[source]
        self._store(bid, index, response)

    def _worker(self, bid):
        try:
            while True:
                lease = self._claim(bid)
                if lease is False:
                    return
                if lease is None:
                    time.sleep(5)
                    continue
                with self._db() as db:
                    row = db.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
                plan = json.loads(row["payload"])
                if row["cancel_requested"]:
                    self._mark(bid, "cancelled")
                    return
                if row["idx"] >= len(plan["jobs"]):
                    self._mark(bid, "done")
                    return
                try:
                    self._one(bid, row, plan)
                except Exception as exc:
                    # Invalid inputs and calculation-version conflicts cannot be repaired
                    # by repeating an expensive battle; preserve checkpoints and pause.
                    attempts = self._failed_attempt(bid)
                    if isinstance(exc, ValueError):
                        attempts = 3
                    if attempts >= 3:
                        self._mark(bid, "paused",
                                   "計算エンジンの処理に失敗しました。完了分は保存済みです。再開できます")
                        return
                    if not self._renew(bid):
                        return
                    time.sleep(self.retry_delay * attempts)
        finally:
            with self._lock:
                if self._workers.get(bid) is threading.current_thread():
                    self._workers.pop(bid, None)
