"""Compare generic 6v3 pretraining vs targeted mid-battle HP/shield pretraining at 150s."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
from tempfile import TemporaryDirectory

from pvpoke_rl_mc_generalized import GeneralizedMonteCarloPolicy
from pvpoke_rl_step_client import NativeStepError
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
from tools.evaluate_rl_azumarill_switch_rl_150s import (
    ARM_ACTIONS, MAX_STEPS, WAIT_TURNS, _SwitchRlWorkerTransport,
    train_worlds_switch_policy,
)
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
WINDOWS = (2500012, 2501012)
GENERIC_TRAIN_SEED = 2500
TARGETED_TRAIN_SEED = 2600
TRAIN_EPISODES = 100
EVAL_POLICY_SEED = 2599
OWN_CONTINUATIONS = (
    "cpu",
    "rl_generic_cpu_fallback",
    "rl_targeted_cpu_fallback",
    "rl_targeted_priority",
)
CONTINUATION_SPECS = {
    "cpu": (None, None),
    "rl_generic_cpu_fallback": ("generic", CpuFallbackMonteCarloPolicy),
    "rl_targeted_cpu_fallback": ("targeted", CpuFallbackMonteCarloPolicy),
    "rl_targeted_priority": ("targeted", GuardedWaitMonteCarloPolicy),
}


def window_cases(window):
    """Build single-factor HP/shield batches at fixed 150s remaining clock."""
    if type(window) is not int or window not in WINDOWS:
        raise ValueError("Use a predeclared 150s targeted RL window")
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


def train_targeted_switch_policy(
    worker, *, seed=TARGETED_TRAIN_SEED, episodes=TRAIN_EPISODES
):
    """Train on Worlds-legal mid-battle HP/shield distributions over full 240s clock."""
    if type(episodes) is not int or not 0 <= episodes <= 120:
        raise ValueError("Training episode budget must be 0..120")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1000:
        raise ValueError("Invalid targeted training seed")
    own_base, _, enemy_base = fixture_teams()
    build_items = list(BUILDS.items())
    hp_levels = (20, 40, 60, 85)
    shield_levels = (0, 1, 2)
    other_enemy_slots = [idx for idx in range(len(enemy_base)) if idx != 2]
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

        if ep % 2 == 0:
            trio = tuple(sorted(rng.sample(range(6), 3)))
            lead = rng.choice(trio)
            opp_shields = (0, 1)[(ep // 2) % 2]
        else:
            trio = tuple(sorted((2, *rng.sample(other_enemy_slots, 2))))
            lead = 2
            opp_shields = 0

        public = [{key: row[key] for key in ("species", "roster_clause_id")} for row in enemy]
        preview = SixToThreeSelection(own, public, enemy, trio, lead, ruleset_id=RULESET_ID)
        selection = "0,2,4|2"
        kind, sel_key, legal_sel = policy.encode_state(preview.observe())
        if selection not in legal_sel:
            raise RuntimeError("Illegal predeclared targeted training selection")
        preview.choose(selection)
        handoff = preview._private_engine_input()
        decisions = [(kind, sel_key, selection)]

        hp_percent = hp_levels[ep % len(hp_levels)]
        own_shields = shield_levels[ep % len(shield_levels)]
        res = worker.reset(
            handoff,
            seed=ep_seed,
            shields=(own_shields, opp_shields),
            hp_percent=hp_percent,
            wait_turns=0,
        )
        for _ in range(MAX_STEPS):
            view = res["observation"]
            if view is None:
                break
            action, record = policy.choose(view, epsilon=0.30)
            decisions.append(record)
            res = worker.step(action)
        if res["observation"] is not None:
            raise NativeStepError("Targeted training episode exceeded step budget")
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
        "regime": "targeted_mid_battle_hp_shield",
    }


def _restore_frozen_policy(own_continuation, snapshots):
    regime, cls = CONTINUATION_SPECS[own_continuation]
    if regime is None:
        return None, None
    snap = snapshots.get(regime)
    if snap is None:
        raise ValueError(f"Frozen {regime} RL snapshot required")
    return cls.restore(snap, seed=EVAL_POLICY_SEED), snap


def _run_arm(worker, case, own_continuation, snapshots, arm):
    action_name, target_slot = ARM_ACTIONS[arm]
    policy, snapshot = _restore_frozen_policy(own_continuation, snapshots)
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
        "low_hp_shield_seen_states": 0,
        "low_hp_shield_seen_overrides_to_yes": 0,
        "low_hp_shield_unseen_overrides_to_yes": 0,
        "low_hp_shield_seen_kept_no": 0,
    }

    res = worker.step(action_name)
    for _ in range(MAX_STEPS):
        view = res["observation"]
        if view is None:
            break
        cpu_action = choose_team_cpu(view)
        is_seen = False
        if policy is None:
            action = cpu_action
        else:
            _, key, legal = policy.encode_state(view)
            action, _ = policy.choose(view, epsilon=0.0)
            is_seen = key in tactic_table
            if len(legal) > 1:
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
                if is_seen:
                    rl_stats["low_hp_shield_seen_states"] += 1
                if action == "shield_yes":
                    rl_stats["low_hp_shield_yes"] += 1
                    if is_seen:
                        rl_stats["low_hp_shield_seen_overrides_to_yes"] += 1
                    elif policy is not None:
                        rl_stats["low_hp_shield_unseen_overrides_to_yes"] += 1
                else:
                    rl_stats["low_hp_shield_no"] += 1
                    if is_seen:
                        rl_stats["low_hp_shield_seen_kept_no"] += 1
        res = worker.step(action)

    if res["observation"] is not None:
        raise RuntimeError("150s targeted RL switch episode exceeded step budget")
    if policy is not None and policy.snapshot() != snapshot:
        raise RuntimeError("Frozen RL policy mutated during evaluation")

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
        "rl_stats": rl_stats,
    }


def _compare_case(worker, case, own_continuation, snapshots):
    arm_skarmory = _run_arm(worker, case, own_continuation, snapshots, "switch_skarmory")
    arm_quagsire = _run_arm(worker, case, own_continuation, snapshots, "switch_quagsire")
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
    }
    row["traces"] = {arm: trace_arm(row, arm) for arm in ARMS}
    return row


def summarize_group(rows):
    """Summarize outcomes, censoring, seen/unseen low-HP shield overrides, and RL coverage."""
    report = summarize_clock_group(rows)
    keys = (
        "post_fork_nontrivial_decisions",
        "learned_state_hits",
        "diverged_on_seen_states",
        "diverged_on_unseen_states",
        "low_hp_shield_yes",
        "low_hp_shield_no",
        "low_hp_shield_seen_states",
        "low_hp_shield_seen_overrides_to_yes",
        "low_hp_shield_unseen_overrides_to_yes",
        "low_hp_shield_seen_kept_no",
    )
    totals = {key: sum(row["rl_stats"][arm][key] for row in rows for arm in ARMS) for key in keys}
    decisions = totals["post_fork_nontrivial_decisions"]
    hits = totals["learned_state_hits"]
    report["low_hp_shield_decisions"] = {
        "shield_yes": totals["low_hp_shield_yes"],
        "shield_no": totals["low_hp_shield_no"],
        "seen_states": totals["low_hp_shield_seen_states"],
        "seen_overrides_to_yes": totals["low_hp_shield_seen_overrides_to_yes"],
        "unseen_overrides_to_yes": totals["low_hp_shield_unseen_overrides_to_yes"],
        "seen_kept_no": totals["low_hp_shield_seen_kept_no"],
    }
    report["rl_diagnostics"] = {
        "post_fork_nontrivial_decisions": decisions,
        "learned_state_hits": hits,
        "learned_hit_rate": hits / decisions if decisions else None,
        "diverged_on_seen_states": totals["diverged_on_seen_states"],
        "diverged_on_unseen_states": totals["diverged_on_unseen_states"],
        "total_diverged_from_cpu": totals["diverged_on_seen_states"] + totals["diverged_on_unseen_states"],
    }
    return report


def _shift_slice(groups_by_cont, own_continuations):
    gen_hit = (
        groups_by_cont["rl_generic_cpu_fallback"]["rl_diagnostics"]["learned_hit_rate"]
        if "rl_generic_cpu_fallback" in groups_by_cont else None
    )
    tgt_hit = (
        groups_by_cont["rl_targeted_cpu_fallback"]["rl_diagnostics"]["learned_hit_rate"]
        if "rl_targeted_cpu_fallback" in groups_by_cont else None
    )
    return {
        "generic_hit_rate": gen_hit,
        "targeted_hit_rate": tgt_hit,
        "hit_rate_gain": tgt_hit - gen_hit if None not in (gen_hit, tgt_hit) else None,
        "seen_divergences": {
            cont: groups_by_cont[cont]["rl_diagnostics"]["diverged_on_seen_states"]
            for cont in own_continuations
        },
        "unseen_divergences": {
            cont: groups_by_cont[cont]["rl_diagnostics"]["diverged_on_unseen_states"]
            for cont in own_continuations
        },
        "low_hp_shield_seen_states": {
            cont: groups_by_cont[cont]["low_hp_shield_decisions"]["seen_states"]
            for cont in own_continuations
        },
        "low_hp_shield_seen_overrides_to_yes": {
            cont: groups_by_cont[cont]["low_hp_shield_decisions"]["seen_overrides_to_yes"]
            for cont in own_continuations
        },
        "low_hp_shield_yes": {
            cont: groups_by_cont[cont]["low_hp_shield_decisions"]["shield_yes"]
            for cont in own_continuations
        },
        "both_timeout": {
            cont: groups_by_cont[cont]["outcome_breakdown"]["both_timeout"]
            for cont in own_continuations
        },
        "both_ko_decided": {
            cont: groups_by_cont[cont]["outcome_breakdown"]["both_ko_decided"]
            for cont in own_continuations
        },
        "mean_reward_delta": {
            cont: groups_by_cont[cont]["ko_reward_comparison"]["mean_reward_delta"]
            for cont in own_continuations
        },
    }


def summarize_results(rows, own_continuations):
    """Group metrics by continuation, condition, roster, and generic-vs-targeted training shift."""
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

    overall_groups = {cont: by_continuation[cont]["overall"] for cont in own_continuations}
    condition_shift = {
        cond: _shift_slice(
            {cont: by_continuation[cont]["by_condition"][cond] for cont in own_continuations},
            own_continuations,
        )
        for cond, *_ in CONDITIONS
    }
    return {
        "by_continuation": by_continuation,
        "training_shift_comparison": {
            "overall": _shift_slice(overall_groups, own_continuations),
            "by_condition": condition_shift,
        },
    }


def evaluate_rl_switch_targeted(
    *,
    windows=WINDOWS,
    own_continuations=OWN_CONTINUATIONS,
    train_episodes=TRAIN_EPISODES,
):
    """Run matched 150s comparisons across CPU, generic RL, and targeted HP/shield RL."""
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
    needed_regimes = {
        CONTINUATION_SPECS[cont][0] for cont in own_continuations
        if CONTINUATION_SPECS[cont][0] is not None
    }
    snapshots = {}
    training_summaries = {}
    before_wires = {}

    with TemporaryDirectory(prefix="quagsire-rl-targeted-") as temp:
        gm_path = Path(temp) / "strategy_gamemaster_shadow.json"
        gm_path.write_text(json.dumps(shadow_gamemaster()), encoding="utf-8")
        with _SwitchRlWorkerTransport(ROOT / "vendor/pvpoke", gm_path, timeout=15.0) as worker:
            if "generic" in needed_regimes:
                snap_g, sum_g = train_worlds_switch_policy(
                    worker, seed=GENERIC_TRAIN_SEED, episodes=train_episodes
                )
                snapshots["generic"] = snap_g
                training_summaries["generic"] = sum_g
                before_wires["generic"] = json.dumps(snap_g, sort_keys=True)
            if "targeted" in needed_regimes:
                snap_t, sum_t = train_targeted_switch_policy(
                    worker, seed=TARGETED_TRAIN_SEED, episodes=train_episodes
                )
                snapshots["targeted"] = snap_t
                training_summaries["targeted"] = sum_t
                before_wires["targeted"] = json.dumps(snap_t, sort_keys=True)
            rows = [
                _compare_case(worker, case, cont, snapshots)
                for cont in own_continuations
                for case in cases
            ]

    snapshots_unchanged = {
        regime: wire == json.dumps(snapshots[regime], sort_keys=True)
        for regime, wire in before_wires.items()
    }
    if not all(snapshots_unchanged.values()):
        raise RuntimeError("Frozen RL snapshot mutated after evaluation")

    return {
        "ruleset_id": RULESET_ID,
        "battle_clock_ms": BATTLE_CLOCK_MS,
        "remaining_seconds": REMAINING_SECONDS,
        "study": "synthetic_150s_targeted_vs_generic_public_rl",
        "ruleset_distinction": ruleset_distinction,
        "windows": list(windows),
        "own_continuations": list(own_continuations),
        "training": training_summaries,
        "policy_snapshots_unchanged": snapshots_unchanged,
        "reward_difference": "ヌオーに交代 − エアームドに交代",
        "summary": summarize_results(rows, own_continuations),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=WINDOWS, help="Default runs both 2500012+ windows")
    parser.add_argument("--own-continuation", choices=OWN_CONTINUATIONS)
    parser.add_argument("--train-episodes", type=int, default=TRAIN_EPISODES)
    args = parser.parse_args()
    if not 0 <= args.train_episodes <= 120:
        parser.error("Require 0 <= --train-episodes <= 120")
    result = evaluate_rl_switch_targeted(
        windows=WINDOWS if args.window is None else (args.window,),
        own_continuations=OWN_CONTINUATIONS if args.own_continuation is None else (args.own_continuation,),
        train_episodes=args.train_episodes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
