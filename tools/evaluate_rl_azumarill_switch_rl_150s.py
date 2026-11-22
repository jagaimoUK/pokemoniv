"""Compare CPU vs frozen public-RL continuations on the fixed-150s synthetic switch study."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from queue import Queue
import random
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread

from pvpoke_child_env import child_environment
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from pvpoke_rl_step_client import NativeStepError, _NativeWorkerTransport, _pipe_exchange
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_rl_coverage import CpuFallbackMonteCarloPolicy
from tools.evaluate_rl_azumarill_sensitivity import (
    _public_charge_state, _verified_native_ko_reward, choose_team_cpu,
)
from tools.evaluate_rl_azumarill_switch_150s import (
    BUILDS, CONDITIONS, REMAINING_SECONDS, ROSTERS,
)
from tools.evaluate_rl_azumarill_switch_clock import summarize_clock_group
from tools.evaluate_rl_azumarill_switch_strata import ARMS
from tools.evaluate_rl_branches import PRIMEAPE
from tools.evaluate_rl_quagsire import build_window_cases, shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility, validate_team_for_ruleset,
)
from tools.rl_wait_guard import GuardedWaitMonteCarloPolicy
from tools.run_rl_mc import GAME_DATA, fixture_teams

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "tools" / "rl_azumarill_switch_rl_worker.cjs"
WINDOWS = (2400012, 2401012)
TRAIN_SEED = 2400
TRAIN_EPISODES = 100
EVAL_POLICY_SEED = 2499
MAX_STEPS = 2000
WAIT_TURNS = (240 - REMAINING_SECONDS) * 2
OWN_CONTINUATIONS = ("cpu", "rl_v2_cpu_fallback", "rl_v2_priority")
ARM_ACTIONS = {"switch_skarmory": ("switch_2", 2), "switch_quagsire": ("switch_1", 1)}


class _SwitchRlWorkerTransport(_NativeWorkerTransport):
    """Persistent bounded worker transport supporting shadow gamemaster and wait-turn forks."""

    def __init__(self, source, gamemaster_path, *, timeout=15.0):
        super().__init__(source, timeout=timeout)
        self._gamemaster_path = str(gamemaster_path)

    def _start(self):
        if self._proc is None:
            self._proc = subprocess.Popen(
                ["node", "--max-old-space-size=128", str(WORKER)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=child_environment({"PVP_PVPOKE_SOURCE": str(self._source)}),
            )
        if self._pipe_thread is None:
            self._requests = Queue()
            self._replies = Queue()
            thread = Thread(
                target=_pipe_exchange, args=(self._proc, self._requests, self._replies),
                name="pvpoke-switch-rl-pipe", daemon=True,
            )
            try:
                thread.start()
            except RuntimeError as error:
                raise NativeStepError("Could not start the switch RL worker") from error
            self._pipe_thread = thread

    def reset(self, handoff, *, seed, shields, hp_percent=None, wait_turns=0):
        payload = {
            "op": "reset",
            "gamemaster_path": self._gamemaster_path,
            "handoff": handoff,
            "seed": seed,
            "shields": list(shields),
            "wait_turns": wait_turns,
        }
        if hp_percent is not None:
            payload["hp_percent"] = hp_percent
        return self._rpc(payload)["result"]

    def step(self, action):
        return self._rpc({"op": "step", "action": action})["result"]

    def public_replay(self):
        return self._rpc({"op": "public_replay"})["public_replay"]


def window_cases(window):
    """Build single-factor HP/shield batches at fixed 150s remaining clock."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared 150s RL comparison window")
    base_cases = build_window_cases(window, (RULESET_ID,), ROSTERS, 3, own_selection="0,2,4|2")
    cases = []
    for row in base_cases:
        quagsire = row["handoff"]["own_team"][1]
        if row["opponent_shields"] == 0 and quagsire["charged2"] == BUILDS[quagsire["species"]]:
            cases.extend(
                {
                    **row,
                    "condition": condition,
                    "hp_percent": hp_percent,
                    "own_shields": own_shields,
                    "remaining_seconds": REMAINING_SECONDS,
                }
                for condition, hp_percent, own_shields in CONDITIONS
            )
    return cases


