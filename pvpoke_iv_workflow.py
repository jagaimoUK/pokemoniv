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
from pvpoke_mega import is_mega_form

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
    if candidate.get("mega_level") is not None:
        own["mega_level"] = candidate["mega_level"]
    if candidate.get("charged3") is not None and str(candidate["charged3"]).strip():
        own["charged3"] = str(candidate["charged3"]).strip().upper()
    if candidate.get("level_override") is not None:
        own["level_override"] = float(candidate["level_override"])
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


def _verify_zip(archive: ZipFile, ticket: dict) -> dict:
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
    return manifest


class IVWorkflow:
    def __init__(self, backend):
        self.backend = backend
        self._lock = threading.RLock()
        self._ticket = None
        self._request_ids = []

    def run(self, candidate: dict, ivs: str, batch_mode: str = "simple",
            focus_opponents: list[str] | None = None,
            highlight_limit: int = 20, review_limit: int = 8,
            focus_limit: int = 20, wait_seconds: int = 12,
            expected_meta_sha256: str | None = None,
            report_format: str = "decision", selection_policy: dict | None = None,
            meta_preset_id: str | None = None, force_recalculate: bool = False, request_id: str | None = None,
            rules: dict | None = None) -> dict:
        requested_at = time.monotonic()
        if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id)):
            raise ValueError("Invalid calculation request_id")
        resolved_rules = None
        if rules is not None:
            from pvpoke_mega import resolve_battle_rules
            resolved_rules = resolve_battle_rules(rules)
        req_payload = [candidate, ivs, batch_mode, focus_opponents, highlight_limit,
            review_limit, focus_limit, expected_meta_sha256, report_format, selection_policy,
            meta_preset_id, force_recalculate]
        if resolved_rules is not None:
            req_payload.append(resolved_rules)
        request_body = json.dumps(req_payload, sort_keys=True)

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
            if request_id is not None and self._ticket and self._ticket.get("request_id") == request_id:
                if self._ticket.get("request_body") != request_body:
                    raise ValueError("request_id was used for different calculation inputs")
                return self.result(self._ticket["run_ref"], wait_seconds=0)
            if request_id is not None and request_id in self._request_ids:
                raise ValueError("Calculation request has been superseded; resume its exact result")
            current = self.backend.status()
            if current.get("state") in ("running", "cancelling"):
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
            if resolved_rules is not None:
                force_args["rules"] = resolved_rules
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
                "run_ref": uuid.uuid4().hex, "request_id": request_id, "request_body": request_body,
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
                "rules": resolved_rules,
                "inventory_form_notice": inventory_form_notice,
                "requested_at": requested_at,
                "completed_result": None,
                "result_cache": started.get("preview", {}).get("result_cache", {"reused":False}),
            }
            self._ticket = ticket
            if request_id is not None:
                self._request_ids = (self._request_ids + [request_id])[-128:]

        result = self.result(ticket["run_ref"], wait_seconds=wait_seconds)
        result["preview"] = started["preview"]
        return result

    def cancel(self, run_ref: str) -> dict:
        """A request may cancel only its exact active IV run, never another job."""
        if not isinstance(run_ref, str) or not run_ref:
            raise ValueError("run_ref is required")
        with self._lock:
            ticket = self._ticket
            if ticket is None or ticket["run_ref"] != run_ref:
                raise ValueError("Unknown or superseded run_ref")
            current = self.backend.status()
            if current.get("started_at") != ticket["started_at"] or not current.get("batch24"):
                raise ValueError("PvPoke job identity changed or the server restarted")
            if current.get("state") not in ("running", "cancelling"):
                return {"run_ref": run_ref, "state": current.get("state"), "cancelled": False}
            result = self.backend.cancel()
            return {"run_ref": run_ref, "state": result["state"],
                    "cancelled": result["cancelled"]}

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
            if current.get("state") in ("cancelling", "cancelled"):
                return {"run_ref": run_ref, "state": current["state"],
                        "message": "計算を中止しました" if current["state"] == "cancelled"
                                   else "計算の停止を処理中"}
            if current.get("state") == "error":
                return {"run_ref": run_ref, "state": "error",
                        "message": current.get("message"),
                        "exit_code": current.get("exit_code")}
            if current.get("state") != "done":
                started_at = ticket.get("started_at")
                elapsed_seconds = (
                    round(max(0.0, time.time() - float(started_at)), 1)
                    if isinstance(started_at, (int, float)) else None
                )
                progress = None
                eta_seconds = None
                log_lines = list(current.get("logs") or ())
                msg_text = current.get("message")
                if isinstance(msg_text, str) and msg_text:
                    log_lines.append(msg_text)
                batch_cur = batch_tot = None
                done_in_batch = 0
                for line in log_lines:
                    if not isinstance(line, str):
                        continue
                    m = re.search(r"Batch\s+(\d+)\s*/\s*(\d+)", line)
                    if m:
                        batch_cur, batch_tot = int(m.group(1)), int(m.group(2))
                        done_in_batch = 0
                    elif batch_tot and (" OK" in line or "を再利用" in line):
                        done_in_batch = min(6, done_in_batch + 1)
                if batch_tot and batch_tot > 0 and batch_cur is not None:
                    frac = ((batch_cur - 1) + (done_in_batch / 6.0)) / batch_tot
                    progress = min(98, max(2, int(round(frac * 96))))
                    if elapsed_seconds is not None and elapsed_seconds >= 1.0 and 0.02 <= frac < 0.99:
                        eta_seconds = max(1, int(round(elapsed_seconds * (1.0 - frac) / frac)))
                return {"run_ref": run_ref, "state": "running",
                        "message": current.get("message"),
                        "candidate_count": len(ticket["iv_rows"]),
                        "batch_mode": ticket["batch_mode"],
                        "elapsed_seconds": elapsed_seconds,
                        "progress": progress,
                        "eta_seconds": eta_seconds}
            if ticket["completed_result"] is not None:
                return deepcopy(ticket["completed_result"])
            analysis_started = time.monotonic()
            with self.backend._zip() as archive:
                manifest = _verify_zip(archive, ticket)
                calculation_revision = manifest.get("calculation_version")
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
            # A restored ZIP records the old run's counters, not this request's.
            if not ticket["result_cache"].get("reused"):
                output["matchup_cache"] = manifest.get("matchup_cache", {"enabled": False})
            if app_selection is not None:
                if ticket.get('inventory_form_notice'):
                    app_selection.setdefault('input_notices', []).append(ticket['inventory_form_notice'])
                output["selection"] = app_selection
                output["complete"] = app_selection["complete"]
                output["total_ratings_checked"] = app_selection["total_ratings_checked"]
                output["reports"] = {}
                if ticket.get("diff_context") is not None:
                    output["pool_diff"] = build_pool_diff(app_selection, ticket["diff_context"])
            if ticket.get("rules") is not None:
                output["rules"] = ticket["rules"]
            ticket["completed_result"] = output
            return deepcopy(output)

    def run_with_selection_pool(
        self,
        candidate: dict,
        ivs: str,
        batch_mode: str = "simple",
        focus_opponents: list[str] | None = None,
        highlight_limit: int = 20,
        review_limit: int = 8,
        focus_limit: int = 20,
        wait_seconds: int = 12,
        expected_meta_sha256: str | None = None,
        selection_policy: dict | None = None,
        meta_preset_id: str | None = None,
        force_recalculate: bool = False,
        request_id: str | None = None,
        rules: dict | None = None,
        selection_pool: dict | None = None,
    ) -> dict:
        """Evaluate newly read IVs together with saved selection_pool candidates (TV-03)."""
        own, _, incoming_rows = _canonical(candidate, ivs, batch_mode)
        owned_species_id = candidate.get("owned_species_id")
        if owned_species_id is not None:
            if not isinstance(owned_species_id, str) or not owned_species_id.strip():
                raise ValueError("owned_species_id must be a non-empty string when specified")
            owned_species_id = owned_species_id.strip().lower()
        target_species = battle_entry_species(own["species"])
        resolved_rules = None
        if rules is not None:
            from pvpoke_mega import resolve_battle_rules
            resolved_rules = resolve_battle_rules(rules)

        pool_source = "override"
        pool_payload = selection_pool
        if pool_payload is None:
            pool_source = "selection_pool"
            if hasattr(self.backend, "selection_pool"):
                try:
                    pool_payload = self.backend.selection_pool([target_species])
                except Exception:
                    pool_payload = {"snapshots": {}}
                    pool_source = "unavailable"
            else:
                pool_payload = {"snapshots": {}}
                pool_source = "unavailable"
        if not isinstance(pool_payload, dict):
            raise ValueError("selection_pool must be a dict")
        snapshots = pool_payload.get("snapshots") if isinstance(pool_payload.get("snapshots"), dict) else {}
        snapshot = snapshots.get(target_species) if isinstance(snapshots.get(target_species), dict) else {}

        saved_pool_ivs = []
        for raw_iv in snapshot.get("ivs") or ():
            if isinstance(raw_iv, str) and raw_iv.strip():
                normalized_iv = raw_iv.strip().replace(",", "/")
                if normalized_iv not in saved_pool_ivs:
                    saved_pool_ivs.append(normalized_iv)

        incoming_ivs_slash = ["/".join(map(str, row)) for row in incoming_rows]
        combined_ivs_slash = list(dict.fromkeys([*incoming_ivs_slash, *saved_pool_ivs]))
        if len(combined_ivs_slash) > MAX_CANDIDATES:
            raise ValueError(
                f"Combined incoming + saved selection_pool IVs ({len(combined_ivs_slash)}) "
                f"exceed MAX_CANDIDATES ({MAX_CANDIDATES})"
            )
        combined_ivs_str = "\n".join(iv.replace("/", ",") for iv in combined_ivs_slash)

        diff_context = {
            "target_species_id": target_species,
            "owned_species_id": owned_species_id,
            "incoming_ivs": incoming_ivs_slash,
            "saved_pool_ivs": saved_pool_ivs,
            "saved_revision": snapshot.get("revision"),
            "saved_links": list(snapshot.get("links") or ()),
            "needs_reevaluation": bool(
                snapshot.get("needs_reevaluation")
                or (isinstance(snapshot.get("freshness"), dict) and snapshot["freshness"].get("needs_reevaluation"))
            ),
            "freshness": snapshot.get("freshness"),
            "pool_source": pool_source,
            "rules": resolved_rules,
        }

        result = self.run(
            own,
            combined_ivs_str,
            batch_mode=batch_mode,
            focus_opponents=focus_opponents,
            highlight_limit=highlight_limit,
            review_limit=review_limit,
            focus_limit=focus_limit,
            wait_seconds=wait_seconds,
            expected_meta_sha256=expected_meta_sha256,
            report_format="app",
            selection_policy=selection_policy,
            meta_preset_id=meta_preset_id,
            force_recalculate=force_recalculate,
            request_id=request_id,
            rules=rules,
        )

        with self._lock:
            if self._ticket is not None and self._ticket.get("run_ref") == result.get("run_ref"):
                self._ticket["diff_context"] = deepcopy(diff_context)
                if result.get("state") == "done" and result.get("selection") is not None:
                    pool_diff = build_pool_diff(result["selection"], diff_context)
                    result["pool_diff"] = pool_diff
                    if self._ticket.get("completed_result") is not None:
                        self._ticket["completed_result"]["pool_diff"] = deepcopy(pool_diff)
        return result


