"""Train two public tactical encoders on one native 6v3 history per seed."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory

from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_azumarill_natural_energy import (
    POLICY_CLASSES, _reset, _run_case, summarize_cohorts,
)
from tools.evaluate_rl_azumarill_sensitivity import _verified_native_ko_reward, choose_team_cpu
from tools.evaluate_rl_azumarill_switch_150s import BUILDS
from tools.evaluate_rl_azumarill_switch_rl_150s import MAX_STEPS, _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import EVAL_POLICY_SEED, ROOT, ruleset_distinction
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_tournament_rules import validate_team_for_ruleset
from tools.run_rl_mc import fixture_teams

TRAIN_WINDOW = 2900012
EVAL_WINDOWS = (2901012, 2902012)
TRAIN_SEEDS_PER_ROSTER = 8
EVAL_SEEDS_PER_ROSTER = 3
# Name, own selection, opponent lead, training trio, held-out trio.
# Keep an overlapping lead matchup while varying the opponent bench.
ROSTERS = (
    ("skarmory", "0,2,4|0", 4, (1, 4, 5), (3, 4, 5)),
    ("clodsire", "0,2,4|0", 1, (1, 3, 5), (1, 3, 4)),
    ("azumarill", "0,2,4|2", 2, (1, 2, 5), (0, 2, 3)),
    ("fearow", "0,3,5|0", 3, (0, 3, 4), (2, 3, 5)),
    ("wigglytuff", "0,4,5|0", 5, (1, 4, 5), (0, 3, 5)),
    ("quagsire", "0,3,4|0", 0, (0, 1, 4), (0, 3, 5)),
)


def window_cases(window):
    """Construct both splits from the same fixed public fixture pool."""
    if type(window) is not int or window not in (TRAIN_WINDOW, *EVAL_WINDOWS):
        raise ValueError("Use a predeclared shared-history window")
    training = window == TRAIN_WINDOW
    seeds_per_roster = TRAIN_SEEDS_PER_ROSTER if training else EVAL_SEEDS_PER_ROSTER
    rosters = [(name, selection, lead, train_trio if training else eval_trio)
               for name, selection, lead, train_trio, eval_trio in ROSTERS]
    return build_history_cases(window, rosters, seeds_per_roster, training=training)


def build_history_cases(window, rosters, seeds_per_roster, *, training=False):
    """Build native 2/2 cases with both Quagsire forms and a committed selection."""
    own_base, public, enemy = fixture_teams()
    validate_team_for_ruleset(enemy, RULESET_ID)
    cases = []
    for index, (roster, selection, lead, trio) in enumerate(rosters):
        for species, move in BUILDS.items():
            own = [{**own_base[0], "species": species, "charged2": move}, *own_base[1:]]
            validate_team_for_ruleset(own, RULESET_ID)
            preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=RULESET_ID)
            selection_view = preview.observe() if training else None
            preview.choose(selection)
            handoff = preview._private_engine_input()
            for offset in range(seeds_per_roster):
                cases.append({
                    "roster": roster, "seed": window + index * seeds_per_roster + offset,
                    "opponent_shields": 2, "handoff": handoff,
                    **({"selection_view": selection_view, "selection": selection,
                        "explore": offset >= 2} if training else {}),
                })
    return cases


def _behavior_action(view, rng, *, explore):
    """Public CPU with seeded 1/8 exploration among other non-wait actions."""
    cpu = choose_team_cpu(view)
    alternatives = [action for action in view["legal_actions"] if action not in ("wait", cpu)]
    if explore and alternatives and rng.randrange(8) == 0:
        return rng.choice(alternatives)
    return cpu


def _append_shared(records, models, view, action):
    for name, model in models.items():
        kind, key, legal = model.encode_state(view)
        if action not in legal:
            raise RuntimeError("Illegal action in shared training history")
        records[name].append((kind, key, action))


def train_shared(worker, cases):
    """Record each action once and update both tables from the same native KO."""
    models = {name: model(seed=TRAIN_WINDOW) for name, model in POLICY_CLASSES.items()}
    outcomes = Counter()
    seen = hashlib.sha256()
    updates = 0
    for case in cases:
        if case["opponent_shields"] != 2:
            raise ValueError("Shared histories require two starting shields per side")
        rng = random.Random(case["seed"])
        records = {name: [] for name in models}
        action = case["selection"]
        _append_shared(records, models, case["selection_view"], action)
        actions = [action]
        result = _reset(worker, case)
        for _ in range(MAX_STEPS):
            view = result["observation"]
            if view is None:
                break
            action = _behavior_action(view, rng, explore=case["explore"])
            _append_shared(records, models, view, action)
            actions.append(action)
            result = worker.step(action)
        if result["observation"] is not None:
            raise RuntimeError("Shared training episode exceeded the step budget")

        reward = _verified_native_ko_reward(result)
        outcome = result["info"]["outcome"]
        outcomes[outcome] += 1
        if reward is not None:
            seen.update(json.dumps([case["seed"], case["roster"], actions, reward]).encode("utf-8"))
            for name, model in models.items():
                model.learn(records[name], reward=reward, selection_reward=reward)
            updates += 1

    snapshots = {name: deepcopy(model.snapshot()) for name, model in models.items()}
    return snapshots, {
        "attempted": len(cases), "trained": updates, "excluded": len(cases) - updates,
        "outcomes": dict(outcomes),
        "shared_action_reward_sha256": seen.hexdigest(),
        "models": {
            name: {"schema": snapshot["schema"], "completed_matches": snapshot["completed_matches"],
                   "tactical_states": len(snapshot["values"]["tactics"])}
            for name, snapshot in snapshots.items()
        },
    }


def _validate_split(train, evaluation):
    def matchups(cases):
        return {
            tuple(tuple(member["species"] for member in case["handoff"][side])
                  for side in ("own_team", "opponent_team"))
            for case in cases
        }

    if ({case["seed"] for case in train} & {case["seed"] for case in evaluation}
            or matchups(train) & matchups(evaluation)):
        raise ValueError("Shared-history training and evaluation overlap")
    if any(case["opponent_shields"] != 2 for case in (*train, *evaluation)):
        raise ValueError("Shared histories require two starting shields per side")


def evaluate_shared_history(*, windows=EVAL_WINDOWS):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)) or not set(windows) <= set(EVAL_WINDOWS):
        raise ValueError("Use one or both distinct evaluation windows")
    train = window_cases(TRAIN_WINDOW)
    cases = [case for window in windows for case in window_cases(window)]
    _validate_split(train, cases)
    with TemporaryDirectory(prefix="quagsire-shared-history-") as temp:
        path = Path(temp) / "strategy_gamemaster_shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            snapshots, training = train_shared(worker, train)
            models = {name: cls.restore(snapshots[name], seed=EVAL_POLICY_SEED)
                      for name, cls in POLICY_CLASSES.items()}
            tables = {name: model.snapshot()["values"]["tactics"] for name, model in models.items()}
            rows = [row for case in cases for row in _run_case(worker, case, models, tables)]
    if any(model.snapshot() != snapshots[name] for name, model in models.items()):
        raise RuntimeError("Frozen model changed during shared-history evaluation")

    return {
        "ruleset_id": RULESET_ID,
        "ruleset_distinction": ruleset_distinction(),
        "starting_shields": [2, 2],
        "training_window": TRAIN_WINDOW,
        "evaluation_windows": list(windows),
        "evaluation_rosters": [row[0] for row in ROSTERS],
        "evaluation_planned_histories": len(cases),
        "training": training,
        "policy_snapshots_unchanged": True,
        "summary": summarize_cohorts(rows),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=EVAL_WINDOWS)
    args = parser.parse_args()
    windows = EVAL_WINDOWS if args.window is None else (args.window,)
    print(json.dumps(evaluate_shared_history(windows=windows), sort_keys=True))


if __name__ == "__main__":
    main()
