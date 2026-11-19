"""Offline paired tactical rollouts from a verified native 3v3 history."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from time import monotonic

from pvpoke_rl_step_client import NativeStepError
from pvpoke_rl_team_env import (
    ACTIONS, SCHEMA, InvalidNativeTeamResult, SixToThreeEnvironment, verified_6v3_return,
)
from tools.evaluate_rl_mc import fixed_public_action, heldout_scenarios
from tools.run_rl_mc import GAME_DATA, fixture_teams

PAIRS = {"fast": ("turn", "fast", "wait"),
         "shield": ("shield", "shield_yes", "shield_no")}
OWN_SELECTION = "2,3,5|2"
DEFAULT_SEED = 400012
MAX_SCENARIOS = 12
MAX_DECISIONS = 2000
AUDIT_FIELDS = {
    "game_data_sha256": str, "seed": int, "horizon": int, "handoff": dict,
    "initial_conditions": list, "starting_shields": list, "initial": dict,
    "decisions": list, "randomness": list, "events": list, "state": dict,
}
AUDIT_HISTORY = ("decisions", "randomness", "events")


class _ReplayMismatch(Exception):
    """A case failed an integrity check and cannot contribute a pair."""


@dataclass(frozen=True, repr=False)
class _Rollout:
    transition: tuple
    audit: dict


def _verdict(transition):
    view, reward, terminated, truncated, info = transition
    if terminated is False and truncated is False and view is not None:
        return None, "decision_limit"
    if view is None:
        target = verified_6v3_return(reward, terminated, truncated, info)
        if target is not None:
            return target, None
        if (terminated is False and truncated is True and reward is None and
                type(info) is dict and info.get("training_eligible") is False and
                info.get("outcome") in ("timeout", "unsupported")):
            return None, info["outcome"]
    return None, "invalid_outcome"


def _start(env, seed, horizon):
    env.reset(seed=seed, horizon=horizon)
    return env.step(OWN_SELECTION)


def _read_audit(env):
    try:
        audit = env.private_replay()
    except KeyError:
        raise InvalidNativeTeamResult("Missing native audit") from None
    battle = audit.get("battle") if type(audit) is dict else None
    if (type(battle) is not dict or audit.get("selection") != OWN_SELECTION or
            battle.get("schema") != SCHEMA or "result" not in battle or
            any(type(battle.get(key)) is not expected for key, expected in AUDIT_FIELDS.items())):
        raise InvalidNativeTeamResult("Invalid native audit")
    for decision in battle["decisions"]:
        actions = decision.get("actions") if type(decision) is dict else None
        if (type(actions) is not list or len(actions) != 2 or
                any(type(action) is not str or action not in ACTIONS for action in actions)):
            raise InvalidNativeTeamResult("Invalid native audit actions")
    return audit


def _find_frontier(env, transition, pair, budget):
    phase, baseline, candidate = pair
    prefix = []
    while len(prefix) < budget:
        view = transition[0]
        if view is None:
            _, reason = _verdict(transition)
            return None, reason or "completed_before_frontier"
        action = fixed_public_action(view)
        if (prefix and view["phase"] == phase and action == baseline and
                baseline in view["legal_actions"] and candidate in view["legal_actions"]):
            audit = _read_audit(env)
            if len(audit["battle"]["decisions"]) < len(prefix):
                raise InvalidNativeTeamResult("Incomplete native prefix audit")
            return (tuple(prefix), transition, audit), None
        prefix.append(action)
        transition = env.step(action)
    _, reason = _verdict(transition)
    return None, reason or "completed_before_frontier"


def _check_replay(env, transition, frontier):
    prefix, expected, audit = frontier
    for action in prefix:
        view = transition[0]
        if view is None or action not in view["legal_actions"]:
            raise _ReplayMismatch("fork_state_mismatch")
        transition = env.step(action)
    # The worker regenerates opponent actions, including its internal shield
    # decisions. Equality verifies the actual two-sided history and RNG draws.
    if transition != expected or _read_audit(env) != audit:
        raise _ReplayMismatch("fork_state_mismatch")


def _roll_out(env, first_action, budget, prefix_audit):
    action = first_action
    for index in range(budget):
        transition = env.step(action)
        view, _, terminated, truncated, info = transition
        if terminated or truncated or view is None or index + 1 == budget:
            elapsed = info.get("elapsed_ms") if type(info) is dict else None
            if type(elapsed) is not int or elapsed < 0:
                raise InvalidNativeTeamResult("Invalid native rollout clock")
            audit = _read_audit(env)
            prefix, battle = prefix_audit["battle"], audit["battle"]
            depth = len(prefix["decisions"])
            if (len(battle["decisions"]) < depth + index + 1 or
                    battle["decisions"][depth]["actions"][0] != first_action or
                    any(battle[key][:len(prefix[key])] != prefix[key] for key in AUDIT_HISTORY)):
                raise InvalidNativeTeamResult("Invalid native branch audit")
            return _Rollout(transition, audit)
        action = fixed_public_action(view)
    raise AssertionError("Branch requires a positive decision budget")


def _record_divergence(metrics, prefix_audit, baseline, candidate):
    old, new = baseline.audit["battle"], candidate.audit["battle"]
    prefix = prefix_audit["battle"]
    start = len(prefix["decisions"])
    old_actions = [row["actions"][1] for row in old["decisions"][start:]]
    new_actions = [row["actions"][1] for row in new["decisions"][start:]]
    start = len(prefix["randomness"])
    metrics["audited_pairs"] += 1
    metrics["opponent_action_suffix_differed"] += old_actions != new_actions
    metrics["rng_record_suffix_differed"] += old["randomness"][start:] != new["randomness"][start:]
    metrics["elapsed_ms_differed"] += (
        baseline.transition[4]["elapsed_ms"] != candidate.transition[4]["elapsed_ms"])


def _record_pair(metrics, arms, baseline, candidate):
    for name, (reward, reason) in (("baseline", baseline), ("candidate", candidate)):
        arm = arms[name]
        if reason is None:
            arm[{1: "wins", -1: "losses", 0: "draws"}[reward]] += 1
        else:
            arm["censored"][reason] += 1

    old, new = baseline[0], candidate[0]
    if old is not None and new is not None:
        metrics["both_completed"] += 1
        metrics["better" if new > old else "worse" if new < old else "equal"] += 1
    elif old is not None:
        metrics["baseline_only_completed"] += 1
    elif new is not None:
        metrics["candidate_only_completed"] += 1
    else:
        metrics["both_censored"] += 1


def _run_case(env, seed, pair, horizon, budget, report):
    frontier, missing = _find_frontier(env, _start(env, seed, horizon), pair, budget)
    if frontier is None:
        report["excluded_before_pair"][missing] += 1
        return
    report["candidate_frontiers"] += 1
    prefix, _, audit = frontier
    _, baseline_action, candidate_action = pair
    remaining = budget - len(prefix)
    baseline = _roll_out(env, baseline_action, remaining, audit)

    _check_replay(env, _start(env, seed, horizon), frontier)
    report["fork_state_matches"] += 1
    repeated = _roll_out(env, baseline_action, remaining, audit)
    if repeated != baseline:
        raise _ReplayMismatch("same_action_replay_mismatch")
    report["same_action_replay_matches"] += 1

    _check_replay(env, _start(env, seed, horizon), frontier)
    report["fork_state_matches"] += 1
    report["branch_legal_count"] += 1
    report["attempted_pairs"] += 1
    try:
        candidate = _roll_out(env, candidate_action, remaining, audit)
    except InvalidNativeTeamResult:
        candidate_verdict = (None, "invalid_native_result")
    except NativeStepError:
        candidate_verdict = (None, "worker_failure")
    else:
        candidate_verdict = _verdict(candidate.transition)
        _record_divergence(report["post_fork_divergence"], audit, baseline, candidate)
    _record_pair(report, report["arms"], _verdict(baseline.transition), candidate_verdict)


def compare_branches(*, pair="shield", seed=DEFAULT_SEED, scenarios=6,
                     horizon=500, max_decisions=MAX_DECISIONS):
    """Return aggregate comparisons; raw native audits stay inside this harness.

    A candidate frontier follows at least one tactical step. Each accepted pair
    contributes two fork state matches and one same-action control match.
    A partial integrity failure can contribute an individual match but no pair.
    """
    if (type(pair) is not str or pair not in PAIRS or
            type(scenarios) is not int or not 1 <= scenarios <= MAX_SCENARIOS or
            type(horizon) is not int or not 1 <= horizon <= 500 or
            type(max_decisions) is not int or not 1 <= max_decisions <= MAX_DECISIONS):
        raise ValueError("Invalid bounded branch experiment parameters")
    cases = heldout_scenarios(count=scenarios, seed=seed)
    own, public, opponent = fixture_teams()
    report = dict.fromkeys((
        "candidate_frontiers", "fork_state_matches", "same_action_replay_matches",
        "branch_legal_count", "attempted_pairs", "both_completed", "baseline_only_completed",
        "candidate_only_completed", "both_censored", "better", "equal", "worse",
    ), 0)
    report["arms"] = {
        arm: {"wins": 0, "losses": 0, "draws": 0, "censored": Counter()}
        for arm in ("baseline", "candidate")
    }
    exclusions = report["excluded_before_pair"] = Counter()
    report["post_fork_divergence"] = dict.fromkeys((
        "audited_pairs", "opponent_action_suffix_differed",
        "rng_record_suffix_differed", "elapsed_ms_differed",
    ), 0)
    started = monotonic()
    for scenario_seed, hidden, lead in cases:
        with SixToThreeEnvironment(GAME_DATA, own, public, opponent, hidden, lead,
                                   ruleset_id="great-league-v1") as env:
            try:
                _run_case(env, scenario_seed, PAIRS[pair], horizon, max_decisions, report)
            except _ReplayMismatch as error:
                exclusions[str(error)] += 1
            except InvalidNativeTeamResult:
                exclusions["invalid_native_result"] += 1
            except NativeStepError:
                exclusions["worker_failure"] += 1
    phase, baseline, candidate = PAIRS[pair]
    return {
        "experiment": "native_3v3_paired_tactical_branches_v1",
        "scenarios": scenarios,
        "phase": phase,
        "baseline_action": baseline,
        "candidate_action": candidate,
        "horizon": horizon,
        "max_decisions": max_decisions,
        **report,
        "elapsed_seconds": round(monotonic() - started, 3),
        "limits": "synthetic fixture, two replay checks per accepted pair; divergent actions can consume RNG differently",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", choices=tuple(PAIRS), default="shield")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--scenarios", type=int, default=6)
    args = parser.parse_args()
    try:
        result = compare_branches(pair=args.pair, seed=args.seed, scenarios=args.scenarios)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
