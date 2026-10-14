"""All-candidate downside evidence from the same validated battle matrices.

The reference is the best supplied candidate in each individual matchup,
not a single superior build. These counters are not S/A grades.
"""
from __future__ import annotations

from pvpoke_selection_matrix import SelectionMatrix, SHIELDS


def candidate_tradeoffs(data: SelectionMatrix, ivs: list[str],
                       focus: list[str]) -> list[dict]:
    words = tuple(word.casefold() for word in focus)
    rows = {iv: {"ivs": iv, "lower_than_best": 0, "lost_gt500": 0,
                 "example": None} for iv in ivs}
    priorities = {}
    for shield_index, shield in enumerate(SHIELDS):
        for pos, opponent in enumerate(data.opponents):
            scores = data.ordered_scores[shield][pos]
            best_iv, best = scores[0]
            focused = any(word in opponent.casefold() for word in words)
            for iv, rating in scores:
                if rating >= best:
                    continue
                row = rows[iv]
                row["lower_than_best"] += 1
                lost = rating <= 500 < best
                row["lost_gt500"] += int(lost)
                prefix = (-int(focused), -int(lost), -int(shield.startswith("i")))
                previous = priorities.get(iv)
                if previous is not None and prefix > previous[:3]:
                    continue
                gap = round(best - rating, 2)
                # Tiny non-boundary differences still count, but are not
                # promoted into a representative weakness.
                if not lost and gap < 20:
                    continue
                priority = (*prefix, -gap, shield_index, opponent, pos)
                if iv not in priorities or priority < priorities[iv]:
                    priorities[iv] = priority
                    row["example"] = {
                        "opponent": opponent, "shield": shield,
                        "rating": rating, "best_iv": best_iv,
                        "best_rating": best, "gap": gap, "focus": focused,
                    }
    return [rows[iv] for iv in ivs]
