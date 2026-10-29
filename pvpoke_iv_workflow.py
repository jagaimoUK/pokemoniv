"""One-request launch + bounded wait + compact reports for curated PvPoke IV jobs.

Only a *completed* job whose identity and candidate/IV rows match the
initiating request can produce a report. No hidden background service is
created: the already existing single PvPoke worker does the calculations.
"""
from __future__ import annotations

from pvpoke_input_limits import MAX_CANDIDATES, MAX_IMPORT_CHARS, MAX_APP_REQUEST_BYTES

import csv
from copy import deepcopy
import io
import json
import re
import threading
import time
import uuid
from zipfile import ZipFile

from pvpoke_selection_digest import build_selection_digest
from pvpoke_decision_digest import decision_digest, decision_digest_v2
from pvpoke_app_selection import recommendations_from_zip, validate_policy
from pvpoke_form_rules import battle_entry_species, battle_entry_notice

MODES = ("default", "rank1", "attack", "defense")
IV_LINE = re.compile(r"^(\d{1,2}),(\d{1,2}),(\d{1,2})$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _canonical(candidate: dict, ivs: str, batch_mode: str) -> tuple[dict, str, tuple]:
    if batch_mode not in ("simple", "detailed"):
        raise ValueError("batch_mode must be simple or detailed")
    if not isinstance(candidate, dict) or any(
        not isinstance(candidate.get(key), str) or not candidate[key].strip()
        for key in ("species", "fast", "charged1", "charged2")
    ):
        raise ValueError("candidate requires species, fast, charged1, charged2")
    own = {"species": candidate["species"].strip().lower()}
    for key in ("fast", "charged1", "charged2"):
        own[key] = candidate[key].strip().upper()
    if not isinstance(ivs, str):
        raise ValueError("ivs must be a multiline string")
    rows = []
    for index, raw in enumerate(ivs.replace("，", ",").replace("、", ",").splitlines(), 1):
        if not raw.strip():
            continue
        normalized = ",".join(n.strip() for n in raw.split(","))
        match = IV_LINE.fullmatch(normalized)
        if not match or any(int(x) > 15 for x in match.groups()):
            raise ValueError(f"Invalid IV at line {index} (ATK,DEF,HP must be 0..15)")
        rows.append(tuple(int(x) for x in match.groups()))
    if not 1 <= len(rows) <= MAX_CANDIDATES:
        raise ValueError(f"ivs must have 1..{MAX_CANDIDATES} triplets")
    if len(set(rows)) != len(rows):
        raise ValueError("Duplicate IV triplets")
    return own, "\n".join(",".join(str(x) for x in row) for row in rows), tuple(rows)


def _verify_zip(archive: ZipFile, ticket: dict) -> None:
    """Do not mistake the previous persisted ZIP for the just-started job."""
    import json
    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    if manifest.get("batch_mode") != ticket["batch_mode"]:
        raise ValueError("The ZIP mode differs from the requested job")
    if manifest.get("candidates") != len(ticket["iv_rows"]):
        raise ValueError("The ZIP candidate count differs from the requested job")
    if (ticket["expected_meta_sha256"] is not None
            and ticket["server_meta_sha256"] != ticket["expected_meta_sha256"]):
        raise ValueError("Server meta snapshot differs from the project source")
    with archive.open("ranking_summary.csv") as raw:
        summary = list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))
    expected_modes = ("default",) if ticket["batch_mode"] == "simple" else MODES
    own = ticket["candidate"]
    expected_ivs = set(ticket["iv_rows"])
    if len(summary) != len(expected_ivs) * len(expected_modes):
        raise ValueError("Ranking summary row count differs from the job")
    for mode in expected_modes:
        rows = [row for row in summary if row.get("opponent_iv_mode") == mode]
        if len(rows) != len(expected_ivs):
            raise ValueError(f"Missing mode rows for {mode}")
        seen = set()
        for row in rows:
            if any(str(row.get(key, "")).lower() != own[key].lower()
                   for key in ("species", "fast", "charged1", "charged2")):
                raise ValueError("The saved ZIP is for a different Pokemon or moves")
            triple = tuple(int(row[key]) for key in ("atk", "def", "hp"))
            if triple not in expected_ivs or triple in seen:
                raise ValueError("The saved ZIP candidate IVs differ from the job")
            seen.add(triple)


