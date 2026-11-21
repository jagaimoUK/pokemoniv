"""Pure, explicit approximations for Pokémon GO show-six/pick-three.

Ratings are PvPoke Battle Ratings (0..1000), NOT probabilities. Unknown cells
must never be treated as losses. No ChatGPT-connected PvPoke tool is used.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations, permutations, product
import hashlib
import json
import math

STANDARD = (2, 2)
ALL_SHIELDS = tuple(product(range(3), repeat=2))
ALLOCATIONS = tuple(x for x in product(range(3), repeat=3) if sum(x) <= 2)
EVALUATION_VERSION = "party-static-v1"


def unverified_mechanic_reason(species_id):
    """Return explicit reason when a species' core battle mechanic is unverified/unsupported."""
    sid = str(species_id or "").strip().lower()
    if sid == "minior" or sid.startswith("minior_"):
        return "メテノのリミットシールド/対面別最良戦略は現行エンジン未対応のためunknown（勝敗未断定）として扱います"
    return None


def provisional_mechanic_reason(species_id):
    """Return explicit notice when a species is simulated with a provisional engine mechanic."""
    sid = str(species_id or "").strip().lower()
    if sid == "mimikyu" or sid.startswith("mimikyu_"):
        return "ミミッキュの「ばけのかわ」はPvPoke仮仕様（最初のゲージ技をダメージ1で防ぐ）で計算しています"
    return None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def combatant_id(p):
    return digest({k: p.get(k) for k in ("species", "fast", "charged1", "charged2",
                   "atk", "def", "hp", "level", "cp", "state")})[:24]


def weight_rows(opponents, importance=None):
    """Deduplicate exact hypotheses; give each species group a fixed total weight."""
    importance = importance or {}
    groups = defaultdict(dict)
    for entry in opponents:
        gid = entry.get("meta_group_id") or entry["species"]
        groups[gid][entry["id"]] = entry
    if not groups:
        raise ValueError("対戦相手が空です")
    gweights = {}
    for gid in groups:
        value = importance.get(gid, 1)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("メタ重要度は0以上の有限数です")
        gweights[gid] = value
    total = sum(gweights.values())
    if total <= 0:
        raise ValueError("メタ重要度がすべて0です")
    return {entry_id: gweights[gid] / total / len(items)
            for gid, items in groups.items() for entry_id in items}


def strength(rating, margin=50):
    return max(0.0, min(1.0, (rating - 500) / margin)) if rating is not None else None


def lookup(matrix, own, enemy, shields=STANDARD):
    return matrix.get((own, enemy, tuple(shields)))


def team_summary(team, opponents, matrix, weights, shields=STANDARD):
    """Return D0, D1 and severity with separately accounted unknown weight."""
    d0 = d1 = severity = unknown = coverage = 0.0
    missing = []
    critical = []
    for enemy in opponents:
        w = weights.get(enemy, 0)
        vals = [lookup(matrix, own, enemy, shields) for own in team]
        if any(x is None for x in vals):
            unknown += w
            missing.append(enemy)
            continue
        winners = sum(x > 500 for x in vals)
        best = max(vals)
        coverage += w * max(strength(x) for x in vals)
        if winners == 0:
            d0 += w
            severity += w * max(0, (500 - best) / 500)
            critical.append({"opponent": enemy, "best_rating": best, "weight": w})
        elif winners == 1:
            d1 += w
    critical.sort(key=lambda x: (-x["weight"], x["best_rating"]))
    return {"d0": round(d0, 6), "d1": round(d1, 6),
            "severity0": round(severity, 6), "coverage": round(coverage, 6),
            "unknown_weight": round(unknown, 6), "missing": missing,
            "critical": critical[:15], "complete": unknown < 1e-10}


def pair_summary(a, b, opponents, matrix, weights, shields=STANDARD):
    rescue_ab = rescue_ba = cover = hole = unknown = 0.0
    breakers = []
    for enemy in opponents:
        w = weights.get(enemy, 0)
        ra, rb = lookup(matrix, a, enemy, shields), lookup(matrix, b, enemy, shields)
        if ra is None or rb is None:
            unknown += w
            continue
        sa, sb = strength(ra), strength(rb)
        rescue_ab += w * (1 - sa) * sb
        rescue_ba += w * (1 - sb) * sa
        cover += w * max(sa, sb)
        hole += w * (1 - sa) * (1 - sb)
        if max(ra, rb) <= 500:
            breakers.append({"opponent": enemy,
                "severity": round(w * (0.5 + 0.5 * max(0, (500 - max(ra, rb)) / 500)), 6),
                "draw_only": max(ra, rb) == 500})
    breakers.sort(key=lambda x: -x["severity"])
    return {"members": [a, b], "balance": round(math.sqrt(rescue_ab * rescue_ba), 6),
            "rescue_a_to_b": round(rescue_ab, 6), "rescue_b_to_a": round(rescue_ba, 6),
            "coverage": round(cover, 6), "hole": round(hole, 6),
            "unknown_weight": round(unknown, 6), "core_breakers": breakers[:8],
            "pressure": None, "absorb": None, "detail_status": "未計算"}


def max_matching(own, opponent, matrix, shield=STANDARD):
    """Small exact bipartite maximum matching; distinct answers are required."""
    edges = {x: [y for y in own if (r := lookup(matrix, y, x, shield)) is not None and r > 500]
             for x in opponent}
    def walk(i, taken):
        if i == len(opponent):
            return 0
        x = opponent[i]
        return max([walk(i + 1, taken)] +
                   [1 + walk(i + 1, taken | {y}) for y in edges[x] if y not in taken])
    return walk(0, frozenset())


