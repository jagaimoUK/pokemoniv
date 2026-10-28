"""Read-only, nonpersonal low-score search contract for the Android reader.

No app cookie, API key, ranking score dump, IV history, or MCP access is
needed. The backend compiles conditions from the same fixed snapshot that
powers the authenticated Web diagnostics page.
"""
from pvpoke_score_search import search_low_scores


def reader_cleanup_payload(species_catalog):
    result = search_low_scores(
        {"mode": "practical", "threshold": 70, "exclude_favorites": True},
        species_catalog,
    )
    items = [
        {"search": row["query"], "confidence": "ranked"}
        for row in result["queries"]
    ]
    # An unranked basic-stage Pokémon is a *review suggestion*, NEVER
    # labelled a proven low-score Pokémon or mixed with ranked groups.
    items += [
        {"search": row["query"], "confidence": "unranked_review"}
        for row in result["unranked_queries"]
    ]
    if not items:
        raise ValueError("安全に表現できる検索式がありません。ランキングと図鑑を確認してください")
    if len(items) > 10000 or any(
        len(item["search"]) > 2000 or not item["search"] for item in items
    ):
        raise ValueError("検索式の件数またはサイズの制限を超えました")
    return {
        "format": "pokemoniv-search-queue-v1",
        "source_date": result["source_date"],
        "mode": "practical",
        "threshold": 70,
        "excluded_favorites": True,
        "items": items,
        "verified_query_count": len(result["queries"]),
        "review_query_count": len(result["unranked_queries"]),
        "verified_species_count": result["searchable_count"],
        "review_species_count": result["unranked_review_count"],
        "exclusion_reasons": result["exclusion_reasons"],
        "review_examples": result["unranked_review"][:30],
        "notice": ("検索式は候補の確認用で、博士送りを保証しません。"
                   "未掲載候補はスコア未評価のため、通常検索式とは分けています。"
                   "Pokémon GOのShow Evolutionary LineはOFF推奨。"),
    }
