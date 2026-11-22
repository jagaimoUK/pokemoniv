"""Strict 3v3 native-state snapshot contract, NOT a battle simulator.

A future native engine supplies authoritative states after all actions.
This module never invents damage, switch transitions or shield decisions.
"""
from __future__ import annotations
from copy import deepcopy


def integer(value, low, high):
    return type(value) is int and low <= value <= high


class ThreeVThreeSnapshot:
    def __init__(self, native_state):
        if (type(native_state) is not dict or
                set(native_state) != {"turn", "sides"} or
                not integer(native_state["turn"], 1, 100000)):
            raise ValueError("Invalid native 3v3 state wrapper")
        sides = native_state["sides"]
        if type(sides) is not list or len(sides) != 2:
            raise ValueError("Exactly two teams required")
        for side in sides:
            if (type(side) is not dict or
                    set(side) != {"team", "active_slot", "shields",
                                  "switch_timer_ms"} or
                    not integer(side["active_slot"], 0, 2) or
                    not integer(side["shields"], 0, 2) or
                    not integer(side["switch_timer_ms"], 0, 240000)):
                raise ValueError("Invalid shared shields or switch timer")
            team = side["team"]
            if type(team) is not list or len(team) != 3:
                raise ValueError("Exactly three selected Pokemon required")
            for member in team:
                if (type(member) is not dict or
                        set(member) != {"species", "hp", "max_hp",
                                        "energy_points", "buffs", "cooldown_ms"} or
                        type(member["species"]) is not str or
                        not member["species"] or
                        not integer(member["max_hp"], 1, 10000) or
                        not integer(member["hp"], 0, member["max_hp"]) or
                        not integer(member["energy_points"], 0, 100) or
                        type(member["buffs"]) is not list or
                        len(member["buffs"]) != 2 or
                        not all(integer(stage, -4, 4)
                                for stage in member["buffs"]) or
                        not integer(member["cooldown_ms"], 0, 240000)):
                    raise ValueError("Invalid per-Pokemon native state")
            if team[side["active_slot"]]["hp"] == 0:
                raise ValueError("Resolve fainted active Pokemon before snapshot")
        self._data = deepcopy(native_state)

    def export_private(self):
        """Trusted engine/handoff only: includes both hidden bench teams."""
        return deepcopy(self._data)

    def observe(self, *, own_side=0, revealed_opponent_slots=None):
        """Exclude hidden opposing bench members and private resource states."""
        if not integer(own_side, 0, 1):
            raise ValueError("Invalid observer side")
        opponent = self._data["sides"][1 - own_side]
        revealed = set(revealed_opponent_slots or ())
        if any(not integer(i, 0, 2) for i in revealed):
            raise ValueError("Invalid revealed opponent slot")
        revealed.add(opponent["active_slot"])
        return {
            "schema": "rl-public-3v3-state-v1",
            "turn": self._data["turn"],
            "own": deepcopy(self._data["sides"][own_side]),
            "opponent": {
                "active_species": opponent["team"][opponent["active_slot"]]["species"],
                "shields": opponent["shields"],
                # Sort species rather than private slot indexes/order.
                "known_species": sorted({
                    opponent["team"][i]["species"] for i in revealed
                }),
            },
            "verified_native_transition": False,
        }
