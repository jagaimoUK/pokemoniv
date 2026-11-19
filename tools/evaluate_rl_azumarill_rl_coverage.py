"""CPU-compatible cold fallback vs 100-episode training scale ablation on 2026 Worlds Azumarill."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import random

from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from pvpoke_rl_mc_train import PRIORITY
from pvpoke_rl_step_client import NativeStepError
from pvpoke_rl_team_preview import SixToThreeSelection
from tools.evaluate_rl_azumarill import (
    CLOSER_ROSTERS, CLOSER_SELECTION, LEAD_ROSTERS, LEAD_SELECTION,
    RULESET_ID, TOURNAMENT_EVIDENCE, _build_enemy_six, _build_own_six,
)
from tools.evaluate_rl_azumarill_sensitivity import (
    CLOSER_STARTING_SHIELDS, LEAD_OPPONENT_SHIELDS, MAX_STEPS, OPPONENT_POLICIES,
    ROLES, ROOT, SEEDS_PER_ROSTER, _SensitivityWorkerTransport, _public_charge_state,
    _verified_native_ko_reward, choose_team_cpu,
)
from tools.rl_charge_metrics import charge_stratum, paired_charge_rewards
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility,
)
from tools.rl_wait_guard import GuardedWaitMonteCarloPolicy
from tools.run_rl_mc import GAME_DATA

WINDOWS = (1400012, 1401012)
TRAIN_SEED = 1400
SMALL_EPISODES = 24
LARGE_EPISODES = 100
EVAL_POLICY_SEED = 1499
OWN_CONTINUATIONS = (
    "cpu",
    "rl_v2_cpu_fallback_small",
    "rl_v2_cpu_fallback_large",
    "rl_v2_priority_large",
)


class CpuFallbackMonteCarloPolicy(GeneralizedMonteCarloPolicy):
    """Evaluation-only v2 overlay: break exact ties using choose_team_cpu, keeping wait guard."""

    def choose(self, view, *, epsilon=0.2):
        encoded = self.encode_state(view)
        kind, key, legal = encoded
        if kind != "tactics" or epsilon != 0:
            return super()._choose_encoded(encoded, epsilon=epsilon)

        # Advance RNG identically to v2 deterministic evaluation without learning.
        self._rng.random()
        table = self._values["tactics"].get(key, {})
        candidates = legal
        if ("wait" in legal and
                any(a == "fast" or a.startswith("charge_") for a in legal)):
            observed_wait = table.get("wait")
            if observed_wait is None or observed_wait[1] <= 0:
                candidates = tuple(a for a in legal if a != "wait")
        estimates = {a: table[a][1] if a in table else 0.0 for a in candidates}
        best = max(estimates.values())
        ties = [a for a in candidates if estimates[a] == best]
        cpu_action = choose_team_cpu(view)
        action = cpu_action if cpu_action in ties else min(ties, key=PRIORITY.index)
        return action, (kind, key, action)


def window_cases(window, role=None):
    """Build predeclared, ruleset-validated scenarios for the coverage ablation."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared RL coverage window")
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


def _snapshot_stats(policy, *, seed, episodes, counts):
    snap = deepcopy(policy.snapshot())
    return snap, {
        "seed": seed,
        "episodes": episodes,
        "complete": counts["complete"],
        "discarded": counts["discarded"],
        "wins": counts["wins"],
        "losses": counts["losses"],
        "draws": counts["draws"],
        "learned_tactic_states": len(snap["values"]["tactics"]),
        "policy_schema": policy.MODEL_VERSION,
    }


def train_worlds_rl_checkpoints(
    worker, *, seed=TRAIN_SEED, small_episodes=SMALL_EPISODES, large_episodes=LARGE_EPISODES
):
    """Train one v2 policy sequentially and capture paired small/large checkpoints."""
    if (type(small_episodes) is not int or type(large_episodes) is not int or
            not 0 <= small_episodes <= large_episodes <= 120):
        raise ValueError("Invalid paired training episode counts")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1000:
        raise ValueError("Invalid training seed")
    own, base_enemy = _build_own_six()
    policy = GeneralizedMonteCarloPolicy(seed=seed)
    counts = Counter()
    captured = {}
    if small_episodes == 0:
        captured["small"] = _snapshot_stats(policy, seed=seed, episodes=0, counts=counts)
    for ep in range(large_episodes):
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
        if ep + 1 == small_episodes:
            captured["small"] = _snapshot_stats(
                policy, seed=seed, episodes=small_episodes, counts=counts
            )
    captured["large"] = _snapshot_stats(
        policy, seed=seed, episodes=large_episodes, counts=counts
    )
    return captured


def _restore_frozen_policy(own_continuation, checkpoints):
    if own_continuation == "cpu":
        return None, None
    mapping = {
        "rl_v2_cpu_fallback_small": (CpuFallbackMonteCarloPolicy, "small"),
        "rl_v2_cpu_fallback_large": (CpuFallbackMonteCarloPolicy, "large"),
        "rl_v2_priority_large": (GuardedWaitMonteCarloPolicy, "large"),
    }
    cls, scale = mapping[own_continuation]
    snap = checkpoints[scale]
    return cls.restore(snap, seed=EVAL_POLICY_SEED), snap


