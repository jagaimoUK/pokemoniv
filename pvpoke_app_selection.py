"""Deterministic, versioned recommendations from complete saved battle matrices.

No GPT calls. Grades are this project's rule-based candidates, not PvPoke grades.
Unresolved non-dominated candidates remain visible for human/GPT review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from zipfile import ZipFile

from pvpoke_selection_matrix import MODES, SHIELDS, SelectionMatrix, load_selection_matrix
from pvpoke_app_sizes import pumpkin_search


@dataclass(frozen=True)
class SelectionPolicy:
    version: str = "roles-v1"
    meaningful_win_lead: float = 20


def validate_policy(value: dict | None) -> SelectionPolicy:
    if value is None:
        return SelectionPolicy()
    if not isinstance(value, dict) or set(value) - {"meaningful_win_lead"}:
        raise ValueError("policy accepts only meaningful_win_lead")
    threshold = value.get("meaningful_win_lead", 20)
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 1 <= threshold <= 1000):
        raise ValueError("meaningful_win_lead must be 1..1000")
    return SelectionPolicy(meaningful_win_lead=threshold)


def validate_focus(focus: list[str] | None) -> list[str]:
    if focus is None:
        return []
    if (not isinstance(focus, list) or len(focus) > 15
            or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in focus)):
        raise ValueError("focus_opponents must have up to 15 nonempty names")
    return [x.strip() for x in focus]


def search_string(name: str, iv: str, shadow: bool = False, species_id: str | None = None) -> str:
    values = [int(x) for x in iv.split("/")]
    if len(values) != 3 or any(not 0 <= x <= 15 for x in values):
        raise ValueError("Invalid candidate IV")
    if not name or any(x in name for x in "&\r\n"):
        raise ValueError("A valid English species name is required")
    form_search = pumpkin_search(species_id)
    if form_search:
        name, size_filter = form_search
    else:
        size_filter = ""
    def bucket(x):
        return 0 if x == 0 else 1 if x <= 5 else 2 if x <= 10 else 3 if x < 15 else 4
    return name + "".join(f"&{bucket(x)}{label}" for x, label in zip(values, ("attack", "defense", "hp"))) + size_filter + ("&shadow" if shadow else "")


def recommend(matrices: dict[str, SelectionMatrix], candidate: dict,
              english_name: str, focus_opponents: list[str] | None = None,
              policy: dict | None = None) -> dict:
    rules, focus = validate_policy(policy), validate_focus(focus_opponents)
    if set(matrices) not in ({"default"}, set(MODES)):
        raise ValueError("Recommendations require all modes for simple or detailed")
    ivs = matrices["default"].candidates
    if not ivs or any(set(m.candidates) != set(ivs) or not m.opponents for m in matrices.values()):
        raise ValueError("Missing candidates or opponents in recommendation matrices")
    # Compare the same matchup within each mode; opponent IV names can differ
    # across modes. Dominance requires one rival to dominate across ALL modes.
    cells = [(mode, shield, pos, opponent) for mode in MODES if mode in matrices
             for shield in SHIELDS for pos, opponent in enumerate(matrices[mode].opponents)]
    vectors = {iv: tuple(matrices[mode].ratings[shield][iv][pos]
                        for mode, shield, pos, _ in cells) for iv in ivs}
    dominated = {iv: [other for other in ivs if other != iv
                     and all(a >= b for a, b in zip(vectors[other], vectors[iv]))
                     and any(a > b for a, b in zip(vectors[other], vectors[iv]))]
                 for iv in ivs}
    equivalents: dict[str, list[str]] = {}
    owners = {}
    for iv in sorted(ivs, key=lambda v: tuple(map(int, v.split("/")))):
        vector = vectors[iv]
        if vector in owners:
            equivalents[owners[vector]].append(iv)
        else:
            owners[vector] = iv
            equivalents[iv] = []
    reps = [iv for iv in equivalents if not dominated[iv]]
    events = {iv: [] for iv in reps}
    losses = {iv: [] for iv in reps}
    for index, (mode, shield, pos, opponent) in enumerate(cells):
        scores = [(iv, vectors[iv][index]) for iv in reps]
        best = max(r for _, r in scores)
        best_iv = next(iv for iv, r in scores if r == best)
        focused = any(term.casefold() in opponent.casefold() for term in focus)
        for iv, rating in scores:
            # "Unique >500" means every other supplied performance group is
            # <=500, including dominated candidates. Equivalent IVs are an
            # explicitly displayed alternative, not a distinct role.
            others = [vectors[other][index] for other in ivs
                      if other != iv and other not in equivalents[iv]]
            second = max(others) if others else None
            kind = None
            if not others and rating >= 500:
                kind = "available_matchup"
            elif second is not None:
                if rating > 500 and second <= 500:
                    kind = "unique_gt500"
                elif rating == 500 and second < 500:
                    kind = "unique_eq500"
                elif rating > 500 and rating == best and any(r <= 500 for r in others):
                    kind = "best_crossover"
                elif rating > 500 and rating - second >= rules.meaningful_win_lead:
                    kind = "winning_margin"
                elif len(reps) == 1 and rating >= 500:
                    kind = "available_matchup"
            event = {"mode": mode, "shield": shield, "opponent": opponent,
                     "rating": rating, "next_best": second, "focus": focused,
                     "disadvantage": shield in SHIELDS[3:]}
            if kind:
                events[iv].append({**event, "kind": kind})
            if rating <= 500 < best:
                losses[iv].append({**event, "best_iv": best_iv, "best_rating": best})
    def priority(e):
        return (-int(e["focus"]), -int(e["kind"] == "unique_gt500"),
                -int(e["disadvantage"]), -(e["rating"] - (e["next_best"] if e["next_best"] is not None else 500)),
                MODES.index(e["mode"]), SHIELDS.index(e["shield"]), e["opponent"])
    recommendations, held = [], []
    shadow = "shadow" in candidate["species"].split("_") or candidate["species"].endswith("-shadow")
    for iv in reps:
        found = sorted(events[iv], key=priority)
        equivalent_rows = [{"ivs": x, "search_string": search_string(english_name, x, shadow, candidate['species'])} for x in equivalents[iv]]
        if not found:
            held.append({"ivs": iv, "status": "review", "reason": "完全支配はされていません。自動推薦の採用根拠が不足しています。",
                         "equivalent_candidates": equivalent_rows})
            continue
        unique_focus = any(e["focus"] and e["kind"] == "unique_gt500" for e in found)
        cross_role = any(e["focus"] for e in found) and any(e["disadvantage"] and e["kind"] == "unique_gt500" for e in found)
        grade = "S候補" if unique_focus or cross_role else "A候補"
        role = "重要対面対応型" if unique_focus else "不利シールド対応型" if any(e["disadvantage"] for e in found) else "特定対面対応型"
        if len(reps) == 1:
            role = "比較内の代表個体" if len(ivs) > 1 else "単独候補（比較対象なし）"
        example = found[0]
        reason = f'{example["opponent"]}・{example["mode"]}/{example["shield"]}でRating {example["rating"]:g}'
        if example["next_best"] is not None:
            reason += f'（他候補の最高 {example["next_best"]:g}）'
        reason += "。"
        loss = max(losses[iv], key=lambda e: (e["focus"], e["best_rating"] - e["rating"]), default=None)
        recommendations.append({"ivs": iv, "grade": grade, "role": role, "reason": reason,
                                "search_string": search_string(english_name, iv, shadow, candidate['species']),
                                "evidence_count": len(found), "evidence": found,
                                "tradeoff_count": len(losses[iv]), "tradeoff": loss,
                                "equivalent_candidates": equivalent_rows})
    recommendations.sort(key=lambda row: (row["grade"] != "S候補", priority(row["evidence"][0]),
                                            -len(row["evidence"]), -sum(vectors[row["ivs"]]) / len(cells), row["ivs"]))
    for rank, row in enumerate(recommendations, 1):
        row["rank"] = rank
    matched_focus = [x for x in focus if any(x.casefold() in name.casefold() for _, _, _, name in cells)]
    return {"format": "app-recommendations-v1", "complete": True, "policy": asdict(rules),
            "grade_source": "project rule-based provisional candidates", "candidate": candidate,
            "english_name": english_name, "candidate_count": len(ivs),
            "candidate_ivs": ivs,
            "mode_count": len(matrices), "condition_count": len(matrices) * 6,
            "total_ratings_checked": len(cells) * len(ivs),
            "focus_opponents": focus, "unmatched_focus": [x for x in focus if x not in matched_focus],
            "recommendations": recommendations, "review_candidates": held,
            "dominated_by": {iv: by for iv, by in dominated.items() if by},
            "excluded": matrices["default"].manifest.get("excluded"),
            "counts_estimated_from_rating": True}


def recommendations_from_zip(archive: ZipFile, candidate: dict, english_name: str,
                             batch_mode: str, focus_opponents=None, policy=None) -> dict:
    if batch_mode not in ("simple", "detailed"):
        raise ValueError("batch_mode must be simple or detailed")
    modes = ("default",) if batch_mode == "simple" else MODES
    return recommend({mode: load_selection_matrix(archive, mode) for mode in modes},
                     candidate, english_name, focus_opponents, policy)
