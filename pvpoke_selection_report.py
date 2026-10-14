"""Compact, lossless-simulation analysis of a completed PvPoke IV matrix ZIP.

This module never estimates or recalculates a battle: it summarizes the ratings
already present in the six CSV files. Full raw data remains available through
get_results. Rankings are descriptive, not PvPoke S/A grades.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from zipfile import ZipFile

SHIELDS = ("s0", "s1", "s2", "i0y1", "i0y2", "i1y2")
MODES = ("default", "rank1", "attack", "defense")
IV_SUFFIX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{1,2})$")
EXPECTED_END = ("rating_gt500", "rating_lt500", "rating_eq500", "mean_rating")


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
    names: list[str] | None = None
    candidates: list[str] | None = None
    matrix: dict[str, dict[str, list[float]]] = {}

    for shield in SHIELDS:
        path = f"{mode}_{shield}.csv"
        if path not in archive.namelist():
            raise ValueError(f"Missing required condition: {path}")
        table = list(csv.reader(io.StringIO(archive.read(path).decode("utf-8-sig"))))
        if len(table) < 2 or len(table[0]) < 6:
            raise ValueError(f"Invalid matrix CSV: {path}")
        header = table[0]
        if tuple(header[-4:]) != EXPECTED_END:
            raise ValueError(f"Unexpected summary columns in {path}")
        opponents = header[1:-4]
        if names is None:
            names = opponents
        elif names != opponents:
            raise ValueError(f"Opponent order differs in {path}")
        per_candidate = {}
        for row in table[1:]:
            if len(row) != len(header):
                raise ValueError(f"Malformed candidate row in {path}")
            match = IV_SUFFIX.search(row[0])
            if match is None:
                raise ValueError(f"Missing IV triplet in candidate: {row[0]}")
            key = "/".join(str(int(v)) for v in match.groups())
            if key in per_candidate:
                raise ValueError(f"Duplicate candidate IVs in {path}: {key}")
            values = [float(value) for value in row[1:-4]]
            if any(not math.isfinite(r) or r < 0 or r > 1000 for r in values):
                raise ValueError(f"Invalid Battle Rating in {path}")
            per_candidate[key] = values
        keys = list(per_candidate)
        if candidates is None:
            candidates = keys
        elif candidates != keys:
            raise ValueError(f"Candidate order differs in {path}")
        matrix[shield] = per_candidate

    assert names is not None and candidates is not None
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
    manifest = json.loads(archive.read("manifest.json").decode("utf-8")) if "manifest.json" in archive.namelist() else {}
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
        "crossovers_returned": min(max_flips, len(crossover)),
        "crossovers": crossover[:max_flips],
        "focus_matchups": focus_matchups,
        "excluded": manifest.get("excluded"),
        "gamemaster_timestamp": manifest.get("gamemaster_timestamp"),
    }
