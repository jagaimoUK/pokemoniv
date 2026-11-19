#!/usr/bin/env python3
"""Run a tiny synthetic 6v3 Monte Carlo learning/evaluation batch offline.

Examples:
  PYTHONPATH=.:tests python tools/run_rl_mc.py --train 8 --evaluate 4
  PYTHONPATH=.:tests python tools/run_rl_mc.py --train 8 --save /tmp/rl-mc-01.json
  PYTHONPATH=.:tests python tools/run_rl_mc.py --load /tmp/rl-mc-01.json \
    --train 8 --save /tmp/rl-mc-02.json

No app database, HTTP endpoint, PvPoke MCP, cloud storage, or production model.
The private opponent selection is restricted to the local synthetic evaluator.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pvpoke_rl_mc_train import PublicMonteCarloPolicy, play_episode
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy

POLICY_VARIANTS = {"v1": PublicMonteCarloPolicy,
                   "v2": GeneralizedMonteCarloPolicy}
from pvpoke_rl_team_env import SixToThreeEnvironment

FIXTURE = ROOT / "tests" / "fixtures"
ROWS = FIXTURE / "strategy_rows.json"
GAME_DATA = FIXTURE / "strategy_gamemaster.json"


def save_new_checkpoint(path, policy):
    """Create a new 0600 checkpoint, never overwrite an existing one."""
    destination = Path(path).expanduser().absolute()
    if not destination.parent.is_dir():
        raise ValueError("Checkpoint parent directory does not exist")
    data = json.dumps(policy.snapshot(), sort_keys=True, separators=(",", ":"))
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Checkpoint exceeds 8 MiB")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=".rl-mc-pending-", delete=False
        ) as tmp:
            temp_path = Path(tmp.name)
            os.fchmod(tmp.fileno(), 0o600)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        # Atomic new-file creation; leave previous checkpoints intact.
        os.link(temp_path, destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def read_checkpoint(path, seed, policy_class=PublicMonteCarloPolicy):
    source = Path(path).expanduser()
    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Checkpoint exceeds 8 MiB")
    return policy_class.restore(
        json.loads(source.read_text(encoding="utf-8")), seed=seed)


def fixture_teams():
    raw = json.loads(ROWS.read_text(encoding="utf-8"))
    if type(raw) is not list or len(raw) != 6:
        raise ValueError("Expected six distinct synthetic fixture entries")
    def clone(side):
        return [{**row, "combatant_id": f"{side}{i}",
                 "roster_clause_id": row["species"]} for i, row in enumerate(raw)]
    own, opponent = clone("own"), clone("opponent")
    public = [{"species": row["species"], "roster_clause_id": row["roster_clause_id"]}
              for row in opponent]
    return own, public, opponent


def run_batch(policy, *, episodes, seed, epsilon, training):
    # The private opponent trio changes between episodes, but selection-policy
    # inputs do not contain it. This is a tiny synthetic distribution, not a
    # real tournament-meta sample or evidence of competitive strength.
    own, public, opponent = fixture_teams()
    stats = {"complete": 0, "discarded": 0, "wins": 0, "draws": 0, "losses": 0,
             "decisions": 0, "updates": 0}
    for episode in range(episodes):
        episode_seed = seed + episode
        rng = random.Random(episode_seed)
        chosen = tuple(sorted(rng.sample(range(6), 3)))
        lead = rng.choice(chosen)
        with SixToThreeEnvironment(
            GAME_DATA, own, public, opponent, chosen, lead,
            ruleset_id="great-league-v1"
        ) as env:
            result = play_episode(env, policy, seed=episode_seed,
                                  epsilon=epsilon, learn=training)
        stats[result["status"]] += 1
        stats["decisions"] += result["decisions"]
        stats["updates"] += int(result["updated"])
        if result["status"] == "complete":
            stats[{1: "wins", 0: "draws", -1: "losses"}[result["reward"]]] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=int, default=8)
    parser.add_argument("--evaluate", type=int, default=4)
    parser.add_argument("--seed", type=int, default=12)
    parser.add_argument("--epsilon", type=float, default=0.25)
    parser.add_argument("--policy", choices=tuple(POLICY_VARIANTS), default="v1")
    parser.add_argument("--load", type=Path)
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    if not 0 <= args.train <= 32 or not 0 <= args.evaluate <= 32:
        parser.error("Each batch must have at most 32 episodes")
    if not 0 <= args.seed <= 2**32 - 100000:
        parser.error("Invalid episode seed")
    if not 0 <= args.epsilon <= 1:
        parser.error("epsilon must be in [0,1]")

    policy_class = POLICY_VARIANTS[args.policy]
    policy = read_checkpoint(args.load, args.seed, policy_class) if args.load else (
        policy_class(seed=args.seed))
    trained = run_batch(policy, episodes=args.train, seed=args.seed,
                        epsilon=args.epsilon, training=True)
    evaluated = run_batch(policy, episodes=args.evaluate, seed=args.seed + 100000,
                          epsilon=0.0, training=False)
    if args.save:
        save_new_checkpoint(args.save, policy)

    print(json.dumps({
        "mode": "offline_synthetic_mc_experiment_not_competitive_validation",
        "model_schema": policy.snapshot()["schema"],
        "policy_variant": args.policy,
        "training": trained, "evaluation": evaluated,
        "cumulative_completed_matches": policy.completed_matches,
        "checkpoint_saved": bool(args.save),
        "selection_actions": 60,
        "limits": {"supported": "great-league synthetic fixture; native 3v3 only",
                   "untested": "realistic meta, real-time input, population self-play"},
    }, sort_keys=True))


if __name__ == "__main__":
    main()
