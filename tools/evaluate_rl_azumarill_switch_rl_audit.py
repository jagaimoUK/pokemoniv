"""Audit seen-state divergences and energy-state aliasing under targeted 150s RL."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pvpoke_rl_mc_train import public_state as v1_public_state
from tools.evaluate_rl_azumarill_mirror_followup import trace_arm
from tools.evaluate_rl_azumarill_rl_coverage import CpuFallbackMonteCarloPolicy
from tools.evaluate_rl_azumarill_sensitivity import (
    _public_charge_state, _verified_native_ko_reward, choose_team_cpu,
)
from tools.evaluate_rl_azumarill_switch_150s import (
    BUILDS, CONDITIONS, REMAINING_SECONDS, ROSTERS,
)
from tools.evaluate_rl_azumarill_switch_clock import summarize_clock_group
from tools.evaluate_rl_azumarill_switch_rl_150s import (
    ARM_ACTIONS, MAX_STEPS, WAIT_TURNS, _SwitchRlWorkerTransport,
)
from tools.evaluate_rl_azumarill_switch_rl_targeted import (
    EVAL_POLICY_SEED, TARGETED_TRAIN_SEED, TRAIN_EPISODES,
    train_targeted_switch_policy,
)
from tools.evaluate_rl_azumarill_switch_strata import ARMS
from tools.evaluate_rl_quagsire import build_window_cases, shadow_gamemaster
from tools.evaluate_rl_quagsire_timeouts import RULESET_ID
from tools.rl_charge_metrics import BATTLE_CLOCK_MS
from tools.rl_tournament_rules import (
    evaluate_simulator_analyzability, evaluate_tournament_eligibility,
)
from tools.run_rl_mc import GAME_DATA

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = (2600012, 2601012)
OWN_CONTINUATIONS = ("cpu", "rl_targeted_cpu_fallback")


def window_cases(window):
    """Build single-factor HP/shield batches at fixed 150s remaining clock."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared 150s RL audit window")
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


def _audit_arm(worker, case, own_continuation, snapshot, arm):
    action_name, target_slot = ARM_ACTIONS[arm]
    policy = (
        CpuFallbackMonteCarloPolicy.restore(snapshot, seed=EVAL_POLICY_SEED)
        if own_continuation == "rl_targeted_cpu_fallback" else None
    )
    tactic_table = snapshot["values"]["tactics"] if policy is not None else {}

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

    divergences = []
    stats = {
        "post_fork_nontrivial_decisions": 0,
        "learned_state_hits": 0,
        "diverged_on_seen_states": 0,
        "diverged_on_unseen_states": 0,
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
            _, v2_key, legal = policy.encode_state(view)
            action, _ = policy.choose(view, epsilon=0.0)
            is_seen = v2_key in tactic_table
            if len(legal) > 1:
                stats["post_fork_nontrivial_decisions"] += 1
                stats["learned_state_hits"] += int(is_seen)
                if action != cpu_action:
                    if is_seen:
                        stats["diverged_on_seen_states"] += 1
                        active = view["own"]["team"][view["own"]["active_slot"]]
                        _, v1_key, _ = v1_public_state(view)
                        energy = active["energy_points"]
                        divergences.append({
                            "turn": view["turn"],
                            "elapsed_ms": view["elapsed_ms"],
                            "phase": view["phase"],
                            "species": active["species"],
                            "opponent_species": view["opponent"]["active_species"],
                            "cpu_action": cpu_action,
                            "rl_action": action,
                            "transition": f"{cpu_action}->{action}",
                            "energy_points": energy,
                            "energy_band_10": energy // 10,
                            "own_hp_pct": round(100 * active["hp"] / active["max_hp"], 1),
                            "v2_key": v2_key,
                            "v1_key": v1_key,
                        })
                    else:
                        stats["diverged_on_unseen_states"] += 1
        res = worker.step(action)

    if res["observation"] is not None:
        raise RuntimeError("150s RL audit episode exceeded step budget")
    if policy is not None and policy.snapshot() != snapshot:
        raise RuntimeError("Frozen RL policy mutated during audit")

    reward = _verified_native_ko_reward(res)
    replay = worker.public_replay()
    action_resolved = any(
        e["kind"] == "switch" and e["side"] == "self" and not e["forced"]
        and e["turn"] == fork_turn and e["species"] == target_species
        and e["previous_species"] == "azumarill"
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
        "rl_stats": stats,
        "seen_divergences": divergences,
    }


def _compare_case(worker, case, own_continuation, snapshot):
    arm_skarmory = _audit_arm(worker, case, own_continuation, snapshot, "switch_skarmory")
    arm_quagsire = _audit_arm(worker, case, own_continuation, snapshot, "switch_quagsire")
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
        "switch_targets": {
            "switch_skarmory": skarmory["species"],
            "switch_quagsire": quagsire["species"],
        },
        "after_event_seq": 0,
        "switch_skarmory": arm_skarmory["summary"],
        "switch_quagsire": arm_quagsire["summary"],
        "rl_stats": {
            "switch_skarmory": arm_skarmory["rl_stats"],
            "switch_quagsire": arm_quagsire["rl_stats"],
        },
        "seen_divergences": {
            "switch_skarmory": arm_skarmory["seen_divergences"],
            "switch_quagsire": arm_quagsire["seen_divergences"],
        },
    }
    row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
    return row


