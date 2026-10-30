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


def pair_summary(a, b, opponents, matrix, weights):
    rescue_ab = rescue_ba = cover = hole = unknown = 0.0
    breakers = []
    for enemy in opponents:
        w = weights.get(enemy, 0)
        ra, rb = lookup(matrix, a, enemy), lookup(matrix, b, enemy)
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
