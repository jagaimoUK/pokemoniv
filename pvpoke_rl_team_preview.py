"""Experimental public 6-to-3 selection contract, not a battle simulator.

A selection policy is given only the public six and its own six. Hidden
opponent choices and IVs are private evaluator state, not policy inputs.
"""
from __future__ import annotations
from copy import deepcopy
from itertools import combinations
import math
import re

FIELDS = frozenset(("species", "fast", "charged1", "charged2",
                   "atk", "def", "hp", "level", "cp",
                   "combatant_id", "roster_clause_id"))
PUBLIC_FIELDS = frozenset(("species", "roster_clause_id", "known_moves"))
IDENTIFIER = re.compile(r"[A-Za-z0-9_:-]{1,100}\Z")


def ident(value):
    return type(value) is str and IDENTIFIER.fullmatch(value) is not None


def prepared(row):
    if (type(row) is not dict or set(row) != FIELDS or
            not all(ident(row[k]) for k in
                    ("species", "fast", "charged1", "charged2",
                     "combatant_id", "roster_clause_id")) or
            not all(type(row[k]) is int and 0 <= row[k] <= 15
                    for k in ("atk", "def", "hp")) or
            type(row["level"]) not in (int, float) or
            not math.isfinite(row["level"]) or
            row["level"] * 2 != int(row["level"] * 2) or
            not 1 <= row["level"] <= 50 or
            type(row["cp"]) is not int or not 10 <= row["cp"] <= 1500):
        raise ValueError("Invalid prepared selection member")
    return deepcopy(row)


def public_member(row):
    if (type(row) is not dict or
            not {"species", "roster_clause_id"} <= set(row) or
            not set(row) <= PUBLIC_FIELDS or
            not ident(row["species"]) or not ident(row["roster_clause_id"])):
        raise ValueError("Invalid public team-preview member")
    moves = row.get("known_moves", [])
    if (type(moves) is not list or len(moves) > 3 or
            any(not ident(m) for m in moves) or
            len(set(moves)) != len(moves)):
        raise ValueError("Invalid public moves")
    return {"species": row["species"],
            "roster_clause_id": row["roster_clause_id"],
            "known_moves": moves[:]}


def six(rows, parser, with_ids=False):
    if type(rows) is not list or len(rows) != 6:
        raise ValueError("Exactly six team members required")
    parsed = [parser(row) for row in rows]
    if (len({p["roster_clause_id"] for p in parsed}) != 6 or
            len({p["species"] for p in parsed}) != 6):
        raise ValueError("Duplicate roster clause")
    if with_ids and len({p["combatant_id"] for p in parsed}) != 6:
        raise ValueError("Duplicate combatant ID")
    return parsed


class SixToThreeSelection:
    """One action before battle. Only observe() may be shown to the policy.

    Python object introspection is not an access-control boundary. Trusted
    code must isolate the private evaluator and never pass it to the policy.
    """

    def __init__(self, own_six, opponent_public_six, opponent_private_six,
                 opponent_chosen_three, opponent_lead, *, ruleset_id):
        if not ident(ruleset_id):
            raise ValueError("Explicit versioned ruleset ID required")
        self._own = six(own_six, prepared, True)
        self._preview = six(opponent_public_six, public_member)
        self._opponent = six(opponent_private_six, prepared, True)
        for public, private in zip(self._preview, self._opponent):
            if (public["species"] != private["species"] or
                    public["roster_clause_id"] != private["roster_clause_id"] or
                    any(move not in (private["fast"], private["charged1"],
                                     private["charged2"])
                        for move in public["known_moves"])):
                raise ValueError("Public preview conflicts with private opponent")
        if (type(opponent_chosen_three) not in (tuple, list) or
                len(opponent_chosen_three) != 3 or
                any(type(i) is not int or i not in range(6)
                    for i in opponent_chosen_three) or
                len(set(opponent_chosen_three)) != 3 or
                type(opponent_lead) is not int or
                opponent_lead not in opponent_chosen_three):
            raise ValueError("Invalid hidden opponent selection")
        self._enemy_trio = tuple(sorted(opponent_chosen_three))
        self._enemy_lead = opponent_lead
        self._ruleset = ruleset_id
        self._actions = {
            f"{i},{j},{k}|{lead}": (combo, lead)
            for combo in combinations(range(6), 3)
            for i, j, k in [combo]
            for lead in combo
        }
        if len(self._actions) != 60:
            raise RuntimeError("Invalid preview action count")
        self._choice = None

    def observe(self):
        if self._choice is not None:
            raise RuntimeError("Selection was already committed")
        return {"schema": "rl-6v3-preview-v1", "phase": "select_three",
                "ruleset_id": self._ruleset,
                "own_six": deepcopy(self._own),
                "opponent_public_six": deepcopy(self._preview),
                "legal_actions": list(self._actions),
                "opponent_selected_three_known": False}

    def choose(self, action_id):
        if self._choice is not None:
            raise RuntimeError("Cannot change a committed trio")
        if type(action_id) is not str or action_id not in self._actions:
            raise ValueError("Illegal 6v3 selection")
        trio, lead = self._actions[action_id]
        self._choice = (trio, lead)
        # Crucially, no fabricated match outcome or training reward.
        return {"status": "awaiting_native_3v3_engine",
                "selected_slots": list(trio), "lead_slot": lead,
                "reward": None, "battle_verified": False}

    def _private_engine_input(self):
        """Trusted 3v3 coordinator only; NEVER send to a selection policy."""
        if self._choice is None:
            raise RuntimeError("Commit selection before creating battle input")
        own, lead = self._choice
        own_order = (lead, *(i for i in own if i != lead))
        enemy_order = (self._enemy_lead,
                       *(i for i in self._enemy_trio if i != self._enemy_lead))
        return {"schema": "rl-private-3v3-handoff-v1",
                "ruleset_id": self._ruleset,
                "own_team": deepcopy([self._own[i] for i in own_order]),
                "opponent_team": deepcopy([self._opponent[i] for i in enemy_order]),
                "battle_verified": False}