def train_worlds_switch_policy(worker, *, seed=TRAIN_SEED, episodes=TRAIN_EPISODES):
    """Train a public-only v2 policy on disjoint Worlds-legal 6v3 episodes."""
    if type(episodes) is not int or not 0 <= episodes <= 120:
        raise ValueError("Training episode budget must be 0..120")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1000:
        raise ValueError("Invalid training seed")
    own_base, _, enemy_base = fixture_teams()
    build_items = list(BUILDS.items())
    policy = GeneralizedMonteCarloPolicy(seed=seed)
    counts = Counter()

    for ep in range(episodes):
        ep_seed = seed + ep
        rng = random.Random(ep_seed)
        species, move = build_items[ep % 2]
        own = [{**own_base[0], "species": species, "charged2": move}, *own_base[1:]]
        enemy = [dict(row) for row in enemy_base]
        if ep % 3 == 2:
            enemy[1].update(PRIMEAPE)
        validate_team_for_ruleset(own, RULESET_ID)
        validate_team_for_ruleset(enemy, RULESET_ID)
        trio = tuple(sorted(rng.sample(range(6), 3)))
        lead = rng.choice(trio)
        public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=RULESET_ID)
        selection = "0,2,4|2"
        kind, sel_key, legal_sel = policy.encode_state(preview.observe())
        if selection not in legal_sel:
            raise RuntimeError("Illegal predeclared training selection")
        preview.choose(selection)
        handoff = preview._private_engine_input()
        decisions = [(kind, sel_key, selection)]
        own_shields = (0, 1, 2)[ep % 3]
        opp_shields = (0, 1, 2)[(ep // 3) % 3]
        res = worker.reset(handoff, seed=ep_seed, shields=(own_shields, opp_shields))
        for _ in range(MAX_STEPS):
            view = res["observation"]
            if view is None:
                break
            action, record = policy.choose(view, epsilon=0.25)
            decisions.append(record)
            res = worker.step(action)
        if res["observation"] is not None:
            raise NativeStepError("Training episode exceeded step budget")
        reward = _verified_native_ko_reward(res)
        if reward is not None:
            policy.learn(decisions, reward=reward, selection_reward=reward)
            counts["complete"] += 1
            counts[{1: "wins", -1: "losses", 0: "draws"}[reward]] += 1
        else:
            counts["discarded"] += 1

    snapshot = deepcopy(policy.snapshot())
    return snapshot, {
        "seed": seed,
        "episodes": episodes,
        "complete": counts["complete"],
        "discarded": counts["discarded"],
        "wins": counts["wins"],
        "losses": counts["losses"],
        "draws": counts["draws"],
        "learned_tactic_states": len(snapshot["values"]["tactics"]),
        "policy_schema": policy.MODEL_VERSION,
    }


def _restore_frozen_policy(own_continuation, snapshot):
    if own_continuation == "cpu":
        return None
    if snapshot is None:
        raise ValueError("Frozen RL snapshot required")
    cls = CpuFallbackMonteCarloPolicy if own_continuation == "rl_v2_cpu_fallback" else GuardedWaitMonteCarloPolicy
    return cls.restore(snapshot, seed=EVAL_POLICY_SEED)


def _run_arm(worker, case, own_continuation, snapshot, arm):
    action_name, target_slot = ARM_ACTIONS[arm]
    policy = _restore_frozen_policy(own_continuation, snapshot)
    tactic_table = snapshot["values"]["tactics"] if snapshot is not None else {}

    res = worker.reset(
        case["handoff"],
        seed=case["seed"],
        shields=(case["own_shields"], 0),
        hp_percent=case["hp_percent"],
        wait_turns=WAIT_TURNS,
    )
    fork_view = res["observation"]
    if fork_view is None or fork_view["elapsed_ms"] != BATTLE_CLOCK_MS - REMAINING_SECONDS * 1000:
        raise RuntimeError("Fork did not land at expected 150s remaining clock")
    target_species = fork_view["own"]["team"][target_slot]["species"]
    fork_turn = fork_view["turn"]

    rl_stats = {
        "post_fork_nontrivial_decisions": 0,
        "learned_state_hits": 0,
        "diverged_on_seen_states": 0,
        "diverged_on_unseen_states": 0,
        "low_hp_shield_yes": 0,
        "low_hp_shield_no": 0,
    }

    res = worker.step(action_name)
    for _ in range(MAX_STEPS):
        view = res["observation"]
        if view is None:
            break
        cpu_action = choose_team_cpu(view)
        if policy is None:
            action = cpu_action
        else:
            _, key, legal = policy.encode_state(view)
            action, _ = policy.choose(view, epsilon=0.0)
            if len(legal) > 1:
                is_seen = key in tactic_table
                rl_stats["post_fork_nontrivial_decisions"] += 1
                rl_stats["learned_state_hits"] += int(is_seen)
                if action != cpu_action:
                    if is_seen:
                        rl_stats["diverged_on_seen_states"] += 1
                    else:
                        rl_stats["diverged_on_unseen_states"] += 1
        if "shield_yes" in view["legal_actions"]:
            active = view["own"]["team"][view["own"]["active_slot"]]
            if active["hp"] / active["max_hp"] < 0.25:
                if action == "shield_yes":
                    rl_stats["low_hp_shield_yes"] += 1
                else:
                    rl_stats["low_hp_shield_no"] += 1
        res = worker.step(action)

    if res["observation"] is not None:
        raise RuntimeError("150s RL switch episode exceeded step budget")
    if policy is not None and policy.snapshot() != snapshot:
        raise RuntimeError("Frozen RL policy mutated during evaluation")

    reward = _verified_native_ko_reward(res)
    replay = worker.public_replay()
    action_resolved = any(
        e["kind"] == "switch" and e["side"] == "self" and not e["forced"]
        and e["turn"] == fork_turn and e["species"] == target_species and e["previous_species"] == "azumarill"
        for e in replay["events"]
    )
    return {
        "fork_view": fork_view,
        "summary": {
            "action_resolved": action_resolved,
            "reward": reward,
            "outcome": res["info"]["outcome"],
            "elapsed_ms": replay["elapsed_ms"],
            "replay": replay,
        },
        "rl_stats": rl_stats,
    }


def _compare_case(worker, case, own_continuation, snapshot):
    arm_skarmory = _run_arm(worker, case, own_continuation, snapshot, "switch_skarmory")
    arm_quagsire = _run_arm(worker, case, own_continuation, snapshot, "switch_quagsire")
    if arm_skarmory["fork_view"] != arm_quagsire["fork_view"]:
        raise RuntimeError("Fork views differ before switching")
    view = arm_skarmory["fork_view"]
    quagsire = case["handoff"]["own_team"][1]
    skarmory = case["handoff"]["own_team"][2]
    row = {
        "seed": case["seed"],
        "roster": case["roster"],
        "condition": case["condition"],
        "own_continuation": own_continuation,
        "species": quagsire["species"],
        "second_move": quagsire["charged2"],
        "hp_percent": case["hp_percent"],
        "own_shields": case["own_shields"],
        "remaining_seconds": REMAINING_SECONDS,
        "public_state": _public_charge_state(view),
        "switch_targets": {"switch_skarmory": skarmory["species"], "switch_quagsire": quagsire["species"]},
        "after_event_seq": 0,
        "switch_skarmory": arm_skarmory["summary"],
        "switch_quagsire": arm_quagsire["summary"],
        "rl_stats": {
            "switch_skarmory": arm_skarmory["rl_stats"],
            "switch_quagsire": arm_quagsire["rl_stats"],
        },
    }
    row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
    return row


def summarize_group(rows):
    """Summarize outcomes, censoring separation, low-HP shielding, and RL diagnostics."""
    report = summarize_clock_group(rows)
    decisions = hits = seen_div = unseen_div = sh_yes = sh_no = 0
    for row in rows:
        for arm in ARMS:
            st = row["rl_stats"][arm]
            decisions += st["post_fork_nontrivial_decisions"]
            hits += st["learned_state_hits"]
            seen_div += st["diverged_on_seen_states"]
            unseen_div += st["diverged_on_unseen_states"]
            sh_yes += st["low_hp_shield_yes"]
            sh_no += st["low_hp_shield_no"]
    report["low_hp_shield_decisions"] = {"shield_yes": sh_yes, "shield_no": sh_no}
    report["rl_diagnostics"] = {
        "post_fork_nontrivial_decisions": decisions,
        "learned_state_hits": hits,
        "learned_hit_rate": hits / decisions if decisions else None,
        "diverged_on_seen_states": seen_div,
        "diverged_on_unseen_states": unseen_div,
        "total_diverged_from_cpu": seen_div + unseen_div,
    }
    return report


def summarize_results(rows, own_continuations):
    """Group metrics by continuation policy, condition, and roster."""
    by_continuation = {}
    for cont in own_continuations:
        cont_rows = [r for r in rows if r["own_continuation"] == cont]
        by_condition = {}
        for cond, hp_pct, own_sh in CONDITIONS:
            selected = [r for r in cont_rows if r["condition"] == cond]
            by_condition[cond] = {
                "hp_percent": hp_pct,
                "own_shields": own_sh,
                **summarize_group(selected),
                "by_roster": {
                    name: summarize_group([r for r in selected if r["roster"] == name])
                    for name, *_ in ROSTERS
                },
            }
        by_continuation[cont] = {
            "overall": summarize_group(cont_rows),
            "by_condition": by_condition,
        }

    comparison_vs_cpu = {}
    if "cpu" in by_continuation:
        cpu_conds = by_continuation["cpu"]["by_condition"]
        for cont in own_continuations:
            if cont == "cpu":
                continue
            comp = {}
            for cond, *_ in CONDITIONS:
                c_cpu = cpu_conds[cond]
                c_rl = by_continuation[cont]["by_condition"][cond]
                d_cpu = c_cpu["ko_reward_comparison"]["mean_reward_delta"]
                d_rl = c_rl["ko_reward_comparison"]["mean_reward_delta"]
                comp[cond] = {
                    "cpu_both_ko_delta": d_cpu,
                    "rl_both_ko_delta": d_rl,
                    "delta_shift": d_rl - d_cpu if None not in (d_cpu, d_rl) else None,
                    "cpu_both_timeout": c_cpu["outcome_breakdown"]["both_timeout"],
                    "rl_both_timeout": c_rl["outcome_breakdown"]["both_timeout"],
                    "cpu_low_hp_shield_yes": c_cpu["low_hp_shield_decisions"]["shield_yes"],
                    "rl_low_hp_shield_yes": c_rl["low_hp_shield_decisions"]["shield_yes"],
                }
            comparison_vs_cpu[cont] = comp

    return {"by_continuation": by_continuation, "comparison_vs_cpu": comparison_vs_cpu}


def evaluate_rl_switch_150s(
    *,
    windows=WINDOWS,
    own_continuations=OWN_CONTINUATIONS,
    train_episodes=TRAIN_EPISODES,
):
    """Run matched 150s switch comparisons across CPU and frozen public-RL continuations."""
    for cont in own_continuations:
        if cont not in OWN_CONTINUATIONS:
            raise ValueError(f"Unknown continuation: {cont!r}")

    pokemon_by_id = {
        entry["speciesId"]: entry
        for entry in json.loads(GAME_DATA.read_text(encoding="utf-8"))["pokemon"]
    }
    ruleset_distinction = {
        "worlds_2026_mimikyu": evaluate_tournament_eligibility("mimikyu", RULESET_ID),
        "cs_2026_11_16_mimikyu": evaluate_tournament_eligibility("mimikyu", "play-pokemon-cs-2026-11-16-gl"),
        "open_gl_mimikyu": evaluate_tournament_eligibility("mimikyu", "great-league-v1"),
        "simulator_analyzability_azumarill": evaluate_simulator_analyzability("azumarill", pokemon_by_id),
    }

    cases = [case for window in windows for case in window_cases(window)]
    needs_rl = any(cont != "cpu" for cont in own_continuations)
    snapshot = None
    training_summary = None
    before_wire = None
    snapshot_unchanged = None

    with TemporaryDirectory(prefix="quagsire-rl-150s-") as temp:
        gm_path = Path(temp) / "strategy_gamemaster_shadow.json"
        gm_path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", gm_path, timeout=15.0) as worker:
            if needs_rl:
                snapshot, training_summary = train_worlds_switch_policy(
                    worker, seed=TRAIN_SEED, episodes=train_episodes
                )
                before_wire = json.dumps(snapshot, sort_keys=True)
            rows = [
                _compare_case(worker, case, cont, snapshot)
                for cont in own_continuations
                for case in cases
            ]

    if before_wire is not None:
        snapshot_unchanged = (before_wire == json.dumps(snapshot, sort_keys=True))
        if not snapshot_unchanged:
            raise RuntimeError("Frozen RL snapshot mutated after evaluation")

    return {
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "remaining_seconds": REMAINING_SECONDS,
        "study": "synthetic_150s_cpu_vs_public_rl_continuation",
        "ruleset_distinction": ruleset_distinction,
        "windows": list(windows),
        "own_continuations": list(own_continuations),
        "training": training_summary,
        "policy_snapshot_unchanged": snapshot_unchanged,
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "summary": summarize_results(rows, own_continuations),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both 2400012+ windows")
    parser.add_argument("--own-continuation", choices=OWN_CONTINUATIONS)
    parser.add_argument("--train-episodes", type=int, default=TRAIN_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.train_episodes <= 120:
        parser.error("Require 0 <= --train-episodes <= 120")
    result = evaluate_rl_switch_150s(
        windows=WINDOWS if args.window is None else (args.window,),
        own_continuations=OWN_CONTINUATIONS if args.own_continuation is None else (args.own_continuation,),
        train_episodes=args.train_episodes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
