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
    requirements = role["definition"]["requirements"]
    index = {}
    for cell in evidence["cells"]:
        slots = [condition_id(cell["spec"])]
        if cell.get("starts_at_full_hp"):
            slots.append(condition_id(cell["spec"], full_hp=True))
        for slot in slots:
            if slot not in requirements:
                continue
            spec = cell["spec"]
            try:
                _, payload = sandbox.prepare({"schema": spec["schema"], "mode": "sandbox",
                                              "rules": spec["rules"], "combatants": spec["combatants"]})
            except UnsupportedBattle:
                # Standard matchups can include forms the experimental Sandbox
                # explicitly does not support. Do not hide valid other matches.
                continue
            key = _world_key(payload)
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
        with service.store._reader() as db:
            loaded = observed._read(db, search_id)
            if loaded is None:
                raise ValueError("Observed search unavailable for this owner")
            if loaded.get("stale"):
                raise ValueError("Observed search is stale")
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
        conditions = [{**item, "aligned_role_ids":
                       _aligned_roles(requirements[item["condition_id"]], declared_roles)}
                      for item in sorted(by_condition.values(), key=lambda v: v["condition_id"])]
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
