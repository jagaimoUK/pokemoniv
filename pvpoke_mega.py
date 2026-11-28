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
SUPER_MAX_HYPOTHESIS_MODES: dict[str, float] = {
    'none': 50.0,
    'hypothesis_1_pl52': 52.0,
    'hypothesis_2_pl53': 53.0,
}
LEAGUE_CP_CAPS = {'great': 1500, 'ultra': 2500, 'master': 10000}
MEGA_DOWNSCALING_CUPS = frozenset({
    'great_mega', 'ultra_mega', 'mega_edition', 'mega_color', 'mega_catch', 'mega_halloween',
})
UNSCALED_CUPS = frozenset({'strict_unscaled', 'no_downscaling'})
NON_MEGA_RULESETS = frozenset({
    'cp1500-lv50', 'all', 'great', 'ultra', 'master',
    'open_great', 'open_ultra', 'open_master',
})


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
    ruleset = rules.get('ruleset')
    if ruleset is not None:
        if not isinstance(ruleset, str) or not ruleset.strip():
            raise ValueError('ruleset must be a non-empty string when specified')
        ruleset = ruleset.strip()
        if cup_id is None:
            if ruleset in ('great_mega', 'ultra_mega') or ruleset not in NON_MEGA_RULESETS:
                cup_id = ruleset
        if league is None:
            if ruleset in ('great_mega', 'cp1500-lv50', 'great', 'open_great'):
                league = 'great'
            elif ruleset in ('ultra_mega', 'ultra', 'open_ultra'):
                league = 'ultra'
            elif ruleset in ('master', 'open_master'):
                league = 'master'
    raw_cap = rules.get('cp_cap')
    if raw_cap is not None:
        if isinstance(raw_cap, bool) or not isinstance(raw_cap, int) or not 10 <= raw_cap <= 10000:
            raise ValueError(f'Invalid cp_cap in rules: {raw_cap}')
        cp_cap: int | None = raw_cap
    elif isinstance(league, str) and league in LEAGUE_CP_CAPS:
        cp_cap = LEAGUE_CP_CAPS[league]
    else:
        cp_cap = None

    has_super_max_mode = 'super_max_mode' in rules and rules['super_max_mode'] is not None
    if has_super_max_mode:
        super_max_mode = rules['super_max_mode']
        if not isinstance(super_max_mode, str) or super_max_mode not in SUPER_MAX_HYPOTHESIS_MODES:
            raise ValueError(f'Invalid super_max_mode in rules: {super_max_mode}')
        mode_cap = SUPER_MAX_HYPOTHESIS_MODES[super_max_mode]
    else:
        super_max_mode = None
        mode_cap = 50.0

    raw_max_level = rules.get('max_level', mode_cap)
    if isinstance(raw_max_level, bool) or not isinstance(raw_max_level, (int, float)) or not 1 <= raw_max_level <= 100:
        raise ValueError(f'Invalid max_level in rules: {raw_max_level}')
    max_level = float(raw_max_level)
    if has_super_max_mode and max_level > mode_cap:
        raise ValueError(f'max_level {max_level} exceeds super_max_mode cap {mode_cap}')

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

    resolved = {
        'league': league,
        'cup_id': cup_id,
        'cp_cap': cp_cap,
        'max_level': max_level,
        'allow_cp_downscaling': allow_downscale,
        'rule_explicit': cp_cap is not None and explicit_downscale,
    }
    if has_super_max_mode:
        resolved['super_max_mode'] = super_max_mode
    if ruleset is not None:
        resolved['ruleset'] = ruleset
    return resolved


