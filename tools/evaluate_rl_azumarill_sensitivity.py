"""Non-fixed opponent shielding and public-RL continuation sensitivity on 2026 Worlds Azumarill."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import subprocess

from pvpoke_child_env import child_environment
from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from pvpoke_rl_step_client import NativeStepError, _NativeWorkerTransport, _pipe_exchange
from pvpoke_rl_team_env import OUTCOME_REWARD
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_azumarill import (
    CLOSER_ROSTERS, CLOSER_SELECTION, LEAD_ROSTERS, LEAD_SELECTION,
    RULESET_ID, TOURNAMENT_EVIDENCE, _build_enemy_six, _build_own_six,
)
from tools.rl_charge_metrics import charge_stratum, paired_charge_rewards
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility, validate_team_for_ruleset,
)
from tools.rl_wait_guard import ABLATION_NAME, GuardedWaitMonteCarloPolicy
from tools.run_rl_mc import GAME_DATA

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "tools" / "rl_azumarill_sensitivity_worker.cjs"
WINDOWS = (1300012, 1301012)
SEEDS_PER_ROSTER = 2
TRAIN_SEED = 1300
TRAIN_EPISODES = 24
EVAL_POLICY_SEED = 1399
ROLES = ("lead", "closer")
OPPONENT_POLICIES = ("cpu_always", "save_high_hp", "seeded_mixed_50")
OWN_CONTINUATIONS = ("cpu", "rl_v2_guarded")
LEAD_OPPONENT_SHIELDS = (1, 2)
CLOSER_STARTING_SHIELDS = (2,)
MAX_STEPS = 2000


class _SensitivityWorkerTransport(_NativeWorkerTransport):
    """Persistent bounded worker transport supporting opponent shielding regimes."""

    def _start(self):
        from queue import Queue
        from threading import Thread

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
                name="pvpoke-sensitivity-pipe", daemon=True,
            )
            try:
                thread.start()
            except RuntimeError as error:
                raise NativeStepError("Could not start the sensitivity worker") from error
            self._pipe_thread = thread

    def reset(self, handoff, *, seed, shields, opponent_policy):
        return self._rpc({
            "op": "reset",
            "handoff": handoff,
            "seed": seed,
            "shields": list(shields),
            "opponent_policy": opponent_policy,
        })["result"]

    def step(self, action):
        return self._rpc({"op": "step", "action": action})["result"]

    def private_replay(self):
        return self._rpc({"op": "replay"})["replay"]


def choose_team_cpu(view):
    """Pure public baseline action selector matching native chooseTeamCpu."""
    legal = view["legal_actions"]
    if "shield_yes" in legal:
        active = view["own"]["team"][view["own"]["active_slot"]]
        return "shield_yes" if active["hp"] / active["max_hp"] >= 0.25 else "shield_no"
    switches = [action for action in legal if action.startswith("switch_")]
    if view["phase"] == "replace":
        return switches[0] if switches else "wait"
    for action in legal:
        if action.startswith("charge_"):
            return action
    active = view["own"]["team"][view["own"]["active_slot"]]
    if active["hp"] / active["max_hp"] < 0.25 and switches:
        return switches[0]
    return "fast" if "fast" in legal else "wait"


def _verified_native_ko_reward(response):
    info = response.get("info")
    if type(info) is not dict:
        raise NativeStepError("Missing native terminal info")
    outcome = info.get("outcome")
    if response.get("terminated"):
        if (response.get("truncated") is not False or info.get("training_eligible") is not True or
                outcome not in OUTCOME_REWARD or OUTCOME_REWARD[outcome] != response.get("reward")):
            raise NativeStepError("Native study returned an unverified terminal reward")
        return response["reward"]
    if (response.get("truncated") is not True or response.get("reward") is not None or
            info.get("training_eligible") is not False or outcome not in ("timeout", "unsupported")):
        raise NativeStepError("Native study returned an invalid truncated response")
    return None


def _public_charge_state(view):
    enemy = next(
        (p for p in view["opponent"]["revealed"] if p["species"] == view["opponent"]["active_species"]),
        None,
    )
    if enemy is None or enemy["fainted"]:
        raise RuntimeError("Missing public target at charge fork")
    return {
        "turn": view["turn"],
        "hp_bucket_5pct": enemy["hp_bucket_5pct"],
        "opponent_shields": view["opponent"]["shields"],
        "elapsed_ms": view["elapsed_ms"],
    }


def window_cases(window, role=None):
    """Build predeclared, ruleset-validated sensitivity scenarios."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared sensitivity window")
    if role is not None and role not in ROLES:
        raise ValueError("Use a predeclared Azumarill role")
    own, base_enemy = _build_own_six()
    selected_roles = ROLES if role is None else (role,)
    cases = []
    for item in selected_roles:
        if item == "lead":
            selection, target_slot, rosters, shields_list, expect_fixed = (
                LEAD_SELECTION, 0, LEAD_ROSTERS, LEAD_OPPONENT_SHIELDS, True
            )
        else:
            selection, target_slot, rosters, shields_list, expect_fixed = (
                CLOSER_SELECTION, 2, CLOSER_ROSTERS, CLOSER_STARTING_SHIELDS, False
            )
        for index, (name, replaced, swap_3_4, trio, lead) in enumerate(rosters):
            enemy = _build_enemy_six(base_enemy, replaced, swap_3_4)
            public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
            preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=RULESET_ID)
            preview.choose(selection)
            handoff = preview._private_engine_input()
            start = window + index * SEEDS_PER_ROSTER
            for seed in range(start, start + SEEDS_PER_ROSTER):
                for shields in shields_list:
                    cases.append({
                        "seed": seed,
                        "role": item,
                        "target_slot": target_slot,
                        "roster": name,
                        "opponent_shields": shields,
                        "expected_opponent_shields": shields if expect_fixed else None,
                        "handoff": handoff,
                    })
    return cases


