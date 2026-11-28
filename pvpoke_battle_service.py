"""Internal single-battle contract for the pinned Great League detail runner.

The caller owns the DirectMatrixClient and must serialize access to it. Engine
paths are supplied through that trusted client, never through a battle spec.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
import sqlite3
import time
from typing import TYPE_CHECKING
from pathlib import Path

from pvpoke_batch_v2 import CP_CAP, MAX_LEVEL, optimize
from pvpoke_calculation_version import content_hash
from pvpoke_direct_backend import DirectMatrixClient, DirectMatrixError
from pvpoke_mega import (
    MEGA_DOWNSCALING_CUPS,
    SUPER_MAX_HYPOTHESIS_MODES,
    UNSCALED_CUPS,
    compute_cp,
    is_mega_form,
    max_level_and_cp,
)

if TYPE_CHECKING:
    from pvpoke_battle_store import BattleStore

SPEC_SCHEMA = 'battle-spec-v1'
RESULT_SCHEMA = 'battle-result-v1'
MAX_REQUEST_BYTES = 128 * 1024
ROOT = Path(__file__).resolve().parent
OUTCOMES = {
    'self_ko_win': 'self_win', 'opponent_ko_win': 'opponent_win',
    'simultaneous_ko': 'simultaneous_ko', 'timeout': 'timeout', 'boundary': 'boundary',
}


class UnsupportedBattle(ValueError):
    """The request describes a condition this adapter cannot execute."""


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _json_hash(value):
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError('JSON numbers must be finite')


def _object(value, name, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError(f'{name}: missing or unknown fields')
    return value


def _items(value, name, minimum, maximum):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError(f'{name}: invalid list length')
    return value


def _integer(value, name, low, high):
    if type(value) not in (int, float) or not low <= value <= high or int(value) != value:
        raise ValueError(f'{name}: expected an integer from {low} to {high}')
    return int(value)


def _identifier(value, name, pattern=r'[a-z0-9_]{1,100}'):
    if type(value) is not str or not re.fullmatch(pattern, value):
        raise ValueError(f'{name}: invalid identifier')
    return value


def _move(value):
    return _identifier(value, 'move ID', r'[A-Z0-9_]{1,100}')


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f'{name}: expected a boolean')
    return value


def _terminal_state(state):
    max_hp = _integer(state['max_hp'], 'maximum HP', 1, 10000)
    return {
        'hp': _integer(state['hp'], 'remaining HP', 0, max_hp), 'max_hp': max_hp,
        'energy_points': _integer(state['energy_points'], 'remaining energy', 0, 100),
        'shields': _integer(state['shields'], 'remaining shields', 0, 2),
        'buffs': [_integer(stage, 'stage', -4, 4) for stage in _items(state['buffs'], 'buffs', 2, 2)],
    }


def _resolved_move(event, index):
    _object(event, 'resolved move',
            ('index', 'turn', 'actor', 'kind', 'move_id', 'damage', 'shielded', 'target_hp'))
    _integer(event['index'], 'event index', index, index)
    if event['kind'] not in ('fast', 'charged'):
        raise ValueError('Unknown resolved move kind')
    return {
        'index': index, 'turn': _integer(event['turn'], 'resolved turn', 1, 10000),
        'actor': _integer(event['actor'], 'actor', 0, 1),
        'kind': event['kind'], 'move_id': _move(event['move_id']),
        'damage': _integer(event['damage'], 'damage', 0, 10000),
        'shielded': _boolean(event['shielded'], 'shielded'),
        'target_hp': _integer(event['target_hp'], 'target HP', 0, 10000),
    }



def _battle_metrics(result, *, events_field, elapsed_field):
    damage = []
    for item in _items(result['damage'], 'damage', 2, 2):
        _object(item, 'damage totals', ('fast', 'charged'))
        damage.append({key: _integer(item[key], 'damage total', 0, 10000)
                       for key in ('fast', 'charged')})
    events = _items(result[events_field], 'resolved moves', 0, 2000)
    return {
        'rating': _integer(result['rating'], 'rating', 0, 1000),
        'terminal': [_terminal_state(state) for state in _items(result['terminal'], 'terminal', 2, 2)],
        'shields_used': [_integer(value, 'shields used', 0, 2)
                         for value in _items(result['shields_used'], 'shields used', 2, 2)],
        'damage': damage,
        'executed_moves': [_resolved_move(event, index) for index, event in enumerate(events)],
        'turns': _integer(result['turns'], 'turns', 0, 10000),
        'simulation_elapsed_ms': _integer(result[elapsed_field], 'elapsed time', 0, 1000000),
    }


def validate_complete_result(result, key, spec, versions):
    """Validate a stored v1 summary against a server-normalized spec and active versions."""
    _object(result, 'battle result', (
        'schema', 'status', 'battle_key', 'spec', 'versions', 'outcome', 'rating',
        'terminal', 'shields_used', 'damage', 'executed_moves', 'action_results',
        'turns', 'simulation_elapsed_ms', 'compute_wall_ms',
    ))
    _object(versions, 'battle versions', ('engine', 'game_data'))
    for version in versions.values():
        _identifier(version, 'battle version', r'[a-f0-9]{64}')
    if (result['schema'] != RESULT_SCHEMA or result['status'] != 'complete'
            or result['outcome'] not in ('self_win', 'opponent_win', 'simultaneous_ko')
            or result['action_results'] != [] or spec['mode'] != 'standard'
            or spec['calculation_version'] != _json_hash([versions['engine'], versions['game_data']])
            or result['battle_key'] != key or key != _json_hash(spec)
            or result['versions'] != versions or _canonical_json(result['spec']) != _canonical_json(spec)):
        raise ValueError('Result does not match the complete battle summary')
    metrics = _battle_metrics(result, events_field='executed_moves', elapsed_field='simulation_elapsed_ms')
    if metrics['terminal'] != result['terminal']:
        raise ValueError('Unexpected terminal state fields')
    timing = result['compute_wall_ms']
    if type(timing) not in (int, float) or not 0 <= timing < math.inf:
        raise ValueError('Invalid battle compute time')


def _file_signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _validate_script(actions, decisions):
    ids, slots, charged = set(), set(), {}
    for action in _items(actions, 'actions', 0, 1000):
        _object(action, 'action', ('id', 'actor', 'turn', 'kind'), ('move_id',))
        action_id = _identifier(action['id'], 'action ID', r'[A-Za-z0-9_-]{1,64}')
        actor = _integer(action['actor'], 'actor', 0, 1)
        turn = _integer(action['turn'], 'turn', 1, 500)
        kind = action['kind']
        if kind not in ('fast', 'charged', 'wait') or ('move_id' in action) == (kind == 'wait'):
            raise ValueError('Action kind and move ID do not agree')
        if kind != 'wait':
            _move(action['move_id'])
        if action_id in ids or (actor, turn) in slots:
            raise ValueError('Duplicate action ID or actor and turn')
        ids.add(action_id)
        slots.add((actor, turn))
        if kind == 'charged':
            charged[action_id] = actor
    seen = set()
    for decision in _items(decisions, 'shield decisions', 0, 1000):
        _object(decision, 'shield decision', ('action_id', 'defender', 'use_shield'))
        action_id = _identifier(decision['action_id'], 'action ID', r'[A-Za-z0-9_-]{1,64}')
        defender = _integer(decision['defender'], 'defender', 0, 1)
        _boolean(decision['use_shield'], 'use_shield')
        if charged.get(action_id) != 1 - defender or action_id in seen:
            raise ValueError('Shield decision must target one opposing charged action')
        seen.add(action_id)


class BattleService:
    """Translate a validated spec and run one battle using an existing client."""

    def __init__(self, client: DirectMatrixClient, *, store: BattleStore | None = None):
        self.client = client
        self.store = store
        self.cache_stats = dict(hits=0, engine_calls=0, storage_errors=0, read_seconds=0.0, write_seconds=0.0)
        self._verified_process = None
        self._data_path = client.gamemaster
        source = client.source / 'src'
        engine_paths = {
            path.relative_to(source).as_posix(): path for path in (source / 'js').rglob('*.js')
        }
        for name in ('pvpoke_node_matrix.js', 'pvpoke_battle_policy.js', 'pvpoke_minior_strategy.js'):
            engine_paths[f'adapter/{name}'] = ROOT / name
        python_paths = [ROOT / name for name in (
            'pvpoke_direct_backend.py', 'pvpoke_batch_v2.py', 'pvpoke_mega.py', Path(__file__).name,
        )]
        self._input_signatures = {
            path: _file_signature(path) for path in [self._data_path, *engine_paths.values(), *python_paths]
        } if store is not None else {}
        raw = client.gamemaster.read_bytes()
        self.data_version = hashlib.sha256(raw).hexdigest()
        self.species = {row['speciesId']: row for row in json.loads(raw)['pokemon']}
        pokemon_source = (source / 'js/pokemon/Pokemon.js').read_bytes()
        match = re.search(rb'\bvar\s+cpms\s*=\s*\[([^\]]+)\]', pokemon_source)
        if not match:
            raise ValueError('PvPoke CPM table is missing')
        self.cpms = [float(value) for value in match[1].split(b',')]
        self.source_hashes = {name: content_hash(path) for name, path in engine_paths.items()}
        self.source_hashes['js/pokemon/Pokemon.js'] = hashlib.sha256(pokemon_source).hexdigest()
        self.engine_version = _json_hash([self.source_hashes, [content_hash(path) for path in python_paths]])
        self.versions = {'engine': self.engine_version, 'game_data': self.data_version}
        self.calculation_version = _json_hash([self.engine_version, self.data_version])

    def _combatant(self, value, *, cp_cap=CP_CAP, max_level=MAX_LEVEL, super_max_mode='none'):
        _object(value, 'combatant', ('species_id', 'ivs', 'level', 'moves', 'initial'), ('mega_level',))
        species = _identifier(value['species_id'], 'species ID')
        ivs = _object(value['ivs'], 'IVs', ('attack', 'defense', 'hp'))
        attack, defense, stamina = (_integer(ivs[k], k, 0, 15) for k in ('attack', 'defense', 'hp'))
        level = value['level']
        if type(level) not in (float, int) or not 1 <= level <= 100 or level * 2 % 1:
            raise ValueError('Level must be in half-level increments')
        level = float(level)
        moves = _object(value['moves'], 'moves', ('fast', 'charged'))
        fast = _move(moves['fast'])
        charged = [_move(move) for move in _items(moves['charged'], 'charged moves', 0, 3)]
        if len(set(charged)) != len(charged):
            raise ValueError('Duplicate charged move')
        initial = _object(value['initial'], 'initial state', ('hp', 'energy', 'shields', 'stages'))
        hp = initial['hp']
        if hp != 'full':
            _integer(hp, 'initial HP', 1, 10000)
        energy = _integer(initial['energy'], 'energy', 0, 100)
        shields = _integer(initial['shields'], 'shields', 0, 2)
        stages = [_integer(stage, 'stage', -4, 4) for stage in _items(initial['stages'], 'stages', 2, 2)]
        pokemon = self.species.get(species)
        if pokemon is None:
            raise ValueError('Unknown species or form')
        tags = pokemon.get('tags') or ()
        is_mega = is_mega_form(species) or ('mega' in tags)
        raw_mega_level = value.get('mega_level')
        if raw_mega_level is not None:
            if not is_mega:
                raise ValueError('mega_level is only valid for Mega or Primal forms')
            mega_level = _integer(raw_mega_level, 'mega_level', 1, 4)
        elif is_mega:
            mega_level = 4 if 'supermega' in tags else 3
        else:
            mega_level = None
        if len(charged) == 3 and not is_mega:
            raise ValueError('A third charged move requires a Mega or Primal form')
        super_max_enabled = (
            is_mega and mega_level == 4
            and super_max_mode in ('hypothesis_1_pl52', 'hypothesis_2_pl53')
        )
        effective_max_level = float(max_level) if super_max_enabled else float(MAX_LEVEL)
        if species.startswith('minior') or level > effective_max_level or len(charged) not in (2, 3):
            raise UnsupportedBattle('This runner requires a supported form, level 50 or lower, and 2 or 3 charged moves')
        row = dict(species=species, fast=fast, charged1=charged[0], charged2=charged[1],
                   atk=attack, hp=stamina, level_override=level, **{'def': defense})
        if len(charged) == 3:
            row['charged3'] = charged[2]
        if mega_level is not None:
            row['mega_level'] = mega_level
        opt_rules = (
            {'cp_cap': cp_cap, 'max_level': effective_max_level, 'super_max_mode': super_max_mode}
            if super_max_enabled else None
        )
        try:
            prepared, = optimize([row], self.species, self.cpms, 'battle', cp_cap=cp_cap, rules=opt_rules)
        except ValueError:
            raise ValueError('Moves or level do not match the species, form or CP cap') from None
        # Pokemon.initialize applies a fixed HP rule to Shedinja after CPM scaling.
        max_hp = 10 if pokemon.get('dex') == 292 else max(
            10, math.floor(self.cpms[int(level * 2) - 2] * (pokemon['baseStats']['hp'] + stamina)))
        hp = max_hp if hp == 'full' else _integer(hp, 'initial HP', 1, max_hp)
        normalized = {
            'species_id': species, 'ivs': {'attack': attack, 'defense': defense, 'hp': stamina}, 'level': level,
            'moves': {'fast': fast, 'charged': charged},
            'initial': {'hp': hp, 'energy': energy, 'shields': shields, 'stages': stages},
        }
        if mega_level is not None:
            normalized['mega_level'] = mega_level
        return normalized, {key: item for key, item in prepared.items() if key != 'level_override'}

    def _prepare(self, request):
        if type(request) in (str, bytes):
            if len(request) > MAX_REQUEST_BYTES or (
                type(request) is str and len(request.encode('utf-8')) > MAX_REQUEST_BYTES
            ):
                raise ValueError('Battle JSON is too large')
            request = json.loads(request, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        _object(request, 'battle spec', ('schema', 'rules', 'combatants', 'mode'),
                ('calculation_version', 'policies', 'actions', 'shield_decisions'))
        if request['schema'] != SPEC_SCHEMA:
            raise UnsupportedBattle('Unknown battle spec version')
        rules = _object(request['rules'], 'rules', ('league', 'cp_cap'),
                        ('max_level', 'cup_id', 'allow_cp_downscaling', 'super_max_mode'))
        league = _identifier(rules['league'], 'league')
        cap = _integer(rules['cp_cap'], 'CP cap', 10, 10000)
        has_super_max = 'super_max_mode' in rules and rules['super_max_mode'] is not None
        if has_super_max:
            super_max_mode = rules['super_max_mode']
            if type(super_max_mode) is not str or super_max_mode not in SUPER_MAX_HYPOTHESIS_MODES:
                raise ValueError('Invalid super_max_mode in rules')
            expected_level_cap = int(SUPER_MAX_HYPOTHESIS_MODES[super_max_mode])
        else:
            super_max_mode = None
            expected_level_cap = MAX_LEVEL
        level_cap = _integer(rules.get('max_level', expected_level_cap), 'max level', 1, 100)
        cup = _identifier(rules.get('cup_id', 'all'), 'cup ID')
        has_downscale_flag = 'allow_cp_downscaling' in rules
        allow_downscaling = _boolean(rules['allow_cp_downscaling'], 'allow_cp_downscaling') if has_downscale_flag else None

        supported_cups_great = {'all', *MEGA_DOWNSCALING_CUPS, *UNSCALED_CUPS} - {'ultra_mega'}
        supported_cups_ultra = {'ultra_mega', 'mega_edition', *UNSCALED_CUPS}
        supported_cups_master = {'all', 'master', 'mega_edition', *UNSCALED_CUPS}
        valid_level_cap = (
            level_cap in (MAX_LEVEL, expected_level_cap)
            if super_max_mode in ('hypothesis_1_pl52', 'hypothesis_2_pl53')
            else level_cap == MAX_LEVEL
        )
        if not valid_level_cap or not (
            (league == 'great' and cap == CP_CAP and cup in supported_cups_great)
            or (league == 'ultra' and cap == 2500 and cup in supported_cups_ultra)
            or (league == 'master' and cap == 10000 and cup in supported_cups_master)
        ):
            raise UnsupportedBattle('Unsupported league, CP cap, level cap, or cup ID')
        if cup in ('all', 'master') and allow_downscaling is True:
            raise UnsupportedBattle('Standard unscaled league does not support Mega CP downscaling')
        if cup in UNSCALED_CUPS and allow_downscaling is True:
            raise UnsupportedBattle('Unscaled cup does not support Mega CP downscaling')
        if cup in MEGA_DOWNSCALING_CUPS and allow_downscaling is None:
            allow_downscaling = True

        mode = request['mode']
        if mode not in ('standard', 'sandbox'):
            raise ValueError('Invalid battle mode')
        if 'calculation_version' in request:
            requested = _identifier(request['calculation_version'], 'calculation version', r'[a-f0-9]{64}')
            if requested != self.calculation_version:
                raise UnsupportedBattle('Calculation version differs from the active version')
        actions = request.get('actions', [])
        decisions = request.get('shield_decisions', [])
        _validate_script(actions, decisions)
        policies = _object(request.get('policies', {}), 'policies', (), ('attack', 'shield', 'bait'))
        attack = _items(policies.get('attack', ['standard'] * 2), 'attack policies', 2, 2)
        if any(policy not in ('standard', 'fast_only') for policy in attack):
            raise ValueError('Invalid attack policy')
        shield = _items(policies.get('shield', ['standard'] * 2), 'shield policies', 2, 2)
        if any(policy not in ('standard', 'manual') for policy in shield):
            raise ValueError('Invalid shield policy')
        bait = [_boolean(value, 'bait') for value in _items(policies.get('bait', [True] * 2), 'bait', 2, 2)]
        if mode == 'sandbox' or actions or decisions or shield != ['standard'] * 2:
            raise UnsupportedBattle('Sandbox actions and manual shield decisions are not executable in this version')
        combatants, rows = zip(*(
            self._combatant(
                value,
                cp_cap=cap,
                max_level=level_cap,
                super_max_mode=super_max_mode or 'none',
            )
            for value in _items(request['combatants'], 'combatants', 2, 2)
        ))
        normalized_rules = {'league': league, 'cp_cap': cap, 'max_level': level_cap, 'cup_id': cup}
        if allow_downscaling is not None:
            normalized_rules['allow_cp_downscaling'] = allow_downscaling
        if has_super_max:
            normalized_rules['super_max_mode'] = super_max_mode
        spec = {
            'schema': SPEC_SCHEMA, 'mode': mode, 'calculation_version': self.calculation_version,
            'rules': normalized_rules,
            'combatants': list(combatants), 'actions': [], 'shield_decisions': [],
            'policies': {'attack': list(attack), 'shield': list(shield), 'bait': bait},
        }
        initial = [value['initial'] for value in combatants]
        payload = {
            'self': rows[0], 'opponent': rows[1], 'shields': [state['shields'] for state in initial],
            'initial': [{'hp_points': state['hp'], 'energy_points': state['energy'], 'buffs': state['stages']}
                        for state in initial],
            'attack_policies': list(attack), 'bait': bait,
        }
        if cap != CP_CAP:
            payload['cp_cap'] = cap
        return spec, payload

    def simulate(self, request: dict | str | bytes) -> dict:
        """Return a result envelope. Rejected requests never reach the engine."""
        try:
            spec, payload = self._prepare(request)
        except UnsupportedBattle as exc:
            return self._error('unsupported', str(exc))
        except (json.JSONDecodeError, UnicodeError, RecursionError):
            return self._error('invalid', 'Malformed battle JSON')
        except ValueError as exc:
            return self._error('invalid', str(exc))

        key = _json_hash(spec)
        try:
            self._check_inputs()
        except (DirectMatrixError, OSError):
            return self._error('failed', 'The active battle inputs have changed')
        if self.store is not None:
            started = time.perf_counter()
            try:
                cached = self.store.get(key, spec, self.versions)
            except (sqlite3.Error, OSError, ValueError):
                self.cache_stats['storage_errors'] += 1
                cached = None
            finally:
                self.cache_stats['read_seconds'] += time.perf_counter() - started
            if cached is not None:
                try:
                    if self._verified_process is None or self._verified_process is not self.client.proc:
                        identity = self.client.strategy('engine_identity', {})
                        self._verify_engine(identity.get('engine_sources'))
                    self._check_inputs()
                except (DirectMatrixError, OSError):
                    return self._error('failed', 'The cached result does not match the active engine inputs')
                self.cache_stats['hits'] += 1
                return cached

        self.cache_stats['engine_calls'] += 1
        result = self._calculate(key, spec, payload)
        if self.store is not None and result['status'] == 'complete':
            started = time.perf_counter()
            try:
                self.store.put(key, spec, self.versions, result)
            except (sqlite3.Error, OSError, ValueError):
                self.cache_stats['storage_errors'] += 1
            finally:
                self.cache_stats['write_seconds'] += time.perf_counter() - started
        return result

    def _check_inputs(self):
        if self.store is not None and (
            self.client.gamemaster != self._data_path or any(
                _file_signature(path) != signature for path, signature in self._input_signatures.items()
            )
        ):
            raise DirectMatrixError('Battle inputs changed after initialization')

    def _verify_engine(self, loaded):
        if (
            type(loaded) is not dict or not loaded
            or (self.store is not None and loaded.keys() != self.source_hashes.keys())
            or any(self.source_hashes.get(name) != digest for name, digest in loaded.items())
        ):
            raise DirectMatrixError('Loaded engine source version mismatch')
        self._verified_process = self.client.proc

    def _calculate(self, key, spec, payload):
        started = time.perf_counter()
        try:
            result = self.client.strategy('detail', payload, include_engine_sources=True)
            if result['status'] != 'calculated' or result['gamemaster_hash'] != self.data_version:
                raise DirectMatrixError('Detail result or data version mismatch')
            self._verify_engine(result['engine_sources'])
            self._check_inputs()
            outcome = OUTCOMES[result['outcome']]
            return {
                'schema': RESULT_SCHEMA, 'status': 'partial' if outcome in ('timeout', 'boundary') else 'complete',
                'battle_key': key, 'spec': spec,
                'versions': dict(self.versions),
                'outcome': outcome, 'action_results': [],
                **_battle_metrics(result, events_field='events', elapsed_field='elapsed_ms'),
                'compute_wall_ms': (time.perf_counter() - started) * 1000,
            }
        except (DirectMatrixError, OSError, KeyError, TypeError, ValueError):
            return self._error('failed', 'The pinned battle engine did not return a compatible result')

    @staticmethod
    def _error(status, message):
        return {'schema': RESULT_SCHEMA, 'status': status, 'error': {'message': message}}

    def compare_super_max_hypotheses(self, request: dict | str | bytes) -> dict:
        """Compare baseline (<=50) vs Super MAX PL+2 Hypothesis 1 (<=52) and Hypothesis 2 (<=53).

        Marked explicitly as unconfirmed reference-only simulations; never asserts confirmed live rules.
        """
        try:
            base_spec, _ = self._prepare(request)
        except UnsupportedBattle as exc:
            return self._error('unsupported', str(exc))
        except (json.JSONDecodeError, UnicodeError, RecursionError):
            return self._error('invalid', 'Malformed battle JSON')
        except ValueError as exc:
            return self._error('invalid', str(exc))

        c0 = base_spec['combatants'][0]
        species_id = c0['species_id']
        pokemon = self.species.get(species_id) or {}
        tags = pokemon.get('tags') or ()
        is_mega = is_mega_form(species_id) or ('mega' in tags)
        if not is_mega:
            return self._error('unsupported', 'Super MAX PL+2 comparison requires a Mega or Primal form')
        if c0.get('mega_level') != 4:
            return self._error('unsupported', 'Super MAX PL+2 comparison requires mega_level=4')

        base_rules = base_spec['rules']
        cp_cap = base_rules['cp_cap']
        allow_downscaling = base_rules.get('allow_cp_downscaling') is True
        base_level = float(c0['level'])
        ivs = c0['ivs']
        stats = pokemon['baseStats']

        def _resolve_target(mode_key: str, plus_pl: float, max_cap: float) -> tuple[float, int, bool]:
            if mode_key == 'none':
                cp_val = compute_cp(stats, ivs, base_level, self.cpms)
                return base_level, cp_val, False
            theoretical_level = min(max_cap, base_level + plus_pl)
            theoretical_cp = compute_cp(stats, ivs, theoretical_level, self.cpms)
            if theoretical_cp <= cp_cap:
                return theoretical_level, theoretical_cp, False
            fitted = max_level_and_cp(stats, ivs, cp_cap=cp_cap, max_level=max_cap, cpms=self.cpms)
            if fitted is None:
                raise UnsupportedBattle('No eligible level fits CP cap under Super MAX hypothesis')
            return fitted[0], fitted[1], allow_downscaling

        scenarios = (
            ('baseline', 'none', 0.0, 50.0, '通常MAX基準（PL+2補正なし・上限PL50）'),
            ('hypothesis_1_pl52', 'hypothesis_1_pl52', 2.0, 52.0, 'スーパーMAX 仮説1（通常+2＝上限PL52・未確定参考）'),
            ('hypothesis_2_pl53', 'hypothesis_2_pl53', 3.0, 53.0, 'スーパーMAX 仮説2（相棒ブースト+PL+2＝上限PL53・未確定参考）'),
        )
        results = {}
        try:
            for key, mode_name, plus_pl, max_cap, label in scenarios:
                lvl, cp_val, downscaled = _resolve_target(mode_name, plus_pl, max_cap)
                spec_req = deepcopy(base_spec)
                spec_req.pop('calculation_version', None)
                spec_req['combatants'][0]['level'] = lvl
                spec_req['combatants'][0]['initial']['hp'] = 'full'
                spec_rules = dict(base_rules)
                spec_rules['super_max_mode'] = mode_name
                spec_rules['max_level'] = int(max_cap)
                spec_req['rules'] = spec_rules
                sim_res = self.simulate(spec_req)
                if sim_res.get('status') not in ('complete', 'partial'):
                    return sim_res
                results[key] = {
                    'label': label,
                    'super_max_mode': mode_name,
                    'level': lvl,
                    'cp': cp_val,
                    'downscaled': downscaled,
                    'status': sim_res['status'],
                    'outcome': sim_res.get('outcome'),
                    'rating': sim_res.get('rating'),
                    'battle_key': sim_res.get('battle_key'),
                    'result': sim_res,
                }
        except UnsupportedBattle as exc:
            return self._error('unsupported', str(exc))

        base_rating = results['baseline'].get('rating')
        for item in results.values():
            r = item.get('rating')
            item['rating_delta_vs_baseline'] = (
                (r - base_rating) if (isinstance(r, int) and isinstance(base_rating, int)) else None
            )

        return {
            'schema': 'super-max-comparison-v1',
            'status': 'complete' if all(v['status'] == 'complete' for v in results.values()) else 'partial',
            'comparison_mode': 'unconfirmed_reference_only',
            'super_max_pl_hypothesis_status': 'unconfirmed_deferred',
            'disclaimer': (
                '※スーパーMAX（PL+2）の補正仕様は未確定のため、仮説1（上限PL52）と'
                '仮説2（上限PL53）の対戦比較は未確定参考値であり、ゲーム内確定仕様ではありません。'
            ),
            'versions': dict(self.versions),
            'baseline': results['baseline'],
            'hypothesis_1_pl52': results['hypothesis_1_pl52'],
            'hypothesis_2_pl53': results['hypothesis_2_pl53'],
        }

