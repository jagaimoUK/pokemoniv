#!/usr/bin/env python3
"""Exploratory follow-up on two predeclared high-completion synthetic selections.

The lineups were selected AFTER examining a six-scenario fixture probe, so
results MUST NOT be advertised as an unbiased competitiveness estimate.
Use a fresh held-out scenario seed window and never train on evaluation cases.
Both trained/untrained and fixed CPU use the same trio+lead in each comparison.
No private opponent data is passed to selectors or printed.
"""
from __future__ import annotations

import argparse
import json

from tools.evaluate_rl_fixed_selection import FixedOwnSelection, train_fixed_own
from tools.evaluate_rl_mc import evaluate_paired, heldout_scenarios
from tools.run_rl_mc import POLICY_VARIANTS
from tools.rl_wait_guard import ABLATION_NAME, GuardedWaitMonteCarloPolicy
from tools.rl_supported_tactics import MIN_EPISODES, SupportedTacticsPolicy

FOLLOWUP_SELECTIONS = ("2,3,5|2", "0,4,5|4")
HELDOUT_OFFSET = 200000
MAX_SEED = 2**32 - 300000


def compare_followup(*, policy_variant="v2", seed=12, train=12, evaluate=6,
                     guarded_ablation=False, support_ablation=False):
    if policy_variant not in POLICY_VARIANTS:
        raise ValueError("Unknown policy variant")
    if type(guarded_ablation) is not bool or (
            guarded_ablation and policy_variant != "v2"):
        raise ValueError("The wait ablation is opt-in and v2-only")
    if type(support_ablation) is not bool or (
            support_ablation and (policy_variant != "v2" or guarded_ablation)):
        raise ValueError("The support ablation is v2-only and runs separately")
    if (type(seed) is not int or not 0 <= seed <= MAX_SEED or
            type(train) is not int or not 0 <= train <= 16 or
            type(evaluate) is not int or not 1 <= evaluate <= 12):
        raise ValueError("Invalid bounded diagnostic parameters")
    cls = POLICY_VARIANTS[policy_variant]
    # Construct ONCE: both selections face precisely the same new opponent
    # selections, leads and per-episode native seed. None were used to choose
    # the follow-up lineups in the earlier 100000-offset fixture probe.
    scenarios = heldout_scenarios(
        count=evaluate, seed=seed + HELDOUT_OFFSET)
    out = {}
    for selection in FOLLOWUP_SELECTIONS:
        learner = cls(seed=seed)
        train_stats = train_fixed_own(
            learner, count=train, seed=seed, selection=selection)
        eval_policy_seed = seed + 70000
        trained = FixedOwnSelection(
            cls.restore(learner.snapshot(), seed=eval_policy_seed),
            selection)
        untrained = FixedOwnSelection(
            cls(seed=eval_policy_seed), selection)
        kwargs = {"trained": trained, "untrained": untrained,
                  "scenarios": scenarios, "fixed_selection": selection}
        if guarded_ablation:
            # Restore the exact same learned table and the same RNG seed.
            # Only the deterministic selection of unproven voluntary 'wait'
            # changes; no re-training or mutation of the original policy.
            guarded = FixedOwnSelection(
                GuardedWaitMonteCarloPolicy.restore(
                    learner.snapshot(), seed=eval_policy_seed), selection)
            kwargs["guarded"] = guarded
        if support_ablation:
            kwargs["supported"] = FixedOwnSelection(
                SupportedTacticsPolicy.restore(learner.snapshot(), seed=eval_policy_seed),
                selection)
        paired = evaluate_paired(**kwargs)
        out[selection] = {"training": train_stats, "evaluation": paired}
    return {
        "phase": "rl_fixed_selection_fresh_holdout_exploratory_v1",
        "policy_variant": policy_variant,
        "predeclared_own_selections": list(FOLLOWUP_SELECTIONS),
        "training_episodes_per_selection": train,
        "evaluation_scenarios_per_selection": evaluate,
        "heldout_seed_offset": HELDOUT_OFFSET,
        "wait_guard_ablation": ABLATION_NAME if guarded_ablation else None,
        **({"support_ablation": {"minimum_completed_episodes_per_action": MIN_EPISODES}}
           if support_ablation else {}),
        "selection_results": out,
        "limitations": (
            "Lineups selected from previous probe; exploratory only. "
            "Same initial RNG seed does not guarantee identical future draws "
            "after different tactical decisions. Clock timeouts are censored; "
            "no competitive-strength claim."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", choices=tuple(POLICY_VARIANTS), default="v2")
    p.add_argument("--seed", type=int, default=12)
    p.add_argument("--train", type=int, default=12)
    p.add_argument("--evaluate", type=int, default=6)
    ablation = p.add_mutually_exclusive_group()
    ablation.add_argument("--guarded-ablation", action="store_true",
                          help="Compare an evaluation-only v2 wait guard on the same checkpoint")
    ablation.add_argument("--support-ablation", action="store_true",
                          help="Compare tactical decisions supported by both action counts")
    a = p.parse_args()
    try:
        result = compare_followup(policy_variant=a.policy, seed=a.seed,
                                  train=a.train, evaluate=a.evaluate,
                                  guarded_ablation=a.guarded_ablation,
                                  support_ablation=a.support_ablation)
    except ValueError as e:
        p.error(str(e))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