def resolve_party_mega_rules(rules: str | Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve show-six and pick-three Mega allowance strictly from explicit tournament/cup rules.

    Allows multiple Mega candidates in 6-Pokémon registration (up to max_megas_in_six, default 6)
    and never assumes max_megas_in_three == 1 for unverified or unknown cups.
    """
    if rules is None:
        raw: Mapping[str, Any] = {}
    elif isinstance(rules, str):
        token = rules.strip()
        if not token:
            raise ValueError('rules string must not be empty')
        raw = {'ruleset': token, 'cup_id': token}
    elif isinstance(rules, Mapping):
        raw = rules
    else:
        raise ValueError('rules must be None, a string, or a mapping')

    ruleset = raw.get('ruleset')
    if ruleset is not None and (not isinstance(ruleset, str) or not ruleset.strip()):
        raise ValueError('ruleset must be a non-empty string when specified')
    cup_id = raw.get('cup_id')
    if cup_id is not None and (not isinstance(cup_id, str) or not cup_id.strip()):
        raise ValueError('cup_id must be a non-empty string when specified')
    league = raw.get('league')
    effective_cup = cup_id or (ruleset if ruleset not in (None, 'cp1500-lv50') else None)

    raw_max_six = raw.get('max_megas_in_six', 6)
    if isinstance(raw_max_six, bool) or not isinstance(raw_max_six, int) or not 0 <= raw_max_six <= 6:
        raise ValueError(f'max_megas_in_six must be an integer 0..6: {raw_max_six}')
    max_megas_in_six = raw_max_six

    explicit_allowed = raw.get('mega_allowed')
    if explicit_allowed is not None and type(explicit_allowed) is not bool:
        raise ValueError('mega_allowed must be a bool when specified')

    raw_max_three = raw['max_megas_in_three'] if 'max_megas_in_three' in raw else raw.get('max_megas')
    if raw_max_three is not None:
        if isinstance(raw_max_three, bool) or not isinstance(raw_max_three, int) or not 0 <= raw_max_three <= 3:
            raise ValueError(f'max_megas_in_three must be an integer 0..3: {raw_max_three}')
        if explicit_allowed is False and raw_max_three > 0:
            raise ValueError('Contradictory rules: mega_allowed=False with max_megas_in_three > 0')
        if explicit_allowed is True and raw_max_three == 0:
            raise ValueError('Contradictory rules: mega_allowed=True with max_megas_in_three == 0')
        max_megas_in_three: int | None = raw_max_three
        mega_allowed: bool | None = raw_max_three > 0
        rule_verified = True
        source = 'explicit'
    elif explicit_allowed is False:
        max_megas_in_three = 0
        mega_allowed = False
        rule_verified = True
        source = 'explicit_mega_banned'
    elif effective_cup in MEGA_DOWNSCALING_CUPS:
        max_megas_in_three = 1
        mega_allowed = True
        rule_verified = True
        source = 'known_mega_cup'
    elif (effective_cup in NON_MEGA_RULESETS or (effective_cup is None and ruleset in NON_MEGA_RULESETS)) and explicit_allowed is not True:
        max_megas_in_three = 0
        mega_allowed = False
        rule_verified = True
        source = 'standard_non_mega_ruleset'
    else:
        max_megas_in_three = None
        mega_allowed = explicit_allowed
        rule_verified = False
        source = 'unverified'

    return {
        'ruleset': ruleset,
        'cup_id': cup_id,
        'league': league,
        'effective_cup': effective_cup,
        'max_megas_in_six': max_megas_in_six,
        'allow_multiple_megas_in_six': max_megas_in_six >= 2,
        'max_megas_in_three': max_megas_in_three,
        'mega_allowed': mega_allowed,
        'rule_verified': rule_verified,
        'source': source,
    }


def _extract_species_id(item: Any, species_lookup: Mapping[str, str] | None = None) -> str:
    if isinstance(item, Mapping):
        sid = item.get('species') if item.get('species') is not None else item.get('species_id', '')
        return str(sid)
    if isinstance(item, str):
        if species_lookup is not None and item in species_lookup:
            return str(species_lookup[item])
        return item
    return ''


def count_mega_forms(members: Sequence[Any], species_lookup: Mapping[str, str] | None = None) -> int:
    """Count Mega/Primal combatants in a roster or 3-pick lineup."""
    return sum(1 for item in members if is_mega_form(_extract_species_id(item, species_lookup)))


def validate_party_mega_rules(
    six_roster: Sequence[Any] | None = None,
    pick_three: Sequence[Any] | None = None,
    *,
    rules: str | Mapping[str, Any] | None = None,
    species_lookup: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate 6-member registration (multi-Mega allowed) and 3-pick battle Mega limits."""
    policy = resolve_party_mega_rules(rules)
    six_count = count_mega_forms(six_roster, species_lookup) if six_roster is not None else None
    three_count = count_mega_forms(pick_three, species_lookup) if pick_three is not None else None

    six_valid: bool | None = (
        six_count <= policy['max_megas_in_six'] if six_count is not None else None
    )

    if three_count is None:
        three_valid: bool | None = None
        reason = 'six_roster_only' if six_valid is not False else 'six_mega_limit_exceeded'
    elif not policy['rule_verified'] or policy['max_megas_in_three'] is None:
        three_valid = None
        reason = 'mega_rule_unverified'
    elif three_count > policy['max_megas_in_three']:
        three_valid = False
        reason = 'mega_limit_exceeded'
    elif six_valid is False:
        three_valid = False
        reason = 'six_mega_limit_exceeded'
    else:
        three_valid = True
        reason = 'ok'

    return {
        'six_roster_valid': six_valid,
        'pick_three_valid': three_valid,
        'mega_count_in_six': six_count,
        'mega_count_in_three': three_count,
        'max_megas_in_six': policy['max_megas_in_six'],
        'max_megas_in_three': policy['max_megas_in_three'],
        'rule_verified': policy['rule_verified'],
        'reason': reason,
        'policy': policy,
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

    training_goal = build_training_goal(
        owned_record,
        target_level=effective_level,
        needs_evolution=needs_evolution,
        downscaled=downscaled,
        mega_level=mega_level,
        shadow=is_shadow_form(owned_species),
    )

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
        'training_goal': training_goal,
    }


_DEFAULT_GL_RANKINGS_PATH = Path(__file__).resolve().parent / 'data' / 'cp1500_role_scores_20261015.json'
_REGIONAL_WORD_TO_JA = {
    'alolan': 'アローラ',
    'galarian': 'ガラル',
    'hisuian': 'ヒスイ',
    'paldean': 'パルデア',
}
_POWER_UP_HALF_COSTS: tuple[tuple[int, int, int], ...] = (
    # Each entry covers one half-level step starting at (idx + 2) / 2.0 (1.0 -> 49.5): (stardust, candy, candy_xl)
    *((200, 1, 0),) * 4,
    *((400, 1, 0),) * 4,
    *((600, 1, 0),) * 4,
    *((800, 1, 0),) * 4,
    *((1000, 1, 0),) * 4,
    *((1300, 2, 0),) * 4,
    *((1600, 2, 0),) * 4,
    *((1900, 2, 0),) * 4,
    *((2200, 2, 0),) * 4,
    *((2500, 2, 0),) * 4,
    *((3000, 3, 0),) * 4,
    *((3500, 3, 0),) * 4,
    *((4000, 3, 0),) * 2,
    *((4000, 4, 0),) * 2,
    *((4500, 4, 0),) * 4,
    *((5000, 4, 0),) * 4,
    *((6000, 6, 0),) * 4,
    *((7000, 8, 0),) * 4,
    *((8000, 10, 0),) * 4,
    *((9000, 12, 0),) * 4,
    *((10000, 15, 0),) * 2,
    *((10000, 0, 10),) * 2,
    *((11000, 0, 10),) * 2,
    *((11000, 0, 12),) * 2,
    *((12000, 0, 12),) * 2,
    *((12000, 0, 15),) * 2,
    *((13000, 0, 15),) * 2,
    *((13000, 0, 17),) * 2,
    *((14000, 0, 17),) * 2,
    *((14000, 0, 20),) * 2,
    *((15000, 0, 20),) * 2,
)


def _validate_half_level(value: float, name: str, *, max_level: float = 55.0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number: {value}')
    doubled = int(round(float(value) * 2))
    if abs(float(value) * 2 - doubled) > 1e-6 or doubled < 2 or doubled > int(round(max_level * 2)):
        raise ValueError(f'{name} must be in half-level increments 1.0..{max_level:g}: {value}')
    return doubled


def compute_power_up_cost(
    current_level: float | None,
    target_level: float,
    *,
    lucky: bool = False,
    purified: bool = False,
    shadow: bool = False,
    mega_level: int | None = None,
) -> dict[str, Any]:
    """Compute Pokémon GO Stardust, Candy, and Candy XL needed to reach target_level (paid steps <= PL50).

    Super MAX PL+2 remains unconfirmed/deferred and never fabricates Lv 50.5+ power-up costs.
    """
    if type(lucky) is not bool or type(purified) is not bool or type(shadow) is not bool:
        raise ValueError('lucky, purified, and shadow must be bools')
    if shadow and purified:
        raise ValueError('Pokémon cannot be both Shadow and Purified')
    if mega_level is not None and (type(mega_level) is not int or not 1 <= mega_level <= 4):
        raise ValueError(f'mega_level must be 1..4: {mega_level}')

    target_doubled = _validate_half_level(target_level, 'target_level', max_level=55.0)
    paid_target_doubled = min(target_doubled, 100)  # Paid power-ups stop at PL 50.0.
    super_max_status = 'unconfirmed_deferred' if mega_level == 4 else 'not_applicable'
    super_max_note = 'スーパー MAX PL+2 仮説保留（仮補正なし）' if mega_level == 4 else None

    if current_level is None:
        return {
            'current_level': None,
            'target_level': target_doubled / 2.0,
            'paid_target_level': paid_target_doubled / 2.0,
            'power_ups': None,
            'stardust': None,
            'candy': None,
            'candy_xl': None,
            'uses_xl_candy': paid_target_doubled > 80,
            'cost_verified': False,
            'target_level_capped_at_50': target_doubled > 100,
            'super_max_pl_hypothesis_status': super_max_status,
            'super_max_pl_note': super_max_note,
        }

    cur_doubled = _validate_half_level(current_level, 'current_level', max_level=55.0)
    if cur_doubled >= paid_target_doubled:
        return {
            'current_level': cur_doubled / 2.0,
            'target_level': target_doubled / 2.0,
            'paid_target_level': paid_target_doubled / 2.0,
            'power_ups': 0,
            'stardust': 0,
            'candy': 0,
            'candy_xl': 0,
            'uses_xl_candy': False,
            'cost_verified': True,
            'target_level_capped_at_50': target_doubled > 100,
            'super_max_pl_hypothesis_status': super_max_status,
            'super_max_pl_note': super_max_note,
        }

    total_dust = 0
    total_candy = 0
    total_xl = 0
    for doubled in range(cur_doubled, paid_target_doubled):
        dust, candy, xl = _POWER_UP_HALF_COSTS[doubled - 2]
        if shadow:
            dust = math.ceil(dust * 1.2)
            candy = math.ceil(candy * 1.2)
            xl = math.ceil(xl * 1.2)
        elif purified:
            dust = math.ceil(dust * 0.9)
            candy = math.ceil(candy * 0.9)
            xl = math.ceil(xl * 0.9)
        if lucky:
            dust = math.ceil(dust * 0.5)
        total_dust += dust
        total_candy += candy
        total_xl += xl

    return {
        'current_level': cur_doubled / 2.0,
        'target_level': target_doubled / 2.0,
        'paid_target_level': paid_target_doubled / 2.0,
        'power_ups': paid_target_doubled - cur_doubled,
        'stardust': total_dust,
        'candy': total_candy,
        'candy_xl': total_xl,
        'uses_xl_candy': total_xl > 0,
        'cost_verified': True,
        'target_level_capped_at_50': target_doubled > 100,
        'super_max_pl_hypothesis_status': super_max_status,
        'super_max_pl_note': super_max_note,
    }


def compute_super_max_cost_comparison(
    current_level: float | None,
    target_level: float = 50.0,
    *,
    lucky: bool = False,
    purified: bool = False,
    shadow: bool = False,
) -> dict[str, Any]:
    """Compare theoretical power-up costs for Super MAX PL+2 hypotheses without claiming confirmed rules.

    - Hypothesis 1 (PL50 + 2 = 52): +2 PL boost from Super MAX (saves 2.0 PL of paid power-ups below PL50).
    - Hypothesis 2 (PL51 + 2 = 53): Buddy +1 plus Super MAX +2 (saves 3.0 PL of paid power-ups below PL50).
    Paid power-ups always remain capped at PL 50.0.
    """
    target_doubled = _validate_half_level(target_level, 'target_level', max_level=50.0)
    effective_target = target_doubled / 2.0
    is_max_cap = target_doubled >= 100

    h1_paid_target = 50.0 if is_max_cap else max(1.0, effective_target - 2.0)
    h2_paid_target = 50.0 if is_max_cap else max(1.0, effective_target - 3.0)

    baseline_cost = compute_power_up_cost(
        current_level, effective_target, lucky=lucky, purified=purified, shadow=shadow, mega_level=3,
    )

    def _entry(label: str, paid_target: float, boosted_level: float, ml: int | None) -> dict[str, Any]:
        cost = compute_power_up_cost(
            current_level, paid_target, lucky=lucky, purified=purified, shadow=shadow, mega_level=ml,
        )
        verified = bool(cost['cost_verified'] and baseline_cost['cost_verified'])
        return {
            'label': label,
            'paid_target_level': cost['paid_target_level'],
            'effective_level': boosted_level,
            'power_ups': cost['power_ups'],
            'stardust': cost['stardust'],
            'candy': cost['candy'],
            'candy_xl': cost['candy_xl'],
            'stardust_diff': (cost['stardust'] - baseline_cost['stardust']) if verified else None,
            'candy_diff': (cost['candy'] - baseline_cost['candy']) if verified else None,
            'candy_xl_diff': (cost['candy_xl'] - baseline_cost['candy_xl']) if verified else None,
            'cost_verified': cost['cost_verified'],
        }

    return {
        'current_level': baseline_cost['current_level'],
        'target_level': effective_target,
        'super_max_pl_hypothesis_status': 'unconfirmed_deferred',
        'super_max_pl_note': (
            'スーパー MAX PL+2 仮説保留（仮説1・仮説2の育成コスト差は未確定参考値であり、'
            'ゲーム内確定仕様ではありません）'
        ),
        'baseline': _entry('通常MAX基準（補正なし）', effective_target, effective_target, 3),
        'hypothesis_1': _entry(
            'スーパーMAX 仮説1（通常+2＝PL52相当）',
            h1_paid_target,
            52.0 if is_max_cap else effective_target,
            4,
        ),
        'hypothesis_2': _entry(
            'スーパーMAX 仮説2（相棒ブースト+2＝PL53相当）',
            h2_paid_target,
            53.0 if is_max_cap else effective_target,
            4,
        ),
    }


def build_training_goal(
    owned_record: Mapping[str, Any] | None,
    *,
    target_level: float,
    needs_evolution: bool = False,
    downscaled: bool = False,
    mega_level: int | None = None,
    shadow: bool = False,
) -> dict[str, Any]:
    """Summarize target PL, evolution/downscale state, power-up resources, and Super MAX note."""
    rec = owned_record if isinstance(owned_record, Mapping) else {}
    cur_level = rec.get('current_level')
    cur_cp = rec.get('current_cp')
    cost = compute_power_up_cost(
        float(cur_level) if cur_level is not None else None,
        float(target_level),
        lucky=bool(rec.get('lucky', False)),
        purified=bool(rec.get('purified', False)),
        shadow=shadow,
        mega_level=mega_level,
    )
    needs_power_up: bool | None = (
        None if cost['power_ups'] is None else cost['power_ups'] > 0
    )
    return {
        **cost,
        'current_cp': int(cur_cp) if cur_cp is not None else None,
        'needs_power_up': needs_power_up,
        'needs_evolution': bool(needs_evolution),
        'downscaled': bool(downscaled),
    }


def evaluate_gl_mega_score_70_or(
    *,
    normal_gl_overall: float | None,
    mega_gl_overall: float | None = None,
    threshold: float = 70.0,
    all_species_mode: bool = False,
    has_mega_form: bool = True,
) -> dict[str, Any]:
    """Evaluate Q2 / TV-04: keep if Normal GL >= 70 OR Mega GL >= 70 (fail closed when unverified).

    All-species mode never excludes by the 70-point threshold.
    """
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 1 <= threshold <= 100:
        raise ValueError(f'threshold must be 1..100: {threshold}')
    if type(all_species_mode) is not bool:
        raise ValueError('all_species_mode must be a bool')

    if all_species_mode:
        return {
            'keep': True,
            'verified': True,
            'reason': 'all_species_mode',
            'threshold': float(threshold),
            'matched_leagues': [],
            'normal_gl_overall': normal_gl_overall,
            'mega_gl_overall': mega_gl_overall,
        }

    matched: list[str] = []
    if normal_gl_overall is not None and float(normal_gl_overall) >= threshold:
        matched.append('normal_gl')
    if has_mega_form and mega_gl_overall is not None and float(mega_gl_overall) >= threshold:
        matched.append('mega_gl')

    if matched:
        return {
            'keep': True,
            'verified': True,
            'reason': 'meets_threshold_or',
            'threshold': float(threshold),
            'matched_leagues': matched,
            'normal_gl_overall': float(normal_gl_overall) if normal_gl_overall is not None else None,
            'mega_gl_overall': float(mega_gl_overall) if mega_gl_overall is not None else None,
        }

    if normal_gl_overall is None or (has_mega_form and mega_gl_overall is None):
        return {
            'keep': True,
            'verified': False,
            'reason': 'ranking_unverified',
            'threshold': float(threshold),
            'matched_leagues': [],
            'normal_gl_overall': float(normal_gl_overall) if normal_gl_overall is not None else None,
            'mega_gl_overall': float(mega_gl_overall) if mega_gl_overall is not None else None,
        }

    return {
        'keep': False,
        'verified': True,
        'reason': 'below_threshold',
        'threshold': float(threshold),
        'matched_leagues': [],
        'normal_gl_overall': float(normal_gl_overall),
        'mega_gl_overall': float(mega_gl_overall) if mega_gl_overall is not None else None,
    }


@lru_cache(maxsize=4)
def load_gl_ranking_snapshot(path: str | None = None) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Load the pinned PvPoke GL role-score snapshot (`pvpoke-role-scores-v1`)."""
    import json

    target = Path(path) if path else _DEFAULT_GL_RANKINGS_PATH
    raw = json.loads(target.read_text(encoding='utf-8'))
    roles = ('overall', 'leads', 'closers', 'switches', 'chargers', 'attackers', 'consistency')
    if raw.get('schema') != 'pvpoke-role-scores-v1' or raw.get('columns') != ['name', 'dex', *roles]:
        raise ValueError(f'Invalid ranking snapshot schema in {target}')
    rows: list[dict[str, Any]] = []
    for fields in raw['rows']:
        name, dex, *scores = fields
        rows.append({'name': name, 'dex': dex, **dict(zip(roles, scores))})
    return str(raw['source_date']), tuple(rows)


def _lookup_snapshot_overall(
    species_id: str,
    rows: Sequence[Mapping[str, Any]],
    species_catalog: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[float | None, str | None]:
    row_meta = (species_catalog or {}).get(species_id)
    tokens = set(re.split(r'[_-]', species_id.casefold()))
    is_shadow = 'shadow' in tokens
    region_ja = next((ja for en, ja in _REGIONAL_WORD_TO_JA.items() if en in tokens), None)

    candidate_names: list[str] = []
    dex: int | None = None
    if isinstance(row_meta, Mapping):
        raw_dex = row_meta.get('dex')
        if isinstance(raw_dex, int) and not isinstance(raw_dex, bool):
            dex = raw_dex
        if isinstance(row_meta.get('name_ja'), str):
            candidate_names.append(row_meta['name_ja'])
    if dex is not None and not candidate_names:
        try:
            from pvpoke_app_defaults import NAMES_JA
            ja_base = NAMES_JA.get(dex)
        except Exception:
            ja_base = None
        if isinstance(ja_base, str) and ja_base:
            built = ja_base + (f' ({region_ja})' if region_ja else '')
            if is_shadow:
                built += ' (シャドウ)'
            candidate_names.append(built)

    norm_candidates = {re.sub(r'\s+', '', n) for n in candidate_names if n}
    if norm_candidates:
        exact = [
            r for r in rows
            if re.sub(r'\s+', '', str(r.get('name', ''))) in norm_candidates
            and (dex is None or r.get('dex') == dex)
        ]
        if len(exact) == 1:
            return float(exact[0]['overall']), str(exact[0]['name'])

    if dex is not None:
        dex_matches = []
        for r in rows:
            if r.get('dex') != dex:
                continue
            r_name = str(r.get('name', ''))
            labels = re.findall(r'\(([^()]*)\)', r_name)
            r_shadow = 'シャドウ' in labels
            r_regions = [x for x in labels if x in _REGIONAL_WORD_TO_JA.values()]
            if r_shadow != is_shadow:
                continue
            if region_ja:
                if r_regions != [region_ja]:
                    continue
            elif r_regions:
                continue
            # Exclude other explicit form labels when plain species_id has no extra tokens beyond base+region+shadow.
            extra_labels = [x for x in labels if x != 'シャドウ' and x not in _REGIONAL_WORD_TO_JA.values()]
            if extra_labels and not (tokens - {'shadow', *_REGIONAL_WORD_TO_JA.keys()}):
                continue
            dex_matches.append(r)
        if len(dex_matches) == 1:
            return float(dex_matches[0]['overall']), str(dex_matches[0]['name'])

    return None, None


def resolve_gl_mega_ranking_70_or(
    species_id: str,
    *,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
    normal_snapshot: tuple[str, Sequence[Mapping[str, Any]]] | None = None,
    mega_scores: Mapping[Any, Any] | None = None,
    threshold: float = 70.0,
    all_species_mode: bool = False,
) -> dict[str, Any]:
    """Evaluate TV-04 70-point OR rule using real PvPoke GL ranking data and optional Mega GL scores."""
    source_date, rows = normal_snapshot if normal_snapshot is not None else load_gl_ranking_snapshot()
    is_mega = is_mega_form(species_id)
    normal_sid = base_species_id(species_id) if is_mega else species_id
    mega_forms = [species_id] if is_mega else (
        mega_forms_for_base(normal_sid, list(species_catalog or {}), species_catalog)
        if species_catalog and not is_shadow_form(normal_sid)
        else []
    )
    has_mega = bool(mega_forms)

    normal_overall, matched_name = _lookup_snapshot_overall(normal_sid, rows, species_catalog)
    mega_overall: float | None = None
    mega_source_date: str | None = None
    if isinstance(mega_scores, Mapping):
        mega_source_date = str(mega_scores.get('source_date')) if mega_scores.get('source_date') else None
        lookup_keys: list[Any] = [species_id, *mega_forms]
        if matched_name:
            lookup_keys.append(matched_name)
        norm_meta = (species_catalog or {}).get(normal_sid)
        if isinstance(norm_meta, Mapping) and isinstance(norm_meta.get('dex'), int):
            lookup_keys.append(norm_meta['dex'])
        for k in lookup_keys:
            if k is None or k not in mega_scores:
                continue
            entry = mega_scores[k]
            if isinstance(entry, Mapping) and isinstance(entry.get('overall'), (int, float)) and not isinstance(entry.get('overall'), bool):
                mega_overall = float(entry['overall'])
                break
            if isinstance(entry, (int, float)) and not isinstance(entry, bool):
                mega_overall = float(entry)
                break

    verdict = evaluate_gl_mega_score_70_or(
        normal_gl_overall=normal_overall,
        mega_gl_overall=mega_overall,
        threshold=threshold,
        all_species_mode=all_species_mode,
        has_mega_form=has_mega,
    )
    return {
        **verdict,
        'species_id': species_id,
        'normal_species_id': normal_sid,
        'mega_species_ids': mega_forms,
        'has_mega_form': has_mega,
        'normal_gl_source_date': source_date,
        'normal_gl_matched_name': matched_name,
        'mega_gl_source_date': mega_source_date,
        'mega_gl_status': (
            'not_applicable' if not has_mega
            else ('verified' if mega_overall is not None else 'unverified')
        ),
    }


def _forward_evolutions(
    start_species_id: str,
    species_catalog: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    """Return catalog-verified forward non-Mega evolutions matching Shadow status."""
    if not species_catalog or start_species_id not in species_catalog or is_mega_form(start_species_id):
        return []
    start_shadow = is_shadow_form(start_species_id)
    reverse_parents: dict[str, list[str]] = {}
    for sid, row in species_catalog.items():
        if not isinstance(row, Mapping):
            continue
        fam = row.get('family')
        if isinstance(fam, Mapping):
            parent = fam.get('parent')
            if isinstance(parent, str):
                reverse_parents.setdefault(parent, []).append(sid)

    visited = {start_species_id}
    queue = [start_species_id]
    evolutions: list[str] = []
    while queue:
        cur = queue.pop(0)
        row = species_catalog.get(cur)
        children: list[str] = []
        if isinstance(row, Mapping):
            fam = row.get('family')
            if isinstance(fam, Mapping):
                for child in fam.get('evolutions') or ():
                    if isinstance(child, str):
                        children.append(child)
        children.extend(reverse_parents.get(cur, ()))
        for child in children:
            if (child in visited or child not in species_catalog
                    or is_mega_form(child) or is_shadow_form(child) != start_shadow):
                continue
            visited.add(child)
            evolutions.append(child)
            queue.append(child)
    return evolutions


def pre_evolutions_for_target(
    target_species_id: str,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Return catalog-verified pre-evolutions for Mega or normal evolved target species."""
    if is_mega_form(target_species_id):
        return eligible_pre_evolutions(target_species_id, species_catalog)
    if not species_catalog or target_species_id not in species_catalog:
        return ()
    target_shadow = is_shadow_form(target_species_id)
    reverse_parents: dict[str, list[str]] = {}
    for sid, row in species_catalog.items():
        if not isinstance(row, Mapping):
            continue
        fam = row.get('family')
        if isinstance(fam, Mapping):
            for child in fam.get('evolutions') or ():
                if isinstance(child, str):
                    reverse_parents.setdefault(child, []).append(sid)

    chain: list[str] = []
    visited = {target_species_id}
    queue = [target_species_id]
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
            if (parent in visited or parent not in species_catalog
                    or is_mega_form(parent) or is_shadow_form(parent) != target_shadow):
                continue
            visited.add(parent)
            chain.append(parent)
            queue.append(parent)
    return tuple(chain)


def can_evolve_to(
    owned_species_id: str,
    target_species_id: str,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    """Return True iff owned_species_id can evolve to target_species_id without fabricating paths."""
    if not owned_species_id or not target_species_id or owned_species_id == target_species_id:
        return False
    if is_mega_form(target_species_id):
        return can_mega_evolve(owned_species_id, target_species_id, species_catalog)
    return owned_species_id in pre_evolutions_for_target(target_species_id, species_catalog)


def discover_reachable_forms(
    owned_species_id: str,
    species_catalog: Mapping[str, Mapping[str, Any]] | None = None,
    species_ids: Sequence[str] | set[str] | None = None,
    *,
    evaluated_species_id: str | None = None,
) -> dict[str, Any]:
    """Discover reachable normal evolutions and Mega forms while distinguishing owned vs evaluated."""
    target = evaluated_species_id or owned_species_id
    pool = (
        list(species_ids) if species_ids is not None
        else list(species_catalog or ())
    )
    evolutions = _forward_evolutions(owned_species_id, species_catalog)
    mega_forms = (
        mega_forms_for_base(owned_species_id, pool, species_catalog)
        if not is_mega_form(owned_species_id)
        else [owned_species_id]
    )
    pre_evolutions = list(pre_evolutions_for_target(target, species_catalog))
    return {
        'owned_species_id': owned_species_id,
        'evaluated_species_id': target,
        'form_distinct': target != owned_species_id,
        'evolutions': evolutions,
        'mega_forms': mega_forms,
        'pre_evolutions': pre_evolutions,
    }


def evaluate_selection_freshness(
    recorded: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare recorded evaluation fingerprints vs active context (TV-09 conservative fail-closed).

    Checks GM/engine versions & calculation_version, ranking snapshot date/hash,
    meta preset SHA-256, and policy/rule digests. Missing or unprovable axes mark
    needs_reevaluation=True while preserving old results read-only.
    """
    rec = recorded if isinstance(recorded, Mapping) else {}
    cur = current if isinstance(current, Mapping) else {}
    reasons: list[str] = []
    checked_axes: list[str] = []

    # 1. GM / Engine versions & calculation_version
    checked_axes.append('gm_and_engine')
    rec_vers = rec.get('versions') if isinstance(rec.get('versions'), Mapping) else None
    cur_vers = cur.get('versions') if isinstance(cur.get('versions'), Mapping) else None
    rec_calc = rec.get('calculation_version')
    cur_calc = cur.get('calculation_version')
    if cur_vers is not None or rec_vers is not None:
        if rec_vers is None or cur_vers is None:
            reasons.append('calculation_version_unverified')
        elif rec_vers != cur_vers:
            reasons.append('engine_or_gamemaster_changed')
    if cur_calc is not None or rec_calc is not None:
        if not rec_calc or not cur_calc:
            if 'calculation_version_unverified' not in reasons:
                reasons.append('calculation_version_unverified')
        elif rec_calc != cur_calc and 'engine_or_gamemaster_changed' not in reasons:
            reasons.append('calculation_version_changed')
    elif cur_vers is None and rec_vers is None:
        reasons.append('calculation_version_unverified')

    # 2. Ranking snapshot & Mega GL ranking verification
    if ('ranking_source_date' in cur or 'ranking_source_date' in rec
            or 'ranking_sha256' in cur or 'ranking_sha256' in rec
            or rec.get('mega_gl_status') == 'unverified'
            or cur.get('mega_gl_status') == 'unverified'):
        checked_axes.append('ranking')
        cur_date = cur.get('ranking_source_date')
        rec_date = rec.get('ranking_source_date')
        cur_rhash = cur.get('ranking_sha256')
        rec_rhash = rec.get('ranking_sha256')
        if cur_date is not None or rec_date is not None:
            if not rec_date or not cur_date:
                reasons.append('ranking_unverified')
            elif rec_date != cur_date:
                reasons.append('ranking_changed')
        if cur_rhash is not None or rec_rhash is not None:
            if not rec_rhash or not cur_rhash:
                if 'ranking_unverified' not in reasons:
                    reasons.append('ranking_unverified')
            elif rec_rhash != cur_rhash and 'ranking_changed' not in reasons:
                reasons.append('ranking_changed')
        if rec.get('mega_gl_status') == 'unverified' or cur.get('mega_gl_status') == 'unverified':
            reasons.append('mega_ranking_unverified')

    # 3. Meta preset hash (when applicable)
    if rec.get('meta_sha256') is not None or cur.get('meta_sha256') is not None:
        checked_axes.append('meta')
        if not rec.get('meta_sha256') or not cur.get('meta_sha256'):
            reasons.append('meta_unverified')
        elif rec.get('meta_sha256') != cur.get('meta_sha256'):
            reasons.append('meta_changed')

    # 4. Rules, downscaling policy, and selection policy
    if ('policy_version' in cur or 'policy_version' in rec
            or 'rules_digest' in cur or 'rules_digest' in rec
            or 'rules' in cur or 'rules' in rec
            or rec.get('mega_rule_unverified') or cur.get('mega_rule_unverified')):
        checked_axes.append('rules_and_policy')
        if 'policy_version' in cur or 'policy_version' in rec:
            if not rec.get('policy_version') or not cur.get('policy_version'):
                reasons.append('policy_version_unverified')
            elif rec.get('policy_version') != cur.get('policy_version'):
                reasons.append('policy_version_changed')
        if 'rules_digest' in cur or 'rules_digest' in rec:
            if not rec.get('rules_digest') or not cur.get('rules_digest'):
                reasons.append('rules_unverified')
            elif rec.get('rules_digest') != cur.get('rules_digest'):
                reasons.append('rules_changed')
        if 'rules' in cur or 'rules' in rec:
            rec_rules = resolve_battle_rules(rec.get('rules')) if rec.get('rules') is not None else None
            cur_rules = resolve_battle_rules(cur.get('rules')) if cur.get('rules') is not None else None
            if (rec_rules is None) != (cur_rules is None):
                reasons.append('rules_unverified')
            elif rec_rules is not None and rec_rules != cur_rules:
                reasons.append('rules_changed')
        if rec.get('mega_rule_unverified') or cur.get('mega_rule_unverified'):
            reasons.append('mega_rule_unverified')

    if rec.get('impact_provable') is False or cur.get('impact_provable') is False:
        reasons.append('impact_not_provable')

    needs_reeval = bool(reasons)
    return {
        'fresh': not needs_reeval,
        'needs_reevaluation': needs_reeval,
        'status': 'reevaluation_pending' if needs_reeval else 'current',
        'display_label': '再評価が必要（再評価保留）' if needs_reeval else '最新の計算基準と一致',
        'reasons': reasons,
        'checked_axes': checked_axes,
        'old_result_preserved': True,
    }


