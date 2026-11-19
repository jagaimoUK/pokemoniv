"""Per-tournament eligibility rules separate from global simulator analyzability."""
from __future__ import annotations

import re
from types import MappingProxyType

_MINIOR_RE = re.compile(r"^minior(?:$|[_-])", re.IGNORECASE)

RULESETS = MappingProxyType({
    "play-pokemon-worlds-2026-gl": MappingProxyType({
        "tournament_name": "2026 Pokémon GO World Championships",
        "event_dates": "2026-08-28..2026-08-30",
        "location": "San Francisco, CA",
        "cp_cap": 1500,
        "species_clause": True,
        "banned_species": frozenset(("ditto", "shedinja", "mimikyu")),
        "ban_list_scope": "verified_subset_not_exhaustive",
        "rules_url": "https://www.pokemon.com/us/play-pokemon/about/tournaments-rules-and-resources",
        "handbook_url": "https://www.pokemon.com/static-assets/content-assets/cms2/pdf/play-pokemon/rules/play-pokemon-pokemon-go-tournament-handbook-en.pdf",
        "banned_list_url": "https://www.pokemon.com/us/play-pokemon/about/play-pokemon-pokemon-go-championship-series-banned-pokemon-list",
        "results_url": "https://www.pokemon.com/us/play-pokemon/worlds/2026/pokemon-go-results",
    }),
    "play-pokemon-cs-2026-11-16-gl": MappingProxyType({
        "tournament_name": "Play! Pokémon Pokémon GO Championship Series (effective 2026-11-16)",
        "event_dates": "2026-11-16+",
        "cp_cap": 1500,
        "species_clause": True,
        "banned_species": frozenset(("ditto", "shedinja")),
        "ban_list_scope": "verified_subset_not_exhaustive",
        "rules_url": "https://www.pokemon.com/us/play-pokemon/about/tournaments-rules-and-resources",
        "handbook_url": "https://www.pokemon.com/static-assets/content-assets/cms2/pdf/play-pokemon/rules/play-pokemon-pokemon-go-tournament-handbook-en.pdf",
        "banned_list_url": "https://www.pokemon.com/us/play-pokemon/about/play-pokemon-pokemon-go-championship-series-banned-pokemon-list",
        "update_url": "https://www.pokemon.com/uk/news/battle-with-mimikyu-in-the-play-pokemon-pokemon-go-championship-series",
    }),
    "great-league-v1": MappingProxyType({
        "tournament_name": "Open Great League (Unrestricted Simulator Ruleset)",
        "cp_cap": 1500,
        "species_clause": True,
        "banned_species": frozenset(),
        "ban_list_scope": "none",
    }),
})


def get_ruleset(ruleset_id):
    """Return a mutable copy of the registered ruleset metadata."""
    if type(ruleset_id) is not str or ruleset_id not in RULESETS:
        raise ValueError(f"Unknown ruleset: {ruleset_id!r}")
    return dict(RULESETS[ruleset_id])


def evaluate_tournament_eligibility(species_id, ruleset_id):
    """Check whether a species is legal under a specific tournament ruleset."""
    if type(species_id) is not str or not species_id:
        raise ValueError("Invalid species_id")
    ruleset = get_ruleset(ruleset_id)
    banned = species_id.lower() in ruleset["banned_species"]
    return {
        "species": species_id,
        "ruleset_id": ruleset_id,
        "tournament_eligible": not banned,
        "reason": "banned_in_ruleset" if banned else "allowed",
    }


def evaluate_simulator_analyzability(species_id, pokemon_by_id):
    """Check whether the native simulator can model a species regardless of tournament bans."""
    if type(species_id) is not str or not species_id:
        raise ValueError("Invalid species_id")
    entry = pokemon_by_id.get(species_id)
    if entry is None:
        return {
            "species": species_id,
            "simulator_analyzable": False,
            "reason": "missing_from_gamemaster",
        }
    tags = entry.get("tags") or ()
    if entry.get("formChange") or "mega" in tags or _MINIOR_RE.match(species_id):
        return {
            "species": species_id,
            "simulator_analyzable": False,
            "reason": "unsupported_engine_mechanic",
        }
    return {
        "species": species_id,
        "simulator_analyzable": True,
        "reason": "supported",
    }


def validate_team_for_ruleset(team_rows, ruleset_id):
    """Validate CP cap, species clause, and tournament bans for a team roster."""
    ruleset = get_ruleset(ruleset_id)
    if not isinstance(team_rows, (list, tuple)) or not team_rows:
        raise ValueError("Nonempty team required")
    seen_species = set()
    seen_clauses = set()
    for row in team_rows:
        if type(row) is not dict:
            raise ValueError("Invalid team member row")
        cp = row.get("cp")
        if type(cp) is not int or not 10 <= cp <= ruleset["cp_cap"]:
            raise ValueError(f"Team member exceeds CP cap for {ruleset_id}: {cp!r}")
        eligibility = evaluate_tournament_eligibility(row.get("species"), ruleset_id)
        if not eligibility["tournament_eligible"]:
            raise ValueError(f"{eligibility['species']} is banned in {ruleset_id}")
        if ruleset["species_clause"]:
            species = row["species"]
            clause = row.get("roster_clause_id", species)
            if species in seen_species or clause in seen_clauses:
                raise ValueError(f"Duplicate species clause entry in {ruleset_id}: {species}")
            seen_species.add(species)
            seen_clauses.add(clause)
