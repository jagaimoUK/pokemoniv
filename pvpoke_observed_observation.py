"""Public inputs for the bounded offline observation model."""
from dataclasses import dataclass
import hashlib
import json
import re

SCHEMA = "observed-history-v2"
MODEL = "synthetic-clock-v2"
FLAGS = {"information_fairness": "not_established", "live_reproducibility": "not_verified",
         "practical_role_covered": False}
MAX_EVENTS = 64
MAX_DECISIONS = 512
_ACTIONS = ("fast", "charge_0", "charge_1", "wait_one_window")
_SHIELDS = ("shield_no", "shield_yes")
_FIELDS = {
    "window": (), "charge_announced": (), "intent": ("action",),
    "charge_revealed": ("move_id",), "opponent_fast": ("move_id",),
    "own_fast_resolved": (), "own_charge_resolved": ("slot",),
    "own_shield_used": (), "opponent_shield_used": (),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def integer(value, low, high):
    return type(value) is int and low <= value <= high


@dataclass(frozen=True)
class Context:
    build_id: str
    costs: tuple[int, int]
    initial_energy: int
    initial_shields: tuple[int, int]
    fast_gain: int = 8
    public_opponent: str = "unknown"

    def __post_init__(self):
        if (not isinstance(self.build_id, str) or not re.fullmatch(r"[a-f0-9]{64}", self.build_id)
                or type(self.costs) is not tuple or len(self.costs) != 2
                or not all(integer(x, 1, 100) for x in self.costs)
                or not integer(self.initial_energy, 0, 100)
                or type(self.initial_shields) is not tuple or len(self.initial_shields) != 2
                or not all(integer(x, 0, 2) for x in self.initial_shields)
                or not integer(self.fast_gain, 0, 100)
                or not isinstance(self.public_opponent, str)
                or not re.fullmatch(r"[a-z0-9_]{1,80}", self.public_opponent)):
            raise ValueError("Invalid public context")

    @property
    def key(self):
        return digest([MODEL, self.build_id, self.costs, self.initial_energy,
                       self.initial_shields, self.fast_gain, self.public_opponent])


@dataclass(frozen=True)
class ObservationV2:
    key: str
    seq: int
    phase: str
    legal: tuple[str, ...]
    self_knowledge: tuple[int, int, int]
    timing_candidates: tuple[int, ...]

    @classmethod
    def read(cls, context, events):
        if type(events) is not list or not 1 <= len(events) <= 2 * MAX_DECISIONS + MAX_EVENTS:
            raise ValueError("Invalid observation length")
        energy = context.initial_energy
        shields = list(context.initial_shields)
        phase = pending = None
        last_low = last_high = public = decisions = 0
        for i, event in enumerate(events, 1):
            if type(event) is not dict or type(event.get("kind")) is not str:
                raise ValueError("Invalid observation event")
            kind = event["kind"]
            if kind not in _FIELDS or set(event) != {"seq", "kind", "observed_time_range", *_FIELDS[kind]}:
                raise ValueError("Unknown observation fields")
            time = event["observed_time_range"]
            if (not integer(event["seq"], i, i) or type(time) is not list or len(time) != 2
                    or not integer(time[0], last_low, 500) or not integer(time[1], max(last_high, time[0]), 500)):
                raise ValueError("Invalid observation order")
            last_low, last_high = time
            if phase is not None and kind != "intent":
                raise ValueError("Missing intent before subsequent observation")
            if kind in ("window", "charge_announced"):
                decisions += 1
                if pending is not None:
                    raise ValueError("Overlapping prompt")
                phase = kind
            elif kind == "intent":
                legal = _legal(phase, energy, shields[0], context.costs)
                if event["action"] not in legal:
                    raise ValueError("Invalid observed intent")
                if phase == "charge_announced":
                    pending = event["action"]
                phase = None
            else:
                public += 1
                if kind in ("charge_revealed", "opponent_fast"):
                    if not isinstance(event["move_id"], str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", event["move_id"]):
                        raise ValueError("Invalid revealed move")
                if kind == "charge_revealed":
                    if pending is None:
                        raise ValueError("Charge reveal before shield decision")
                    pending = None
                elif kind == "own_fast_resolved":
                    energy = min(100, energy + context.fast_gain)
                elif kind == "own_charge_resolved":
                    slot = event["slot"]
                    if not integer(slot, 0, 1) or energy < context.costs[slot]:
                        raise ValueError("Invalid own charge resolution")
                    energy -= context.costs[slot]
                elif kind.endswith("_shield_used"):
                    side = int(kind.startswith("opponent"))
                    if shields[side] == 0 or (side == 0 and pending != "shield_yes"):
                        raise ValueError("Invalid shield use")
                    shields[side] -= 1
                    if side == 0:
                        pending = "shield_consumed"
            if public > MAX_EVENTS or decisions > MAX_DECISIONS:
                raise ValueError("Observation budget exceeded")
        if phase is None:
            raise ValueError("History must end at a decision")
        return cls(digest([SCHEMA, context.key, events]), len(events), phase,
                   _legal(phase, energy, shields[0], context.costs), (energy, *shields),
                   tuple(range(last_low, last_high + 1)))


def _legal(phase, energy, shields, costs):
    if phase == "window":
        return tuple(a for a in _ACTIONS if not a.startswith("charge_") or energy >= costs[int(a[-1])])
    if phase == "charge_announced":
        return _SHIELDS if shields else _SHIELDS[:1]
    return ()


def history_key(context, events):
    return ObservationV2.read(context, events).key