def legal_triples(roster, *, clause=None):
    for group in combinations(roster, 3):
        if clause and len({clause[x] for x in group}) != 3:
            continue
        yield group


def role_orders(roster, *, clause=None):
    for triple in legal_triples(roster, clause=clause):
        for lead in triple:
            yield (lead, *(x for x in triple if x != lead))


def assignment_report(own, enemy, matrix):
    missing = [(a, b) for a in own for b in enemy if lookup(matrix, a, b) is None]
    if missing:
        return {"status": "未計算", "missing_cells": len(missing)}
    matching = max_matching(own, enemy, matrix)
    return {"status": "計算済み", "matching": matching,
            "deficit": round((len(enemy) - matching) / len(enemy), 6)}


def utility(ours, theirs, matrix, a, b, swap=False):
    mapping = (0, 2, 1) if swap else (0, 1, 2)
    cells = [lookup(matrix, ours[i], theirs[mapping[i]], (a[i], b[mapping[i]]))
             for i in range(3)]
    if any(v is None for v in cells):
        return None
    return sum((v - 500) / 500 for v in cells) / 3


def static_bounds(ours, theirs, matrix):
    """max own allocation; min opponent allocation; min/max backline matching.

    This is a static robustness diagnostic, not a 3v3 win probability.
    """
    low, high = -math.inf, -math.inf
    for a in ALLOCATIONS:
        lower_b, higher_b = math.inf, math.inf
        for b in ALLOCATIONS:
            x = utility(ours, theirs, matrix, a, b)
            y = utility(ours, theirs, matrix, a, b, swap=True)
            if x is None or y is None:
                return None
            lower_b = min(lower_b, x, y)
            higher_b = min(higher_b, max(x, y))
        low = max(low, lower_b)
        high = max(high, higher_b)
    return (round(low, 6), round(high, 6))


def choose_three(ours, enemies, matrix, *, max_enemies=60):
    own_orders = list(role_orders(ours))
    enemy_orders = list(role_orders(enemies))
    if not own_orders or not enemy_orders:
        raise ValueError("合法な3体選出がありません")
    if len(enemy_orders) > max_enemies:
        raise ValueError("相手の選出が多すぎます")
    rows = []
    for order in own_orders:
        comparisons = []
        for opposing in enemy_orders:
            bounds = static_bounds(order, opposing, matrix)
            if bounds is None:
                return {"status": "未計算", "required_shields": len(ALL_SHIELDS),
                        "missing_condition": "相手6体の全9シールド条件が必要です"}
            comparisons.append((opposing, bounds))
        worst = min(x[1][0] for x in comparisons)
        rows.append({"selection": list(order), "worst": worst,
                     "optimistic_matching_worst": min(x[1][1] for x in comparisons),
                     "worst_opponent": list(min(comparisons, key=lambda x: x[1][0])[0]),
                     "comparisons": {"/".join(key): value[0] for key, value in comparisons}})
    rows.sort(key=lambda row: (-row["worst"], -row["optimistic_matching_worst"],
                               row["selection"]))
    chosen = [rows[0]]
    first = chosen[0]
    others = [r for r in rows[1:] if tuple(sorted(r["selection"])) != tuple(sorted(first["selection"]))]
    if others:
        target = "/".join(first["worst_opponent"])
        chosen.append(max(others, key=lambda r: (
            r["comparisons"][target] - first["comparisons"][target],
            r["worst"])))
    others = [r for r in rows[1:] if r not in chosen and r["selection"][0] != first["selection"][0]]
    if others:
        chosen.append(max(others, key=lambda r: r["worst"]))
    for row in chosen:
        row.pop("comparisons")
    return {"status": "計算済み", "model": EVALUATION_VERSION,
            "own_variants": len(own_orders), "opponent_variants": len(enemy_orders),
            "interpretation": "共有シールド2枚を使った静的な比較値（勝率ではない）",
            "recommendations": chosen}


def dangerous_pairs(triples, opponents, matrix, weights, clauses, *, top=20, limit=10):
    """Potential answer concentration and counter-switch traps, not certain defeats.

    Pair importance sqrt(w_x*w_y) is a search priority, NOT occurrence frequency.
    Exclude same-species move hypotheses from simultaneous opposing selections.
    """
    shortlist = sorted(opponents, key=lambda x: -weights.get(x, 0))[:top]
    scored = []
    for own in triples[:3]:
        for x, y in combinations(shortlist, 2):
            if clauses[x] == clauses[y]:
                continue
            if any(lookup(matrix, p, q) is None for p in own for q in (x, y)):
                continue
            deficit = (2 - max_matching(own, (x, y), matrix)) / 2
            trap = 0.0
            for main, counter in ((x, y), (y, x)):
                responses = [p for p in own if lookup(matrix, p, main) > 500]
                for answer in responses:
                    if all(lookup(matrix, p, main) <= 500 for p in own if p != answer):
                        trap = max(trap, (1 - strength(lookup(matrix, answer, counter))) *
                                   min(1 - strength(lookup(matrix, p, main))
                                       for p in own if p != answer))
            if deficit == 0 and trap <= 0:
                continue
            priority = math.sqrt(weights.get(x, 0) * weights.get(y, 0)) * (deficit + .5 * trap)
            scored.append({"own": list(own), "opponents": [x, y],
                           "assignment_deficit": deficit, "trap_risk": round(trap, 5),
                           "priority": round(priority, 6)})
    scored.sort(key=lambda x: -x["priority"])
    return scored[:limit]



