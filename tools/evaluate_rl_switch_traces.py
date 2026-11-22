"""Reproduce historical switch losses and compare resolved synthetic battle traces."""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import takewhile
import json

from pvpoke_rl_step_client import NativeStepError
from pvpoke_rl_team_env import InvalidNativeTeamResult, SixToThreeEnvironment
from tools.evaluate_rl_branches import (
    MAX_DECISIONS, PAIRS, PRIMEAPE, ROSTERS, _ReplayMismatch, _check_replay,
    _find_frontier, _roll_out, _start, _verdict,
)
from tools.evaluate_rl_mc import heldout_scenarios
from tools.run_rl_mc import GAME_DATA, fixture_teams

WINDOWS = {"historical": (500012, 501012), "holdout": (700012, 701012)}
CASES_PER_WINDOW = 6
HORIZON = 500
LEGACY_SELECTION = ROSTERS["skarmory"][0]  # Skarmory, Primeape, Wigglytuff (native slot order).
CROSSED_SELECTION = "0,3,4|4"  # Skarmory, Primeape, Fearow.
SIDES = ("self", "opponent")


def _side(event, *, defender=False):
    actor = event.get("actor")
    if type(actor) is not int or actor not in (0, 1):
        raise InvalidNativeTeamResult("Invalid native event actor")
    return SIDES[1 - actor if defender else actor]


def _move(event):
    return {"side": _side(event), "species": event["species"], "move": event["move_id"],
            "turn": event["turn"], "shielded": event["shielded"]}


def _spent_shields(events):
    spent = dict.fromkeys(SIDES, 0)
    for event in events:
        if event["kind"] == "charged" and event["shielded"] is True:
            spent[_side(event, defender=True)] += 1
    return spent


def _move_counts(events, kinds):
    counts = Counter((_side(e), e["species"], e["move_id"], e["shielded"])
                     for e in events if e["kind"] in kinds)
    return [{"side": side, "species": species, "move": move, "shielded": shielded, "count": count}
            for (side, species, move, shielded), count in sorted(counts.items())]


def _summarize_rollout(rollout, frontier, action):
    _, transition, prefix = frontier
    battle = rollout.audit["battle"]
    events = battle["events"]
    fork_depth = len(prefix["battle"]["events"])
    fork_turn = transition[0]["turn"]
    first_ko_index = next((i for i, event in enumerate(events) if event["kind"] == "faint"), len(events))
    # If a match is censored before the first KO, these counts cover only the
    # observed interval. The first_ko field remains null.
    before_ko = events[:first_ko_index]
    charged = [_move(event) for event in before_ko if event["kind"] == "charged"]
    first_ko = None
    if first_ko_index < len(events):
        ko_turn = events[first_ko_index]["turn"]
        same_ko = takewhile(lambda e: e["kind"] == "faint" and e["turn"] == ko_turn,
                            events[first_ko_index:])
        first_ko = {
            # The native faint event is emitted after the battle step increments its turn.
            "action_turn": ko_turn - 1, "native_event_turn": ko_turn,
            "before_fork": first_ko_index < fork_depth,
            "fainted": [{"side": _side(event), "species": event["species"]}
                        for event in same_ko],
        }
    spent = _spent_shields(events)
    for i, side in enumerate(SIDES):
        if spent[side] != battle["starting_shields"][i] - battle["state"]["sides"][i]["shields"]:
            raise InvalidNativeTeamResult("Native shield events disagree with team inventory")
    reward, censor = _verdict(rollout.transition)
    last_move = next((_move(event) for event in reversed(before_ko)
                      if event["kind"] in ("fast", "charged")), None)
    return {
        "reward": reward, "censor": censor, "elapsed_ms": rollout.transition[4]["elapsed_ms"],
        "switch_at_fork": next((event["species"] for event in events[fork_depth:]
                                if event["kind"] == "switch" and event["actor"] == 0 and
                                event["turn"] == fork_turn and not event["forced"]), None)
        if action.startswith("switch_") else None,
        "first_ko": first_ko, "last_resolved_move_before_ko": last_move if first_ko else None,
        "charged_before_first_ko": charged,
        "fast_before_first_ko": _move_counts(before_ko, ("fast",)),
        "moves_after_first_ko": _move_counts(events[first_ko_index:], ("fast", "charged")),
        "shields_before_first_ko": _spent_shields(before_ko), "shields_total": spent,
    }