def summarize_divergences(rows):
    """Aggregate seen-state action transitions and v2->v1 energy-band aliasing."""
    events = [
        {**ev, "arm": arm, "condition": row["condition"], "roster": row["roster"]}
        for row in rows
        for arm in ARMS
        for ev in row["seen_divergences"][arm]
    ]
    v2_to_v1 = defaultdict(set)
    v2_to_ebands = defaultdict(set)
    for ev in events:
        v2_to_v1[ev["v2_key"]].add(ev["v1_key"])
        v2_to_ebands[ev["v2_key"]].add(ev["energy_band_10"])

    energies = [ev["energy_points"] for ev in events]
    aliased_v2_keys = sum(len(bands) > 1 for bands in v2_to_ebands.values())
    aliased_events = sum(len(v2_to_ebands[ev["v2_key"]]) > 1 for ev in events)
    return {
        "total_seen_divergences": len(events),
        "by_arm": dict(Counter(ev["arm"] for ev in events)),
        "by_transition": dict(Counter(ev["transition"] for ev in events)),
        "by_species": dict(Counter(ev["species"] for ev in events)),
        "by_phase": dict(Counter(ev["phase"] for ev in events)),
        "energy_points": {
            "min": min(energies) if energies else None,
            "max": max(energies) if energies else None,
            "mean": sum(energies) / len(energies) if energies else None,
            "at_or_above_charge_55": sum(e >= 55 for e in energies),
            "at_max_100": sum(e == 100 for e in energies),
        },
        "v2_energy_aliasing": {
            "distinct_v2_keys": len(v2_to_v1),
            "distinct_v1_keys": len({v1 for s in v2_to_v1.values() for v1 in s}),
            "v2_keys_spanning_multiple_energy_bands": aliased_v2_keys,
            "divergences_in_aliased_v2_keys": aliased_events,
        },
    }


def summarize_audit(rows):
    """Build condition-level outcome separation and divergence breakdown."""
    by_cont = {}
    for cont in OWN_CONTINUATIONS:
        cont_rows = [r for r in rows if r["own_continuation"] == cont]
        if not cont_rows:
            continue
        overall = summarize_clock_group(cont_rows)
        overall["divergence_audit"] = summarize_divergences(cont_rows)
        decisions = sum(r["rl_stats"][arm]["post_fork_nontrivial_decisions"] for r in cont_rows for arm in ARMS)
        hits = sum(r["rl_stats"][arm]["learned_state_hits"] for r in cont_rows for arm in ARMS)
        unseen_div = sum(r["rl_stats"][arm]["diverged_on_unseen_states"] for r in cont_rows for arm in ARMS)
        overall["rl_coverage"] = {
            "post_fork_nontrivial_decisions": decisions,
            "learned_state_hits": hits,
            "learned_hit_rate": hits / decisions if decisions else None,
            "diverged_on_unseen_states": unseen_div,
        }
        by_condition = {}
        for cond, hp_pct, own_sh in CONDITIONS:
            selected = [r for r in cont_rows if r["condition"] == cond]
            cond_summary = summarize_clock_group(selected)
            cond_summary["hp_percent"] = hp_pct
            cond_summary["own_shields"] = own_sh
            cond_summary["divergence_audit"] = summarize_divergences(selected)
            c_dec = sum(r["rl_stats"][arm]["post_fork_nontrivial_decisions"] for r in selected for arm in ARMS)
            c_hits = sum(r["rl_stats"][arm]["learned_state_hits"] for r in selected for arm in ARMS)
            cond_summary["rl_coverage"] = {
                "post_fork_nontrivial_decisions": c_dec,
                "learned_state_hits": c_hits,
                "learned_hit_rate": c_hits / c_dec if c_dec else None,
            }
            by_condition[cond] = cond_summary
        by_cont[cont] = {"overall": overall, "by_condition": by_condition}
    return by_cont


def evaluate_rl_switch_audit(
    *,
    windows=WINDOWS,
    own_continuations=OWN_CONTINUATIONS,
    train_episodes=TRAIN_EPISODES,
):
    """Run 2600012+ audit comparing CPU vs frozen targeted RL continuations."""
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
    needs_rl = "rl_targeted_cpu_fallback" in own_continuations
    snapshot = None
    training_summary = None
    before_wire = None
    snapshot_unchanged = None

    with TemporaryDirectory(prefix="quagsire-rl-audit-") as temp:
        gm_path = Path(temp) / "strategy_gamemaster_shadow.json"
        gm_path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", gm_path, timeout=15.0) as worker:
            if needs_rl:
                snapshot, training_summary = train_targeted_switch_policy(
                    worker, seed=TARGETED_TRAIN_SEED, episodes=train_episodes
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
            raise RuntimeError("Frozen RL snapshot mutated after audit")

    return {
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "remaining_seconds": REMAINING_SECONDS,
        "study": "synthetic_150s_targeted_rl_divergence_audit",
        "ruleset_distinction": ruleset_distinction,
        "windows": list(windows),
        "own_continuations": list(own_continuations),
        "training": training_summary,
        "policy_snapshot_unchanged": snapshot_unchanged,
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "summary": summarize_audit(rows),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both 2600012+ windows")
    parser.add_argument("--own-continuation", choices=OWN_CONTINUATIONS)
    parser.add_argument("--train-episodes", type=int, default=TRAIN_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.train_episodes <= 120:
        parser.error("Require 0 <= --train-episodes <= 120")
    result = evaluate_rl_switch_audit(
        windows=WINDOWS if args.window is None else (args.window,),
        own_continuations=OWN_CONTINUATIONS if args.own_continuation is None else (args.own_continuation,),
        train_episodes=args.train_episodes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
