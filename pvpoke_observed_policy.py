"""Internal, pure observation-only decision *proposal* for PvP research.

This is NOT a runnable native PvPoke policy or a claim of practical wins.
A future adapter must prove that snapshot/events come from information already
observable at each decision point, then validate actual native executions.
Never pass a full native battle state or the opponent's private statistics.
"""
from __future__ import annotations

import re

SCHEMA = "observable-tactic-proposal-v1"
EVENTS = {
    "opponent_fast", "opponent_charge_announced",
    "opponent_charge_resolved", "opponent_shield_used",
}
PHASES = {"choose_action", "shield_prompt"}
SHIELD_RULES = {"always", "never", "first_announcement"}
MAX_EVENTS = 64


def _object(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"Invalid {name} fields")
    return value


def _int(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Invalid {name}")
    return value


def _events(value, current_turn):
    if type(value) is not list or len(value) > MAX_EVENTS:
        raise ValueError("Invalid observed history size")
    previous = 0
    announced = 0
    pending_charge = False
    for event in value:
        if type(event) is not dict or set(event) not in (
                {"turn", "kind"}, {"turn", "kind", "move_id"}):
            raise ValueError("Invalid observed event fields")
        turn = _int(event["turn"], max(1, previous), current_turn, "event turn")
        previous = turn
        kind = event["kind"]
        if type(kind) is not str or kind not in EVENTS:
            raise ValueError("Unknown visible event")
        if "move_id" in event:
            # Revealed *after* an opponent charge resolves, not before the
            # player must commit to shielding it.
            if kind != "opponent_charge_resolved" or type(event["move_id"]) is not str or not re.fullmatch(
                    r"[A-Z0-9_]{1,100}", event["move_id"]):
                raise ValueError("Unrevealed move or invalid move ID")
        if kind == "opponent_charge_announced":
            if pending_charge:
                raise ValueError("Overlapping charge announcements are unobservable")
            pending_charge = True
            announced += 1
        elif kind == "opponent_charge_resolved":
            if not pending_charge:
                raise ValueError("Unannounced opponent charge resolution")
            pending_charge = False
    return announced, pending_charge


def propose(snapshot, policy):
    """Deterministic intent from observable input only; no native simulation.

    Explicit allowlists reject hidden opponent IVs, energy, unrevealed move
    IDs, opponent intention, and arbitrary native state. The caller must
    independently establish the *provenance* of visible event observations.
    """
    _object(snapshot, (
        "turn", "phase", "own_energy", "own_shields",
        "opponent_shields_visible", "own_can_act", "events"
    ), "visible snapshot")
    turn = _int(snapshot["turn"], 1, 500, "turn")
    phase = snapshot["phase"]
    if type(phase) is not str or phase not in PHASES:
        raise ValueError("Unknown decision phase")
    energy = _int(snapshot["own_energy"], 0, 100, "own energy")
    shields = _int(snapshot["own_shields"], 0, 2, "own shields")
    _int(snapshot["opponent_shields_visible"], 0, 2, "visible opponent shields")
    if type(snapshot["own_can_act"]) is not bool:
        raise ValueError("Invalid own action readiness")
    announcements, pending_charge = _events(snapshot["events"], turn)

    _object(policy, ("own_charged_moves", "energy_reserve", "shield_rule"),
            "fixed self policy")
    moves = policy["own_charged_moves"]
    if type(moves) is not list or len(moves) != 2:
        raise ValueError("Specify exactly two equipped own charge moves")
    seen = set()
    for move in moves:
        _object(move, ("move_id", "energy_cost"), "own charged move")
        move_id = move["move_id"]
        if type(move_id) is not str or not re.fullmatch(r"[A-Z0-9_]{1,100}", move_id):
            raise ValueError("Invalid own charged move ID")
        if move_id in seen:
            raise ValueError("Duplicate own charged move")
        seen.add(move_id)
        _int(move["energy_cost"], 1, 100, "charged move cost")
    reserve = _int(policy["energy_reserve"], 0, 30, "energy reserve")
    rule = policy["shield_rule"]
    if type(rule) is not str or rule not in SHIELD_RULES:
        raise ValueError("Unknown shield rule")

    if phase == "shield_prompt":
        if (not pending_charge or not snapshot["events"] or
                snapshot["events"][-1]["kind"] != "opponent_charge_announced"):
            raise ValueError("Shield choice requires a visible charge announcement")
        use = shields > 0 and (rule == "always" or
                            (rule == "first_announcement" and announcements == 1))
        action = {"kind": "shield", "use_shield": use}
    elif pending_charge:
        raise ValueError("Resolve the visible charge prompt before the next turn")
    elif not snapshot["own_can_act"]:
        action = {"kind": "wait"}
    else:
        chosen = next((move for move in moves
                       if energy >= move["energy_cost"] + reserve), None)
        action = ({"kind": "charged", "move_id": chosen["move_id"]} if chosen
                  else {"kind": "fast"})

    return {
        "schema": SCHEMA,
        "action": action,
        "information_model": "visible_input_contract_only",
        "observation_provenance_verified": False,
        "native_execution_verified": False,
        "practical_role_covered": False,
        "live_reproducibility": "not_verified",
    }