def recommend_single_swaps(roster, candidates, opponents, matrix, weights, clause,
                           locked_slots=(), limit=5):
    """Compare legal one-slot changes against the same complete 2-2 matrix.

    Priority is lexicographic D0, severity, D1, coverage, not win probability.
    Never recommend incomplete matrix rows or changing locked slots.
    """
    before = team_summary(roster, opponents, matrix, weights)
    if not before["complete"]:
        return {"status": "unknown", "baseline": before, "items": []}
    baseline_rank = rank_partial(roster, opponents, matrix, weights)
    locked = set(locked_slots)
    improvements = []
    for slot, old in enumerate(roster):
        if slot in locked:
            continue
        other_clauses = {clause[x] for i, x in enumerate(roster) if i != slot}
        for new in candidates:
            if new == old or clause[new] in other_clauses:
                continue
            proposed = list(roster)
            proposed[slot] = new
            after = team_summary(proposed, opponents, matrix, weights)
            if not after["complete"]:
                continue
            ranking = rank_partial(proposed, opponents, matrix, weights)
            if ranking >= baseline_rank:
                continue
            old_holes = {x["opponent"] for x in before["critical"]}
            new_holes = {x["opponent"] for x in after["critical"]}
            improvements.append((ranking, slot, new, {
                "slot": slot, "out": old, "in": new, "after": after,
                "resolved": sorted(old_holes - new_holes)[:3],
                "new_holes": sorted(new_holes - old_holes)[:3],
            }))
    improvements.sort(key=lambda x: (x[0], x[1], x[2]))
    return {"status": "improved" if improvements else "no_improvement",
            "baseline": before, "items": [x[3] for x in improvements[:limit]]}



def iterative_party_optimization(roster, candidates, opponents, matrix, weights,
                                 clauses, locked_slots=(), max_steps=10,
                                 beam_width=8, max_finalists=3):
    """Bounded monotone local search of real six-member rosters.

    Every transition strictly improves rank_partial on the SAME 2-2 matrix.
    This is a local search, not a guarantee of perfect coverage or global optimum.
    The initial slot order and locked slots are preserved throughout.
    """
    if len(roster) != 6 or len(set(roster)) != 6:
        raise ValueError("自分の6体が必要です")
    if not 1 <= max_steps <= 10 or not 1 <= beam_width <= 16 or not 1 <= max_finalists <= 3:
        raise ValueError("自動補完の探索上限が不正です")
    if any(x not in clauses for x in (*roster, *candidates)):
        raise ValueError("候補の種族制限情報がありません")
    if len({clauses[x] for x in roster}) != 6:
        raise ValueError("自分の6体に同種重複があります")
    locked = set(locked_slots)
    if any(type(x) is not int or not 0 <= x < 6 for x in locked_slots):
        raise ValueError("固定枠が不正です")

    # Include departed members as replacement choices for later steps.
    choices = list(dict.fromkeys((*roster, *candidates)))
    score_cache = {}
    def score(ordered):
        key = tuple(sorted(ordered))
        if key not in score_cache:
            summary = team_summary(ordered, opponents, matrix, weights)
            if not summary["complete"]:
                score_cache[key] = None
            else:
                rank = (summary["unknown_weight"], summary["d0"],
                        summary["severity0"], summary["d1"], -summary["coverage"])
                score_cache[key] = rank, summary
        return score_cache[key]

    baseline = score(tuple(roster))
    if baseline is None:
        return {"status": "unknown", "baseline": team_summary(roster, opponents, matrix, weights),
                "finalists": [], "explored": len(score_cache),
                "max_steps": max_steps, "beam_width": beam_width}

    first = {"roster": tuple(roster), "steps": (), "score": baseline[0],
             "summary": baseline[1], "stop": "searching"}
    frontier = [first]
    ended = {}
    visited = {tuple(sorted(roster))}
    for depth in range(max_steps):
        new = {}
        for state in frontier:
            current = state["roster"]
            current_rank = state["score"]
            has_improvement = False
            for slot, old in enumerate(current):
                if slot in locked:
                    continue
                blocked = {clauses[x] for j, x in enumerate(current) if j != slot}
                for candidate in choices:
                    if candidate == old or clauses[candidate] in blocked:
                        continue
                    trial = list(current)
                    trial[slot] = candidate
                    key = tuple(sorted(trial))
                    assessed = score(tuple(trial))
                    if assessed is None or assessed[0] >= current_rank:
                        continue
                    has_improvement = True
                    if key in visited:
                        continue
                    step = {"slot": slot, "out": old, "in": candidate}
                    state_new = {"roster": tuple(trial),
                                 "steps": (*state["steps"], step),
                                 "score": assessed[0], "summary": assessed[1],
                                 "stop": "searching"}
                    existing = new.get(key)
                    if existing is None or (state_new["score"], len(state_new["steps"]),
                                            state_new["roster"]) < (
                                            existing["score"], len(existing["steps"]),
                                            existing["roster"]):
                        new[key] = state_new
            if not has_improvement:
                ended[tuple(sorted(current))] = {
                    **state, "stop": "no_further_improvement"}
        if not new:
            break
        # Keep promising alternative paths rather than a single greedy chain.
        frontier = sorted(new.values(),
                          key=lambda s: (s["score"], len(s["steps"]), s["roster"]))[:beam_width]
        visited.update(tuple(sorted(state["roster"])) for state in frontier)
    else:
        for state in frontier:
            ended[tuple(sorted(state["roster"]))] = {**state, "stop": "step_limit"}

    # A beam may have parked some paths that do not have any improving successor.
    # The finalists here are local search endpoints, or a declared step limit.
    results = sorted(ended.values(),
                     key=lambda s: (s["score"], len(s["steps"]), s["roster"]))
    finalists = []
    for state in results[:max_finalists]:
        before, explained = list(roster), []
        for step in state["steps"]:
            after = list(before)
            after[step["slot"]] = step["in"]
            explained.append({**step, "reason": explain_party_swap(
                before, after, step["out"], step["in"], opponents, matrix, weights)})
            before = after
        finalists.append({"roster": list(state["roster"]),
                          "steps": explained,
                          "summary": state["summary"],
                          "stop": state["stop"]})
    return {"status": "improved" if finalists and finalists[0]["steps"] else "no_improvement",
            "baseline": baseline[1], "finalists": finalists,
            "explored": len(score_cache), "max_steps": max_steps,
            "beam_width": beam_width, "scope": "候補範囲内の反復的な局所探索。全体最適・完全補完・3対3勝率は保証しません"}


