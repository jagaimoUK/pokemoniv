"""Read-only, owner-scoped reference between saved missing roles and observed policies.

Results from finite scenarios never upgrade normal role coverage, ownership,
or live reproducibility. No native replay or write transaction is performed.
"""
from __future__ import annotations

from pvpoke_battle_service import _json_hash, UnsupportedBattle
from pvpoke_missing_analysis import MissingAnalysis
from pvpoke_observed_observation import FLAGS
from pvpoke_observed_search import ObservedSearch
from pvpoke_role_evaluation import RoleEvaluation, _hash, condition_id
from pvpoke_sandbox import SandboxService

SCHEMA = "missing-observed-evidence-v1"
# This display-only endpoint must not rehydrate multiple large replay ledgers
# in one authenticated HTTP request. Full histories remain in Sandbox.
MAX_COMPARE_RECEIPTS = 1024
MAX_COMPARE_RECEIPT_BYTES = 16 * 1024 * 1024
OUTCOMES = {"self_win": "self_ko_win", "opponent_win": "opponent_ko_win",
            "simultaneous_ko": "simultaneous_ko"}
RESOURCES = {"hp": "hp", "energy": "energy", "shields_remaining": "shields"}


def _world_key(battle):
    return _json_hash([battle["self"], battle["opponent"], battle["initial"], battle["shields"]])


def _aligned_roles(requirement, roles):
    minimum = requirement.get("minimum", {})
    if not set(minimum) <= set(RESOURCES):
        return []
    wanted = {RESOURCES[k]: v for k, v in minimum.items() if v}
    outcomes = {OUTCOMES[o] for o in requirement.get("outcomes", OUTCOMES)}
    return [role["id"] for role in roles
            if set(role["outcomes"]) == outcomes and
            {k: v for k, v in role["minimum"].items() if v} == wanted]


def _compact(policy):
    fields = ("policy_hash", "role", "scope_complete", "tested", "failed", "unknown",
              "worst_outcome")
    role_fields = ("id", "meets", "passed", "failed", "unknown",
                   "worst_outcome", "resource_floor")
    return {**{k: policy[k] for k in fields},
            "roles": [{k: role.get(k) for k in role_fields}
                      for role in policy.get("roles", [])]}


def _policy_condition(policy, scenario_indices, aligned_role_ids):
    """Summary for one matched matchup, never for a union of different worlds."""
    counts = {name: 0 for name in (*OUTCOMES.values(), "timeout", "unknown")}
    outcomes = policy["outcomes"]
    for index in scenario_indices:
        outcome = outcomes[index] if index < len(outcomes) else None
        counts[outcome if outcome in counts else "unknown"] += 1
    matches = []
    for role in policy.get("roles", []):
        if role["id"] not in aligned_role_ids:
            continue
        values = role["scenario_meets"]
        rows = [values[index] if index < len(values) else None
                for index in scenario_indices]
        matches.append({
            "id": role["id"], "passed": rows.count(True),
            "failed": rows.count(False), "unknown": rows.count(None),
            "meets": (False if False in rows else
                      None if None in rows else True),
        })
    return {"policy_hash": policy["policy_hash"],
            "scenario_count": len(scenario_indices), "outcomes": counts,
            "aligned_roles": matches}


def _check_receipt_budget(db, owner, search_ids):
    """Fail before replaying large stored histories; caller owns one DB snapshot."""
    if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='observed_jobs_v2'").fetchone():
        raise ValueError("Observed search unavailable for this owner")
    work_total, bytes_total = 0, 0
    for search_id in search_ids:
        row = db.execute(
            "SELECT cursor FROM observed_jobs_v2 WHERE owner=? AND id=?",
            (owner, search_id)).fetchone()
        if row is None:
            raise ValueError("Observed search unavailable for this owner")
        cursor = row[0]
        if type(cursor) is not int or cursor < 0:
            raise ValueError("Invalid observed search cursor")
        work_total += cursor
        if work_total > MAX_COMPARE_RECEIPTS:
            raise ValueError("Observed evidence too large for one comparison; inspect in Sandbox")
        receipt_bytes = db.execute(
            "SELECT COALESCE(SUM(LENGTH(receipt)),0) FROM observed_work_v2 "
            "WHERE owner=? AND id=?", (owner, search_id)
        ).fetchone()[0]
        if type(receipt_bytes) is not int or receipt_bytes < 0:
            raise ValueError("Invalid observed receipt size")
        bytes_total += receipt_bytes
        if bytes_total > MAX_COMPARE_RECEIPT_BYTES:
            raise ValueError("Observed evidence too large for one comparison; inspect in Sandbox")
    return work_total, bytes_total


