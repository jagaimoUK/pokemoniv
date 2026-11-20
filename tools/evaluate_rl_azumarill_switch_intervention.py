"""Replay the first learned switch disagreement with a common CPU continuation."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evaluate_rl_azumarill_natural_energy import POLICY_CLASSES, _candidates, _forks, replay_fork
from tools.evaluate_rl_azumarill_sensitivity import _verified_native_ko_reward, choose_team_cpu
from tools.evaluate_rl_azumarill_shared_history import (
    TRAIN_WINDOW, _validate_split, build_history_cases, train_shared, window_cases as training_cases,
)
from tools.evaluate_rl_azumarill_switch_rl_150s import MAX_STEPS, _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import EVAL_POLICY_SEED, ROOT, ruleset_distinction
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import paired_charge_rewards

WINDOWS = (3000012, 3001012)
SEEDS_PER_ROSTER = 3
# Name, own selection, opponent lead, opponent selected trio.
ROSTERS = (
    ("fearow_reference", "0,3,5|0", 3, (2, 3, 5)),
    ("fearow_clodsire_wigglytuff", "0,3,5|0", 3, (1, 3, 5)),
    ("fearow_azumarill_skarmory", "0,3,5|0", 3, (2, 3, 4)),
    ("fearow_skarmory_wigglytuff", "0,3,5|0", 3, (3, 4, 5)),
    ("wigglytuff_control", "0,4,5|0", 5, (2, 4, 5)),
    ("skarmory_control", "0,2,4|0", 4, (1, 3, 4)),
)


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared switch-intervention window")
    return build_history_cases(window, ROSTERS, SEEDS_PER_ROSTER)


def find_switch_fork(worker, case, models, tables):
    """Follow the agreed actions from hp_60 up to the first disagreement."""
    hp_fork = _forks(worker, case).get("hp_60")
    if hp_fork is None:
        return None, "hp_60_not_reached"
    prefix, _ = hp_fork
    history = list(prefix)
    result = replay_fork(worker, case, hp_fork)
    for _ in range(MAX_STEPS):
        view = result["observation"]
        if view is None:
            _verified_native_ko_reward(result)
            return None, "no_action_difference"
        legal = view["legal_actions"]
        action = legal[0]
        if len(legal) > 1:
            chosen, hits = _candidates(view, models, tables)
            action = chosen["v2"]
            if action != chosen["energy"]:
                if not (hits["v2"] and hits["energy"]):
                    return None, "first_difference_state_miss"
                if not all(chosen[name].startswith("switch_") for name in POLICY_CLASSES):
                    return None, "first_difference_not_two_switches"
                return ((tuple(history), view), {name: chosen[name] for name in POLICY_CLASSES}), None
        history.append(action)
        result = worker.step(action)
    raise RuntimeError("Shared policy prefix exceeded the step budget")


def _play_switch(worker, case, fork, action):
    result = replay_fork(worker, case, fork)
    view = result["observation"]
    if not action.startswith("switch_") or action not in view["legal_actions"]:
        raise RuntimeError("Illegal intervention switch")
    own = view["own"]
    active = own["team"][own["active_slot"]]["species"]
    target = own["team"][int(action[-1])]["species"]
    before_seq = view["recent_events"][-1]["seq"] if view["recent_events"] else 0

    # Check the public events immediately so a later forced replacement does
    # not count as execution of the requested switch.
    result = worker.step(action)
    switch_resolved = any(
        event["seq"] > before_seq and event["kind"] == "switch" and event["side"] == "self"
        and event["previous_species"] == active and event["species"] == target
        and event["forced"] == (view["phase"] == "replace")
        for event in worker.public_replay()["events"]
    )
    for _ in range(MAX_STEPS):
        view_after = result["observation"]
        if view_after is None:
            break
        result = worker.step(choose_team_cpu(view_after))
    if result["observation"] is not None:
        raise RuntimeError("CPU continuation exceeded the step budget")
    return {
        "action": action,
        "target_species": target,
        "switch_resolved": switch_resolved,
        "outcome": result["info"]["outcome"],
        "reward": _verified_native_ko_reward(result),
        "elapsed_ms": result["info"]["elapsed_ms"],
    }


def _run_case(worker, case, models, tables):
    metadata = {
        "seed": case["seed"], "roster": case["roster"],
        "own_lead": case["handoff"]["own_team"][0]["species"],
    }
    found, excluded = find_switch_fork(worker, case, models, tables)
    if found is None:
        return {**metadata, "excluded": excluded}
    fork, actions = found
    arms = {name: _play_switch(worker, case, fork, action) for name, action in actions.items()}
    if arms["v2"] != _play_switch(worker, case, fork, actions["v2"]):
        raise RuntimeError("Identical switch A/A replay produced a different result")
    _, view = fork
    own = view["own"]
    active = own["team"][own["active_slot"]]
    return {
        **metadata,
        "fork": {
            "turn": view["turn"], "phase": view["phase"], "elapsed_ms": view["elapsed_ms"],
            "own_active": active["species"], "opponent_active": view["opponent"]["active_species"],
            "own_hp_pct": 100 * active["hp"] / active["max_hp"],
            "public_view_sha256": hashlib.sha256(
                json.dumps(view, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        },
        **arms,
    }


def summarize(rows):
    selected = [row for row in rows if "fork" in row]
    pairs = [(row["v2"], row["energy"]) for row in selected]
    resolved = [(v2, energy) for v2, energy in pairs if v2["switch_resolved"] and energy["switch_resolved"]]
    outcomes = Counter((v2["outcome"], energy["outcome"]) for v2, energy in resolved)
    ko_deltas = [
        energy["elapsed_ms"] - v2["elapsed_ms"]
        for v2, energy in resolved if v2["reward"] is not None and energy["reward"] is not None
    ]
    return {
        "planned_histories": len(rows),
        "eligible_forks": len(pairs),
        "distinct_public_forks": len({row["fork"]["public_view_sha256"] for row in selected}),
        "both_switches_resolved": len(resolved),
        "excluded": dict(Counter(row["excluded"] for row in rows if "excluded" in row)),
        "switch_targets": [
            {"v2": v2, "energy": energy, "count": count}
            for (v2, energy), count in sorted(Counter(
                (left["target_species"], right["target_species"]) for left, right in resolved
            ).items())
        ],
        "intention_outcomes": [
            {"v2": v2, "energy": energy, "count": count}
            for (v2, energy), count in sorted(Counter(
                (left["outcome"], right["outcome"]) for left, right in pairs
            ).items())
        ],
        "resolved_outcomes": [
            {"v2": v2, "energy": energy, "count": count}
            for (v2, energy), count in sorted(outcomes.items())
        ],
        "timeouts": {
            "v2": sum(count for (v2, _), count in outcomes.items() if v2 == "timeout"),
            "energy": sum(count for (_, energy), count in outcomes.items() if energy == "timeout"),
            "both": outcomes[("timeout", "timeout")],
        },
        "ko_reward_comparison": paired_charge_rewards(resolved),
        "both_ko_elapsed_delta_ms_energy_minus_v2": dict(sorted(Counter(ko_deltas).items())),
    }


def evaluate_switch_intervention(*, windows=WINDOWS):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)) or not set(windows) <= set(WINDOWS):
        raise ValueError("Use one or both distinct switch-intervention windows")
    train = training_cases(TRAIN_WINDOW)
    cases_by_window = {window: window_cases(window) for window in windows}
    _validate_split(train, [case for cases in cases_by_window.values() for case in cases])
    with TemporaryDirectory(prefix="quagsire-switch-intervention-") as temp:
        path = Path(temp) / "strategy_gamemaster_shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            snapshots, training = train_shared(worker, train)
            models = {name: cls.restore(snapshots[name], seed=EVAL_POLICY_SEED)
                      for name, cls in POLICY_CLASSES.items()}
            tables = {name: model.snapshot()["values"]["tactics"] for name, model in models.items()}
            rows = [
                {**_run_case(worker, case, models, tables), "window": window}
                for window, cases in cases_by_window.items() for case in cases
            ]
    if any(model.snapshot() != snapshots[name] for name, model in models.items()):
        raise RuntimeError("Frozen model changed during switch intervention")
    return {
        "ruleset_id": RULESET_ID,
        "ruleset_distinction": ruleset_distinction(),
        "starting_shields": [2, 2],
        "training": training,
        "windows": list(windows),
        "policy_snapshots_unchanged": True,
        "summary": summarize(rows),
        "by_roster": {name: summarize([row for row in rows if row["roster"] == name])
                      for name, *_ in ROSTERS},
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS)
    args = parser.parse_args()
    print(json.dumps(evaluate_switch_intervention(
        windows=WINDOWS if args.window is None else (args.window,)
    ), sort_keys=True))


if __name__ == "__main__":
    main()