def explain_party_swap(before, after, old, new, opponents, matrix, weights, limit=5):
    """Consequences of one actual search step, using the fixed 2-2 search basis."""
    benefits, costs = [], []
    for enemy in opponents:
        a = [lookup(matrix, own, enemy) for own in before]
        b = [lookup(matrix, own, enemy) for own in after]
        if any(v is None for v in a + b):
            continue
        na, nb = sum(v > 500 for v in a), sum(v > 500 for v in b)
        row = {"opponent": enemy, "weak_members": [own for own, v in zip(before, a) if v <= 500],
               "before_answers": na, "after_answers": nb,
               "before_best": max(a), "after_best": max(b),
               "out_rating": lookup(matrix, old, enemy), "in_rating": lookup(matrix, new, enemy),
               "weight": weights.get(enemy, 0)}
        if nb > na or max(b) > max(a):
            benefits.append(row)
        if nb < na or max(b) < max(a):
            costs.append(row)
    benefits.sort(key=lambda r: (r["before_answers"] != 0, -r["weight"],
                                r["before_answers"], -r["after_best"]))
    costs.sort(key=lambda r: (r["after_answers"] != 0, -r["weight"], r["after_answers"]))
    return {"shields": [2, 2], "before_roster": list(before), "after_roster": list(after),
            "benefits": benefits[:limit], "costs": costs[:limit],
            "benefit_count": len(benefits), "cost_count": len(costs)}


def party_matchup_heatmap(roster, opponents, matrix, shields=STANDARD):
    """Raw ratings in a declared shield condition; unknown stays null."""
    return [{"opponent": enemy,
             "ratings": [lookup(matrix, own, enemy, shields) for own in roster]}
            for enemy in opponents]


def rank_partial(roster, opponents, matrix, weights):
    result = team_summary(roster, opponents, matrix, weights)
    # Same-depth comparisons only. A missing cell cannot be assigned a loss.
    return (result["unknown_weight"], result["d0"], result["severity0"],
            result["d1"], -result["coverage"])


def beam_search(candidates, opponents, matrix, weights, *, locks=(),
                width=16, expansion=24):
    """Deterministic bounded beam with a one-slot local improvement pass."""
    candidates = list(dict.fromkeys(candidates))
    locks = list(dict.fromkeys(locks))
    if len(locks) > 6 or any(x not in candidates for x in locks):
        raise ValueError("固定枠が候補に存在しないか6体を超えています")
    if len(candidates) < 6:
        raise ValueError("構築候補が6体未満です")
    if not 1 <= width <= 32 or not 1 <= expansion <= 60:
        raise ValueError("探索幅が上限を超えています")
    beam = [tuple(sorted(locks))]
    for depth in range(len(locks), 6):
        pool = {}
        for partial in beam:
            remaining = (x for x in candidates if x not in partial)
            nexts = sorted(remaining, key=lambda x: rank_partial((*partial, x), opponents, matrix, weights))[:expansion]
            for x in nexts:
                next_roster = tuple(sorted((*partial, x)))
                pool[next_roster] = rank_partial(next_roster, opponents, matrix, weights)
        beam = sorted(pool, key=lambda x: (pool[x], x))[:width]
    if not beam:
        raise ValueError("合法な構築がありません")
    best = beam[0]
    for _ in range(2):
        ranked = [(rank_partial(best, opponents, matrix, weights), best)]
        for old in best:
            if old in locks:
                continue
            for new in candidates:
                if new in best:
                    continue
                trial = tuple(sorted((*[x for x in best if x != old], new)))
                ranked.append((rank_partial(trial, opponents, matrix, weights), trial))
        improved = min(ranked)
        if improved[1] == best:
            break
        best = improved[1]
    return {"roster": list(best), "summary": team_summary(best, opponents, matrix, weights),
            "beam_width": width, "expansion": expansion,
            "explored_candidates": len(candidates),
            "scope": "指定候補内の暫定構築。グローバル最適は保証しません"}


def _order_roster_preserving_locks(chosen_set, initial_slots, locked_slots):
    """Place locked members at their exact initial indices; fill remaining slots deterministically."""
    locked_map = {idx: initial_slots[idx] for idx in locked_slots if 0 <= idx < len(initial_slots)}
    locked_ids = set(locked_map.values())
    remaining = [x for x in chosen_set if x not in locked_ids]
    ordered = [None] * 6
    for idx, mid in locked_map.items():
        if idx < 6:
            ordered[idx] = mid
    # Keep surviving unlocked members in their original slot when convenient (display only, zero score bias).
    for idx in range(min(6, len(initial_slots))):
        if ordered[idx] is None and initial_slots[idx] in remaining:
            ordered[idx] = initial_slots[idx]
            remaining.remove(initial_slots[idx])
    for idx in range(6):
        if ordered[idx] is None:
            ordered[idx] = remaining.pop(0)
    return ordered


