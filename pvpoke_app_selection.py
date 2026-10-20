"""Deterministic, versioned recommendations from complete saved battle matrices.

No GPT calls. Grades are this project's rule-based candidates, not PvPoke grades.
Unresolved non-dominated candidates remain visible for human/GPT review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
import json
from zipfile import ZipFile

from pvpoke_selection_matrix import MODES, SHIELDS, SelectionMatrix, load_selection_matrix
from pvpoke_app_sizes import pumpkin_search
from pvpoke_classic_curator import curate_for_box


@dataclass(frozen=True)
class SelectionPolicy:
    version: str = "box-first-v3"
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


# Pokémon GO searches by a region keyword, not the PvPoke display-name suffix.
# E.g. "Wooper (Paldean)" means "Wooper&paldea", not a literal nickname.
# Only regional *forms* get the extra term. Newly introduced species from
# these regions keep their ordinary species-name search unchanged.
REGIONAL_FORM_TERMS = {
    "alolan": "alola",
    "galarian": "galar",
    "hisuian": "hisui",
    "paldean": "paldea",
}


def _regional_go_name(name: str, species_id: str | None = None) -> tuple[str, str]:
    """Return base GO name and &region, handling English form aliases.

    The PvPoke species ID is authoritative if present; fallback to the
    catalog name for callers without an ID. Non-regional form labels stay
    untouched rather than being silently interpreted as regional variants.
    """
    sid_parts = set(re.split(r"[_-]", (species_id or "").casefold()))
    region_from_id = next(
        (region for adjective, region in REGIONAL_FORM_TERMS.items()
         if adjective in sid_parts), None)
    found = []
    for adjective, region in REGIONAL_FORM_TERMS.items():
        names = (adjective, region)
        tokens = "|".join(re.escape(token) for token in names)
        if (re.search(r"^\s*(?:" + tokens + r")\s+", name, re.I)
                or re.search(r"\s*\(\s*(?:" + tokens + r")\s*\)\s*$", name, re.I)
                or re.search(r"\s+(?:" + tokens + r")\s*$", name, re.I)):
            found.append((region, tokens))
    region = region_from_id or (found[0][0] if found else None)
    if not region:
        return name, ""
    tokens = "|".join(re.escape(token) for token, code in
                      REGIONAL_FORM_TERMS.items() if code == region)
    tokens += "|" + re.escape(region)
    cleaned = re.sub(r"^\s*(?:" + tokens + r")\s+", "", name, flags=re.I)
    cleaned = re.sub(r"\s*\(\s*(?:" + tokens + r")\s*\)\s*$",
                     "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+(?:" + tokens + r")\s*$", "", cleaned, flags=re.I)
    if not cleaned.strip():
        raise ValueError("Regional Pokémon search requires a species name")
    return cleaned.strip(), "&" + region


def search_string(name: str, iv: str, shadow: bool = False, species_id: str | None = None) -> str:
    values = [int(x) for x in iv.split("/")]
    if len(values) != 3 or any(not 0 <= x <= 15 for x in values):
        raise ValueError("Invalid candidate IV")
    if not name or any(x in name for x in "&\r\n"):
        raise ValueError("A valid English species name is required")
    # The catalog may label shadows as "Wooper (Paldean) (Shadow)".
    # GO expects the shadow keyword as its own filter too.
    if shadow:
        name = re.sub(r"\s*\(Shadow\)\s*$", "", name, flags=re.I)
    form_search = pumpkin_search(species_id)
    if form_search:
        name, size_filter = form_search
        regional_filter = ""
    else:
        size_filter = ""
        name, regional_filter = _regional_go_name(name, species_id)
    def bucket(x):
        return 0 if x == 0 else 1 if x <= 5 else 2 if x <= 10 else 3 if x < 15 else 4
    return name + regional_filter + "".join(f"&{bucket(x)}{label}" for x, label in zip(values, ("attack", "defense", "hp"))) + size_filter + ("&shadow" if shadow else "")


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
    # Compare outcomes on the FULL matrix, never the evidence excerpts or just
    # opponent names. A higher Rating in an already-won cell is not a new role.
    # Draws must also be covered, by the SAME retained candidate across modes.
    outcomes = {iv: tuple(2 if r > 500 else 1 if r == 500 else 0
                          for r in vectors[iv]) for iv in reps}
    order = {row["ivs"]: index for index, row in enumerate(recommendations)}
    def covers(other, iv):
        a, b = outcomes[other], outcomes[iv]
        return (all(x >= y for x, y in zip(a, b))
                and (a != b or order[other] < order[iv]))
    kept = [row for row in recommendations
            if not any(covers(other["ivs"], row["ivs"])
                       for other in recommendations if other is not row)]
    covered = []
    for row in recommendations:
        if row in kept:
            continue
        covering = next(other for other in kept if covers(other["ivs"], row["ivs"]))
        covered.append({"ivs": row["ivs"], "covered_by": covering["ivs"],
                        "reason": "勝ち・引き分けの全条件が、残した1個体でカバーされています。",
                        "equivalent_candidates": row["equivalent_candidates"]})
    recommendations = kept
    # The full matrix/coverage audit stays unchanged, but copying to Pokémon GO
    # gets a small S-led selection rather than all minor specialist results.
    recommendations, held, additional = curate_for_box(
        recommendations, held, outcomes, vectors, cells, focus,
        english_name, candidate, search_string, shadow, limit=4, original_count=len(ivs))
    selected_ivs = {row["ivs"] for row in recommendations}
    # In box-first mode an old outcome-covering representative can itself be
    # deprioritized. Do not misleadingly claim that a hidden IV is covered by
    # an IV that the user was told to save.
    visible_covered = []
    for row in covered:
        if row["covered_by"] in selected_ivs:
            visible_covered.append(row)
        else:
            additional.append({
                "ivs": row["ivs"],
                "reason": "代表個体の役割と重複しますが、代表も今回の保存対象外です。",
                "equivalent_candidates": row["equivalent_candidates"],
            })
    covered = visible_covered
    order = {row["ivs"]: index for index, row in enumerate(recommendations)}
    # A surviving IV can look redundant when the UI shows a shared win.
    # Compare it to the MOST SIMILAR higher-ranked retained IV across all
    # opponents/modes/shields. A distinct outcome is required because otherwise
    # that higher-ranked IV would have covered the current one above.
    # Do not change selection or infer differences from sparse evidence lists.
    for position, row in enumerate(recommendations):
        earlier = recommendations[:position]
        if not earlier:
            row["comparison_peer"] = None
            row["comparison_differences"] = []
            row["comparison_difference_count"] = 0
            continue
        iv = row["ivs"]
        peer = max(earlier, key=lambda other: (
            sum(a == b for a, b in zip(outcomes[iv], outcomes[other["ivs"]])),
            order[other["ivs"]]))
        peer_iv = peer["ivs"]
        differences = []
        for index, (mode, shield, _, opponent) in enumerate(cells):
            if outcomes[iv][index] <= outcomes[peer_iv][index]:
                continue
            differences.append({
                "mode": mode, "shield": shield, "opponent": opponent,
                "rating": vectors[iv][index], "peer_rating": vectors[peer_iv][index],
                "focus": any(term.casefold() in opponent.casefold() for term in focus),
                "disadvantage": shield in SHIELDS[3:]})
        # Prefer meaningful conditions; show at most three different opponent
        # records, leaving the full recommendation evidence untouched.
        differences.sort(key=lambda e: (
            -int(e["focus"]), -int(e["disadvantage"]), -int(e["rating"] > 500),
            -e["rating"], MODES.index(e["mode"]),
            SHIELDS.index(e["shield"]), e["opponent"]))
        seen_opponents = set()
        selected = []
        for evidence in differences:
            if evidence["opponent"] in seen_opponents:
                continue
            seen_opponents.add(evidence["opponent"])
            selected.append(evidence)
            if len(selected) == 3:
                break
        row["comparison_peer"] = peer_iv
        row["comparison_differences"] = selected
        row["comparison_difference_count"] = len(differences)
    for rank, row in enumerate(recommendations, 1):
        row["rank"] = rank
    matched_focus = [x for x in focus if any(x.casefold() in name.casefold() for _, _, _, name in cells)]
    return {"format": "app-recommendations-v1", "complete": True, "policy": asdict(rules),
            "explanation_version": "pairwise-v1",
            "grade_source": "project rule-based provisional candidates", "candidate": candidate,
            "english_name": english_name, "candidate_count": len(ivs),
            "candidate_ivs": ivs,
            "mode_count": len(matrices), "condition_count": len(matrices) * 6,
            "total_ratings_checked": len(cells) * len(ivs),
            "focus_opponents": focus, "unmatched_focus": [x for x in focus if x not in matched_focus],
            "recommendations": recommendations, "review_candidates": held,
            "additional_candidates": additional,
            "covered_candidates": covered,
            "dominated_by": {iv: by for iv, by in dominated.items() if by},
            "excluded": matrices["default"].manifest.get("excluded"),
            "counts_estimated_from_rating": True}


def recommendations_from_zip(archive: ZipFile, candidate: dict, english_name: str,
                             batch_mode: str, focus_opponents=None, policy=None) -> dict:
    if batch_mode not in ("simple", "detailed"):
        raise ValueError("batch_mode must be simple or detailed")
    modes = ("default",) if batch_mode == "simple" else MODES
    selection = recommend({mode: load_selection_matrix(archive, mode) for mode in modes},
                          candidate, english_name, focus_opponents, policy)
    if not str(candidate.get('species', '')).lower().startswith('minior'):
        return selection
    # The oracle scores are only an optimistic experimental comparison of
    # three fixed tactical policies. Never hide that from someone deciding
    # which physical Pokemon to keep.
    name = 'minior_strategy_evidence.json'
    if name not in archive.namelist():
        raise ValueError('メテノ戦術比較データが欠けています。古い計算結果を推薦に使用しません')
    evidence = json.loads(archive.read(name).decode('utf-8'))
    if evidence.get('version') != 'experimental-max-per-matchup-v1' or not isinstance(evidence.get('rows'), list):
        raise ValueError('メテノ戦術比較データの形式が不正です')
    rows = evidence['rows']
    valid_ivs = set(selection['candidate_ivs'])
    expected = len(valid_ivs) * len(modes) * 6 * len(load_selection_matrix(archive, modes[0]).opponents)
    if len(rows) != expected or any(
        entry.get('candidate_iv') not in valid_ivs or
        entry.get('selected') not in ('instant', 'hold', 'adaptive') or
        not all(type(entry.get(key)) in (int, float) and 0 <= entry[key] <= 1000
                for key in ('rating', 'instant', 'hold', 'adaptive')) or
        entry['rating'] != max(entry['instant'], entry['hold'], entry['adaptive'])
        for entry in rows
    ):
        raise ValueError('メテノ戦術比較データが計算条件と一致しません')
    for recommendation in selection['recommendations']:
        iv_rows = [entry for entry in rows if entry['candidate_iv'] == recommendation['ivs']]
        hold_flips = [entry for entry in iv_rows if entry['hold'] > 500 >= entry['instant']]
        smart_flips = [entry for entry in iv_rows if entry['adaptive'] > 500 >= max(entry['instant'], entry['hold'])]
        examples = sorted(hold_flips, key=lambda e: (
            -int(e['selected'] == 'hold'), -(e['hold'] - e['instant']),
            e['opponent'], e['shield']))[:3]
        recommendation['minior_strategy'] = {
            'hold_win_flip_count': len(hold_flips),
            'adaptive_win_flip_count': len(smart_flips),
            'hold_win_flip_examples': [{
                'opponent': e['opponent'], 'shield': e['shield'],
                'instant': e['instant'], 'hold': e['hold'],
            } for e in examples],
        }
    selection['minior_experimental'] = {
        'version': evidence['version'],
        'verified_live': False,
        'optimistic_oracle': True,
        'note': '各対面の戦術を後から選んだ上限評価です。実機のCP・レベル変動と戦術再現性は未検証です。',
    }
    return selection