def _comparison_case(env, seed, selection, switch_actions):
    initial = _start(env, seed, HORIZON, selection)
    frontier, missing = _find_frontier(env, initial, PAIRS["switch"], MAX_DECISIONS, selection, None, None)
    if frontier is None:
        return {"excluded": missing}
    prefix, transition, audit = frontier
    view = transition[0]
    if any(action not in view["legal_actions"] for action, _ in switch_actions):
        return {"excluded": "switch_target_not_legal_at_common_frontier"}
    budget = MAX_DECISIONS - len(prefix)
    original = _roll_out(env, "fast", budget, audit)
    _check_replay(env, _start(env, seed, HORIZON, selection), frontier)
    if _roll_out(env, "fast", budget, audit) != original:
        raise _ReplayMismatch("same_action_replay_mismatch")
    arms = {"stay": _summarize_rollout(original, frontier, "fast")}
    for action, name in switch_actions:
        _check_replay(env, _start(env, seed, HORIZON, selection), frontier)
        try:
            arms[name] = _summarize_rollout(_roll_out(env, action, budget, audit), frontier, action)
        except InvalidNativeTeamResult:
            arms[name] = {"reward": None, "censor": "invalid_native_result"}
        except NativeStepError:
            arms[name] = {"reward": None, "censor": "worker_failure"}
    return {"opponent_lead": initial[0]["opponent"]["active_species"],
            "opponent_at_fork": view["opponent"]["active_species"], "fork_turn": view["turn"],
            "arms": arms}


def _run_cases(cases, teams, *, crossed):
    own, public, enemy = teams
    selection = CROSSED_SELECTION if crossed else LEGACY_SELECTION
    actions = (("switch_1", "primeape"), ("switch_2", "fearow")) if crossed else (("switch_1", "primeape"),)
    results = []
    for seed, trio, lead in cases:
        with SixToThreeEnvironment(GAME_DATA, own, public, enemy, trio, lead,
                                   ruleset_id="great-league-v1") as env:
            try:
                row = _comparison_case(env, seed, selection, actions)
            except _ReplayMismatch as error:
                row = {"excluded": str(error)}
            except (InvalidNativeTeamResult, KeyError, TypeError, IndexError):
                row = {"excluded": "invalid_native_result"}
            except NativeStepError:
                row = {"excluded": "worker_failure"}
        results.append({"seed": seed, **row})
    return results


def _paired(results, baseline, candidate):
    pairs = [(row["arms"][baseline]["reward"], row["arms"][candidate]["reward"])
             for row in results if "arms" in row]
    deltas = [new - old for old, new in pairs if old is not None and new is not None]
    return {"attempted": len(pairs), "both_completed": len(deltas),
            "both_completed_rate": len(deltas) / len(pairs) if pairs else None,
            "better": sum(d > 0 for d in deltas), "equal": sum(d == 0 for d in deltas),
            "worse": sum(d < 0 for d in deltas),
            "mean_reward_delta": sum(deltas) / len(deltas) if deltas else None}


def evaluate_switch_traces(*, cohort):
    if cohort not in WINDOWS:
        raise ValueError("Select historical or holdout")
    cases = [case for window in WINDOWS[cohort]
             for case in heldout_scenarios(count=CASES_PER_WINDOW, seed=window)]
    own, public, enemy = fixture_teams()
    own[0] = {**own[0], **PRIMEAPE}
    teams = (own, public, enemy)
    legacy = _run_cases(cases, teams, crossed=False)
    worsened = [row["seed"] for row in legacy if "arms" in row and
                all(arm["reward"] is not None for arm in row["arms"].values()) and
                row["arms"]["primeape"]["reward"] < row["arms"]["stay"]["reward"]]
    # Historical diagnostics focus on reproduced cases. The fresh cohort keeps
    # every predeclared seed even if the historical direction does not recur.
    crossed = _run_cases([case for case in cases if cohort == "holdout" or case[0] in worsened],
                         teams, crossed=True)
    return {
        "cohort": cohort, "legacy_worse_seeds": worsened,
        "legacy_primeape_vs_stay": _paired(legacy, "stay", "primeape"),
        "crossed_primeape_vs_stay": _paired(crossed, "stay", "primeape"),
        "crossed_fearow_vs_stay": _paired(crossed, "stay", "fearow"),
        "crossed_fearow_vs_primeape": _paired(crossed, "primeape", "fearow"),
        "legacy": legacy, "crossed": crossed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=tuple(WINDOWS), required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate_switch_traces(cohort=args.cohort), sort_keys=True))


if __name__ == "__main__":
    main()