def autocomplete_search(locked_ids, candidate_ids, opponents, matrix, weights, clause, *,
                        initial_slots=(), locked_slots=(), beam_width=16,
                        expansion=24, max_finalists=3):
    """Unified 0..6-member auto-complete with zero penalty for replacing unlocked members.

    - 0 members -> proposes 6 new members.
    - 1..5 members -> keeps locked members unchanged, optimizes empty + unlocked slots.
    - 6 members (partial/none locked) -> freely replaces any number (1..6) of unlocked members.
    - 6 members (all locked) -> evaluates without changing any slot.
    """
    locked = list(dict.fromkeys(locked_ids))
    if len(locked) > 6:
        raise ValueError("固定枠は最大6体です")
    if len({clause[x] for x in locked}) != len(locked):
        raise ValueError("固定枠に同種重複があります")
    if not 1 <= beam_width <= 32 or not 1 <= expansion <= 60 or not 1 <= max_finalists <= 3:
        raise ValueError("自動補完の探索上限が不正です")

    locked_clauses = {clause[x] for x in locked}
    if len(locked) == 6:
        ordered = _order_roster_preserving_locks(locked, initial_slots, locked_slots) if initial_slots else list(locked)
        summary = team_summary(ordered, opponents, matrix, weights)
        return {
            "status": "all_locked",
            "roster": ordered,
            "baseline": summary,
            "finalists": [{
                "roster": ordered,
                "summary": summary,
                "replaced_count": 0,
                "steps": [],
                "stop": "all_locked",
            }],
            "explored": 1,
            "beam_width": beam_width,
            "candidate_count": len(locked),
            "scope": "6体すべて固定されているため入れ替えを行わず評価しました。",
        }

    candidates = []
    for cid in dict.fromkeys((*locked, *candidate_ids)):
        if cid in locked or clause[cid] not in locked_clauses:
            candidates.append(cid)
    if len({clause[x] for x in candidates}) < 6:
        raise ValueError("同種重複なしで6体を組める候補が不足しています")

    rank_cache = {}
    def rank_of(roster):
        key = tuple(sorted(roster))
        if key not in rank_cache:
            base_rank = rank_partial(key, opponents, matrix, weights)
            # Final tie-breaker after (unknown, d0, severity0, d1, -coverage):
            # prefer higher weighted average strength across members so saturated coverage
            # never picks deadweight slots alphabetically.
            known_vals = [
                weights.get(q, 0) * strength(lookup(matrix, m, q, STANDARD))
                for m in key for q in opponents
                if lookup(matrix, m, q, STANDARD) is not None
            ]
            avg_strength = round(sum(known_vals) / max(1, len(key)), 6)
            rank_cache[key] = (*base_rank, -avg_strength)
        return rank_cache[key]

    beam = [tuple(sorted(locked))]
    for _ in range(len(locked), 6):
        next_pool = {}
        for partial in beam:
            used_clauses = {clause[x] for x in partial}
            choices = [x for x in candidates if x not in partial and clause[x] not in used_clauses]
            choices.sort(key=lambda x: (rank_of((*partial, x)), x))
            for x in choices[:expansion]:
                nxt = tuple(sorted((*partial, x)))
                next_pool[nxt] = rank_of(nxt)
        beam = sorted(next_pool, key=lambda r: (next_pool[r], r))[:beam_width]
        if not beam:
            raise ValueError("同種重複なしで6体を組めません")

    # Polish top beam states with free multi-slot local swaps (zero stay penalty).
    polished = set(beam)
    for start in beam[:min(4, len(beam))]:
        cur = start
        for _ in range(3):
            best_rank = rank_of(cur)
            best_roster = cur
            for old in cur:
                if old in locked:
                    continue
                keep = [x for x in cur if x != old]
                used = {clause[x] for x in keep}
                for cand in candidates:
                    if cand == old or clause[cand] in used:
                        continue
                    trial = tuple(sorted((*keep, cand)))
                    r = rank_of(trial)
                    if (r, trial) < (best_rank, best_roster):
                        best_rank, best_roster = r, trial
            if best_roster == cur:
                break
            cur = best_roster
            polished.add(cur)

    # If starting from a valid 6-member roster, also include it for direct baseline comparison.
    baseline_summary = None
    initial_set = None
    if len(initial_slots) == 6 and len(set(initial_slots)) == 6 and len({clause[x] for x in initial_slots}) == 6:
        baseline_summary = team_summary(initial_slots, opponents, matrix, weights)
        initial_set = tuple(sorted(initial_slots))
        polished.add(initial_set)

    ranked_finalists = sorted(polished, key=lambda r: (rank_of(r), r))[:max_finalists]
    finalists = []
    for chosen in ranked_finalists:
        ordered = _order_roster_preserving_locks(chosen, initial_slots, locked_slots) if initial_slots else list(chosen)
        summary = team_summary(ordered, opponents, matrix, weights)
        steps = []
        if len(initial_slots) == 6:
            before = list(initial_slots)
            for idx in range(6):
                if before[idx] != ordered[idx]:
                    after = list(before)
                    after[idx] = ordered[idx]
                    steps.append({
                        "slot": idx,
                        "out": before[idx],
                        "in": ordered[idx],
                        "reason": explain_party_swap(before, after, before[idx], ordered[idx],
                                                     opponents, matrix, weights),
                    })
                    before = after
            replaced_count = sum(1 for a, b in zip(initial_slots, ordered) if a != b)
        else:
            initial_present = set(initial_slots)
            replaced_count = sum(1 for x in ordered if x not in initial_present)
        finalists.append({
            "roster": ordered,
            "summary": summary,
            "replaced_count": replaced_count,
            "steps": steps,
            "stop": "beam_optimized",
        })

    status = "proposed"
    if initial_set is not None:
        status = "improved" if tuple(sorted(finalists[0]["roster"])) != initial_set else "no_improvement"
    return {
        "status": status,
        "roster": finalists[0]["roster"],
        "baseline": baseline_summary or finalists[0]["summary"],
        "finalists": finalists,
        "explored": len(rank_cache),
        "beam_width": beam_width,
        "candidate_count": len(candidates),
        "scope": "候補範囲内のビーム探索＋局所改善（現在構築の維持ペナルティなし）。全探索・実戦3対3勝率は保証しません",
    }


