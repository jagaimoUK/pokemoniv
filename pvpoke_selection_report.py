"""Compact, lossless-simulation analysis of a completed PvPoke IV matrix ZIP.

This module never estimates or recalculates a battle: it summarizes the ratings
already present in the six CSV files. Full raw data remains available through
get_results. Rankings are descriptive, not PvPoke S/A grades.
"""
from __future__ import annotations

from zipfile import ZipFile
from pvpoke_selection_matrix import (
    SHIELDS, MODES, IV_SUFFIX, EXPECTED_END, SelectionMatrix, load_selection_matrix,
)


def _mean(numbers: list[float]) -> float:
    return round(sum(numbers) / len(numbers), 2)


def build_selection_report(
    archive: ZipFile,
    mode: str = "default",
    focus_opponents: list[str] | None = None,
    max_flips: int = 120,
) -> dict:
    """Return all-candidate rankings, all crossovers (up to cap), and focus matchups.

    One archive read replaces six or more paginated get_results round-trips.
    Crossovers use the same strict Battle Rating >500 / <500 rule as the skill.
    """
    if mode not in MODES:
        raise ValueError("mode must be default, rank1, attack or defense")
    if not isinstance(max_flips, int) or not 0 <= max_flips <= 522:
        raise ValueError("max_flips must be an integer between 0 and 522")
    focus = focus_opponents if focus_opponents is not None else []
    if (not isinstance(focus, list) or len(focus) > 15
            or any(not isinstance(word, str) or not word.strip() or len(word) > 100
                   for word in focus)):
        raise ValueError("focus_opponents must contain up to 15 nonempty names")
    return report_from_matrix(load_selection_matrix(archive, mode), mode, focus, max_flips)


def report_from_matrix(data: SelectionMatrix, mode: str, focus: list[str],
                       max_flips: int | None = None) -> dict:
    """Internal uncapped view; public report keeps its existing output limit."""
    names, candidates, matrix = data.opponents, data.candidates, data.ratings
    rankings = []
    for iv in candidates:
        equal = [r for s in SHIELDS[:3] for r in matrix[s][iv]]
        disadvantage = [r for s in SHIELDS[3:] for r in matrix[s][iv]]
        combined = equal + disadvantage
        rankings.append({
            "ivs": iv,
            "mean_rating": _mean(combined),
            "equal_mean": _mean(equal),
            "disadvantage_mean": _mean(disadvantage),
            "rating_gt500": sum(r > 500 for r in combined),
            "equal_gt500": sum(r > 500 for r in equal),
            "disadvantage_gt500": sum(r > 500 for r in disadvantage),
            "rating_eq500": sum(r == 500 for r in combined),
            "min_rating": min(combined),
            "matchups": len(combined),
        })
    rankings.sort(key=lambda row: (-row["mean_rating"], row["ivs"]))

    crossover = []
    for shield in SHIELDS:
        for pos, opponent in enumerate(names):
            scores = sorted(
                ((iv, matrix[shield][iv][pos]) for iv in candidates),
                key=lambda pair: (-pair[1], pair[0]),
            )
            if scores[0][1] <= 500 or scores[-1][1] >= 500:
                continue
            focused = any(term.casefold() in opponent.casefold() for term in focus)
            crossover.append({
                "shield": shield,
                "opponent": opponent,
                "range": round(scores[0][1] - scores[-1][1], 2),
                "focus": focused,
                "above500_ivs": [iv for iv, rating in scores if rating > 500],
                "best": [{"ivs": iv, "rating": rating} for iv, rating in scores[:3]],
                "worst": {"ivs": scores[-1][0], "rating": scores[-1][1]},
            })
    crossover.sort(key=lambda event: (
        -int(event["focus"]), -event["range"],
        SHIELDS.index(event["shield"]), event["opponent"],
    ))

    focus_matchups = []
    for pos, opponent in enumerate(names):
        if any(term.casefold() in opponent.casefold() for term in focus):
            focus_matchups.append({
                "opponent": opponent,
                "by_iv": {
                    iv: [matrix[shield][iv][pos] for shield in SHIELDS]
                    for iv in candidates
                },
            })
    manifest = data.manifest
    returned = len(crossover) if max_flips is None else min(max_flips, len(crossover))
    return {
        "mode": mode,
        "batch_mode": manifest.get("batch_mode"),
        "shield_order": list(SHIELDS),
        "candidate_count": len(candidates),
        "opponent_count": len(names),
        "condition_count": len(SHIELDS),
        "total_ratings_checked": len(candidates) * len(names) * len(SHIELDS),
        "complete": True,
        "counts_estimated_from_rating": True,
        "rankings": rankings,
        "crossovers_total": len(crossover),
        "crossovers_returned": returned,
        "crossovers": crossover[:returned],
        "focus_matchups": focus_matchups,
        "excluded": manifest.get("excluded"),
        "gamemaster_timestamp": manifest.get("gamemaster_timestamp"),
    }

