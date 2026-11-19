#!/usr/bin/env python3
"""Controlled fixed-own-selection diagnostic for native 6v3 Monte Carlo.

The held-out opponent's chosen three and lead vary per seed. Own selection is
intentionally held constant in TRAINING and EVALUATION to distinguish selection
distribution shift from sparse tactical-state transfer.

Do not use these artificially fixed-selection results as a competition rating.
"""
from __future__ import annotations

import argparse
import json
import random

from pvpoke_rl_mc_train import play_episode
from tools.evaluate_rl_mc import evaluate_paired, heldout_scenarios
from tools.run_rl_mc import GAME_DATA, POLICY_VARIANTS, fixture_teams
from pvpoke_rl_team_env import SixToThreeEnvironment

DEFAULT_SELECTION = "0,1,4|4"


class FixedOwnSelection:
    """A public-policy adapter: selects an agreed legal trio, learns tactics.

    No private opponent information, no access to native replay, no modification
    of the underlying policy's state representation or checkpoint.
    """
    def __init__(self, policy, selection=DEFAULT_SELECTION):
        if type(selection) is not str:
            raise ValueError("Invalid fixed selection")
        self.policy = policy
        self.selection = selection

    def choose(self, view, *, epsilon=0.0):
        kind, key, legal = self.policy.encode_state(view)
        if kind == "selection":
            if self.selection not in legal:
                raise ValueError("Fixed selection must be a legal public action")
            return self.selection, (kind, key, self.selection)
        return self.policy.choose(view, epsilon=epsilon)

    def encode_state(self, view):
        return self.policy.encode_state(view)

    def snapshot(self):
        return self.policy.snapshot()


def train_fixed_own(policy, *, count, seed, selection=DEFAULT_SELECTION):
    """Train only from valid KO-decided episodes and return an honest summary."""
    if type(count) is not int or not 0 <= count <= 32:
        raise ValueError("Training count must be 0..32")
    if type(seed) is not int or not 0 <= seed <= 2**32 - count:
        raise ValueError("Invalid seed")
    own, public, enemy = fixture_teams()
    adapter = FixedOwnSelection(policy, selection)
    stats = {"complete": 0, "discarded": 0, "updates": 0,
             "wins": 0, "losses": 0, "draws": 0}
    for n in range(count):
        rng = random.Random(seed + n)
        hidden = tuple(sorted(rng.sample(range(6), 3)))
        lead = rng.choice(hidden)
        with SixToThreeEnvironment(
            GAME_DATA, own, public, enemy, hidden, lead,
            ruleset_id="great-league-v1"
        ) as env:
            result = play_episode(env, adapter, seed=seed + n,
                                  epsilon=0.25, learn=True)
        stats[result["status"]] += 1
        stats["updates"] += int(result["updated"])
        if result["status"] == "complete":
            stats[{1: "wins", -1: "losses", 0: "draws"}[result["reward"]]] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=tuple(POLICY_VARIANTS), default="v2")
    parser.add_argument("--train", type=int, default=12)
    parser.add_argument("--evaluate", type=int, default=6)
    parser.add_argument("--seed", type=int, default=12)
    parser.add_argument("--selection", default=DEFAULT_SELECTION)
    args = parser.parse_args()
    if not 0 <= args.train <= 32 or not 1 <= args.evaluate <= 32:
        parser.error("Train and evaluation counts are limited to 0..32 and 1..32")
    if type(args.seed) is not int or not 0 <= args.seed <= 2**32 - 100001:
        parser.error("Invalid experiment seed")
    cls = POLICY_VARIANTS[args.policy]
    learner = cls(seed=args.seed)
    training = train_fixed_own(learner, count=args.train, seed=args.seed,
                               selection=args.selection)
    eval_seed = args.seed + 70000
    trained = FixedOwnSelection(cls.restore(learner.snapshot(), seed=eval_seed),
                                args.selection)
    untrained = FixedOwnSelection(cls(seed=eval_seed), args.selection)
    metrics = evaluate_paired(
        trained=trained, untrained=untrained,
        scenarios=heldout_scenarios(count=args.evaluate,
                                    seed=args.seed + 100000))
    print(json.dumps({
        "experiment": "fixed_own_selection_tactics_transfer_diagnostic_v1",
        "policy_variant": args.policy,
        "own_selection": args.selection,
        "training": training,
        "evaluation": metrics,
        "limits": "synthetic 6v3 only; hidden opponent lineup varies; fixed baseline uses separate own selection",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