def evaluate_all_triples(roster, opponents, matrix, weights, *, clause=None, enemy=None):
    """Evaluate all legal 3-member selections (up to 20) with roles and avoid explanations.

    Static 1v1-based approximations only; explicitly distinguishes unknown cells from losses.
    """
    triples = list(legal_triples(roster, clause=clause))
    enemy_orders = list(role_orders(enemy)) if enemy and len(enemy) == 6 else []
    enemy_complete = bool(enemy_orders) and all(
        lookup(matrix, p, q, s) is not None
        for p in roster for q in enemy for s in ALL_SHIELDS
    )
    meta_clauses = {}
    items = []
    for group in triples:
        summary = team_summary(group, opponents, matrix, weights)
        # Role assignment within the 3: lead (2-2 & 1-1 resilience), safe switch (0-1 & 1-2 breadth), closer.
        def lead_score(pid):
            s22 = sum(weights.get(q, 0) * (strength(lookup(matrix, pid, q, (2, 2))) or 0.0) for q in opponents)
            s11 = sum(weights.get(q, 0) * (strength(lookup(matrix, pid, q, (1, 1))) or 0.0) for q in opponents)
            return round(0.6 * s22 + 0.4 * s11, 6)

        def safe_score(pid):
            s01 = sum(weights.get(q, 0) * (strength(lookup(matrix, pid, q, (0, 1))) or 0.0) for q in opponents)
            s12 = sum(weights.get(q, 0) * (strength(lookup(matrix, pid, q, (1, 2))) or 0.0) for q in opponents)
            return round(0.5 * s01 + 0.5 * s12, 6)

        best_lead = max(group, key=lambda pid: (lead_score(pid), pid))
        rem = [pid for pid in group if pid != best_lead]
        best_safe = max(rem, key=lambda pid: (safe_score(pid), pid))
        best_closer = next(pid for pid in rem if pid != best_safe)

        vs_enemy = None
        if enemy_complete:
            # Choose the strongest role order for this triple against opponent's 6.
            best_order = None
            for lead_candidate in group:
                order = (lead_candidate, *(x for x in group if x != lead_candidate))
                comps = [(opp, static_bounds(order, opp, matrix)) for opp in enemy_orders]
                worst_pair = min(comps, key=lambda x: x[1][0])
                entry = (worst_pair[1][0], min(x[1][1] for x in comps), order, list(worst_pair[0]))
                if best_order is None or entry[:2] > best_order[:2]:
                    best_order = entry
            best_lead = best_order[2][0]
            rem = [pid for pid in group if pid != best_lead]
            best_safe = max(rem, key=lambda pid: (safe_score(pid), pid))
            best_closer = next(pid for pid in rem if pid != best_safe)
            vs_enemy = {
                "worst": best_order[0],
                "optimistic_worst": best_order[1],
                "worst_opponent_triple": best_order[3],
            }

        favorable = []
        for q in sorted(opponents, key=lambda x: -weights.get(x, 0)):
            vals = [lookup(matrix, pid, q, STANDARD) for pid in group]
            if any(v is None for v in vals):
                continue
            if sum(v > 500 for v in vals) >= 2 or max(vals) >= 580:
                favorable.append({"opponent": q, "best_rating": max(vals), "answers": sum(v > 500 for v in vals)})
            if len(favorable) >= 4:
                break

        avoid_reasons = []
        if summary["critical"]:
            avoid_reasons.append({
                "kind": "uncovered_meta",
                "opponents": [c["opponent"] for c in summary["critical"][:3]],
                "detail": f"未対応の重要相手あり（D0 {summary['d0']*100:.1f}%）",
            })
        if summary["d1"] >= 0.35:
            avoid_reasons.append({
                "kind": "single_answer_fragility",
                "detail": f"担当1体のみ依存が広い（D1 {summary['d1']*100:.1f}%：釣り出し・出し負けに弱い）",
            })
        if summary["unknown_weight"] > 0:
            avoid_reasons.append({
                "kind": "unverified_mechanics",
                "detail": f"未検証/unknown対面を含む（重み {summary['unknown_weight']*100:.1f}%：勝敗未断定）",
            })
        if vs_enemy is not None and vs_enemy["worst"] < 0:
            avoid_reasons.append({
                "kind": "enemy_counter_line",
                "opponents": vs_enemy["worst_opponent_triple"],
                "detail": f"相手の合理的対策選出に対し不利見込み（最悪比較値 {vs_enemy['worst']:.3f}）",
            })
        if not avoid_reasons:
            avoid_reasons.append({
                "kind": "general_caveat",
                "detail": "大きな静的穴は小さいが、交代読み・エネルギー管理・実戦3対3勝率は別途確認が必要",
            })

        sort_key = (
            -(vs_enemy["worst"]) if vs_enemy is not None else 0.0,
            summary["unknown_weight"],
            summary["d0"],
            summary["severity0"],
            summary["d1"],
            -summary["coverage"],
            tuple(group),
        )
        items.append({
            "members": list(group),
            "roles": {"lead": best_lead, "safe_switch": best_safe, "closer": best_closer},
            "summary": summary,
            "vs_enemy": vs_enemy,
            "favorable": favorable,
            "avoid_reasons": avoid_reasons,
            "_sort": sort_key,
        })

    items.sort(key=lambda x: x["_sort"])
    total = len(items)
    for rank, item in enumerate(items, start=1):
        item.pop("_sort", None)
        item["rank"] = rank
        item["unfavorable"] = rank > max(3, total // 2) or item["summary"]["d0"] > 0.15 or (
            item["vs_enemy"] is not None and item["vs_enemy"]["worst"] < -0.1
        )
    return items


