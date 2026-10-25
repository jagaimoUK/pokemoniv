"""Pokémon GO query terms, separate from battle recommendation policy."""
import re
import unicodedata

from pvpoke_app_sizes import pumpkin_search


def species_search_term(name: str, species_id: str | None = None) -> str:
    """Flabébé uses its exact dex number to avoid accent/language ambiguity.

    This is a GO query token, not the displayed English name. Other species
    keep English names, and form/status filters remain separate.
    """
    root = re.split(r"[_-]", (species_id or "").casefold())[0]
    plain = "".join(c for c in unicodedata.normalize("NFD", name)
                    if not unicodedata.combining(c)).casefold().strip()
    return "669" if (root == "flabebe" or plain == "flabebe"
                     or unicodedata.normalize("NFKC", name).strip() == "フラベベ") else name


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
    # PvPoke UI names contain display-only form labels. GO species searches
    # do not accept literal "(Core)", "(Meteor)", "(Origin)", etc. as names.
    # Keep verified filters (region, pumpkin size, shadow) separate; for other
    # forms search broadly by the actual species name rather than return a
    # silently broken literal query. Internal species IDs remain unchanged.
    name = re.sub(r"(?:\s*[(（][^()（）]*[)）]\s*)+$", "", name).strip()
    if not name:
        raise ValueError("Pokémon GO search requires an unqualified species name")
    def bucket(x):
        return 0 if x == 0 else 1 if x <= 5 else 2 if x <= 10 else 3 if x < 15 else 4
    return species_search_term(name, species_id) + regional_filter + "".join(f"&{bucket(x)}{label}" for x, label in zip(values, ("attack", "defense", "hp"))) + size_filter + ("&shadow" if shadow else "")

