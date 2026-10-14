"""Small, evidence-rich IV report for a completed PvPoke ZIP.

Keeps all battle calculations and validation from the full selection report.
The digest is an evidence preview, NOT an official PvPoke S/A ranking.
Use get_selection_report/get_results to inspect the omitted raw matchups.
"""
from __future__ import annotations

import csv
import io
from zipfile import ZipFile

from pvpoke_selection_report import (
    IV_SUFFIX, MODES, SHIELDS, build_selection_report,
)


def _dominance(archive: ZipFile, mode: str, ivs: list[str]) -> dict[str, list[str]]:
    """Pairwise Pareto dominance over ALL opponent/shield Battle Ratings."""
    series = {iv: [] for iv in ivs}
    for shield in SHIELDS:
        table = list(csv.reader(io.StringIO(
            archive.read(f"{mode}_{shield}.csv").decode("utf-8-sig")
        )))
        for row in table[1:]:
            match = IV_SUFFIX.search(row[0])
            if match is None:
                raise ValueError(f"Missing IV in {shield}")
            iv = "/".join(str(int(number)) for number in match.groups())
            if iv not in series:
                raise ValueError(f"Unexpected IV in {shield}: {iv}")
            series[iv].extend(float(n) for n in row[1:-4])
    dominated = {}
    for iv in ivs:
        rivals = []
        for other in ivs:
            if iv == other:
                continue
            a, b = series[other], series[iv]
            if len(a) != len(b):
                raise ValueError("Unequal matchup lengths")
            if all(x >= y for x, y in zip(a, b)) and any(
                x > y for x, y in zip(a, b)
            ):
                rivals.append(other)
        if rivals:
            dominated[iv] = rivals
    return dominated