def compare_scenarios(roster, opponents, matrix, scenario_entries):
    """Compare one roster across multiple scenarios reusing the exact same matchup matrix.

    Returns per-scenario summaries, cross-scenario average, and worst-case risk summary.
    """
    if not scenario_entries:
        return None
    results = []
    for entry in scenario_entries:
        summary = team_summary(roster, opponents, matrix, entry["weights"])
        results.append({
            "id": entry["id"],
            "name": entry["name"],
            "revision": entry.get("revision"),
            "kind": entry.get("kind", "current"),
            "summary": summary,
        })
    n = len(results)
    avg = {
        "d0": round(sum(r["summary"]["d0"] for r in results) / n, 6),
        "d1": round(sum(r["summary"]["d1"] for r in results) / n, 6),
        "severity0": round(sum(r["summary"]["severity0"] for r in results) / n, 6),
        "coverage": round(sum(r["summary"]["coverage"] for r in results) / n, 6),
        "unknown_weight": round(sum(r["summary"]["unknown_weight"] for r in results) / n, 6),
    }
    worst = max(
        results,
        key=lambda r: (
            r["summary"]["d0"],
            r["summary"]["severity0"],
            r["summary"]["unknown_weight"],
            -r["summary"]["coverage"],
        ),
    )
    return {
        "count": n,
        "scenarios": results,
        "average": avg,
        "worst_case": {
            "scenario_id": worst["id"],
            "scenario_name": worst["name"],
            "summary": worst["summary"],
        },
        "note": "同一の計算済み対面キャッシュを再利用して複数シナリオを比較（平均と最悪ケースを併記）",
    }


def evolve_meta_phases(meta_rows, base_weights, matrix, *, shields=STANDARD, alpha=1.6, top_k=5):
    """Generically evolve any meta weight distribution across 3 time-series phases.

    Phase 1 (起点環境): Current meta weights (or user-adjusted importance distribution).
    Phase 2 (対策集中期): Upweights species with highest weighted win score vs Phase 1.
    Phase 3 (再適応期): Upweights species with highest weighted win score vs Phase 2
                        (counters to the counters), naturally decaying over-targeted picks.
    Unverified/missing matchups (rating is None) are never fabricated and stay neutral.
    """
    active = [row for row in meta_rows if base_weights.get(row["id"], 0) > 0]
    if not active:
        return None
    ids = [row["id"] for row in active]
    species_by_id = {row["id"]: row["species"] for row in active}

    def normalize(wmap):
        total = sum(max(0.0, float(wmap.get(mid, 0.0))) for mid in ids)
        if total <= 0:
            eq = 1.0 / len(ids)
            return {mid: eq for mid in ids}
        return {mid: max(0.0, float(wmap.get(mid, 0.0))) / total for mid in ids}

    w1 = normalize(base_weights)

    def step_phase(prev_w):
        fitness = {}
        reasons = {}
        for mid in ids:
            num = 0.0
            den = 0.0
            beat_contrib = []
            for opp in ids:
                if opp == mid:
                    continue
                ow = prev_w.get(opp, 0.0)
                if ow <= 0:
                    continue
                rating = lookup(matrix, mid, opp, shields)
                if rating is None:
                    continue
                # Map Battle Rating [250..750] to [-1.0..+1.0] around 500.
                score = max(-1.0, min(1.0, (rating - 500.0) / 250.0))
                num += ow * score
                den += ow
                if rating > 520:
                    beat_contrib.append((ow * score, opp, rating))
            fval = (num / den) if den > 1e-9 else 0.0
            fitness[mid] = fval
            beat_contrib.sort(key=lambda x: -x[0])
            reasons[mid] = [
                {"id": opp, "species": species_by_id[opp], "rating": round(rt, 1)}
                for _, opp, rt in beat_contrib[:3]
            ]

        raw_next = {}
        ratios = {}
        for mid in ids:
            # Bounded multiplicative update (discrete replicator step)
            exponent = max(-1.05, min(1.25, alpha * fitness[mid]))
            mult = math.exp(exponent)
            raw_next[mid] = prev_w[mid] * mult
        next_w = normalize(raw_next)
        for mid in ids:
            ratios[mid] = (next_w[mid] / prev_w[mid]) if prev_w[mid] > 1e-12 else 1.0

        rising = [
            {
                "id": mid,
                "species": species_by_id[mid],
                "prev_weight": round(prev_w[mid], 6),
                "next_weight": round(next_w[mid], 6),
                "ratio": round(ratios[mid], 3),
                "fitness": round(fitness[mid], 4),
                "beats": reasons[mid],
            }
            for mid in sorted(ids, key=lambda m: (-ratios[m], -next_w[m], species_by_id[m]))
            if ratios[mid] > 1.08
        ][:top_k]
        falling = [
            {
                "id": mid,
                "species": species_by_id[mid],
                "prev_weight": round(prev_w[mid], 6),
                "next_weight": round(next_w[mid], 6),
                "ratio": round(ratios[mid], 3),
                "fitness": round(fitness[mid], 4),
            }
            for mid in sorted(ids, key=lambda m: (ratios[m], -prev_w[m], species_by_id[m]))
            if ratios[mid] < 0.92
        ][:top_k]
        return next_w, rising, falling

    w2, p2_rising, p2_falling = step_phase(w1)
    w3, p3_rising, p3_falling = step_phase(w2)

    p1_focus = [
        {
            "id": mid,
            "species": species_by_id[mid],
            "weight": round(w1[mid], 6),
        }
        for mid in sorted(ids, key=lambda m: (-w1[m], species_by_id[m]))[:top_k]
    ]

    combined = normalize({mid: (w1[mid] + w2[mid] + w3[mid]) / 3.0 for mid in ids})
    phases = [
        {
            "id": "phase1_base",
            "stage": 1,
            "name": "Phase 1: 起点環境（現在/注目重み）",
            "short_name": "Phase 1（起点）",
            "kind": "phase1",
            "description": "元メタ（またはあなたが重要度を変更した環境）を起点とした基準フェーズ",
            "weights": w1,
            "focus": p1_focus,
            "rising": [],
            "falling": [],
        },
        {
            "id": "phase2_counters",
            "stage": 2,
            "name": "Phase 2: 対策集中期（カウンター台頭）",
            "short_name": "Phase 2（対策集中）",
            "kind": "phase2",
            "description": "Phase 1 の環境全体に有利対面を取りやすい対策枠が自動増加するフェーズ",
            "weights": w2,
            "focus": [],
            "rising": p2_rising,
            "falling": p2_falling,
        },
        {
            "id": "phase3_adaptation",
            "stage": 3,
            "name": "Phase 3: 再適応期（メタのメタ）",
            "short_name": "Phase 3（再適応）",
            "kind": "phase3",
            "description": "Phase 2 で増えた対策枠を狩るポケモンが台頭し、元の軸が対策されて落ち着くフェーズ",
            "weights": w3,
            "focus": [],
            "rising": p3_rising,
            "falling": p3_falling,
        },
    ]
    return {
        "phases": phases,
        "combined_weights": combined,
        "note": "対面マトリクスに基づく汎用3段階メタ遷移（Phase 1→2→3）を自動展開し、全段階の平均と最悪ケース耐性の両方で評価します。",
    }