def build_pool_diff(app_selection: dict, diff_context: dict) -> dict:
    """Summarize TV-03 differential outcomes for incoming IVs vs saved selection_pool."""
    incoming_ivs = list(diff_context.get("incoming_ivs") or ())
    saved_pool_ivs = list(diff_context.get("saved_pool_ivs") or ())
    incoming_set = set(incoming_ivs)
    saved_set = set(saved_pool_ivs)

    recommendations = app_selection.get("recommendations") or ()
    covered_candidates = app_selection.get("covered_candidates") or ()
    dominated_by = app_selection.get("dominated_by") or {}
    review_candidates = app_selection.get("review_candidates") or ()
    additional_candidates = app_selection.get("additional_candidates") or ()

    rec_by_iv = {row["ivs"]: row for row in recommendations if isinstance(row, dict) and row.get("ivs")}
    covered_by_map = {
        row["ivs"]: row.get("covered_by")
        for row in covered_candidates
        if isinstance(row, dict) and row.get("ivs")
    }
    equivalent_rep: dict[str, str] = {}
    for group in (*recommendations, *covered_candidates, *review_candidates, *additional_candidates):
        if not isinstance(group, dict):
            continue
        rep_iv = group.get("ivs")
        for eq in group.get("equivalent_candidates") or ():
            eq_iv = eq.get("ivs") if isinstance(eq, dict) else None
            if eq_iv and rep_iv:
                equivalent_rep[eq_iv] = rep_iv

    review_ivs = {row.get("ivs") for row in review_candidates if isinstance(row, dict)}
    additional_ivs = {row.get("ivs") for row in additional_candidates if isinstance(row, dict)}

    incoming_assessments = []
    unique_win_incoming = []
    recommended_incoming = []
    equivalent_incoming = []
    dominated_incoming = []
    review_incoming = []

    for iv in incoming_ivs:
        if iv in rec_by_iv:
            rec = rec_by_iv[iv]
            unique_evidences = [
                ev for ev in rec.get("evidence") or ()
                if isinstance(ev, dict) and ev.get("kind") in ("unique_gt500", "unique_eq500")
            ]
            is_unique = bool(unique_evidences)
            classification = "unique_win" if is_unique else "recommended"
            eq_saved = [
                eq["ivs"] for eq in rec.get("equivalent_candidates") or ()
                if isinstance(eq, dict) and eq.get("ivs") in saved_set
            ]
            item = {
                "ivs": iv,
                "classification": classification,
                "is_unique_win": is_unique,
                "grade": rec.get("grade"),
                "role": rec.get("role"),
                "reason": rec.get("reason"),
                "unique_evidence_count": len(unique_evidences),
                "equivalent_to_saved_ivs": eq_saved,
                "already_in_saved_pool": iv in saved_set,
            }
            if is_unique:
                unique_win_incoming.append(iv)
            else:
                recommended_incoming.append(iv)
        elif iv in equivalent_rep:
            rep_iv = equivalent_rep[iv]
            item = {
                "ivs": iv,
                "classification": "equivalent_alternative",
                "equivalent_to": rep_iv,
                "is_equivalent_to_saved": rep_iv in saved_set,
                "already_in_saved_pool": iv in saved_set,
            }
            equivalent_incoming.append(iv)
        elif iv in dominated_by:
            dom = list(dominated_by[iv] or ())
            item = {
                "ivs": iv,
                "classification": "dominated",
                "dominated_by": dom,
                "dominated_by_saved": any(d in saved_set for d in dom),
                "already_in_saved_pool": iv in saved_set,
            }
            dominated_incoming.append(iv)
        elif iv in covered_by_map:
            cov = covered_by_map[iv]
            item = {
                "ivs": iv,
                "classification": "covered",
                "covered_by": cov,
                "covered_by_saved": cov in saved_set,
                "already_in_saved_pool": iv in saved_set,
            }
            dominated_incoming.append(iv)
        elif iv in review_ivs:
            item = {
                "ivs": iv,
                "classification": "review",
                "already_in_saved_pool": iv in saved_set,
            }
            review_incoming.append(iv)
        elif iv in additional_ivs:
            item = {
                "ivs": iv,
                "classification": "additional",
                "already_in_saved_pool": iv in saved_set,
            }
            review_incoming.append(iv)
        else:
            item = {
                "ivs": iv,
                "classification": "unclassified",
                "already_in_saved_pool": iv in saved_set,
            }
        incoming_assessments.append(item)

    newly_dominated_saved = []
    retained_saved = []
    for s_iv in saved_pool_ivs:
        doms = dominated_by.get(s_iv) or ()
        if any(d in incoming_set for d in doms) or covered_by_map.get(s_iv) in incoming_set:
            newly_dominated_saved.append(s_iv)
        elif s_iv in rec_by_iv or equivalent_rep.get(s_iv) in rec_by_iv:
            retained_saved.append(s_iv)

    target_species = diff_context.get("target_species_id") or ""
    snapshot_update_recommended = bool(
        unique_win_incoming
        or recommended_incoming
        or [iv for iv in equivalent_incoming if iv not in saved_set]
        or newly_dominated_saved
        or diff_context.get("needs_reevaluation")
    )

    return {
        "version": "tv03-pool-diff-v1",
        "target_species_id": target_species,
        "owned_species_id": diff_context.get("owned_species_id"),
        "is_mega_form": is_mega_form(target_species),
        "rules": diff_context.get("rules"),
        "pool_source": diff_context.get("pool_source", "selection_pool"),
        "saved_revision": diff_context.get("saved_revision"),
        "saved_pool_ivs": saved_pool_ivs,
        "saved_links": list(diff_context.get("saved_links") or ()),
        "needs_reevaluation": bool(diff_context.get("needs_reevaluation")),
        "freshness": diff_context.get("freshness"),
        "incoming_ivs": incoming_ivs,
        "incoming_assessments": incoming_assessments,
        "unique_win_incoming_ivs": unique_win_incoming,
        "recommended_incoming_ivs": recommended_incoming,
        "equivalent_incoming_ivs": equivalent_incoming,
        "dominated_incoming_ivs": dominated_incoming,
        "review_incoming_ivs": review_incoming,
        "newly_dominated_saved_ivs": newly_dominated_saved,
        "retained_saved_ivs": retained_saved,
        "snapshot_update_recommended": snapshot_update_recommended,
    }



