"""Box-first curation layered on the full, auditable PvPoke role matrix.

A representative S is selected by total actual wins, not by a lucky single
unique matchup. Additional saves must contribute meaningful NEW outcomes.
The original per-cell matrix and non-selected candidates remain inspectable.
This is a project heuristic, never an official PvPoke grade.
"""
from __future__ import annotations


def curate_for_box(recommendations, held, outcomes, vectors, cells, focus,
                   english_name, candidate, make_search, shadow, limit=4, original_count=None):
    """Return (box_rows, held_rows, additional_rows) without editing source rows.

    Outcomes represent win=2/draw=1/loss=0 and distinguish opponent mode,
    shield configuration, Pokemon/form/moves as represented by the matrix.
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit must be 1..20")
    focus_words = tuple(x.casefold() for x in focus)
    def focused(name):
        return any(x in name.casefold() for x in focus_words)

    def weight(index):
        shield = cells[index][1]
        return 2.0 if shield in ("s0", "s1") else 1.0

    def global_score(iv):
        wins = sum(weight(i) for i, x in enumerate(outcomes[iv]) if x == 2)
        draws = sum(weight(i) for i, x in enumerate(outcomes[iv]) if x == 1)
        s01 = sum(1 for i, x in enumerate(outcomes[iv])
                  if x == 2 and cells[i][1] in ("s0", "s1"))
        avg = sum(vectors[iv]) / len(vectors[iv])
        return wins, s01, draws, avg

    original = [dict(row) for row in recommendations]
    original_by_iv = {r["ivs"]: r for r in original}
    holding = [dict(row) for row in held]
    holding_by_iv = {r["ivs"]: r for r in holding}
    # Candidates already excluded by one full-result covering representative
    # should not displace that representative just because of Rating differences.
    eligible = set(original_by_iv) | set(holding_by_iv)
    winning = [iv for iv in eligible if any(x == 2 for x in outcomes[iv])]
    if not winning:
        return [], holding, [
            {"ivs": r["ivs"], "reason": "保存するだけの勝利条件がありません。"}
            for r in original
        ]
    champion = max(winning, key=lambda iv: (global_score(iv), iv in original_by_iv, iv))
    if champion in holding_by_iv:
        row = holding_by_iv[champion]
        # A generally strong IV can have no single best-crossover/winning-margin
        # event. It still deserves consideration as the baseline, using a real
        # win from the complete matrix, not invented "unique" evidence.
        best_index = max((i for i, v in enumerate(outcomes[champion]) if v == 2),
                         key=lambda i: (focused(cells[i][3]), weight(i),
                                        vectors[champion][i]))
        mode, shield, _, opponent = cells[best_index]
        next_best = max((vectors[other][best_index] for other in eligible
                         if other != champion), default=None)
        event = {"mode": mode, "shield": shield, "opponent": opponent,
                 "rating": vectors[champion][best_index],
                 "next_best": next_best, "focus": focused(opponent),
                 "disadvantage": shield.startswith("i"), "kind": "mainstay"}
        row.update({
            "search_string": make_search(english_name, champion, shadow,
                                         candidate["species"]),
            "evidence": [event], "evidence_count": 1,
            "tradeoff": None, "tradeoff_count": 0,
            "reason": "全条件の勝利数から選んだ主力。代表的な勝利を表示しています。",
        })
        holding = [x for x in holding if x["ivs"] != champion]
    else:
        row = original_by_iv[champion]
    row["grade"] = "Sランク" if (original_count or len(eligible)) >= 2 else "Aランク"
    row["role"] = ("総合本命（保存最優先）" if (original_count or len(eligible)) >= 2
                   else "単独の比較候補")
    row["box_reason"] = "全条件の勝利数を重視した総合本命"
    row["win_conditions"] = sum(x == 2 for x in outcomes[champion])
    selected = [row]
    pending = {r["ivs"]: r for r in original if r["ivs"] != champion}
    additional = []

    def gains(iv):
        missing = []
        for i, result in enumerate(outcomes[iv]):
            best_saved = max(outcomes[s["ivs"]][i] for s in selected)
            if result > best_saved and result == 2:
                missing.append(i)
        opponents = {cells[i][3] for i in missing}
        shields = {cells[i][1] for i in missing}
        priority = [i for i in missing if focused(cells[i][3])]
        disadv = [i for i in missing if cells[i][1].startswith("i")]
        high_disadv = [
            i for i in disadv
            if vectors[iv][i] >= 540
            and max(vectors[s["ivs"]][i] for s in selected) <= 500
        ]
        # Rating differences within already-won matches never count as gains.
        meaningful = (bool(priority) or len(opponents) >= 2
                      or bool(high_disadv)
                      or (len(shields) >= 2 and len(missing) >= 3))
        ranking = (bool(priority), len(opponents), bool(high_disadv),
                   sum(weight(i) for i in missing), len(disadv),
                   global_score(iv))
        return missing, meaningful, ranking

    while pending and len(selected) < limit:
        ordered = sorted(pending, key=lambda iv: (gains(iv)[2], iv), reverse=True)
        iv = ordered[0]
        missing, meaningful, _ = gains(iv)
        if not missing or not meaningful:
            break
        r = pending.pop(iv)
        r["grade"] = "Aランク"
        r["role"] = "本命にない重要対面・特殊条件を補完"
        r["box_reason"] = f"保存済み個体では拾えない勝利 {len(missing)}条件"
        r["new_win_conditions"] = len(missing)
        selected.append(r)

    for iv, r in pending.items():
        missing, meaningful, _ = gains(iv)
        reason = ("保存済みの個体で勝利をカバーできるため"
                  if not missing else
                  "保存枠上限に達したため" if meaningful else
                  "独自の勝利が限定的で、保存優先度が低いため")
        additional.append({
            "ivs": iv, "reason": reason,
            "new_win_conditions": len(missing),
            "equivalent_candidates": r.get("equivalent_candidates", []),
        })
    # Keep original order for a stable audit list.
    additional.sort(key=lambda x: next(
        i for i, r in enumerate(original) if r["ivs"] == x["ivs"]))
    return selected, holding, additional
