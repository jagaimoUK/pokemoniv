"""Common Mega Evolution / Primal Reversion foundation for species linking and CP evaluation."""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

_DEFAULT_POKEMON_JS = Path(__file__).resolve().parent / 'vendor' / 'pvpoke' / 'src' / 'js' / 'pokemon' / 'Pokemon.js'
_MEGA_SUFFIX_RE = re.compile(r'(?:_|-)(?:mega(?:_[xy])?|primal)$')

# Confirmed in vendor/pvpoke/src/js/battle/DamageCalculator.js (DamageMultiplier.MEGA_BONUS).
MEGA_MOVE_BONUSES = (1.0, 1.1000000238418579, 1.2000000476837158, 1.2999999523162842)
LEAGUE_CP_CAPS = {'great': 1500, 'ultra': 2500, 'master': 10000}
MEGA_DOWNSCALING_CUPS = frozenset({
    'great_mega', 'ultra_mega', 'mega_edition', 'mega_color', 'mega_catch', 'mega_halloween',
})
UNSCALED_CUPS = frozenset({'strict_unscaled', 'no_downscaling'})


def is_mega_form(species_id: str) -> bool:
    """Return True when species_id represents a Mega Evolution or Primal Reversion form."""
    if not isinstance(species_id, str) or not species_id:
        return False
    tokens = set(re.split(r'[_-]', species_id.casefold()))
    return bool(tokens & {'mega', 'primal'})


def is_shadow_form(species_id: str) -> bool:
    """Return True when species_id represents a Shadow Pokémon (cannot Mega Evolve)."""
    if not isinstance(species_id, str) or not species_id:
        return False
    return 'shadow' in re.split(r'[_-]', species_id.casefold())


def base_species_id(species_id: str) -> str:
    """Resolve the pre-Mega / base species ID for a Mega or Primal form."""
    if not isinstance(species_id, str) or not is_mega_form(species_id):
        return species_id
    return _MEGA_SUFFIX_RE.sub('', species_id)