def _run_arm(worker, case, opponent_policy, own_continuation, checkpoints, choice):
    target_slot = case["target_slot"]
    policy, expected_snapshot = _restore_frozen_policy(own_continuation, checkpoints)
    tactic_table = expected_snapshot["values"]["tactics"] if expected_snapshot else {}
    res = worker.reset(
        case["handoff"], seed=case["seed"],
        shields=(2, case["opponent_shields"]), opponent_policy=opponent_policy,
    )
    charge_fork = None
    rl_stats = {
        "post_fork_nontrivial_decisions": 0,
        "learned_state_hits": 0,
        "diverged_on_seen_states": 0,
        "diverged_on_unseen_states": 0,
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
        res = worker.step(action)
    if res["observation"] is not None:
        raise RuntimeError("Charge study exceeded its step budget")
    if charge_fork is None:
        return {"excluded": f'{res["info"]["outcome"]}_before_fork'}
    if policy is not None and policy.snapshot() != expected_snapshot:
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


def _compare_case(worker, case, opponent_policy, own_continuation, checkpoints):
    metadata = {
        "seed": case["seed"],
        "role": case["role"],
        "roster": case["roster"],
        "opponent_policy": opponent_policy,
        "own_continuation": own_continuation,
        "planned_starting_opponent_shields": case["opponent_shields"],
    }
    immediate = _run_arm(worker, case, opponent_policy, own_continuation, checkpoints, "immediate")
    if "excluded" in immediate:
        return {**metadata, "excluded": immediate["excluded"]}
    aa = _run_arm(worker, case, opponent_policy, own_continuation, checkpoints, "immediate")
    if aa != immediate:
        raise RuntimeError("Immediate charge A/A replay differs")
    alternative = _run_arm(worker, case, opponent_policy, own_continuation, checkpoints, "charge_1")
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
    """Aggregate resolution, shielding, censoring, and seen/unseen RL divergence."""
    pairs = [(row["play_rough"], row["hydro_pump"]) for row in cases if "public_state" in row]
    rl_rows = [row["rl_stats"] for row in cases if "public_state" in row]
    decisions = hits = seen_div = unseen_div = 0
    for row in rl_rows:
        for move in ("play_rough", "hydro_pump"):
            stats = row[move]
            decisions += stats["post_fork_nontrivial_decisions"]
            hits += stats["learned_state_hits"]
            seen_div += stats["diverged_on_seen_states"]
            unseen_div += stats["diverged_on_unseen_states"]
    total_div = seen_div + unseen_div
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
            "post_fork_nontrivial_decisions": decisions,
            "learned_state_hits": hits,
            "learned_hit_rate": hits / decisions if decisions else None,
            "diverged_on_seen_states": seen_div,
            "seen_divergence_rate": seen_div / decisions if decisions else None,
            "diverged_on_unseen_states": unseen_div,
            "unseen_divergence_rate": unseen_div / decisions if decisions else None,
            "total_diverged_from_cpu": total_div,
            "cpu_divergence_rate": total_div / decisions if decisions else None,
        },
    }


def _decompose_regimes(by_regime):
    by_opp = {}
    for key, summary in by_regime.items():
        opp_pol, own_cont = key.split(" / ", 1)
        by_opp.setdefault(opp_pol, {})[own_cont] = summary
    decomposition = {}
    for opp_pol, arms in by_opp.items():
        if set(arms) != set(OWN_CONTINUATIONS):
            continue
        deltas = {cont: arms[cont]["mean_reward_delta"] for cont in OWN_CONTINUATIONS}
        d_cpu = deltas["cpu"]
        d_fb_small = deltas["rl_v2_cpu_fallback_small"]
        d_fb_large = deltas["rl_v2_cpu_fallback_large"]
        d_prio_large = deltas["rl_v2_priority_large"]
        decomposition[opp_pol] = {
            "mean_reward_delta": deltas,
            "training_scale_shift": (
                d_fb_large - d_fb_small if None not in (d_fb_large, d_fb_small) else None
            ),
            "learned_override_shift": (
                d_fb_large - d_cpu if None not in (d_fb_large, d_cpu) else None
            ),
            "cold_tiebreak_shift": (
                d_prio_large - d_fb_large if None not in (d_prio_large, d_fb_large) else None
            ),
            "hit_rate_small": arms["rl_v2_cpu_fallback_small"]["rl_diagnostics"]["learned_hit_rate"],
            "hit_rate_large": arms["rl_v2_cpu_fallback_large"]["rl_diagnostics"]["learned_hit_rate"],
            "hit_rate_priority_large": arms["rl_v2_priority_large"]["rl_diagnostics"]["learned_hit_rate"],
            "seen_div_small": arms["rl_v2_cpu_fallback_small"]["rl_diagnostics"]["diverged_on_seen_states"],
            "seen_div_large": arms["rl_v2_cpu_fallback_large"]["rl_diagnostics"]["diverged_on_seen_states"],
            "unseen_div_fallback_small": arms["rl_v2_cpu_fallback_small"]["rl_diagnostics"]["diverged_on_unseen_states"],
            "unseen_div_fallback_large": arms["rl_v2_cpu_fallback_large"]["rl_diagnostics"]["diverged_on_unseen_states"],
            "unseen_div_priority_large": arms["rl_v2_priority_large"]["rl_diagnostics"]["diverged_on_unseen_states"],
        }
    return decomposition


