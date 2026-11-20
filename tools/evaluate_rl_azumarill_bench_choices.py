"""Compare CPU and every legal switch at the same public Shadow Quagsire fork."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evaluate_rl_azumarill_natural_energy import _forks
from tools.evaluate_rl_azumarill_sensitivity import choose_team_cpu
from tools.evaluate_rl_azumarill_shared_history import build_history_cases
from tools.evaluate_rl_azumarill_switch_intervention import play_one_action, public_view_sha256
from tools.evaluate_rl_azumarill_switch_rl_150s import _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import ROOT, ruleset_distinction
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import paired_charge_rewards

WINDOWS = (3100012, 3101012)
SEEDS_PER_ROSTER = 3
EXPECTED_PUBLIC_FORK = "5e326ea96478fbe6aac1d119304a87a66e6fedceb2c7bddabd1940ad668f582a"
# Name, own selection, opponent lead, opponent selected trio. These five
# benches exclude the four previous test benches and the training bench.
ROSTERS = (
    ("quagsire_clodsire", "0,3,5|0", 3, (0, 1, 3)),
    ("quagsire_azumarill", "0,3,5|0", 3, (0, 2, 3)),
    ("quagsire_wigglytuff", "0,3,5|0", 3, (0, 3, 5)),
    ("clodsire_azumarill", "0,3,5|0", 3, (1, 2, 3)),
    ("clodsire_skarmory", "0,3,5|0", 3, (1, 3, 4)),
)
OUTCOMES = ("self_ko_win", "opponent_ko_win", "simultaneous_ko", "timeout", "unsupported")


def window_cases(window):
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared bench-comparison window")
    return [
        case for case in build_history_cases(window, ROSTERS, SEEDS_PER_ROSTER)
        if case["handoff"]["own_team"][0]["species"] == "quagsire_shadow"
    ]


def compare_case(worker, case):
    fork = _forks(worker, case).get("hp_60")
    if fork is None or public_view_sha256(fork[1]) != EXPECTED_PUBLIC_FORK:
        raise RuntimeError("The prior public fork was not reproduced")
    _, view = fork
    cpu = choose_team_cpu(view)
    switches = [action for action in view["legal_actions"] if action.startswith("switch_")]
    if not switches:
        raise RuntimeError("The bench comparison requires a legal switch")

    arms = {action: play_one_action(worker, case, fork, action)
            for action in dict.fromkeys([cpu, *switches])}
    if arms[cpu] != play_one_action(worker, case, fork, cpu):
        raise RuntimeError("Identical CPU action A/A replay produced a different result")
    own = view["own"]
    active = own["team"][own["active_slot"]]
    cpu_move_id = None
    if cpu == "fast":
        cpu_move_id = active["fast_move"]
    elif cpu.startswith("charge_"):
        cpu_move_id = active["charged_moves"][int(cpu[-1])]["move_id"]
    return {
        "roster": case["roster"], "seed": case["seed"],
        "opponent_bench": [member["species"] for member in case["handoff"]["opponent_team"][1:]],
        "cpu_action": cpu, "cpu_move_id": cpu_move_id,
        "actions": arms,
    }


def summarize(rows):
    summary = {}
    if not rows:
        return {"matched_forks": 0, "actions": summary}
    cpu = rows[0]["cpu_action"]
    for action in rows[0]["actions"]:
        arms = [row["actions"][action] for row in rows]
        counts = Counter(arm["outcome"] for arm in arms)
        is_switch = action.startswith("switch_")
        matched = [
            (row["actions"][cpu], arm)
            for row, arm in zip(rows, arms, strict=True)
            if not is_switch or arm["switch_resolved"]
        ]
        summary[action] = {
            "target_species": arms[0]["target_species"],
            "outcomes": {outcome: counts[outcome] for outcome in OUTCOMES},
            "switches_resolved": len(matched) if is_switch else None,
            "ko_reward_vs_cpu": paired_charge_rewards(matched) if action != cpu else None,
        }
    return {"matched_forks": len(rows), "actions": summary}


def replay_bench_cases(batches):
    with TemporaryDirectory(prefix="quagsire-bench-choices-") as temp:
        path = Path(temp) / "strategy_gamemaster_shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            return [{**compare_case(worker, case), "window": window}
                    for window, cases in batches.items() for case in cases]


def evaluate_bench_choices(*, windows=WINDOWS):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)) or not set(windows) <= set(WINDOWS):
        raise ValueError("Use one or both distinct bench-comparison windows")
    rows = replay_bench_cases({window: window_cases(window) for window in windows})
    return {
        "ruleset_id": RULESET_ID,
        "ruleset_distinction": ruleset_distinction(),
        "starting_shields": [2, 2],
        "windows": list(windows),
        "public_view_sha256": EXPECTED_PUBLIC_FORK,
        "cpu_action": rows[0]["cpu_action"],
        "cpu_move_id": rows[0]["cpu_move_id"],
        "summary": summarize(rows),
        "by_roster": {name: summarize([row for row in rows if row["roster"] == name])
                      for name, *_ in ROSTERS},
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS)
    args = parser.parse_args()
    print(json.dumps(evaluate_bench_choices(
        windows=WINDOWS if args.window is None else (args.window,)
    ), sort_keys=True))


if __name__ == "__main__":
    main()
