#!/usr/bin/env python3
"""Matched synthetic 6v3 evaluation: fixed, untrained, and trained policies.

This is a correctness/quality gate, NOT a competitive win-rate estimate.
All candidates face the same public six, hidden trio/lead and native RNG seed
per evaluation scenario. Different decisions can consume RNG differently.
No evaluator reads private_replay or learns on held-out evaluation scenarios.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pvpoke_rl_mc_train import PublicMonteCarloPolicy, public_state
from pvpoke_rl_team_env import SixToThreeEnvironment
from run_rl_mc import GAME_DATA, fixture_teams, run_batch

BASELINE_SELECTION = "0,1,2|0"
KINDS = ("fixed", "untrained", "trained")
MAX_DECISIONS = 2000


def fixed_public_action(view):
    """Fixed first-three lead, native CPU's PUBLIC tactical rule."""
    kind, _, legal = public_state(view)
    if kind == "selection":
        if BASELINE_SELECTION not in legal:
            raise ValueError("Invalid fixed baseline selection space")
        return BASELINE_SELECTION
    actions = set(legal)
    own = view["own"]
    current = own["team"][own["active_slot"]]
    fraction = current["hp"] / current["max_hp"]
    if "shield_yes" in actions:
        return "shield_yes" if fraction >= 0.25 else "shield_no"
    switches = [a for a in legal if a.startswith("switch_")]
    if view["phase"] == "replace":
        return switches[0] if switches else "wait"
    charge = next((a for a in legal if a.startswith("charge_")), None)
    if charge is not None:
        return charge
    if fraction < 0.25 and switches:
        return switches[0]
    return "fast" if "fast" in actions else "wait"


def heldout_scenarios(*, count, seed):
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError("Evaluation episodes must be 1..32")
    if type(seed) is not int or not 0 <= seed <= 2**32 - count:
        raise ValueError("Invalid held-out seed")
    scenarios = []
    for index in range(count):
        episode_seed = seed + index
        rng = random.Random(episode_seed)
        chosen = tuple(sorted(rng.sample(range(6), 3)))
        lead = rng.choice(chosen)
        scenarios.append((episode_seed, chosen, lead))
    return scenarios


def evaluate_one(policy, label, scenario, *, max_decisions=MAX_DECISIONS):
    """Return only public aggregate-worthy outcomes, never secret opponents."""
    if label not in KINDS or type(max_decisions) is not int or not 1 <= max_decisions <= 4000:
        raise ValueError("Invalid evaluation parameters")
    own, public, opponent = fixture_teams()
    episode_seed, hidden, lead = scenario
    with SixToThreeEnvironment(
        GAME_DATA, own, public, opponent, hidden, lead, ruleset_id="great-league-v1"
    ) as env:
        view, _ = env.reset(seed=episode_seed)
        for step in range(1, max_decisions + 1):
            if view is None:
                raise ValueError("No active public evaluation observation")
            if label == "fixed":
                action = fixed_public_action(view)
            else:
                action, _ = policy.choose(view, epsilon=0.0)
            if action not in view["legal_actions"]:
                raise ValueError("Policy produced an illegal action")
            view, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                expected = {"self_ko_win": 1, "opponent_ko_win": -1,
                            "simultaneous_ko": 0}
                eligible = (
                    terminated is True and truncated is False and
                    info.get("training_eligible") is True and
                    type(reward) is int and
                    expected.get(info.get("outcome")) == reward and
                    info.get("selection_reward") == reward
                )
                return {
                    "status": "complete" if eligible else "discarded",
                    "reward": reward if eligible else None,
                    "decisions": step,
                }
    raise RuntimeError("Episode exceeded evaluation decision budget")


def _metrics(results):
    matches = [v for v in results if v["status"] == "complete"]
    wins = sum(v["reward"] == 1 for v in matches)
    losses = sum(v["reward"] == -1 for v in matches)
    draws = sum(v["reward"] == 0 for v in matches)
    count = len(matches)
    return {
        "episodes": len(results), "complete": count,
        "discarded": len(results) - count,
        "wins": wins, "losses": losses, "draws": draws,
        # No percentage when no valid matches. Never hide discarded games.
        "win_fraction_among_completed": round(wins / count, 4) if count else None,
        "mean_return_among_completed": (
            round(sum(v["reward"] for v in matches) / count, 4) if count else None),
        "total_decisions": sum(v["decisions"] for v in results),
    }


def evaluate_paired(*, trained, untrained, scenarios):
    """Use the SAME held-out scenario list for all three competing policies."""
    before = json.dumps(trained.snapshot(), sort_keys=True)
    results = {kind: [] for kind in KINDS}
    for scenario in scenarios:
        for kind, policy in (
            ("fixed", None), ("untrained", untrained), ("trained", trained)
        ):
            results[kind].append(evaluate_one(policy, kind, scenario))
    if json.dumps(trained.snapshot(), sort_keys=True) != before:
        raise RuntimeError("Held-out evaluation mutated the trained model")

    # Comparisons are defined only on the same episodes where BOTH policies
    # completed; timeouts are not losses. Return the denominator explicitly.
    comparisons = {}
    for competitor in ("fixed", "untrained"):
        paired = [
            (t["reward"], b["reward"])
            for t, b in zip(results["trained"], results[competitor])
            if t["status"] == "complete" and b["status"] == "complete"
        ]
        comparisons["trained_vs_" + competitor] = {
            "both_completed": len(paired),
            "trained_better": sum(t > b for t, b in paired),
            "equal_return": sum(t == b for t, b in paired),
            "trained_worse": sum(t < b for t, b in paired),
        }
    return {
        "label": "matched_initial_conditions_synthetic_not_competitive_strength",
        "metrics": {kind: _metrics(results[kind]) for kind in KINDS},
        "paired": comparisons,
        "evaluation_policy_updated": False,
        "rng_limitation": "equal_seed_not_identical_draws_after_divergent_actions",
        "confidence": "insufficient_for_strength_claims",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train", type=int, default=8)
    p.add_argument("--evaluate", type=int, default=4)
    p.add_argument("--seed", type=int, default=12)
    a = p.parse_args()
    if not 0 <= a.train <= 32 or not 1 <= a.evaluate <= 32:
        p.error("Training and evaluation each allow at most 32 episodes")
    if not 0 <= a.seed <= 2**32 - 200000:
        p.error("Invalid experiment seed")
    trained = PublicMonteCarloPolicy(seed=a.seed)
    trained_stats = run_batch(
        trained, episodes=a.train, seed=a.seed, epsilon=0.25, training=True,
    )
    # Reset policy RNGs to the same evaluation seed. Otherwise training-time
    # sampling history would confound "trained vs untrained" comparisons.
    eval_policy_seed = a.seed + 70000
    trained_eval = PublicMonteCarloPolicy.restore(
        trained.snapshot(), seed=eval_policy_seed)
    untrained = PublicMonteCarloPolicy(seed=eval_policy_seed)
    matched = evaluate_paired(
        trained=trained_eval, untrained=untrained,
        scenarios=heldout_scenarios(count=a.evaluate, seed=a.seed + 100000),
    )
    print(json.dumps({
        "phase": "rl-heldout-paired-eval-v1",
        "training": trained_stats,
        "matched_evaluation": matched,
        "training_completed_matches": trained.completed_matches,
        "schema": trained.snapshot()["schema"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