class IVWorkflow:
    def __init__(self, backend):
        self.backend = backend
        self._lock = threading.RLock()
        self._ticket = None

    def run(self, candidate: dict, ivs: str, batch_mode: str = "simple",
            focus_opponents: list[str] | None = None,
            highlight_limit: int = 20, review_limit: int = 8,
            focus_limit: int = 20, wait_seconds: int = 12,
            expected_meta_sha256: str | None = None,
            report_format: str = "decision", selection_policy: dict | None = None,
            meta_preset_id: str | None = None, force_recalculate: bool = False) -> dict:
        requested_at = time.monotonic()
        if report_format not in ("decision", "decision-v1", "compact", "app"):
            raise ValueError("report_format must be decision, decision-v1, compact or app")
        if not isinstance(force_recalculate, bool):
            raise ValueError("force_recalculate must be true or false")
        validate_policy(selection_policy)
        own, normalized, rows = _canonical(candidate, ivs, batch_mode)
        inventory_form_notice = battle_entry_notice(own['species'])
        own['species'] = battle_entry_species(own['species'])
        if not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 20:
            raise ValueError("wait_seconds must be 0..20")
        if (expected_meta_sha256 is not None and
                (not isinstance(expected_meta_sha256, str)
                 or not SHA256.fullmatch(expected_meta_sha256))):
            raise ValueError("expected_meta_sha256 must be a 64-digit SHA256")
        if expected_meta_sha256 is not None:
            expected_meta_sha256 = expected_meta_sha256.lower()
        # Validate digest parameters before starting any real battle job.
        if (focus_opponents is not None and
                (not isinstance(focus_opponents, list)
                 or len(focus_opponents) > 15
                 or any(not isinstance(s, str) or not s.strip() or len(s) > 100
                        for s in focus_opponents))):
            raise ValueError("focus_opponents must have up to 15 nonempty names")
        if not isinstance(highlight_limit, int) or not 1 <= highlight_limit <= 60:
            raise ValueError("highlight_limit must be 1..60")
        if not isinstance(review_limit, int) or not 2 <= review_limit <= 12:
            raise ValueError("review_limit must be 2..12")
        if not isinstance(focus_limit, int) or not 0 <= focus_limit <= 20:
            raise ValueError("focus_limit must be 0..20")

        with self._lock:
            current = self.backend.status()
            if current.get("state") == "running":
                raise ValueError("A PvPoke calculation is already running")
            meta = (self.backend.meta_preset_status(meta_preset_id) if meta_preset_id is not None
                    else self.backend.meta_status())
            actual_sha = meta.get("sha256")
            if isinstance(actual_sha, str):
                actual_sha = actual_sha.lower()
            if (expected_meta_sha256 is not None
                    and (not isinstance(actual_sha, str)
                         or actual_sha.lower() != expected_meta_sha256.lower())):
                raise ValueError("Project meta SHA256 does not match the server; synchronize first")
            # /api/run24 already validates inputs and builds the preview atomically.
            english_name = self.backend.candidate_name(own["species"]) if report_format == "app" else None
            force_args = {"force_recalculate": True} if force_recalculate else {}
            if meta_preset_id is not None:
                started = self.backend.start24(own, normalized, batch_mode,
                    meta_preset_id=meta_preset_id, expected_meta_sha256=actual_sha, **force_args)
            else:
                started = self.backend.start24(own, normalized, batch_mode, **force_args)
            status = self.backend.status()
            started_at = status.get("started_at")
            if status.get("state") not in ("running", "done") or not started_at:
                raise ValueError("Could not verify the new PvPoke job start")
            ticket = {
                "run_ref": uuid.uuid4().hex,
                "candidate": own, "iv_rows": rows, "batch_mode": batch_mode,
                "started_at": started_at,
                "server_meta_sha256": actual_sha,
                "meta_preset": ({k: meta[k] for k in ("id", "name", "sha256") if k in meta}
                                if meta_preset_id is not None else None),
                "expected_meta_sha256": expected_meta_sha256,
                "focus_opponents": focus_opponents,
                "highlight_limit": highlight_limit,
                "review_limit": review_limit,
                "focus_limit": focus_limit,
                "report_format": report_format,
                "english_name": english_name, "selection_policy": selection_policy,
                "inventory_form_notice": inventory_form_notice,
                "requested_at": requested_at,
                "completed_result": None,
                "result_cache": started.get("preview", {}).get("result_cache", {"reused":False}),
            }
            self._ticket = ticket

        result = self.result(ticket["run_ref"], wait_seconds=wait_seconds)
        result["preview"] = started["preview"]
        return result

    def result(self, run_ref: str, wait_seconds: int = 12) -> dict:
        """Bounded long poll avoids repeated model/tool round-trips."""
        if not isinstance(wait_seconds, int) or not 0 <= wait_seconds <= 20:
            raise ValueError("wait_seconds must be 0..20")
        deadline = time.monotonic() + wait_seconds
        while True:
            result = self._result_once(run_ref)
            if result["state"] != "running" or time.monotonic() >= deadline:
                return result
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))

    def _result_once(self, run_ref: str) -> dict:
        if not isinstance(run_ref, str) or not run_ref:
            raise ValueError("run_ref is required")
        with self._lock:
            ticket = self._ticket
            if ticket is None or ticket["run_ref"] != run_ref:
                raise ValueError("Unknown or superseded run_ref; never use an unrelated saved ZIP")
            current = self.backend.status()
            if current.get("started_at") != ticket["started_at"] or not current.get("batch24"):
                raise ValueError("PvPoke job identity changed or the server restarted")
            if current.get("state") == "error":
                return {"run_ref": run_ref, "state": "error",
                        "message": current.get("message"),
                        "exit_code": current.get("exit_code")}
            if current.get("state") != "done":
                return {"run_ref": run_ref, "state": "running",
                        "message": current.get("message"),
                        "candidate_count": len(ticket["iv_rows"]),
                        "batch_mode": ticket["batch_mode"]}
            if ticket["completed_result"] is not None:
                return deepcopy(ticket["completed_result"])
            analysis_started = time.monotonic()
            with self.backend._zip() as archive:
                _verify_zip(archive, ticket)
                calculation_revision = json.loads(archive.read("manifest.json")).get("calculation_version")
                modes = ("default",) if ticket["batch_mode"] == "simple" else MODES
                app_selection = None
                if ticket["report_format"] == "app":
                    app_selection = recommendations_from_zip(
                        archive, ticket["candidate"], ticket["english_name"],
                        ticket["batch_mode"], ticket["focus_opponents"], ticket["selection_policy"])
                    reports = {}
                else:
                    reports = {
                        mode: build_selection_digest(
                            archive, mode, ticket["focus_opponents"],
                            ticket["highlight_limit"], ticket["review_limit"],
                            ticket["focus_limit"],
                            include_tradeoffs=ticket["report_format"] == "decision")
                        for mode in modes
                    }
                expected_ivs = {"/".join(map(str, row)) for row in ticket["iv_rows"]}
                if app_selection is not None and set(app_selection['candidate_ivs']) != expected_ivs:
                    raise ValueError("Matrix candidate IVs differ from the requested job")
                if any({row[0] for row in report["ranking_rows"]} != expected_ivs
                       for report in reports.values()):
                    raise ValueError("Matrix candidate IVs differ from the requested job")
            # Recheck identity after ZIP download/analysis before caching.
            verified = self.backend.status()
            if (verified.get("started_at") != ticket["started_at"]
                    or verified.get("state") != "done" or not verified.get("batch24")):
                raise ValueError("PvPoke job identity changed during result analysis")
            if ticket["report_format"] == "decision":
                reports = {mode: decision_digest_v2(report) for mode, report in reports.items()}
            elif ticket["report_format"] == "decision-v1":
                reports = {mode: decision_digest(report) for mode, report in reports.items()}
            output = {
                "run_ref": run_ref,
                "state": "done", "complete": all(report["complete"] for report in reports.values()),
                "candidate": ticket["candidate"], "batch_mode": ticket["batch_mode"],
                "meta_sha256": ticket["server_meta_sha256"],
                "calculation_version": calculation_revision,
                "meta_preset": ticket.get("meta_preset"),
                "result_cache": ticket["result_cache"],
                "meta_verified_against_project": ticket["expected_meta_sha256"] is not None,
                "total_ratings_checked": sum(
                    report["total_ratings_checked"] for report in reports.values()),
                "reports": reports,
                "timing": {
                    "server_request_to_result_seconds": round(
                        time.monotonic() - ticket["requested_at"], 3),
                    "zip_and_analysis_seconds": round(
                        time.monotonic() - analysis_started, 3),
                    "scope": "server only; excludes GPT evaluation and final response",
                },
            }
            if app_selection is not None:
                if ticket.get('inventory_form_notice'):
                    app_selection.setdefault('input_notices', []).append(ticket['inventory_form_notice'])
                output["selection"] = app_selection
                output["complete"] = app_selection["complete"]
                output["total_ratings_checked"] = app_selection["total_ratings_checked"]
                output["reports"] = {}
            ticket["completed_result"] = output
            return deepcopy(output)



