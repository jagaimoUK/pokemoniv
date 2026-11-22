"""Bounded, offline tabular Monte Carlo learner for public 6v3 observations.

This is a first real learning loop, not PPO or a competitive-strength AI.
Policies see ONLY the public observation; the trainer never reads private_replay.
Only fully terminated, training-eligible matches update values. Incomplete or
unsupported episodes provide neither wins nor losses.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

from pvpoke_rl_team_env import verified_6v3_return

VERSION = "rl-public-mc-v1"
TACTICAL = frozenset(("turn", "shield", "replace"))
TACTIC_ACTIONS = frozenset(("wait", "fast", "charge_0", "charge_1",
                           "switch_0", "switch_1", "switch_2",
                           "shield_yes", "shield_no"))
OWN_PREVIEW = ("species", "fast", "charged1", "charged2",
               "atk", "def", "hp", "level", "cp")
PUBLIC_PREVIEW = ("species", "known_moves")
PRIORITY = ("shield_yes", "charge_0", "charge_1", "fast",
            "switch_0", "switch_1", "switch_2", "shield_no", "wait")
MAX_STATES = 50000


class LearningError(ValueError):
    """Invalid observation, result or training checkpoint."""


def _required(row, key):
    if type(row) is not dict or key not in row:
        raise LearningError("Invalid public observation")
    return row[key]


def _fraction(hp, maximum, scale=10):
    if type(hp) is not int or type(maximum) is not int or maximum < 1 or not 0 <= hp <= maximum:
        raise LearningError("Invalid public HP")
    return (hp * scale) // maximum


def public_state(observation):
    """Derive an allowlisted state key. Never hash raw replay or private data."""
    schema = _required(observation, "schema")
    phase = _required(observation, "phase")
    legal = _required(observation, "legal_actions")
    if (type(legal) is not list or not legal or len(legal) > 60 or
            any(type(a) is not str for a in legal) or
            len(legal) != len(set(legal))):
        raise LearningError("Invalid legal actions")
    if schema == "rl-6v3-preview-v1" and phase == "select_three":
        own = _required(observation, "own_six")
        opponent = _required(observation, "opponent_public_six")
        if type(own) is not list or type(opponent) is not list or len(own) != 6 or len(opponent) != 6:
            raise LearningError("Invalid public team preview")
        if len(legal) != 60:
            raise LearningError("Expected exactly 60 legal 6v3 actions")
        try:
            own_view = [[_required(member, key) for key in OWN_PREVIEW] for member in own]
            enemy_view = [[_required(member, "species"),
                           sorted(_required(member, "known_moves"))] for member in opponent]
        except (TypeError, ValueError) as exc:
            raise LearningError("Invalid public preview fields") from exc
        data = ["select", _required(observation, "ruleset_id"), own_view, enemy_view]
        kind = "selection"
    elif schema == "rl-native-3v3-v1" and phase in TACTICAL:
        if not set(legal) <= TACTIC_ACTIONS:
            raise LearningError("Unsupported tactical action")
        own = _required(observation, "own")
        enemy = _required(observation, "opponent")
        team = _required(own, "team")
        if type(team) is not list or len(team) != 3:
            raise LearningError("Invalid own team observation")
        own_view = []
        for member in team:
            own_view.append([
                _required(member, "species"),
                _fraction(_required(member, "hp"), _required(member, "max_hp")),
                _required(member, "energy_points") // 10,
                _required(member, "buffs"),
                _required(member, "cooldown_ms") // 500,
                _required(member, "fast_move"),
                [[_required(move, "move_id"), _required(move, "energy_cost")]
                 for move in _required(member, "charged_moves")],
            ])
        revealed = _required(enemy, "revealed")
        if type(revealed) is not list or len(revealed) > 3:
            raise LearningError("Invalid revealed opponent team")
        enemy_view = sorted([
            [_required(member, "species"), _required(member, "hp_bucket_5pct"),
             _required(member, "fainted"), sorted(_required(member, "seen_moves"))]
            for member in revealed
        ], key=lambda row: (row[0], row[1], str(row[3])))
        data = [
            "tactic", _required(observation, "ruleset_id"), phase,
            _required(own, "active_slot"), _required(own, "shields"),
            _required(own, "switch_timer_ms") // 5000, own_view,
            _required(enemy, "active_species"), _required(enemy, "shields"),
            enemy_view,
        ]
        kind = "tactics"
    else:
        raise LearningError("Unsupported public observation schema")

    # Include legal actions. Never train a value on an action that is
    # impossible in the current phase, even with similar resource buckets.
    data.append(sorted(legal))
    try:
        wire = json.dumps(data, sort_keys=True, allow_nan=False,
                          ensure_ascii=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise LearningError("Invalid observation values") from exc
    if len(wire) > 32768:
        raise LearningError("Public observation exceeds the state budget")
    return kind, hashlib.sha256(VERSION.encode() + b":" + wire).hexdigest(), tuple(legal)


class PublicMonteCarloPolicy:
    """First-visit terminal-return learner, keyed exclusively by public views.

    Stores counts and return means per state-action. It does not access the
    environment, hidden opponent choices or replay. Tactics receive the same
    final match return, so credit assignment is intentionally coarse.
    """

    MODEL_VERSION = VERSION

    def __init__(self, *, seed=0):
        if type(seed) is not int:
            raise ValueError("Policy seed must be an integer")
        self._rng = random.Random(seed)
        self._values = {"selection": {}, "tactics": {}}
        self.completed_matches = 0

    def encode_state(self, view):
        """Version-matched public state encoder used by decisions AND audits.

        Evaluators must call this method rather than calling public_state()
        directly: the optional v2 policy has a different state-key schema.
        """
        return public_state(view)

    def choose(self, view, *, epsilon=0.2):
        return self._choose_encoded(self.encode_state(view), epsilon=epsilon)

    def _choose_encoded(self, encoded, *, epsilon):
        """Use the same action-selection algorithm with a versioned encoder."""
        if type(epsilon) not in (float, int) or not math.isfinite(epsilon) or not 0 <= epsilon <= 1:
            raise ValueError("epsilon must be between 0 and 1")
        kind, key, legal = encoded
        table = self._values[kind].get(key, {})
        if self._rng.random() < epsilon or (kind == "selection" and not table):
            action = self._rng.choice(legal)
        else:
            estimates = {action: table[action][1] if action in table else 0.0 for action in legal}
            best = max(estimates.values())
            ties = [a for a in legal if estimates[a] == best]
            if kind == "selection":
                action = self._rng.choice(ties)
            else:
                action = min(ties, key=lambda a: PRIORITY.index(a))
        return action, (kind, key, action)

    def learn(self, decisions, *, reward, selection_reward):
        if (type(reward) is not int or reward not in (-1, 0, 1) or
                type(selection_reward) is not int or selection_reward not in (-1, 0, 1) or
                reward != selection_reward or
                type(decisions) is not list or not decisions):
            raise LearningError("Only verified 6v3 terminal returns may train")
        if decisions[0][0] != "selection" or sum(k == "selection" for k, _, _ in decisions) != 1:
            raise LearningError("Each episode must start with exactly one selection")
        for item in decisions:
            if type(item) is not tuple or len(item) != 3:
                raise LearningError("Invalid training decision")
            kind, key, action = item
            if (kind not in self._values or type(key) is not str or len(key) != 64 or
                    any(c not in "0123456789abcdef" for c in key) or
                    type(action) is not str or
                    (kind == "tactics" and action not in TACTIC_ACTIONS)):
                raise LearningError("Invalid training decision")
        # One update per state-action pair per episode. Prevent long episodes
        # dominated by repeated wait decisions from disproportionate weighting.
        unique = tuple(dict.fromkeys(decisions))
        # Check all quotas BEFORE the first write, so errors never half-train.
        for kind in self._values:
            fresh = {key for row_kind, key, _ in unique
                     if row_kind == kind and key not in self._values[kind]}
            if len(self._values[kind]) + len(fresh) > MAX_STATES:
                raise LearningError("Training state budget exhausted")
        for kind, key, action in unique:
            target = selection_reward if kind == "selection" else reward
            states = self._values[kind]
            if key not in states:
                states[key] = {}
            count, mean = states[key].get(action, (0, 0.0))
            states[key][action] = (count + 1, mean + (target - mean) / (count + 1))
        self.completed_matches += 1

    def snapshot(self):
        # No raw observations, opponent private team, replay, or credentials.
        return {"schema": self.MODEL_VERSION, "completed_matches": self.completed_matches,
                "values": self._values}

    @classmethod
    def restore(cls, payload, *, seed=0):
        if (type(payload) is not dict or set(payload) !=
                {"schema", "completed_matches", "values"} or
                payload["schema"] != cls.MODEL_VERSION or
                type(payload["completed_matches"]) is not int or
                payload["completed_matches"] < 0):
            raise LearningError("Invalid learning checkpoint")
        tables = payload["values"]
        if type(tables) is not dict or set(tables) != {"selection", "tactics"}:
            raise LearningError("Invalid checkpoint tables")
        instance = cls(seed=seed)
        for kind, states in tables.items():
            if type(states) is not dict or len(states) > MAX_STATES:
                raise LearningError("Invalid checkpoint state budget")
            for key, rows in states.items():
                if (type(key) is not str or len(key) != 64 or
                        any(c not in "0123456789abcdef" for c in key) or
                        type(rows) is not dict or len(rows) > 60):
                    raise LearningError("Invalid checkpoint state")
                restored = {}
                for action, pair in rows.items():
                    if (type(action) is not str or
                            (kind == "tactics" and action not in TACTIC_ACTIONS) or
                            type(pair) not in (list, tuple) or len(pair) != 2 or
                            type(pair[0]) is not int or pair[0] < 1 or
                            type(pair[1]) not in (float, int) or
                            not math.isfinite(pair[1]) or not -1 <= pair[1] <= 1):
                        raise LearningError("Invalid checkpoint return")
                    restored[action] = (pair[0], float(pair[1]))
                instance._values[kind][key] = restored
        instance.completed_matches = payload["completed_matches"]
        return instance


def play_episode(env, policy, *, seed=0, epsilon=0.2, max_decisions=2000, learn=True):
    """Use only public observations; fail closed on invalid or oversized games."""
    if type(max_decisions) is not int or not 1 <= max_decisions <= 4000:
        raise ValueError("Invalid decision budget")
    view, _ = env.reset(seed=seed)
    decisions = []
    for n in range(max_decisions):
        if view is None:
            raise LearningError("Episode ended before an action")
        action, record = policy.choose(view, epsilon=epsilon if learn else 0.0)
        decisions.append(record)
        view, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            target = verified_6v3_return(reward, terminated, truncated, info)
            eligible = target is not None
            if eligible and learn:
                policy.learn(decisions, reward=target, selection_reward=target)
            return {"status": "complete" if eligible else "discarded",
                    "outcome": info.get("outcome") if type(info) is dict else None,
                    "reward": target,
                    "decisions": n + 1, "updated": bool(eligible and learn)}
    raise LearningError("Episode exceeded the bounded decision budget")