def summarize(cases):
    """Summarize paired results by regime, role, shield/time, and causal decomposition."""
    by_regime, by_regime_role, by_regime_shield_time = {}, {}, {}
    for row in cases:
        regime = f'{row["opponent_policy"]} / {row["own_continuation"]}'
        by_regime.setdefault(regime, []).append(row)
        by_regime_role.setdefault(f'{regime} / {row["role"]}', []).append(row)
        if "public_state" in row:
            shield_time = charge_stratum(row["public_state"]).split(" / ", 1)[1]
            by_regime_shield_time.setdefault(f"{regime} / {shield_time}", []).append(row)
    regime_summaries = {k: summarize_pairs(v) for k, v in by_regime.items()}
    return {
        "overall": summarize_pairs(cases),
        "by_regime": regime_summaries,
        "by_regime_and_role": {k: summarize_pairs(v) for k, v in by_regime_role.items()},
        "by_regime_shield_and_time": {k: summarize_pairs(v) for k, v in by_regime_shield_time.items()},
        "decomposition": _decompose_regimes(regime_summaries),
    }


def evaluate_rl_coverage(
    *,
    windows=WINDOWS,
    opponent_policies=OPPONENT_POLICIES,
    own_continuations=OWN_CONTINUATIONS,
    role=None,
    small_episodes=SMALL_EPISODES,
    large_episodes=LARGE_EPISODES,
):
    """Run matched charge forks decoupling cold tie-breaks from 24-ep vs 100-ep RL coverage."""
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
    checkpoints = {}
    training_summaries = None
    before_wires = None
    needs_rl = any(cont != "cpu" for cont in own_continuations)
    with _SensitivityWorkerTransport(ROOT / "vendor/pvpoke", timeout=15.0) as worker:
        if needs_rl:
            trained = train_worlds_rl_checkpoints(
                worker, small_episodes=small_episodes, large_episodes=large_episodes
            )
            checkpoints = {scale: pair[0] for scale, pair in trained.items()}
            training_summaries = {scale: pair[1] for scale, pair in trained.items()}
            before_wires = {
                scale: json.dumps(snap, sort_keys=True) for scale, snap in checkpoints.items()
            }
        rows = [
            _compare_case(worker, case, opp_pol, own_cont, checkpoints)
            for opp_pol in opponent_policies
            for own_cont in own_continuations
            for case in cases
        ]

    snapshots_unchanged = None
    if before_wires is not None:
        snapshots_unchanged = {
            scale: wire == json.dumps(checkpoints[scale], sort_keys=True)
            for scale, wire in before_wires.items()
        }
        if not all(snapshots_unchanged.values()):
            raise RuntimeError("Frozen RL checkpoint changed after evaluation")

    return {
        "ruleset_id": RULESET_ID,
        "tournament_evidence": TOURNAMENT_EVIDENCE,
        "ruleset_distinction": ruleset_distinction,
        "windows": list(windows),
        "role": role,
        "opponent_policies": list(opponent_policies),
        "own_continuations": list(own_continuations),
        "small_episodes": small_episodes,
        "large_episodes": large_episodes,
        "training": training_summaries,
        "policy_snapshots_unchanged": snapshots_unchanged,
        "summary": summarize(rows),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both coverage windows")
    parser.add_argument("--role", choices=ROLES, help="Default runs both lead and closer roles")
    parser.add_argument("--opponent-policy", choices=OPPONENT_POLICIES)
    parser.add_argument("--own-continuation", choices=OWN_CONTINUATIONS)
    parser.add_argument("--small-episodes", type=int, default=SMALL_EPISODES)
    parser.add_argument("--large-episodes", type=int, default=LARGE_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.small_episodes <= args.large_episodes <= 120:
        parser.error("Require 0 <= --small-episodes <= --large-episodes <= 120")
    result = evaluate_rl_coverage(
        windows=WINDOWS if args.window is None else (args.window,),
        opponent_policies=OPPONENT_POLICIES if args.opponent_policy is None else (args.opponent_policy,),
        own_continuations=OWN_CONTINUATIONS if args.own_continuation is None else (args.own_continuation,),
        role=args.role,
        small_episodes=args.small_episodes,
        large_episodes=args.large_episodes,
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
