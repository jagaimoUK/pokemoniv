"""Bounded offline non-anticipation audit, NOT an observation extractor/search.

All traces must belong to ONE precommitted policy and own build/context.
Only the caller's allowlisted observations and own intents enter history keys.
Passing proves consistency on supplied prefixes, not truthful observations,
exhaustive worlds, executed intents, or live-game reproducibility.
"""
import hashlib
import json

from pvpoke_observed_policy import propose

MAX_TRACES = 64
MAX_DECISIONS = 512


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def audit_traces(traces, policy):
    """Reject differing actions on identical full observable decision prefixes.

    A rolling digest includes prior observations AND prior own intents. The
    current action is deliberately excluded until after the comparison.
    Hash collisions are assumed cryptographically infeasible; order is never
    reconstructed by sorting turn numbers (CMP has within-turn order).
    """
    if type(traces) is not list or not 1 <= len(traces) <= MAX_TRACES:
        raise ValueError("Invalid audit trace count")
    choices = {}
    repeated = total = 0
    for trace in traces:
        if type(trace) is not list or not 1 <= len(trace) <= MAX_DECISIONS:
            raise ValueError("Invalid audit decision count")
        prefix = "observed-audit-v1"
        previous_turn = 0
        previous_events = []
        for row in trace:
            if type(row) is not dict or set(row) != {"visible", "action"}:
                raise ValueError("Invalid audit row")
            visible, action = row["visible"], row["action"]
            # Reuse the v1 strict input validator. Do not require this simple
            # fixed policy's action: future adaptive policies may choose others.
            propose(visible, policy)
            if (visible["turn"] < previous_turn or
                    visible["events"][:len(previous_events)] != previous_events):
                raise ValueError("Observed history rewound or changed")
            previous_turn = visible["turn"]
            previous_events = visible["events"]
            legal = []
            if visible["phase"] == "shield_prompt":
                legal = [{"kind": "shield", "use_shield": False}]
                if visible["own_shields"]:
                    legal.append({"kind": "shield", "use_shield": True})
            else:
                legal = [{"kind": "wait"}]
                if visible["own_can_act"]:
                    legal.append({"kind": "fast"})
                    legal.extend({"kind": "charged", "move_id": m["move_id"]}
                                 for m in policy["own_charged_moves"]
                                 if visible["own_energy"] >= m["energy_cost"])
            # JSON equality distinguishes booleans from numeric 0/1.
            encoded = _canonical(action)
            if type(action) is not dict or encoded not in map(_canonical, legal):
                raise ValueError("Invalid observable action intent")
            key = hashlib.sha256(_canonical([prefix, visible]).encode()).hexdigest()
            if key in choices:
                if choices[key] != encoded:
                    raise ValueError("Different actions for identical observed history")
                repeated += 1
            choices[key] = encoded
            prefix = hashlib.sha256(_canonical([key, action]).encode()).hexdigest()
            total += 1
    return {"schema": "observed-audit-v1", "decisions": total,
            "distinct_histories": len(choices), "repeated_histories": repeated,
            "supplied_prefixes_consistent": True,
            "information_fairness": "not_established",
            "live_reproducibility": "not_verified", "practical_role_covered": False}


def audit_v2(context, traces, table):
    """Check distinct native decision prefixes against one committed table."""
    from pvpoke_observed_observation import FLAGS, ObservationV2

    seen = {}
    repeated = 0
    if not 1 <= len(traces) <= 1024:
        raise ValueError("Invalid v2 trace count")
    for trace in traces:
        for index, event in enumerate(trace):
            if event.get("kind") != "intent":
                continue
            view = ObservationV2.read(context, trace[:index])
            action = event.get("action")
            if action not in view.legal or table.get(view.key) != action:
                raise ValueError("V2 trace differs from committed shared policy")
            repeated += view.key in seen
            seen[view.key] = action
    return {"schema": "observed-audit-v2", "shared_prefixes": repeated, **FLAGS}
