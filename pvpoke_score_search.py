"""Pokémon GO low-score box search from a pinned seven-role ranking snapshot.

No PvPoke battles are run, and no deletion is performed. Searches are kept
conservative: species forms that cannot be expressed safely in Pokémon GO
are surfaced for manual review rather than silently broadened.
"""
from __future__ import annotations

from pvpoke_go_search import species_search_term

from functools import lru_cache
import json
import math
from pathlib import Path
import re

DATA_PATH = Path(__file__).resolve().parent / "data" / "cp1500_role_scores_20261015.json"
EVOLUTIONS_PATH = Path(__file__).resolve().parent / "data" / "pokemon_species_evolutions_20261019.json"
ROLES = ("overall", "leads", "closers", "switches", "chargers", "attackers", "consistency")
PRESETS = {
    "practical": ("overall", "leads", "closers", "switches", "chargers", "attackers"),
    "overall": ("overall",),
    "battle": ("overall", "leads", "closers", "switches"),
    "strict": ROLES,
}
REGIONAL = {"アローラ": "alola", "ガラル": "galar", "ヒスイ": "hisui", "パルデア": "paldea"}
# Keep one search per shared status/form/CP condition whenever practical.
# The Android search-only overlay accepts up to 2,000 characters per query;
# stay comfortably below that bound and split only when necessary.
MAX_QUERY_CHARS = 1200
MAX_NAMES_PER_QUERY = 90


@lru_cache(maxsize=1)
def load_snapshot():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if (raw.get("schema") != "pvpoke-role-scores-v1"
            or raw.get("columns") != ["name", "dex", *ROLES]):
        raise ValueError("ランキングデータの形式が一致しません")
    entries = []
    seen = set()
    for fields in raw["rows"]:
        if len(fields) != 9 or not isinstance(fields[0], str) or fields[0] in seen:
            raise ValueError("重複・不正なランキング行があります")
        name, dex, *scores = fields
        if not name or not isinstance(dex, int) or any(
                isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or not 0 <= value <= 100
                for value in scores):
            raise ValueError("ランキングの種名またはスコアが不正です")
        entries.append({"name": name, "dex": dex,
                        **dict(zip(ROLES, scores))})
        seen.add(name)
    return raw["source_date"], entries