def compare_observed(service, evaluation_id, search_ids):
    """Return only stored, exactly matched candidate/scenario evidence."""
    _hash(evaluation_id)
    if (type(search_ids) is not list or not 1 <= len(search_ids) <= 6 or
            len(set(search_ids)) != len(search_ids)):
        raise ValueError("Specify 1–6 different observed search IDs")
    for value in search_ids:
        _hash(value)
    role = RoleEvaluation(service.store).history(evaluation_id)
    if role is None:
        raise ValueError("Saved role evaluation is unavailable for this owner")
    if role["active_versions"] != service.versions or role["plan_versions"] != service.versions:
        raise ValueError("Saved role evaluation uses outdated battle data")
    evidence = MissingAnalysis(service.store).evidence(
        role["analysis_id"], active_versions=service.versions, normalizer=service)
    if (evidence is None or evidence["ledger_revision"] != role["ledger_revision"] or
            _json_hash(evidence["cells"]) != role["evidence_digest"]):
        raise ValueError("Saved role evidence changed; evaluate it again")

    sandbox = SandboxService(service)
    observed = ObservedSearch(sandbox)
    # The preflight and raw fetch must use one immutable SQLite read snapshot,
    # then close the reader before JSON decoding and replay verification.
    with service.store._reader() as db:
        _check_receipt_budget(db, service.store.owner_scope, search_ids)
        snapshots = {}
        for search_id in search_ids:
            snapshot = observed._fetch(db, search_id)
            if snapshot is None:
                raise ValueError("Observed search unavailable for this owner")
            snapshots[search_id] = snapshot

    loaded_jobs = {}
    for search_id, snapshot in snapshots.items():
        loaded = observed._replay(snapshot)
        if loaded is None:
            raise ValueError("Observed search unavailable for this owner")
        if loaded.get("stale"):
            raise ValueError("Observed search is stale")
        loaded_jobs[search_id] = loaded

    requirements = role["definition"]["requirements"]
    index = {}
    normalized_by_battle = {}
    for cell in evidence["cells"]:
        slots = [condition_id(cell["spec"])]
        if cell.get("starts_at_full_hp"):
            slots.append(condition_id(cell["spec"], full_hp=True))
        for slot in slots:
            if slot not in requirements:
                continue
            spec = cell["spec"]
            if cell["battle_key"] not in normalized_by_battle:
                try:
                    _, payload = sandbox.prepare({"schema": spec["schema"], "mode": "sandbox",
                                                  "rules": spec["rules"], "combatants": spec["combatants"]})
                    normalized_by_battle[cell["battle_key"]] = _world_key(payload)
                except UnsupportedBattle:
                    # A valid standard matchup may lack Sandbox support.
                    normalized_by_battle[cell["battle_key"]] = None
            key = normalized_by_battle[cell["battle_key"]]
            if key is None:
                continue
            check = next((candidate["checks"].get(slot) for candidate in role["candidates"]
                          if candidate["build_id"] == cell["build_id"]), None)
            index.setdefault(key, []).append({
                "build_id": cell["build_id"], "condition_id": slot,
                "standard_status": cell["state"], "standard_meets": check["meets"] if check else None,
                "opponent": {"species_id": spec["combatants"][1]["species_id"],
                             "ivs": spec["combatants"][1]["ivs"]},
                "shields": [combatant["initial"]["shields"] for combatant in spec["combatants"]],
            })

    links = []
    for search_id in search_ids:
        loaded = loaded_jobs[search_id]
        summary = observed._summary(search_id, loaded)
        keys = {_world_key(entry["battle"]) for entry in loaded["plan"]["manifest"].values()}
        by_condition = {(item["build_id"], item["condition_id"]): item
                        for key in keys for item in index.get(key, [])}
        if not by_condition:
            raise ValueError("Observed search does not match a saved matchup")
        builds = {item["build_id"] for item in by_condition.values()}
        if len(builds) != 1:
            raise ValueError("Observed search cannot combine different builds")
        declared_roles = loaded["plan"].get("roles", [])
        manifest = loaded["plan"]["manifest"]
        scenario_indices = {}
        for idx, scenario in enumerate(loaded["search"].scenarios):
            scenario_indices.setdefault(_world_key(manifest[scenario]["battle"]), []).append(idx)
        conditions = []
        for condition in sorted(by_condition.values(), key=lambda v: v["condition_id"]):
            aligned = _aligned_roles(requirements[condition["condition_id"]], declared_roles)
            world = next(key for key in keys if condition in index.get(key, []))
            indices = scenario_indices.get(world, [])
            conditions.append({**condition, "aligned_role_ids": aligned,
                               "scenario_count": len(indices),
                               "policy_scenarios": [
                                   _policy_condition(policy, indices, aligned)
                                   for policy in summary["evaluations"]]})
        links.append({
            "search_id": search_id, "build_id": next(iter(builds)),
            "conditions": conditions, "matching_worlds": len(keys & set(index)),
            "additional_worlds": len(keys - set(index)),
            "scenario_count": summary["scenario_count"], "work": summary["work"],
            "observed_status": summary["status"], "stop_reason": summary["stop_reason"],
            "policy_scope_truncated": summary["policy_scope_truncated"],
            "evaluation_count": summary["evaluation_count"],
            "policies": [_compact(p) for p in summary["evaluations"]],
            "role": summary["role"], "expected_value": None,
            "opponent_response_complete": False, **FLAGS,
        })
    return {"schema": SCHEMA, "evaluation_id": evaluation_id, "links": links,
            "standard_state": role["state"], "new_battles": 0,
            "standard_assessment_unchanged": True, **FLAGS}
