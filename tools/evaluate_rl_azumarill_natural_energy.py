"""Compare frozen tactical keys and CPU fallback on naturally reached 6v3 forks."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evaluate_rl_azumarill_rl_coverage import CpuFallbackMonteCarloPolicy
from tools.evaluate_rl_azumarill_sensitivity import _verified_native_ko_reward, choose_team_cpu
from tools.evaluate_rl_azumarill_switch_150s import BUILDS, ROSTERS as AZUMARILL_LEAD_ROSTERS
from tools.evaluate_rl_azumarill_switch_rl_150s import MAX_STEPS, _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import (
    EVAL_POLICY_SEED, ROOT, TRAIN_EPISODES, ruleset_distinction, train_targeted_switch_policy,
)
from tools.evaluate_rl_azumarill_switch_rl_wait_energy import EnergyBandPolicy
from tools.evaluate_rl_azumarill_switch_strata import ROSTERS as QUAGSIRE_LEAD_ROSTERS
from tools.evaluate_rl_quagsire import build_window_cases, shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID

WINDOWS = (2800012, 2801012)
COHORTS = ("first_charge", "hp_60")
POLICY_CLASSES = {"v2": CpuFallbackMonteCarloPolicy, "energy": EnergyBandPolicy}
HYBRID = "energy_hit_else_v2"
CONTINUATIONS = ("cpu", *POLICY_CLASSES, HYBRID)
COMPARISONS = {"v2": (HYBRID, "energy"), HYBRID: ("energy",)}
SEEDS_PER_ROSTER = 3


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared natural 6v3 seed window")
    cases = []
    for offset, lead, rosters in (
        (0, 0, QUAGSIRE_LEAD_ROSTERS),
        (len(QUAGSIRE_LEAD_ROSTERS) * SEEDS_PER_ROSTER, 2, AZUMARILL_LEAD_ROSTERS),
    ):
        cases.extend(build_window_cases(
            window + offset, (RULESET_ID,), rosters, SEEDS_PER_ROSTER, own_selection=f"0,2,4|{lead}",
        ))
    return [case for case in cases if any(
        BUILDS.get(member["species"]) == member["charged2"] for member in case["handoff"]["own_team"]
    )]


def _reset(worker, case):
    # Native initial state: full HP and zero energy, followed by actual turns from the lead.
    return worker.reset(case["handoff"], seed=case["seed"], shields=(2, case["opponent_shields"]))


def _forks(worker, case):
    """Play a common CPU prefix and pick the first eligible state in each cohort."""
    result = _reset(worker, case)
    history, forks = [], {}
    for _ in range(MAX_STEPS):
        view = result["observation"]
        if view is None:
            _verified_native_ko_reward(result)
            return forks
        if view["phase"] == "turn" and len(view["legal_actions"]) > 1:
            legal = view["legal_actions"]
            active = view["own"]["team"][view["own"]["active_slot"]]
            if "first_charge" not in forks and ("charge_0" in legal or "charge_1" in legal):
                forks["first_charge"] = (tuple(history), view)
            if ("hp_60" not in forks and active["species"] in BUILDS
                    and 2 * active["hp"] >= active["max_hp"] and 4 * active["hp"] < 3 * active["max_hp"]):
                forks["hp_60"] = (tuple(history), view)
            if len(forks) == len(COHORTS):
                return forks
        action = choose_team_cpu(view)
        history.append(action)
        result = worker.step(action)
    raise RuntimeError("Natural prefix exceeded the step budget")


def _candidates(view, models, tables):
    cpu = choose_team_cpu(view)
    chosen, hits = {"cpu": cpu}, {}
    for name, model in models.items():
        action, (_, key, _) = model.choose(view, epsilon=0)
        hits[name] = key in tables[name]
        if action not in view["legal_actions"] or (not hits[name] and action != cpu):
            raise RuntimeError("Illegal tactical action or unexpected action on a state miss")
        chosen[name] = action
    chosen[HYBRID] = chosen["energy"] if hits["energy"] else chosen["v2"]
    return chosen, hits


def _difference_source(hits):
    if hits["energy"]:
        return "both_hit" if hits["v2"] else "energy_only_hit"
    if not hits["v2"]:
        raise RuntimeError("Policies with two state misses must take the CPU action")
    return "v2_hit_energy_miss"


def replay_fork(worker, case, fork):
    """Replay the exact actions and require equality of the entire public view."""
    history, expected_view = fork
    result = _reset(worker, case)
    for action in history:
        result = worker.step(action)
    if result["observation"] != expected_view:
        raise RuntimeError("Native replay did not reproduce the public fork")
    return result


def _continue(worker, case, fork, name, models, tables):
    result = replay_fork(worker, case, fork)

    first_differences, stats = {}, Counter()
    for _ in range(MAX_STEPS):
        view = result["observation"]
        if view is None:
            break
        legal = view["legal_actions"]
        if len(legal) == 1:
            action = legal[0]
        elif name == "cpu":
            action = choose_team_cpu(view)
        else:
            chosen, hits = _candidates(view, models, tables)
            action = chosen[name]
            representation = "energy" if name == HYBRID else name
            stats["choices"] += 1
            stats["hits"] += hits[representation]
            uses_v2_backup = name == HYBRID and not hits["energy"] and hits["v2"]
            stats["v2_backup_hits"] += uses_v2_backup
            stats["cpu_fallbacks"] += not (hits[representation] or uses_v2_backup)
            stats["actions_different_from_cpu"] += action != chosen["cpu"]
            for other in COMPARISONS.get(name, ()):
                if other not in first_differences and action != chosen[other]:
                    first_differences[other] = {
                        "source": _difference_source(hits),
                        "action": action,
                        "other_action": chosen[other],
                        "turn": view["turn"],
                        "elapsed_ms": view["elapsed_ms"],
                    }
        result = worker.step(action)
    if result["observation"] is not None:
        raise RuntimeError("Natural continuation exceeded the step budget")
    return {
        "outcome": result["info"]["outcome"],
        "reward": _verified_native_ko_reward(result),
        "elapsed_ms": result["info"]["elapsed_ms"],
        "stats": dict(stats),
        "first_differences": first_differences,
    }


def _terminal(row):
    return row["outcome"], row["reward"], row["elapsed_ms"]


def _run_case(worker, case, models, tables):
    branches = {}
    for cohort, fork in _forks(worker, case).items():
        history, view = fork
        if len(history) not in branches:
            branches[len(history)] = {
                name: _continue(worker, case, fork, name, models, tables) for name in CONTINUATIONS
            }
        results = branches[len(history)]
        for reference, others in COMPARISONS.items():
            for other in others:
                if (other not in results[reference]["first_differences"]
                        and _terminal(results[reference]) != _terminal(results[other])):
                    raise RuntimeError("Terminal replay differed without an action difference")
        active = view["own"]["team"][view["own"]["active_slot"]]
        quagsire = next(member["species"] for member in view["own"]["team"] if member["species"] in BUILDS)
        yield {
            "cohort": cohort,
            "seed": case["seed"],
            "roster": case["roster"],
            "own_lead": case["handoff"]["own_team"][0]["species"],
            "quagsire_form": quagsire,
            "starting_opponent_shields": case["opponent_shields"],
            "fork": {"elapsed_ms": view["elapsed_ms"], "turn": view["turn"],
                     "species": active["species"], "active_hp_pct": 100 * active["hp"] / active["max_hp"]},
            "continuations": results,
        }


def summarize(rows):
    cpu_ko = sum(row["cpu"]["reward"] is not None for row in rows)
    policies = {}
    for name in CONTINUATIONS:
        outcomes, stats = Counter(), Counter()
        reproduced = 0
        for row in rows:
            result, cpu = row[name], row["cpu"]
            outcomes[result["outcome"]] += 1
            stats.update(result["stats"])
            reproduced += cpu["reward"] is not None and result["outcome"] == cpu["outcome"]
        policies[name] = {
            "outcomes": dict(outcomes),
            "cpu_ko_outcomes_reproduced": reproduced,
            "cpu_ko_outcome_recall": reproduced / cpu_ko if cpu_ko else None,
            "stats": dict(stats),
            "hit_rate": stats["hits"] / stats["choices"] if stats["choices"] else None,
        }

    comparisons = {}
    for reference, others in COMPARISONS.items():
        for other in others:
            sources, outcome_changes = Counter(), Counter()
            for row in rows:
                left, right = row[reference], row[other]
                first = left["first_differences"].get(other)
                sources[first["source"] if first else "same_actions"] += 1
                if left["outcome"] != right["outcome"]:
                    outcome_changes[f'{left["outcome"]}->{right["outcome"]}'] += 1
            comparisons[f"{reference}->{other}"] = {
                "first_action_difference": dict(sources),
                "outcome_changes": dict(outcome_changes),
            }
    return {
        "matched_forks": len(rows), "cpu_ko_forks": cpu_ko,
        "policies": policies, "comparisons": comparisons,
    }


def summarize_cohorts(rows):
    return {
        cohort: summarize([row["continuations"] for row in rows if row["cohort"] == cohort])
        for cohort in COHORTS
    }


def evaluate_natural_energy(*, windows=WINDOWS, train_episodes=TRAIN_EPISODES):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)):
        raise ValueError("Use one or both distinct natural 6v3 seed windows")
    cases_by_window = {window: window_cases(window) for window in windows}
    snapshots, training, models, rows = {}, {}, {}, []
    with TemporaryDirectory(prefix="quagsire-natural-energy-") as temp:
        path = Path(temp) / "strategy_gamemaster_shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            for name, model in POLICY_CLASSES.items():
                snapshots[name], training[name] = train_targeted_switch_policy(
                    worker, episodes=train_episodes, policy_class=model,
                )
                models[name] = model.restore(snapshots[name], seed=EVAL_POLICY_SEED)
            tables = {name: model.snapshot()["values"]["tactics"] for name, model in models.items()}
            for window, cases in cases_by_window.items():
                for case in cases:
                    rows.extend({**row, "window": window} for row in _run_case(worker, case, models, tables))
    if any(model.snapshot() != snapshots[name] for name, model in models.items()):
        raise RuntimeError("Frozen model changed during natural evaluation")

    # The main result uses standard 2/2 starting shields. The older fixture grid
    # also covers reduced opponent shields as a sensitivity check.
    standard = [row for row in rows if row["starting_opponent_shields"] == 2]
    reduced = [row for row in rows if row["starting_opponent_shields"] < 2]
    return {
        "ruleset_id": RULESET_ID,
        "ruleset_distinction": ruleset_distinction(),
        "history": "native_full_hp_cpu_prefix",
        "hp_60_active_quagsire_fraction": {"min_inclusive": 0.50, "max_exclusive": 0.75},
        "planned_histories": sum(map(len, cases_by_window.values())),
        "planned_standard_histories": sum(
            case["opponent_shields"] == 2 for cases in cases_by_window.values() for case in cases
        ),
        "training": training,
        "policy_snapshots_unchanged": True,
        "summary": summarize_cohorts(standard),
        "reduced_opponent_shields": summarize_cohorts(reduced),
        "windows": {window: len(cases) for window, cases in cases_by_window.items()},
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS)
    parser.add_argument("--train-episodes", type=int, default=TRAIN_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.train_episodes <= 120:
        parser.error("Require 0 <= --train-episodes <= 120")
    report = evaluate_natural_energy(
        windows=WINDOWS if args.window is None else (args.window,),
        train_episodes=args.train_episodes,
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