def eligible_pre_evolutions(
    target_species_id: str,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Return non-Shadow pre-Mega and catalog-verified ancestor species IDs for target_species_id.

    Never fabricates cross-regional evolutions when family links are absent.
    """
    if not is_mega_form(target_species_id):
        return ()
    direct_base = base_species_id(target_species_id)
    if not direct_base or is_shadow_form(direct_base) or is_mega_form(direct_base):
        return ()

    chain: list[str] = [direct_base]
    if not species_catalog:
        return tuple(chain)

    reverse_parents: dict[str, list[str]] = {}
    for sid, row in species_catalog.items():
        if is_shadow_form(sid) or is_mega_form(sid) or not isinstance(row, Mapping):
            continue
        fam = row.get('family')
        if isinstance(fam, Mapping):
            for child in fam.get('evolutions') or ():
                if isinstance(child, str):
                    reverse_parents.setdefault(child, []).append(sid)

    visited = {direct_base}
    queue = [direct_base]
    while queue:
        cur = queue.pop(0)
        parents: list[str] = []
        row = species_catalog.get(cur)
        if isinstance(row, Mapping):
            fam = row.get('family')
            if isinstance(fam, Mapping):
                parent = fam.get('parent')
                if isinstance(parent, str):
                    parents.append(parent)
        parents.extend(reverse_parents.get(cur, ()))
        for parent in parents:
            if (parent in visited or is_shadow_form(parent) or is_mega_form(parent)
                    or parent not in species_catalog):
                continue
            visited.add(parent)
            chain.append(parent)
            queue.append(parent)
    return tuple(chain)


def can_mega_evolve(
    owned_species_id: str,
    mega_species_id: str,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    """Return True iff owned_species_id can evolve into mega_species_id (excluding Shadow forms)."""
    if not is_mega_form(mega_species_id) or is_shadow_form(owned_species_id) or is_mega_form(owned_species_id):
        return False
    return owned_species_id in eligible_pre_evolutions(mega_species_id, species_catalog)


def mega_forms_for_base(
    owned_species_id: str,
    species_ids: Sequence[str] | set[str],
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """List Mega/Primal form IDs in species_ids that the given owned species can reach."""
    if is_shadow_form(owned_species_id) or is_mega_form(owned_species_id):
        return []
    return sorted(sid for sid in species_ids if can_mega_evolve(owned_species_id, sid, species_catalog))


def resolve_battle_rules(rules: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve league CP cap, level cap, and explicit Mega downscaling allowance from rules.

    Never infers league or cp_cap from a combatant's CP value.
    """
    if rules is None:
        return {
            'league': None,
            'cup_id': None,
            'cp_cap': None,
            'max_level': 50.0,
            'allow_cp_downscaling': None,
            'rule_explicit': False,
        }
    if not isinstance(rules, Mapping):
        raise ValueError('rules must be a mapping')
    league = rules.get('league')
    cup_id = rules.get('cup_id')
    raw_cap = rules.get('cp_cap')
    if raw_cap is not None:
        if isinstance(raw_cap, bool) or not isinstance(raw_cap, int) or not 10 <= raw_cap <= 10000:
            raise ValueError(f'Invalid cp_cap in rules: {raw_cap}')
        cp_cap: int | None = raw_cap
    elif isinstance(league, str) and league in LEAGUE_CP_CAPS:
        cp_cap = LEAGUE_CP_CAPS[league]
    else:
        cp_cap = None

    raw_max_level = rules.get('max_level', 50.0)
    if isinstance(raw_max_level, bool) or not isinstance(raw_max_level, (int, float)) or not 1 <= raw_max_level <= 100:
        raise ValueError(f'Invalid max_level in rules: {raw_max_level}')
    max_level = float(raw_max_level)

    if 'allow_cp_downscaling' in rules and rules['allow_cp_downscaling'] is not None:
        if type(rules['allow_cp_downscaling']) is not bool:
            raise ValueError('allow_cp_downscaling must be a bool when specified')
        allow_downscale: bool | None = rules['allow_cp_downscaling']
        explicit_downscale = True
    elif cup_id in MEGA_DOWNSCALING_CUPS:
        allow_downscale = True
        explicit_downscale = True
    elif cup_id in UNSCALED_CUPS:
        allow_downscale = False
        explicit_downscale = True
    else:
        allow_downscale = None
        explicit_downscale = False

    return {
        'league': league,
        'cup_id': cup_id,
        'cp_cap': cp_cap,
        'max_level': max_level,
        'allow_cp_downscaling': allow_downscale,
        'rule_explicit': cp_cap is not None and explicit_downscale,
    }


@lru_cache(maxsize=4)
def load_cpms(pokemon_js_path: str | None = None) -> tuple[float, ...]:
    """Load the exact PvPoke CPM table from Pokemon.js."""
    path = Path(pokemon_js_path) if pokemon_js_path else _DEFAULT_POKEMON_JS
    raw = path.read_bytes()
    match = re.search(rb'\bvar\s+cpms\s*=\s*\[([^\]]+)\]', raw)
    if not match:
        raise ValueError(f'PvPoke CPM table missing in {path}')
    return tuple(float(value) for value in match[1].split(b','))


def cpm_for_level(level: float, cpms: Sequence[float] | None = None) -> float:
    """Return the CP multiplier for a half-level increment (1.0 .. max)."""
    table = cpms if cpms is not None else load_cpms()
    doubled = int(round(level * 2))
    if abs(level * 2 - doubled) > 1e-6 or doubled < 2:
        raise ValueError(f'Level must be in half-level increments >= 1.0: {level}')
    idx = doubled - 2
    if idx >= len(table):
        raise ValueError(f'Level {level} exceeds CPM table max {(len(table) + 1) / 2}')
    return float(table[idx])


def compute_cp(base_stats: Mapping[str, Any], ivs: Mapping[str, Any], level: float, cpms: Sequence[float] | None = None) -> int:
    """Compute Pokémon GO CP from base stats, IVs, and level."""
    cpm = cpm_for_level(level, cpms)
    atk = float(base_stats['atk']) + int(ivs['attack'])
    defn = float(base_stats['def']) + int(ivs['defense'])
    hp = float(base_stats['hp']) + int(ivs['hp'])
    raw = (atk * math.sqrt(defn) * math.sqrt(hp) * (cpm ** 2)) / 10.0
    return max(10, math.floor(raw))


def max_level_and_cp(
    base_stats: Mapping[str, Any],
    ivs: Mapping[str, Any],
    *,
    cp_cap: int = 1500,
    max_level: float = 50.0,
    cpms: Sequence[float] | None = None,
) -> tuple[float, int] | None:
    """Find the highest half-level <= max_level whose CP does not exceed cp_cap."""
    table = cpms if cpms is not None else load_cpms()
    top_doubled = min(int(round(max_level * 2)), len(table) + 1)
    for doubled in range(top_doubled, 1, -1):
        lvl = doubled / 2.0
        cp = compute_cp(base_stats, ivs, lvl, table)
        if cp <= cp_cap:
            return lvl, cp
    return None


def evaluate_owned_for_mega(
    owned_record: Mapping[str, Any],
    *,
    mega_species_id: str,
    base_stats: Mapping[str, Any],
    mega_stats: Mapping[str, Any],
    owned_stats: Mapping[str, Any] | None = None,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
    target_level: float | None = None,
    cp_cap: int | None = None,
    max_level: float | None = None,
    cpms: Sequence[float] | None = None,
    allow_cp_downscaling: bool | None = None,
    rules: Mapping[str, Any] | None = None,
    mega_level: int = 3,
    super_max_cp_mode: str = 'none',
) -> dict[str, Any]:
    """Evaluate a pre-Mega or pre-evolution individual for mega_species_id under explicit rules.

    Separates:
      1. actual_owned: current species/PL/CP as observed
      2. mega_theoretical: theoretical Mega form PL/CP and pre-Mega equivalents
      3. battle_effective: effective battle-time PL/CP (accounting for downscaling only when confirmed)
    Super MAX PL+2 hypotheses are kept unconfirmed and never guessed into battle CP.
    """
    if type(mega_level) is not int or not 1 <= mega_level <= 4:
        raise ValueError(f'mega_level must be an integer 1..4: {mega_level}')

    resolved = resolve_battle_rules(rules)
    effective_cap = cp_cap if cp_cap is not None else resolved['cp_cap']
    effective_max_level = float(max_level) if max_level is not None else resolved['max_level']
    effective_allow_downscale = (
        allow_cp_downscaling if allow_cp_downscaling is not None else resolved['allow_cp_downscaling']
    )

    mega_condition = {
        'mega_level': mega_level,
        'move_bonus_multiplier': MEGA_MOVE_BONUSES[mega_level - 1],
        'super_max_cp_mode': super_max_cp_mode,
        'super_max_cp_applied': False,
        'super_max_pl_hypothesis_status': 'unconfirmed_deferred' if mega_level == 4 else 'not_applicable',
    }

    owned_species = owned_record.get('species_id', '')
    if not can_mega_evolve(owned_species, mega_species_id, species_catalog):
        return {
            'eligible': False,
            'reason': 'incompatible_species',
            'downscaled': False,
            'needs_power_up': False,
            'needs_evolution': False,
            'mega_condition': mega_condition,
        }

    direct_base = base_species_id(mega_species_id)
    needs_evolution = owned_species != direct_base
    current_level = owned_record.get('current_level')
    current_cp = owned_record.get('current_cp')

    if effective_cap is None:
        return {
            'eligible': None,
            'reason': 'cp_cap_rule_required',
            'downscaled': None,
            'needs_power_up': None,
            'needs_evolution': needs_evolution,
            'base_species_id': direct_base,
            'mega_species_id': mega_species_id,
            'actual_owned': {
                'species_id': owned_species,
                'level': float(current_level) if current_level is not None else None,
                'cp': int(current_cp) if current_cp is not None else None,
                'cp_level_consistent': None,
            },
            'mega_condition': mega_condition,
        }

    if super_max_cp_mode not in ('none', 'unconfirmed'):
        return {
            'eligible': None,
            'reason': 'super_max_cp_unconfirmed',
            'downscaled': None,
            'needs_power_up': None,
            'needs_evolution': needs_evolution,
            'base_species_id': direct_base,
            'mega_species_id': mega_species_id,
            'mega_condition': mega_condition,
        }

    table = cpms if cpms is not None else load_cpms()
    ivs = owned_record['ivs']
    mega_cap = max_level_and_cp(mega_stats, ivs, cp_cap=effective_cap, max_level=effective_max_level, cpms=table)
    if mega_cap is None:
        return {
            'eligible': False,
            'reason': 'mega_never_fits_cap',
            'downscaled': False,
            'needs_power_up': False,
            'needs_evolution': needs_evolution,
            'mega_condition': mega_condition,
        }

    mega_max_level, mega_max_cp = mega_cap
    effective_level = float(target_level) if target_level is not None else mega_max_level
    effective_mega_cp = compute_cp(mega_stats, ivs, effective_level, table)
    if effective_mega_cp > effective_cap:
        return {
            'eligible': False,
            'reason': 'target_level_exceeds_cap',
            'downscaled': False,
            'needs_power_up': False,
            'needs_evolution': needs_evolution,
            'mega_max_level': mega_max_level,
            'mega_max_cp': mega_max_cp,
            'mega_condition': mega_condition,
        }

    base_cap_cp = compute_cp(base_stats, ivs, effective_level, table)
    owned_stats_effective = owned_stats
    if owned_stats_effective is None:
        if not needs_evolution:
            owned_stats_effective = base_stats
        elif species_catalog and isinstance(species_catalog.get(owned_species), Mapping):
            owned_stats_effective = species_catalog[owned_species].get('baseStats')

    owned_cap_cp = (
        compute_cp(owned_stats_effective, ivs, effective_level, table)
        if owned_stats_effective is not None
        else None
    )

    cp_level_consistent: bool | None = None
    if current_level is not None and current_cp is not None and owned_stats_effective is not None:
        expected_owned_cp = compute_cp(owned_stats_effective, ivs, float(current_level), table)
        cp_level_consistent = int(current_cp) == expected_owned_cp

    exceeds_level = current_level is not None and float(current_level) > effective_level
    exceeds_cp = current_cp is not None and owned_cap_cp is not None and int(current_cp) > owned_cap_cp
    under_level = current_level is not None and float(current_level) < effective_level
    under_cp = current_cp is not None and owned_cap_cp is not None and int(current_cp) < owned_cap_cp

    actual_owned = {
        'species_id': owned_species,
        'level': float(current_level) if current_level is not None else None,
        'cp': int(current_cp) if current_cp is not None else None,
        'cp_level_consistent': cp_level_consistent,
    }
    mega_theoretical = {
        'species_id': mega_species_id,
        'target_level': effective_level,
        'target_cp': effective_mega_cp,
        'cap_max_level': mega_max_level,
        'cap_max_cp': mega_max_cp,
        'base_equivalent_cp_at_target': base_cap_cp,
        'owned_equivalent_cp_at_target': owned_cap_cp,
    }

    if cp_level_consistent is False:
        return {
            'eligible': None,
            'reason': 'inconsistent_cp_level',
            'downscaled': None,
            'needs_power_up': None,
            'needs_evolution': needs_evolution,
            'base_species_id': direct_base,
            'mega_species_id': mega_species_id,
            'effective_level': effective_level,
            'mega_cp': effective_mega_cp,
            'mega_max_level': mega_max_level,
            'mega_max_cp': mega_max_cp,
            'base_cap_cp': base_cap_cp,
            'actual_owned': actual_owned,
            'mega_theoretical': mega_theoretical,
            'battle_effective': {'level': None, 'cp': None, 'downscaled': None, 'matches_target': False},
            'mega_condition': mega_condition,
        }

    if exceeds_level or exceeds_cp:
        downscaled = True
        needs_power_up: bool | None = False
        matches_target = abs(effective_level - mega_max_level) < 1e-6
        battle_effective = {
            'level': mega_max_level if effective_allow_downscale is True else None,
            'cp': mega_max_cp if effective_allow_downscale is True else None,
            'downscaled': True,
            'matches_target': matches_target if effective_allow_downscale is True else False,
        }
        if effective_allow_downscale is False:
            eligible: bool | None = False
            reason = 'level_exceeds_mega_cap' if exceeds_level else 'cp_exceeds_mega_cap'
        elif effective_allow_downscale is None:
            eligible = None
            reason = 'downscaling_rule_unverified'
        else:
            eligible = True
            reason = 'ok_downscaled' if matches_target else 'ok_downscaled_to_cap'
    else:
        downscaled = False
        if under_level or (current_level is None and under_cp):
            needs_power_up = True
            cur_lvl_f = float(current_level) if current_level is not None else None
            battle_effective = {
                'level': cur_lvl_f,
                'cp': compute_cp(mega_stats, ivs, cur_lvl_f, table) if cur_lvl_f is not None else None,
                'downscaled': False,
                'matches_target': False,
            }
            eligible = True
            reason = 'ok_needs_power_up'
        elif current_level is None:
            # Even when current_cp == owned_cap_cp, missing current_level cannot prove PL equality safely.
            needs_power_up = None
            battle_effective = {'level': None, 'cp': None, 'downscaled': False, 'matches_target': False}
            eligible = True
            reason = 'ok_level_unverified'
        else:
            needs_power_up = False
            battle_effective = {
                'level': effective_level,
                'cp': effective_mega_cp,
                'downscaled': False,
                'matches_target': True,
            }
            eligible = True
            reason = 'ok'

    return {
        'eligible': eligible,
        'reason': reason,
        'downscaled': downscaled,
        'needs_power_up': needs_power_up,
        'needs_evolution': needs_evolution,
        'base_species_id': direct_base,
        'mega_species_id': mega_species_id,
        'effective_level': effective_level,
        'mega_cp': effective_mega_cp,
        'mega_max_level': mega_max_level,
        'mega_max_cp': mega_max_cp,
        'base_cap_cp': base_cap_cp,
        'actual_owned': actual_owned,
        'mega_theoretical': mega_theoretical,
        'battle_effective': battle_effective,
        'mega_condition': mega_condition,
    }
