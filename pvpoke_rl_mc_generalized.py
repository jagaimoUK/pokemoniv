"""Opt-in v2 coarse PUBLIC state abstraction for synthetic 6v3 training.

Important: v1 checkpoints are deliberately incompatible. This does not infer
unrevealed opponents or read private_replay. It intentionally groups states
for a learning-baseline experiment, not for certified competitive strength.
"""
from __future__ import annotations

import hashlib
import json

from pvpoke_rl_mc_train import PublicMonteCarloPolicy, LearningError, public_state

VERSION = "rl-public-mc-generalized-v2"


def bounded_integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise LearningError("Invalid public " + name)
    return value


def coarse_public_state(view):
    """Map similar observations to the same state while keeping action legality.

    - Never uses hidden opponents, raw events, private replay or the policy's
      knowledge of the future.
    - Switch target identities must NOT be merged across different teams;
      two different switch_1 destinations may require different choices.
    - Deliberately ignores exact energy/cooldown once the LEGAL action mask is
      fixed; the resulting approximation must be evaluated against the v1 key.
    """
    kind, old_key, legal = public_state(view)
    if kind == "selection":
        # Maintain the exact public 6v3 team preview as one state. Different
        # opponents' hidden trios are still invisible to both encoders.
        data = ["selection", old_key]
    else:
        own, opponent = view["own"], view["opponent"]
        team = own["team"]
        slot = bounded_integer(own["active_slot"], 0, 2, "active slot")
        pokemon = team[slot]
        hp = bounded_integer(pokemon["hp"], 0, pokemon["max_hp"], "active HP")
        max_hp = bounded_integer(pokemon["max_hp"], 1, 10000, "max HP")
        own_hp_band = min(4, hp * 4 // max_hp)
        active_species = pokemon["species"]
        enemy_species = opponent["active_species"]
        revealed = opponent["revealed"]
        if type(active_species) is not str or type(enemy_species) is not str:
            raise LearningError("Invalid active species")
        seen = [member for member in revealed
                if member["species"] == enemy_species]
        if len(seen) != 1:
            raise LearningError("Active opponent must be publicly revealed")
        enemy_hp = bounded_integer(
            seen[0]["hp_bucket_5pct"], 0, 20, "enemy HP band")
        enemy_known_moves = seen[0]["seen_moves"]
        if type(enemy_known_moves) is not list or any(
                type(m) is not str for m in enemy_known_moves):
            raise LearningError("Invalid public enemy move history")
        buff = pokemon["buffs"]
        if type(buff) is not list or len(buff) != 2:
            raise LearningError("Invalid buff observation")
        buff_signs = [(-1 if bounded_integer(v, -4, 4, "buff") < 0 else
                       1 if v > 0 else 0) for v in buff]
        charged = pokemon["charged_moves"]
        if type(charged) is not list or len(charged) != 2:
            raise LearningError("Invalid equipped moves")
        moves = [pokemon["fast_move"],
                 *[m["move_id"] for m in charged]]
        for m in moves:
            if type(m) is not str or not m:
                raise LearningError("Invalid own public move")

        # A switch_1 action has different effects depending on the
        # destination Pokemon. Preserve slot identities only when switching
        # is legal; otherwise allow the same active matchup to generalize.
        has_switch = any(a.startswith("switch_") for a in legal)
        bench = (
            [[member["species"],
              min(4, bounded_integer(member["hp"], 0, member["max_hp"], "bench HP") *
                  4 // bounded_integer(member["max_hp"], 1, 10000, "bench max HP"))]
             for member in team]
            if has_switch else [
                int(member["hp"] > 0) for member in team
            ]
        )
        earlier_seen = sorted([
            (member["species"], bool(member["fainted"]))
            for member in revealed if member["species"] != enemy_species
        ])
        data = [
            "tactics", view["ruleset_id"], view["phase"], slot,
            active_species, moves, own_hp_band,
            bounded_integer(own["shields"], 0, 2, "own shields"),
            bounded_integer(opponent["shields"], 0, 2, "enemy shields"),
            enemy_species, enemy_hp // 5, sorted(enemy_known_moves),
            earlier_seen, bench, buff_signs, sorted(legal),
        ]
    try:
        wire = json.dumps(data, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise LearningError("Invalid public coarse state") from error
    if len(wire) > 32768:
        raise LearningError("Coarse state exceeded bound")
    key = hashlib.sha256(VERSION.encode() + b":" + wire).hexdigest()
    return kind, key, legal


class GeneralizedMonteCarloPolicy(PublicMonteCarloPolicy):
    """Same learner as v1; only the PUBLIC feature map and schema are new."""

    MODEL_VERSION = VERSION

    def encode_state(self, view):
        return coarse_public_state(view)
