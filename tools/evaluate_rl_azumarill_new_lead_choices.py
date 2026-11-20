"""Compare CPU and legal switches at fixed public forks against new leads."""
import argparse
from fractions import Fraction
from itertools import combinations
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.evaluate_rl_azumarill_bench_choices import compare_fork, summarize
from tools.evaluate_rl_azumarill_bench_mixture import score_bench_weights
from tools.evaluate_rl_azumarill_natural_energy import _reset
from tools.evaluate_rl_azumarill_sensitivity import choose_team_cpu
from tools.evaluate_rl_azumarill_shared_history import build_history_cases
from tools.evaluate_rl_azumarill_switch_intervention import public_view_sha256
from tools.evaluate_rl_azumarill_switch_rl_150s import MAX_STEPS, _SwitchRlWorkerTransport
from tools.evaluate_rl_azumarill_switch_rl_targeted import ROOT, ruleset_distinction
from tools.evaluate_rl_quagsire import shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.run_rl_mc import fixture_teams

WINDOWS = (3302012, 3303012)
SEEDS_PER_WINDOW = 3
LEADS = {1: "clodsire", 4: "skarmory"}


def window_cases(window, lead):
    if type(window) is not int or window not in WINDOWS or lead not in LEADS:
        raise ValueError("Use a predeclared lead and seed window")
    _, _, enemy = fixture_teams()
    cases = []
    for left, right in combinations([slot for slot in range(6) if slot != lead], 2):
        name = f'{enemy[left]["species"]}_{enemy[right]["species"]}'
        roster = (name, "0,3,5|0", lead, (left, right, lead))
        cases.extend(case for case in build_history_cases(window, (roster,), SEEDS_PER_WINDOW)
                     if case["handoff"]["own_team"][0]["species"] == "quagsire_shadow")
    return cases


def find_public_fork(worker, case, lead):
    """Take the first turn with damage and both switches while both leads are active."""
    result = _reset(worker, case)
    history = []
    for _ in range(MAX_STEPS):
        view = result["observation"]
        if view is None:
            break
        own = view["own"]
        opponent = view["opponent"]
        if own["active_slot"] != 0 or opponent["active_species"] != lead or len(opponent["revealed"]) != 1:
            break
        active = own["team"][0]
        if (view["phase"] == "turn" and 0 < active["hp"] < active["max_hp"]
                and {"switch_1", "switch_2"} <= set(view["legal_actions"])):
            return tuple(history), view
        action = choose_team_cpu(view)
        history.append(action)
        result = worker.step(action)
    raise RuntimeError(f"No predeclared public fork for {lead}")


def mixture_scores(by_roster):
    """Sweep every pair of benches at 10-point increments, plus uniform."""
    names = list(by_roster)
    uniform = score_bench_weights(by_roster, dict.fromkeys(names, Fraction(1, len(names))))
    pairs = [
        {"first": left, "second": right, "first_pct": pct,
         **score_bench_weights(by_roster, {left: Fraction(pct, 100), right: Fraction(100 - pct, 100)})}
        for left, right in combinations(names, 2) for pct in range(0, 101, 10)
    ]
    return {"uniform": uniform, "pairs": pairs}


def evaluate_new_leads(*, windows=WINDOWS):
    windows = tuple(windows)
    if not windows or len(windows) != len(set(windows)) or not set(windows) <= set(WINDOWS):
        raise ValueError("Use one or both predeclared seed windows")
    cohorts = {}
    with TemporaryDirectory(prefix="quagsire-new-leads-") as temp:
        path = Path(temp) / "shadow.json"
        path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", path) as worker:
            for lead, name in LEADS.items():
                cases = [case for window in windows for case in window_cases(window, lead)]
                forks = [find_public_fork(worker, case, name) for case in cases]
                _, reference = forks[0]
                if any(view != reference for _, view in forks):
                    raise RuntimeError(f"Public fork differs between benches or seeds for {name}")
                rows = [compare_fork(worker, case, fork) for case, fork in zip(cases, forks, strict=True)]
                if any(arm["switch_resolved"] is False for row in rows for arm in row["actions"].values()):
                    raise RuntimeError(f"A requested switch did not resolve for {name}")
                by_roster = {}
                for roster in dict.fromkeys(row["roster"] for row in rows):
                    selected = [row for row in rows if row["roster"] == roster]
                    by_roster[roster] = {"opponent_bench": selected[0]["opponent_bench"], **summarize(selected)}
                for roster, bench in by_roster.items():
                    bench["rates"] = score_bench_weights(by_roster, {roster: Fraction(1)})["rates"]
                cohorts[name] = {
                    "fork": {"turn": reference["turn"], "elapsed_ms": reference["elapsed_ms"],
                             "hp": reference["own"]["team"][0]["hp"],
                             "max_hp": reference["own"]["team"][0]["max_hp"],
                             "sha256": public_view_sha256(reference)},
                    "cpu_action": rows[0]["cpu_action"], "cpu_move_id": rows[0]["cpu_move_id"],
                    "summary": summarize(rows), "by_roster": by_roster,
                    "mixtures": mixture_scores(by_roster), "cases": rows,
                }
    return {"ruleset_id": RULESET_ID, "ruleset_distinction": ruleset_distinction(),
            "starting_shields": [2, 2], "windows": list(windows), "cohorts": cohorts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS)
    args = parser.parse_args()
    print(json.dumps(evaluate_new_leads(windows=WINDOWS if args.window is None else (args.window,)),
                     sort_keys=True))


if __name__ == "__main__":
    main()