def train_worlds_rl_policy(worker, *, seed=TRAIN_SEED, episodes=TRAIN_EPISODES):
    """Train a public-only v2 Monte Carlo checkpoint on disjoint Worlds-legal episodes."""
    if type(episodes) is not int or not 0 <= episodes <= 32:
        raise ValueError("Training episode budget must be 0..32")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1000:
        raise ValueError("Invalid training seed")
    own, base_enemy = _build_own_six()
    policy = GeneralizedMonteCarloPolicy(seed=seed)
    counts = Counter()
    for ep in range(episodes):
        ep_seed = seed + ep
        rng = random.Random(ep_seed)
        opp_policy = OPPONENT_POLICIES[ep % len(OPPONENT_POLICIES)]
        selection = LEAD_SELECTION if ep % 2 == 0 else CLOSER_SELECTION
        replaced = 1 if ep % 3 == 2 else None
        swap_3_4 = (ep % 6 == 5)
        enemy = _build_enemy_six(base_enemy, replaced, swap_3_4)
        trio = tuple(sorted(rng.sample(range(6), 3)))
        lead = rng.choice(trio)
        public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=RULESET_ID)
        kind, sel_key, legal_sel = policy.encode_state(preview.observe())
        if selection not in legal_sel:
            raise RuntimeError("Illegal predeclared training selection")
        preview.choose(selection)
        handoff = preview._private_engine_input()
        decisions = [(kind, sel_key, selection)]
        opp_shields = (1, 2)[(ep // 2) % 2] if ep % 2 == 0 else 2
        res = worker.reset(
            handoff, seed=ep_seed, shields=(2, opp_shields), opponent_policy=opp_policy
        )
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
    snapshot = policy.snapshot()
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


def _run_arm(worker, case, opponent_policy, own_continuation, rl_snapshot, choice):
    target_slot = case["target_slot"]
    policy = None
    tactic_table = {}
    if own_continuation == "rl_v2_guarded":
        if rl_snapshot is None:
            raise ValueError("Frozen RL snapshot required")
        policy = GuardedWaitMonteCarloPolicy.restore(rl_snapshot, seed=EVAL_POLICY_SEED)
        tactic_table = rl_snapshot["values"]["tactics"]
    res = worker.reset(
        case["handoff"], seed=case["seed"],
        shields=(2, case["opponent_shields"]), opponent_policy=opponent_policy,
    )
    charge_fork = None
    rl_stats = {
        "post_fork_nontrivial_decisions": 0,
        "learned_state_hits": 0,
        "diverged_from_cpu_actions": 0,
    }
    for _ in range(MAX_STEPS):
        view = res["observation"]
        if view is None:
            break
        if charge_fork is None:
            if view["own"]["team"][target_slot]["hp"] == 0:
                return {"excluded": "target_fainted_before_fork"}
            if view["phase"] == "turn" and view["own"]["active_slot"] == target_slot:
                legal = view["legal_actions"]
                if "charge_0" in legal and "charge_1" in legal:
                    if (case["expected_opponent_shields"] is not None and
                            view["opponent"]["shields"] != case["expected_opponent_shields"]):
                        raise RuntimeError("Banking changed opponent shields")
                    charge_fork = {
                        "view": view,
                        "audit": worker.private_replay(),
                        "baseline_action": "charge_0",
                    }
                    action = "charge_0" if choice == "immediate" else choice
                else:
                    action = "fast" if "fast" in legal else "wait"
            else:
                action = choose_team_cpu(view)
        else:
            cpu_action = choose_team_cpu(view)
            if own_continuation == "cpu":
                action = cpu_action
            else:
                _, key, legal = policy.encode_state(view)
                action, _ = policy.choose(view, epsilon=0.0)
                if len(legal) > 1:
                    rl_stats["post_fork_nontrivial_decisions"] += 1
                    rl_stats["learned_state_hits"] += int(key in tactic_table)
                    rl_stats["diverged_from_cpu_actions"] += int(action != cpu_action)
        res = worker.step(action)
    if res["observation"] is not None:
        raise RuntimeError("Charge study exceeded its step budget")
    if charge_fork is None:
        return {"excluded": f'{res["info"]["outcome"]}_before_fork'}
    if policy is not None and policy.snapshot() != rl_snapshot:
        raise RuntimeError("Frozen RL policy mutated during evaluation")
    reward = _verified_native_ko_reward(res)
    final_audit = worker.private_replay()
    requested_move = "PLAY_ROUGH" if choice == "immediate" else "HYDRO_PUMP"
    fork_turn = charge_fork["view"]["turn"]
    fork_events = final_audit["events"][len(charge_fork["audit"]["events"]):]
    resolved = next(
        (e for e in fork_events
         if e["kind"] == "charged" and e["actor"] == 0 and
         e["species"] == "azumarill" and e["turn"] == fork_turn and
         e["move_id"] == requested_move),
        None,
    )
    return {
        "charge_fork": charge_fork,
        "final_audit": final_audit,
        "summary": {
            "reward": reward,
            "outcome": res["info"]["outcome"],
            "requested_move": requested_move,
            "move_resolved": resolved is not None,
            "shielded": bool(resolved["shielded"]) if resolved is not None else None,
        },
        "rl_stats": rl_stats,
    }


def _compare_case(worker, case, opponent_policy, own_continuation, rl_snapshot):
    metadata = {
        "seed": case["seed"],
        "role": case["role"],
        "roster": case["roster"],
        "opponent_policy": opponent_policy,
        "own_continuation": own_continuation,
        "planned_starting_opponent_shields": case["opponent_shields"],
    }
    immediate = _run_arm(worker, case, opponent_policy, own_continuation, rl_snapshot, "immediate")
    if "excluded" in immediate:
        return {**metadata, "excluded": immediate["excluded"]}
    aa = _run_arm(worker, case, opponent_policy, own_continuation, rl_snapshot, "immediate")
    if aa != immediate:
        raise RuntimeError("Immediate charge A/A replay differs")
    alternative = _run_arm(worker, case, opponent_policy, own_continuation, rl_snapshot, "charge_1")
    if "excluded" in alternative or alternative["charge_fork"] != immediate["charge_fork"]:
        raise RuntimeError("Charge study histories differ before the fork")
    return {
        **metadata,
        "public_state": _public_charge_state(immediate["charge_fork"]["view"]),
        "play_rough": immediate["summary"],
        "hydro_pump": alternative["summary"],
        "rl_stats": {
            "play_rough": immediate["rl_stats"],
            "hydro_pump": alternative["rl_stats"],
        },
    }


def summarize_pairs(cases):
    """Aggregate resolution, shielding, censoring, RL hits, and paired terminal reward deltas."""
    pairs = [(row["play_rough"], row["hydro_pump"]) for row in cases if "public_state" in row]
    rl_rows = [row["rl_stats"] for row in cases if "public_state" in row]
    rl_decisions = sum(
        r["play_rough"]["post_fork_nontrivial_decisions"] + r["hydro_pump"]["post_fork_nontrivial_decisions"]
        for r in rl_rows
    )
    rl_hits = sum(
        r["play_rough"]["learned_state_hits"] + r["hydro_pump"]["learned_state_hits"]
        for r in rl_rows
    )
    rl_diverged = sum(
        r["play_rough"]["diverged_from_cpu_actions"] + r["hydro_pump"]["diverged_from_cpu_actions"]
        for r in rl_rows
    )
    return {
        "planned": len(cases),
        **paired_charge_rewards(pairs),
        "excluded": dict(Counter(row["excluded"] for row in cases if "excluded" in row)),
        **{
            move: {
                "resolved": sum(pair[idx]["move_resolved"] for pair in pairs),
                "shielded": sum(pair[idx]["shielded"] is True for pair in pairs),
            }
            for idx, move in enumerate(("play_rough", "hydro_pump"))
        },
        "rl_diagnostics": {
            "post_fork_nontrivial_decisions": rl_decisions,
            "learned_state_hits": rl_hits,
            "learned_hit_rate": rl_hits / rl_decisions if rl_decisions else None,
            "diverged_from_cpu_actions": rl_diverged,
            "cpu_divergence_rate": rl_diverged / rl_decisions if rl_decisions else None,
        },
    }


def summarize(cases):
    """Summarize paired sensitivity results by regime, role, shield/time, and stratum."""
    by_regime, by_regime_role, by_regime_shield_time, by_regime_stratum = {}, {}, {}, {}
    for row in cases:
        regime = f'{row["opponent_policy"]} / {row["own_continuation"]}'
        by_regime.setdefault(regime, []).append(row)
        by_regime_role.setdefault(f'{regime} / {row["role"]}', []).append(row)
        if "public_state" in row:
            stratum = charge_stratum(row["public_state"])
            shield_time = stratum.split(" / ", 1)[1]
            by_regime_shield_time.setdefault(f"{regime} / {shield_time}", []).append(row)
            by_regime_stratum.setdefault(f"{regime} / {stratum}", []).append(row)
    return {
        "overall": summarize_pairs(cases),
        "by_regime": {k: summarize_pairs(v) for k, v in by_regime.items()},
        "by_regime_and_role": {k: summarize_pairs(v) for k, v in by_regime_role.items()},
        "by_regime_shield_and_time": {k: summarize_pairs(v) for k, v in by_regime_shield_time.items()},
        "by_regime_and_stratum": {k: summarize_pairs(v) for k, v in by_regime_stratum.items()},
    }


def evaluate_sensitivity(
    *,
    windows=WINDOWS,
    opponent_policies=OPPONENT_POLICIES,
    own_continuations=OWN_CONTINUATIONS,
    role=None,
    train_episodes=TRAIN_EPISODES,
):
    """Run matched charge forks across opponent shielding policies and own continuations."""
    for item in opponent_policies:
        if item not in OPPONENT_POLICIES:
            raise ValueError(f"Unknown opponent policy: {item!r}")
    for item in own_continuations:
        if item not in OWN_CONTINUATIONS:
            raise ValueError(f"Unknown own continuation: {item!r}")

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

    cases = [case for window in windows for case in window_cases(window, role=role)]
    rl_snapshot = None
    training_summary = None
    snapshot_before_wire = None
    with _SensitivityWorkerTransport(ROOT / "vendor/pvpoke", timeout=15.0) as worker:
        if "rl_v2_guarded" in own_continuations:
            rl_snapshot, training_summary = train_worlds_rl_policy(worker, episodes=train_episodes)
            snapshot_before_wire = json.dumps(rl_snapshot, sort_keys=True)
        rows = [
            _compare_case(worker, case, opp_pol, own_cont, rl_snapshot)
            for opp_pol in opponent_policies
            for own_cont in own_continuations
            for case in cases
        ]
    snapshot_unchanged = None
    if snapshot_before_wire is not None:
        snapshot_unchanged = (snapshot_before_wire == json.dumps(rl_snapshot, sort_keys=True))
        if not snapshot_unchanged:
            raise RuntimeError("Frozen RL checkpoint changed after evaluation")

    return {
        "ruleset_id": RULESET_ID,
        "tournament_evidence": TOURNAMENT_EVIDENCE,
        "ruleset_distinction": ruleset_distinction,
        "windows": list(windows),
        "role": role,
        "opponent_policies": list(opponent_policies),
        "own_continuations": list(own_continuations),
        "rl_overlay": ABLATION_NAME if "rl_v2_guarded" in own_continuations else None,
        "training": training_summary,
        "policy_snapshot_unchanged": snapshot_unchanged,
        "summary": summarize(rows),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both sensitivity windows")
    parser.add_argument("--role", choices=ROLES, help="Default runs both lead and closer roles")
    parser.add_argument("--opponent-policy", choices=OPPONENT_POLICIES)
    parser.add_argument("--own-continuation", choices=OWN_CONTINUATIONS)
    parser.add_argument("--train-episodes", type=int, default=TRAIN_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.train_episodes <= 32:
        parser.error("--train-episodes must be 0..32")
    result = evaluate_sensitivity(
        windows=WINDOWS if args.window is None else (args.window,),
        opponent_policies=OPPONENT_POLICIES if args.opponent_policy is None else (args.opponent_policy,),
        own_continuations=OWN_CONTINUATIONS if args.own_continuation is None else (args.own_continuation,),
        role=args.role,
        train_episodes=args.train_episodes,
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