def build_selection_digest(
    archive: ZipFile,
    mode: str = "default",
    focus_opponents: list[str] | None = None,
    highlight_limit: int = 20,
    review_limit: int = 8,
    focus_limit: int = 10,
) -> dict:
    """Compact JSON from the exact six matrices, with no battle recalculation."""
    if mode not in MODES:
        raise ValueError("mode must be default/rank1/attack/defense")
    if not isinstance(highlight_limit, int) or not 1 <= highlight_limit <= 60:
        raise ValueError("highlight_limit must be 1..60")
    if not isinstance(review_limit, int) or not 2 <= review_limit <= 12:
        raise ValueError("review_limit must be 2..12")
    if not isinstance(focus_limit, int) or not 0 <= focus_limit <= 20:
        raise ValueError("focus_limit must be 0..20")

    full = build_selection_report(archive, mode=mode,
                                  focus_opponents=focus_opponents,
                                  max_flips=522)
    candidates = full["rankings"]
    flips = full["crossovers"]
    ivs = [row["ivs"] for row in candidates]
    dominated = _dominance(archive, mode, ivs)

    focus_best = {iv: 0 for iv in ivs}
    focus_unique = {iv: 0 for iv in ivs}
    global_unique = {iv: 0 for iv in ivs}
    for flip in flips:
        best_iv = flip["best"][0]["ivs"]
        if flip["focus"]:
            focus_best[best_iv] += 1
        winners = flip["above500_ivs"]
        if len(winners) == 1:
            global_unique[winners[0]] += 1
            if flip["focus"]:
                focus_unique[winners[0]] += 1

    # Always represent the top four, then add genuinely distinct specialists.
    review = ivs[:min(4, review_limit)]
    scored_specialists = sorted(
        (iv for iv in ivs if iv not in review),
        key=lambda iv: (
            -focus_unique[iv], -focus_best[iv], -global_unique[iv],
            ivs.index(iv),
        ),
    )
    for iv in scored_specialists:
        if len(review) >= review_limit:
            break
        if focus_unique[iv] or focus_best[iv] or global_unique[iv]:
            review.append(iv)
    for iv in ivs:
        if len(review) >= min(review_limit, len(ivs)):
            break
        if iv not in review:
            review.append(iv)

    def event_rank(event: dict) -> tuple:
        is_unique = len(event["above500_ivs"]) == 1
        return (
            -int(event["focus"]),
            -int(is_unique),
            -event["range"],
            SHIELDS.index(event["shield"]),
            event["opponent"],
        )

    # Preserve one useful example for every selected candidate when possible.
    picked: list[dict] = []
    chosen = set()
    for iv in review:
        personal = [i for i, event in enumerate(flips)
                    if event["best"][0]["ivs"] == iv]
        if not personal:
            personal = [i for i, event in enumerate(flips)
                        if iv in event["above500_ivs"]]
        for index in sorted(personal, key=lambda i: event_rank(flips[i])):
            if index not in chosen:
                picked.append(flips[index])
                chosen.add(index)
                break
    for index in sorted(range(len(flips)), key=lambda i: event_rank(flips[i])):
        if len(picked) >= highlight_limit:
            break
        if index not in chosen:
            picked.append(flips[index])
            chosen.add(index)
    picked = sorted(picked[:highlight_limit], key=event_rank)

    # These are comparisons on identical opponents and identical shield cases.
    def compress_flip(event: dict) -> dict:
        best = event["best"]
        return {
            "shield": event["shield"],
            "opponent": event["opponent"],
            "focus": event["focus"],
            "above500_ivs": event["above500_ivs"],
            "best": [best[0]["ivs"], best[0]["rating"]],
            "second": [best[1]["ivs"], best[1]["rating"]]
            if len(best) > 1 else None,
            "worst": [event["worst"]["ivs"], event["worst"]["rating"]],
        }

    # Prioritize one variant of EACH focus name, then fill remaining slots with
    # the strongest focus-crossover evidence. Never present truncated focus
    # arrays as full opponent coverage.
    focus_rows = full["focus_matchups"]
    focus_words = focus_opponents or []
    chosen_focus: list[dict] = []
    seen = set()
    for word in focus_words:
        for i, row in enumerate(focus_rows):
            if i not in seen and word.casefold() in row["opponent"].casefold():
                chosen_focus.append(row)
                seen.add(i)
                break
        if len(chosen_focus) >= focus_limit:
            break
    counts = {}
    for flip in flips:
        if flip["focus"]:
            counts[flip["opponent"]] = counts.get(flip["opponent"], 0) + 1
    for i in sorted(range(len(focus_rows)),
                    key=lambda i: (-counts.get(focus_rows[i]["opponent"], 0), i)):
        if len(chosen_focus) >= focus_limit:
            break
        if i not in seen:
            chosen_focus.append(focus_rows[i])
            seen.add(i)

    focus_compact = [
        {"opponent": row["opponent"],
         "by_iv": {iv: row["by_iv"][iv] for iv in review}}
        for row in chosen_focus[:focus_limit]
    ]

    return {
        "mode": full["mode"],
        "batch_mode": full["batch_mode"],
        "complete": full["complete"],
        "candidate_count": full["candidate_count"],
        "opponent_count": full["opponent_count"],
        "condition_count": full["condition_count"],
        "total_ratings_checked": full["total_ratings_checked"],
        "excluded": full["excluded"],
        "gamemaster_timestamp": full["gamemaster_timestamp"],
        "counts_estimated_from_rating": full["counts_estimated_from_rating"],
        "shield_order": full["shield_order"],
        "ranking_columns": ["ivs", "mean", "equal_mean", "disadvantage_mean",
                            "rating_gt500"],
        "ranking_rows": [
            [row["ivs"], row["mean_rating"], row["equal_mean"],
             row["disadvantage_mean"], row["rating_gt500"]]
            for row in candidates
        ],
        "dominated_by": dominated,
        "review_ivs": review,
        "review_only_not_SA_grade": True,
        "crossovers_total": full["crossovers_total"],
        "focus_crossovers_total": sum(bool(x["focus"]) for x in flips),
        "crossovers_returned": len(picked),
        "crossovers_truncated": len(picked) < full["crossovers_total"],
        "priority_crossovers": [compress_flip(x) for x in picked],
        "focus_matchups_total": len(focus_rows),
        "focus_matchups_returned": len(focus_compact),
        "focus_matchups_truncated": len(focus_compact) < len(focus_rows),
        "focus_matchups": focus_compact,
        "note": "All six matrices checked. Highlights are selective. "
                "Inspect get_selection_report for omitted opponent evidence. "
                "S/A ranks require user-context judgment.",
    }
