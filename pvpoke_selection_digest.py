"""Small, evidence-rich IV report for a completed PvPoke ZIP.

Keeps all battle calculations and validation from the full selection report.
The digest is an evidence preview, NOT an official PvPoke S/A ranking.
Use get_selection_report/get_results to inspect the omitted raw matchups.
"""
from __future__ import annotations

from zipfile import ZipFile

from pvpoke_selection_report import (
    MODES, SHIELDS, report_from_matrix,

)
from pvpoke_selection_matrix import SelectionMatrix, load_selection_matrix


def _dominance(data: SelectionMatrix, ivs: list[str]) -> dict[str, list[str]]:
    """Pairwise Pareto dominance over every validated opponent and shield."""
    series = {iv: [r for shield in SHIELDS for r in data.ratings[shield][iv]]
              for iv in ivs}
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



def _all_candidate_evidence(
    data: SelectionMatrix,
    ivs: list[str],
    dominated: dict[str, list[str]],
    focus_opponents: list[str] | None,
) -> list[dict]:
    """Find distinctive matchup evidence for EVERY candidate, not review_ivs.

    All opponent rows x all six shields are examined, including rows which
    never cross the 500 boundary. A signal is *not* an automatic S/A grade.
    """
    focus = tuple(word.casefold() for word in (focus_opponents or []))
    matrix, opponent_names = data.ratings, data.opponents
    evidence: dict[str, dict] = {
        iv: {
            "ivs": iv, "dominated": iv in dominated,
            "unique_gt500": 0, "unique_gt500_focus": 0,
            "unique_gt500_disadvantage": 0,
            "clear_leads": 0, "clear_leads_focus": 0,
            "clear_leads_disadvantage": 0,
            "strict_leads": 0,
            "_events": [],
        } for iv in ivs
    }
    # A >=20 Battle Rating lead is a diagnostic signal, not a win threshold.
    clear_lead_margin = 20
    for shield in SHIELDS:
        disadvantage = shield.startswith("i")
        for pos, opponent in enumerate(opponent_names):
            focused = any(word in opponent.casefold() for word in focus)
            scores = sorted(
                ((iv, matrix[shield][iv][pos]) for iv in ivs),
                key=lambda item: (-item[1], item[0]),
            )
            # A one-candidate batch has no comparative signals.
            if len(scores) < 2:
                continue
            leader, highest = scores[0]
            second = scores[1][1]
            if highest <= second:
                # No unique best, but one candidate may still be the only one
                # above 500; impossible here if the top score is tied.
                continue
            info = evidence[leader]
            info["strict_leads"] += 1
            gap = round(highest - second, 2)
            unique = highest > 500 and second <= 500
            clear = gap >= clear_lead_margin
            if unique:
                info["unique_gt500"] += 1
                if focused:
                    info["unique_gt500_focus"] += 1
                if disadvantage:
                    info["unique_gt500_disadvantage"] += 1
            if clear:
                info["clear_leads"] += 1
                if focused:
                    info["clear_leads_focus"] += 1
                if disadvantage:
                    info["clear_leads_disadvantage"] += 1
            if unique or clear:
                info["_events"].append({
                    "shield": shield, "opponent": opponent,
                    "rating": highest, "next_best": second,
                    "lead": gap, "unique_gt500": unique,
                    "focus": focused, "disadvantage": disadvantage,
                })

    # At most three grounded examples per IV, but *every* IV is listed even
    # when outside review_ivs. Favor distinct opponents and role coverage.
    rules = (
        lambda e: e["unique_gt500"] and e["focus"],
        lambda e: e["unique_gt500"] and e["disadvantage"],
        lambda e: e["unique_gt500"],
        lambda e: e["focus"] and e["lead"] >= clear_lead_margin,
        lambda e: e["disadvantage"] and e["lead"] >= clear_lead_margin,
        lambda e: True,
    )
    for iv in ivs:
        info = evidence[iv]
        events = sorted(info.pop("_events"), key=lambda e: (
            -int(e["focus"]), -int(e["unique_gt500"]),
            -int(e["disadvantage"]), -e["lead"],
            SHIELDS.index(e["shield"]), e["opponent"],
        ))
        picked = []
        used = set()
        for rule in rules:
            options = [(index, event) for index, event in enumerate(events)
                       if index not in used and rule(event)]
            if not options:
                continue
            diverse = [(index, event) for index, event in options
                       if event["opponent"] not in {p["opponent"] for p in picked}]
            if diverse:
                options = diverse
            index, event = options[0]
            used.add(index)
            picked.append(event)
            if len(picked) == 3:
                break
        info["examples_total"] = len(events)
        info["examples_truncated"] = len(events) > len(picked)
        info["examples"] = [{key: event[key] for key in (
            "opponent", "shield", "rating", "next_best", "lead",
            "unique_gt500", "focus")} for event in picked]
    return [evidence[iv] for iv in ivs]


def build_selection_digest(
    archive: ZipFile,
    mode: str = "default",
    focus_opponents: list[str] | None = None,
    highlight_limit: int = 20,
    review_limit: int = 8,
    focus_limit: int = 20,
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

    # One validated read per CSV; rankings, dominance and evidence share it.
    data = load_selection_matrix(archive, mode)
    focus = focus_opponents if focus_opponents is not None else []
    if (not isinstance(focus, list) or len(focus) > 15
            or any(not isinstance(word, str) or not word.strip() or len(word) > 100
                   for word in focus)):
        raise ValueError("focus_opponents must contain up to 15 nonempty names")
    full = report_from_matrix(data, mode, focus)
    candidates = full["rankings"]
    flips = full["crossovers"]
    ivs = [row["ivs"] for row in candidates]
    dominated = _dominance(data, ivs)
    candidate_evidence = _all_candidate_evidence(data, ivs, dominated, focus)

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
        "candidate_evidence_complete": True,
        "candidate_evidence_count": len(candidate_evidence),
        "candidate_evidence_scope": "all candidates, all opponents, all six shields",
        "clear_lead_minimum": 20,
        "candidate_evidence": candidate_evidence,
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

