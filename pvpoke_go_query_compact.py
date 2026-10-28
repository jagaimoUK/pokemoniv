"""Lossless Pokémon GO search compaction. Only logically complementary
status / region filters may be removed for the same named species and CP.
A full OR-of-AND cannot be expressed as one GO query.
"""
from collections import defaultdict

COMPLEMENTABLE = ("shadow", "alola", "galar", "hisui", "paldea")
MAX_QUERY_LENGTH = 950  # GO automatic input rejects >1024 characters.
MAX_TERMS = 90


def compact_search_groups(rows, max_length=MAX_QUERY_LENGTH):
    if not 1 <= max_length <= 1024:
        raise ValueError("検索式の上限が不正です")
    per_name = defaultdict(set)
    for row in rows:
        query = row["query"]
        names, *suffix = query.split("&")
        if not names or not suffix or len(suffix) != len(set(suffix)) or not any(
                token.startswith("cp") for token in suffix):
            raise ValueError("検索式を安全に分解できません")
        # Reader searches include favorites even if an old browser row does not.
        filters = frozenset(token for token in suffix if token != "!favorite")
        for name in names.split(","):
            if not name or any(c in name for c in "&,\r\n"):
                raise ValueError("検索対象名が不正です")
            per_name[name].add(filters)

    for clauses in per_name.values():
        while True:
            merged = False
            for clause in sorted(clauses, key=lambda x: (len(x), tuple(sorted(x)))):
                for field in COMPLEMENTABLE:
                    for positive, negative in ((field, "!" + field), ("!" + field, field)):
                        if positive not in clause:
                            continue
                        other = (clause - {positive}) | {negative}
                        if other not in clauses:
                            continue
                        clauses.remove(clause)
                        clauses.remove(other)
                        clauses.add(clause - {positive})
                        merged = True
                        break
                    if merged:
                        break
                if merged:
                    break
            if not merged:
                break

    by_suffix = defaultdict(set)
    for name, clauses in per_name.items():
        for suffix in clauses:
            by_suffix[frozenset(suffix)].add(name)

    def sort_filter(token):
        return (2 if token.startswith("cp") else
                1 if token.lstrip("!") == "shadow" else 0, token)

    result = []
    for filters, names in sorted(by_suffix.items(),
                                 key=lambda pair: (len(pair[0]), sorted(pair[0]))):
        tail = "&" + "&".join(sorted(filters, key=sort_filter))
        chunk = []
        for name in sorted(names):
            candidate = ",".join((*chunk, name)) + tail
            if chunk and (len(chunk) == MAX_TERMS or len(candidate) > max_length):
                result.append({"query": ",".join(chunk) + tail,
                               "species_count": len(chunk)})
                chunk = []
                candidate = name + tail
            if len(candidate) > max_length:
                raise ValueError("検索式の文字数制限を超えました")
            chunk.append(name)
        if chunk:
            result.append({"query": ",".join(chunk) + tail,
                           "species_count": len(chunk)})
    return sorted(result, key=lambda row: (-row["species_count"], row["query"]))
