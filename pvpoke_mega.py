"""Common Mega Evolution / Primal Reversion foundation for species linking and CP evaluation."""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Sequence

_DEFAULT_POKEMON_JS = Path(__file__).resolve().parent / 'vendor' / 'pvpoke' / 'src' / 'js' / 'pokemon' / 'Pokemon.js'
_MEGA_SUFFIX_RE = re.compile(r'(?:_|-)(?:mega(?:_[xy])?|primal)$')


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


def can_mega_evolve(owned_species_id: str, mega_species_id: str) -> bool:
    """Return True iff owned_species_id is the non-Shadow base form of mega_species_id."""
    if not is_mega_form(mega_species_id) or is_shadow_form(owned_species_id):
        return False
    return owned_species_id == base_species_id(mega_species_id)


def mega_forms_for_base(owned_species_id: str, species_ids: Sequence[str] | set[str]) -> list[str]:
    """List Mega/Primal form IDs in species_ids that the given owned species can evolve into."""
    if is_shadow_form(owned_species_id) or is_mega_form(owned_species_id):
        return []
    return sorted(sid for sid in species_ids if can_mega_evolve(owned_species_id, sid))


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


def compute_cp(base_stats: dict, ivs: dict, level: float, cpms: Sequence[float] | None = None) -> int:
    """Compute Pokémon GO CP from base stats, IVs, and level."""
    cpm = cpm_for_level(level, cpms)
    atk = float(base_stats['atk']) + int(ivs['attack'])
    defn = float(base_stats['def']) + int(ivs['defense'])
    hp = float(base_stats['hp']) + int(ivs['hp'])
    raw = (atk * math.sqrt(defn) * math.sqrt(hp) * (cpm ** 2)) / 10.0
    return max(10, math.floor(raw))


def max_level_and_cp(
    base_stats: dict,
    ivs: dict,
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
    owned_record: dict,
    *,
    mega_species_id: str,
    base_stats: dict,
    mega_stats: dict,
    target_level: float | None = None,
    cp_cap: int = 1500,
    max_level: float = 50.0,
    cpms: Sequence[float] | None = None,
    allow_cp_downscaling: bool = True,
) -> dict:
    """Evaluate whether a base-species owned individual can be used as mega_species_id within cp_cap."""
    owned_species = owned_record.get('species_id', '')
    if not can_mega_evolve(owned_species, mega_species_id):
        return {'eligible': False, 'reason': 'incompatible_species'}

    table = cpms if cpms is not None else load_cpms()
    ivs = owned_record['ivs']
    mega_cap = max_level_and_cp(mega_stats, ivs, cp_cap=cp_cap, max_level=max_level, cpms=table)
    if mega_cap is None:
        return {'eligible': False, 'reason': 'mega_never_fits_cap'}

    mega_max_level, mega_max_cp = mega_cap
    effective_level = target_level if target_level is not None else mega_max_level
    effective_mega_cp = compute_cp(mega_stats, ivs, effective_level, table)
    if effective_mega_cp > cp_cap:
        return {
            'eligible': False,
            'reason': 'target_level_exceeds_cap',
            'mega_max_level': mega_max_level,
            'mega_max_cp': mega_max_cp,
        }

    base_cap_cp = compute_cp(base_stats, ivs, effective_level, table)
    current_level = owned_record.get('current_level')
    current_cp = owned_record.get('current_cp')
    exceeds_level = current_level is not None and float(current_level) > effective_level
    exceeds_cp = current_cp is not None and int(current_cp) > base_cap_cp
    downscaled = False
    if exceeds_level or exceeds_cp:
        if not allow_cp_downscaling:
            return {
                'eligible': False,
                'reason': 'level_exceeds_mega_cap' if exceeds_level else 'cp_exceeds_mega_cap',
                'mega_max_level': mega_max_level,
                'mega_max_cp': mega_max_cp,
                'base_cap_cp': base_cap_cp,
            }
        downscaled = True

    needs_power_up = False
    if not downscaled:
        if current_level is not None:
            needs_power_up = float(current_level) < effective_level
        elif current_cp is not None:
            needs_power_up = int(current_cp) < base_cap_cp

    return {
        'eligible': True,
        'reason': 'ok_downscaled' if downscaled else 'ok',
        'downscaled': downscaled,
        'needs_power_up': needs_power_up,
        'base_species_id': owned_species,
        'mega_species_id': mega_species_id,
        'effective_level': effective_level,
        'mega_cp': effective_mega_cp,
        'mega_max_level': mega_max_level,
        'mega_max_cp': mega_max_cp,
        'base_cap_cp': base_cap_cp,
    }