@lru_cache(maxsize=1)
def evolution_descendants():
    """Full forward evolution chain keyed by National Pokédex number.

    Unknown branches fail closed: we never assume an unranked evolved Pokémon
    is bad enough to include its pre-evolution in the cleanup list.
    """
    raw = json.loads(EVOLUTIONS_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != "pokemon-species-evolution-v1":
        raise ValueError("進化系統データを確認できません")
    children = {}
    seen = set()
    for dex, parent in raw["nodes"]:
        if not isinstance(dex, int) or dex < 1 or dex in seen:
            raise ValueError("進化系統の図鑑番号が不正です")
        seen.add(dex)
        if parent is not None:
            if not isinstance(parent, int) or parent < 1 or parent == dex:
                raise ValueError("進化系統の親番号が不正です")
            children.setdefault(parent, set()).add(dex)
    if not all(parent in seen for parent in children):
        raise ValueError("進化系統データに欠損があります")
    result = {}
    for dex in seen:
        visited, queue = set(), list(children.get(dex, ()))
        while queue:
            child = queue.pop()
            if child == dex or child in visited:
                continue
            visited.add(child)
            queue.extend(children.get(child, ()))
        result[dex] = tuple(sorted(visited))
    return result


def _stats_by_dex(species_catalog):
    """Extremes across all forms, preventing optimistic CP thresholds."""
    result = {}
    for row in (species_catalog or {}).values():
        if not isinstance(row, dict):
            continue
        dex, base = row.get("dex"), row.get("baseStats")
        if isinstance(dex, bool) or not isinstance(dex, int) or not isinstance(base, dict):
            continue
        if any(isinstance(base.get(k), bool) or not isinstance(base.get(k), (int, float))
               or not math.isfinite(base[k]) or base[k] <= 0 for k in ("atk", "def", "hp")):
            continue
        old = result.get(dex, [])
        old.append((float(base["atk"]), float(base["def"]), float(base["hp"])))
        result[dex] = old
    return result


def _certainly_over_cap_cp(dex, descendants, stats, cp_cap=1500):
    """Find a source CP where *every possible* evolved form exceeds CP cap.

    CP floats are monotonic in same-level IVs. Min evolved numerator divided
    by MAX unevolved numerator provides a safe (possibly conservative) floor.
    This cannot rely on a single form, rank-1 IV or guessed source level.
    """
    sources = stats.get(dex)
    if not sources or any(not stats.get(child) for child in descendants):
        return None
    src_atk = max(x[0] for x in sources) + 15
    src_def = max(x[1] for x in sources) + 15
    src_hp = max(x[2] for x in sources) + 15
    lower = 1.0
    limits = []
    for child in descendants:
        ratio = min(
            a / src_atk * math.sqrt(d / src_def) * math.sqrt(h / src_hp)
            for a, d, h in stats[child]
        )
        if ratio <= 0:
            return None
        # Use a strictly greater integer threshold to absorb rounding error.
        limits.append(math.floor((cp_cap + 1) / ratio) + 1)
    if not limits:
        return None
    cutoff = max(limits)
    return cutoff if 1 <= cutoff <= cp_cap else None

def english_names_by_dex(species_catalog):
    """Resolve English base names using GameMaster dex, never Japanese transliteration.

    More than one distinct base name for the same dex is ambiguous. Return
    no value for that dex instead of guessing or leaking a Japanese term.
    """
    possible = {}
    if not isinstance(species_catalog, dict):
        return {}
    for species_id, row in species_catalog.items():
        if not isinstance(row, dict):
            continue
        dex = row.get("dex")
        english = row.get("name")
        if (isinstance(dex, bool) or not isinstance(dex, int)
                or not isinstance(english, str) or not english.strip()):
            continue
        # GameMaster uses parenthetical form labels and sometimes regional
        # prefixes. Pokémon GO needs the species name plus &region instead.
        english = re.sub(r"\s*\([^()]*\)", "", english).strip()
        english = re.sub(r"^(?:Alolan|Galarian|Hisuian|Paldean)\s+", "",
                         english, flags=re.I)
        english = re.sub(r"\s+(?:Alolan|Galarian|Hisuian|Paldean)$", "",
                         english, flags=re.I)
        if (not english or any(ch in english for ch in ",:;|&!\n\r")
                or re.search(r"[\u3040-\u30ff\u3400-\u9fff]", english)):
            continue
        possible.setdefault(dex, set()).add(english)
    # A unique, validated base English name is required per dex.
    return {dex: next(iter(names)) for dex, names in possible.items()
            if len({name.casefold() for name in names}) == 1}


def _search_term(entry, forms_by_dex, english_species):
    """Return (literal species search, identical-filter suffix) or manual reason.

    Commas in Pokémon GO bind before ampersands, so it is NOT safe to join
    arbitrary 'name&status' combinations with commas.
    """
    name = entry["name"]
    labels = re.findall(r"\(([^()]*)\)", name)
    species = species_search_term(english_species)
    shadow = "シャドウ" in labels
    regions = [REGIONAL[x] for x in labels if x in REGIONAL]
    unknown = [x for x in labels if x != "シャドウ" and x not in REGIONAL]
    if unknown or len(regions) > 1:
        return None, "検索式で姿・性別を厳密に区別できません"
    if not species or any(c in species for c in ",:;|&!\n\r"):
        return None, "検索文字列に使えない文字があります"
    suffix = []
    if regions:
        suffix.append(regions[0])
    else:
        # Avoid matching stronger regional versions through the plain name.
        for region in sorted(forms_by_dex.get(entry["dex"], set())):
            suffix.append("!" + region)
    suffix.append("shadow" if shadow else "!shadow")
    return (species, tuple(suffix)), None


def search_low_scores(params=None, species_catalog=None):
    args = params if isinstance(params, dict) else {}
    mode = args.get("mode", "practical")
    if mode not in PRESETS:
        raise ValueError("検索基準が不正です")
    threshold = args.get("threshold", 70)
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 1 <= threshold <= 100):
        raise ValueError("スコアの上限は1～100で指定してください")
    exclude_favorites = args.get("exclude_favorites", True)
    if not isinstance(exclude_favorites, bool):
        raise ValueError("お気に入り除外の指定が不正です")
    # Reader-only conservative mode: if evolving the same species could make
    # its retention depend on today's CP, omit the *whole species* instead.
    exclude_cp_dependent = args.get("exclude_cp_dependent", False)
    if not isinstance(exclude_cp_dependent, bool):
        raise ValueError("CP依存種の除外指定が不正です")
    source_date, all_rows = load_snapshot()
    roles = PRESETS[mode]
    selected = [x for x in all_rows if all(x[k] < threshold for k in roles)]
    selected.sort(key=lambda r: (r["overall"], r["name"]))
    forms_by_dex = {}
    for r in all_rows:
        for regional_ja, keyword in REGIONAL.items():
            if "(" + regional_ja + ")" in r["name"]:
                forms_by_dex.setdefault(r["dex"], set()).add(keyword)

    english_by_dex = english_names_by_dex(species_catalog)
    descendants_map = evolution_descendants()
    ranked_by_dex = {}
    for entry in all_rows:
        ranked_by_dex.setdefault(entry["dex"], []).append(entry)
    stats = _stats_by_dex(species_catalog)
    groups = {}
    manual = []
    evolution_protected = []
    high_cp_exceptions = []
    cp_dependent_excluded = []
    directly_searchable_by_dex = {}
    for entry in selected:
        if entry["dex"] not in descendants_map:
            evolution_protected.append({
                "name": entry["name"], "reason": "進化系統データを確認できません",
                "evolves_to": ["要確認"]
            })
            continue
        # Protect every later stage, including alternative branches and
        # intermediate evolutions, regardless of the source's weak rating.
        descendant_ids = descendants_map.get(entry["dex"], ())
        relevant = [
            d for d in descendant_ids
            if d not in ranked_by_dex or any(
                row[k] >= threshold for row in ranked_by_dex[d]
                for k in PRESETS["practical"])
        ]
        cp_cutoff = None
        if relevant:
            cp_cutoff = _certainly_over_cap_cp(entry["dex"], relevant, stats)
            if cp_cutoff is None:
                evolution_protected.append({
                    "name": entry["name"],
                    "reason": "進化先に高スコア・未評価の種類があり、CP1500超過を保証できません",
                    "evolves_to": [ranked_by_dex[d][0]["name"] if d in ranked_by_dex
                                   else "図鑑No." + str(d) for d in relevant]
                })
                continue
            if exclude_cp_dependent:
                # A high-CP version is eligible for cleanup, a lower-CP
                # version may still evolve into a useful GL Pokémon.
                # Keep both out of the automatic cleanup list as requested.
                cp_dependent_excluded.append({
                    "name": entry["name"], "dex": entry["dex"],
                    "minimum_cp": cp_cutoff,
                    "reason": "現在CPによって進化先のCP1500以下の可能性が変わるため、種類ごと検索から除外",
                    "evolves_to": [ranked_by_dex[d][0]["name"] if d in ranked_by_dex
                                   else "図鑑No." + str(d) for d in relevant],
                })
                continue
            high_cp_exceptions.append({"name": entry["name"], "minimum_cp": cp_cutoff})
        english = english_by_dex.get(entry["dex"])
        if english is None:
            item, reason = None, "図鑑データの英語名を照合できません"
        else:
            item, reason = _search_term(entry, forms_by_dex, english)
        if reason:
            manual.append({"name": entry["name"], "overall": entry["overall"],
                           "reason": reason})
        else:
            base, suffix = item
            cp_filter = ("cp" + str(cp_cutoff) + "-1500") if cp_cutoff else "cp-1500"
            suffix = (*suffix, cp_filter, *(("!favorite",) if exclude_favorites else ()))
            groups.setdefault(suffix, []).append((base, entry))
            directly_searchable_by_dex.setdefault(entry["dex"], []).append(
                {"name": entry["name"], "high_cp_only": cp_cutoff is not None}
            )

    # A missing ranking row is UNKNOWN, not a low score. Offer a clearly
    # labelled *review-only* search when its entire evolution chain is ranked
    # below the practical threshold. This covers Gothita (#574), whose own
    # score is absent in the pinned snapshot but whose evolutions are known.
    # Never merge these provisional candidates with verified low-score terms.
    unranked_groups = {}
    unranked_review = []
    unranked_with_unknown_evolution = 0
    unranked_with_strong_evolution = 0
    unranked_uncertain_form_or_name = 0
    if isinstance(species_catalog, dict):
        catalog_by_dex = {}
        for species_id, data in species_catalog.items():
            if isinstance(data, dict) and type(data.get("dex")) is int:
                catalog_by_dex.setdefault(data["dex"], []).append((species_id, data))
        for dex, variants in sorted(catalog_by_dex.items()):
            if dex in ranked_by_dex:
                continue
            descendants = descendants_map.get(dex, ())
            # Without ranked descendants there is no evidence of low PvP value.
            if not descendants or any(child not in ranked_by_dex for child in descendants):
                unranked_with_unknown_evolution += 1
                continue
            if any(row[role] >= threshold
                   for child in descendants
                   for row in ranked_by_dex[child]
                   for role in PRESETS["practical"]):
                unranked_with_strong_evolution += 1
                continue
            # A mixed regional / special-form dex cannot be selected by one
            # unequivocal search term. Only regular and shadow catalogue IDs
            # are accepted; shadows are excluded explicitly in GO.
            if any(
                (not isinstance(key, str)
                 or (key != key.split("_shadow")[0] and not key.endswith("_shadow"))
                 or re.search(r"(alolan|galarian|hisuian|paldean|mega|primal|origin|altered|female|male|costume|_)", key.casefold().removesuffix("_shadow")))
                for key, _ in variants
            ):
                unranked_uncertain_form_or_name += 1
                continue
            english = english_by_dex.get(dex)
            if not english or any(c in english for c in (",", ":", ";", "|", "&", "!", chr(10), chr(13))):
                unranked_uncertain_form_or_name += 1
                continue
            token = species_search_term(english)
            if not token:
                continue
            unranked_review.append({
                "name": english,
                "dex": dex,
                "reason": "元の種はランキング未掲載。進化先は全て実戦6項目が基準未満だが、元の強さは未評価なので要確認",
                "evolves_to": [ranked_by_dex[d][0]["name"] for d in descendants],
            })
            suffix = ("!shadow", "cp-1500", *(("!favorite",) if exclude_favorites else ()))
            unranked_groups.setdefault(suffix, []).append((token, None))

    # A one-copy search cannot express separate OR-of-AND conditions in GO.
    # Use exact National Dex terms ONLY for species where ALL known forms are
    # eligible, AND none need a special CP condition. Numeric terms reportedly
    # avoid the Show Evolutionary Line toggle's name-family expansion.
    # If any form is incomplete, uncertain or better ranked, omit the dex.
    catalog_form_counts = {}
    if isinstance(species_catalog, dict):
        for record in species_catalog.values():
            if isinstance(record, dict) and type(record.get("dex")) is int:
                dex = record["dex"]
                catalog_form_counts[dex] = catalog_form_counts.get(dex, 0) + 1
    safe_dex = []
    quick_covered_rows = 0
    for dex, ranked_forms in ranked_by_dex.items():
        included = directly_searchable_by_dex.get(dex, [])
        if (included and len(included) == len(ranked_forms)
                and len(ranked_forms) >= catalog_form_counts.get(dex, 1)
                and not any(row["high_cp_only"] for row in included)):
            safe_dex.append(dex)
            quick_covered_rows += len(included)
    safe_dex.sort()
    one_query = (",".join(map(str, safe_dex)) + "&cp-1500"
                 + ("&!favorite" if exclude_favorites else "")) if safe_dex else ""
    # The single search is always complete for its own conservative subset.
    # Never silently cut it to satisfy UI/import restrictions.
    if len(one_query) > MAX_QUERY_CHARS:
        one_query = ""
        quick_covered_rows = 0
        safe_dex = []

    def grouped_queries(source_groups):
        result = []
        for suffix, names in sorted(source_groups.items(), key=lambda g: (len(g[0]), g[0])):
            chunk = []
            for base, _entry in names:
                tentative = ",".join(chunk + [base]) + "&" + "&".join(suffix)
                if chunk and (len(chunk) >= MAX_NAMES_PER_QUERY
                              or len(tentative) > MAX_QUERY_CHARS):
                    result.append({"query": ",".join(chunk) + "&" + "&".join(suffix),
                                   "species_count": len(chunk)})
                    chunk = []
                chunk.append(base)
            if chunk:
                result.append({"query": ",".join(chunk) + "&" + "&".join(suffix),
                               "species_count": len(chunk)})
        return result

    queries = grouped_queries(groups)
    searched = sum(row["species_count"] for row in queries)
    unranked_queries = grouped_queries(unranked_groups)
    # No names should be silently excluded; the user needs all missing forms.
    if searched + len(manual) + len(evolution_protected) + len(cp_dependent_excluded) != len(selected):
        raise RuntimeError("検索対象の件数が合いません")
    for i, query in enumerate(queries, 1):
        query["index"] = i

    preserved = [x for x in all_rows
                 if x["overall"] < threshold and x not in selected]
    return {
        "source_date": source_date, "league": "cp1500", "mode": mode,
        "threshold": threshold, "excluded_favorites": exclude_favorites,
        "roles_checked": list(roles), "dataset_count": len(all_rows),
        "overall_under_threshold": sum(x["overall"] < threshold for x in all_rows),
        "selected_count": len(selected), "searchable_count": searched,
        "manual_review_count": len(manual), "manual_review": manual,
        "evolution_protected_count": len(evolution_protected),
        "evolution_protected": evolution_protected,
        "evolution_high_cp_count": len(high_cp_exceptions),
        "evolution_high_cp_exceptions": high_cp_exceptions,
        "cp_dependent_excluded_count": len(cp_dependent_excluded),
        "cp_dependent_excluded": cp_dependent_excluded,
        "queries": queries, "preserved_by_other_roles": len(preserved),
        "unranked_review_count": len(unranked_review),
        "unranked_review": unranked_review,
        "unranked_queries": unranked_queries,
        "unranked_unknown_evolution_count": unranked_with_unknown_evolution,
        "unranked_strong_evolution_count": unranked_with_strong_evolution,
        "unranked_uncertain_form_count": unranked_uncertain_form_or_name,
        "exclusion_reasons": {
            "specialist_preserved": len(preserved),
            "evolution_protected": len(evolution_protected),
            "form_or_name_unsearchable": len(manual),
            "cp_dependent_excluded": len(cp_dependent_excluded),
            "unranked_not_verified": unranked_with_unknown_evolution,
            "unranked_strong_evolution": unranked_with_strong_evolution,
            "unranked_uncertain_form_or_name": unranked_uncertain_form_or_name,
            "unranked_manual_review": len(unranked_review),
        },
        "quick_query": one_query,
        "quick_species_count": len(safe_dex),
        "quick_covered_rows": quick_covered_rows,
        "quick_omitted_rows": len(selected) - quick_covered_rows,
        "quick_requires_exact_dex": True,
        "selected_preview": [{"name": x["name"], "overall": x["overall"]}
                             for x in selected[:15]],
        "notice": "CP1500向けの保存済みランキングです。削除の安全性・他リーグでの性能は保証しません。",
    }