def mimikyu_conservative_summary(roster, meta_rows, matrix, weights):
    """Compare standard PvPoke Disguise calculation vs conservative +1-shield equivalent.

    When Mimikyu appears in the meta (or enemy), evaluates roster resilience at:
    - standard (1-1 / 0-0 / 2-2)
    - conservative (+1 shield on Mimikyu side: 1-2 for 1-1, 0-1 for 0-0)
    """
    mim_targets = [
        r for r in meta_rows
        if (r["species"] == "mimikyu" or r["species"].startswith("mimikyu_"))
        and weights.get(r["id"], 0) > 0
    ]
    if not mim_targets:
        return None
    target = mim_targets[0]
    tid = target["id"]
    std_11 = max((lookup(matrix, own, tid, (1, 1)) for own in roster if lookup(matrix, own, tid, (1, 1)) is not None), default=None)
    con_12 = max((lookup(matrix, own, tid, (1, 2)) for own in roster if lookup(matrix, own, tid, (1, 2)) is not None), default=None)
    std_00 = max((lookup(matrix, own, tid, (0, 0)) for own in roster if lookup(matrix, own, tid, (0, 0)) is not None), default=None)
    con_01 = max((lookup(matrix, own, tid, (0, 1)) for own in roster if lookup(matrix, own, tid, (0, 1)) is not None), default=None)
    std_22 = max((lookup(matrix, own, tid, (2, 2)) for own in roster if lookup(matrix, own, tid, (2, 2)) is not None), default=None)

    opponents = [r["id"] for r in meta_rows]
    std_summary = team_summary(roster, opponents, matrix, weights, (1, 1))
    # Build conservative matrix where Mimikyu targets use +1 shield rating if worse
    con_matrix = dict(matrix)
    for own in roster:
        for t in mim_targets:
            r_11 = lookup(matrix, own, t["id"], (1, 1))
            r_12 = lookup(matrix, own, t["id"], (1, 2))
            if r_11 is not None and r_12 is not None:
                con_matrix[(own, t["id"], (1, 1))] = min(r_11, r_12)
    con_summary = team_summary(roster, opponents, con_matrix, weights, (1, 1))
    return {
        "target_id": tid,
        "target_species": target["species"],
        "standard_1_1_best": std_11,
        "conservative_1_2_best": con_12,
        "standard_0_0_best": std_00,
        "conservative_0_1_best": con_01,
        "standard_2_2_best": std_22,
        "standard_team_1_1": {"d0": std_summary["d0"], "coverage": std_summary["coverage"]},
        "conservative_team_1_1": {"d0": con_summary["d0"], "coverage": con_summary["coverage"]},
        "note": "通常計算（PvPoke標準 ばけのかわ仮仕様）に加え、相手ミミッキュ側のシールド+1枚相当（1-2 / 0-1）での保守的耐性を併記しています。",
    }


