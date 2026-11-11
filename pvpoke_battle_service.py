"""Internal single-battle contract for the pinned Great League detail runner.

The caller owns the DirectMatrixClient and must serialize access to it. Engine
paths are supplied through that trusted client, never through a battle spec.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

from pvpoke_batch_v2 import CP_CAP, MAX_LEVEL, optimize
from pvpoke_calculation_version import content_hash
from pvpoke_direct_backend import DirectMatrixClient, DirectMatrixError

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


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


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

    def __init__(self, client: DirectMatrixClient):
        self.client = client
        raw = client.gamemaster.read_bytes()
        self.data_version = hashlib.sha256(raw).hexdigest()
        self.species = {row['speciesId']: row for row in json.loads(raw)['pokemon']}
        source = client.source / 'src'
        pokemon_source = (source / 'js/pokemon/Pokemon.js').read_bytes()
        match = re.search(rb'\bvar\s+cpms\s*=\s*\[([^\]]+)\]', pokemon_source)
        if not match:
            raise ValueError('PvPoke CPM table is missing')
        self.cpms = [float(value) for value in match[1].split(b',')]
        self.source_hashes = {
            path.relative_to(source).as_posix(): content_hash(path)
            for path in (source / 'js').rglob('*.js')
        }
        self.source_hashes['js/pokemon/Pokemon.js'] = hashlib.sha256(pokemon_source).hexdigest()
        for name in ('pvpoke_node_matrix.js', 'pvpoke_battle_policy.js', 'pvpoke_minior_strategy.js'):
            self.source_hashes[f'adapter/{name}'] = content_hash(ROOT / name)
        self.engine_version = _json_hash([
            self.source_hashes,
            [content_hash(ROOT / name) for name in ('pvpoke_direct_backend.py', 'pvpoke_batch_v2.py', Path(__file__).name)],
        ])
        self.calculation_version = _json_hash([self.engine_version, self.data_version])

    def _combatant(self, value):
        _object(value, 'combatant', ('species_id', 'ivs', 'level', 'moves', 'initial'))
        species = _identifier(value['species_id'], 'species ID')
        ivs = _object(value['ivs'], 'IVs', ('attack', 'defense', 'hp'))
        attack, defense, stamina = (_integer(ivs[k], k, 0, 15) for k in ('attack', 'defense', 'hp'))
        level = value['level']
        if type(level) not in (float, int) or not 1 <= level <= 100 or level * 2 % 1:
            raise ValueError('Level must be in half-level increments')
        level = float(level)
        moves = _object(value['moves'], 'moves', ('fast', 'charged'))
        fast = _move(moves['fast'])
        charged = [_move(move) for move in _items(moves['charged'], 'charged moves', 0, 2)]
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
        if species.startswith('minior') or level > MAX_LEVEL or len(charged) != 2:
            raise UnsupportedBattle('This runner requires a supported form, level 50 or lower, and two charged moves')
        row = dict(species=species, fast=fast, charged1=charged[0], charged2=charged[1],
                   atk=attack, hp=stamina, level_override=level, **{'def': defense})
        try:
            prepared, = optimize([row], self.species, self.cpms, 'battle')
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
        rules = _object(request['rules'], 'rules', ('league', 'cp_cap'), ('max_level', 'cup_id'))
        league = _identifier(rules['league'], 'league')
        cap = _integer(rules['cp_cap'], 'CP cap', 10, 10000)
        level_cap = _integer(rules.get('max_level', MAX_LEVEL), 'max level', 1, 100)
        cup = _identifier(rules.get('cup_id', 'all'), 'cup ID')
        if (league, cap, level_cap, cup) != ('great', CP_CAP, MAX_LEVEL, 'all'):
            raise UnsupportedBattle('Only open Great League, CP 1500 and level cap 50 are supported')
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
        combatants, rows = zip(*(self._combatant(value)
                                 for value in _items(request['combatants'], 'combatants', 2, 2)))
        spec = {
            'schema': SPEC_SCHEMA, 'mode': mode, 'calculation_version': self.calculation_version,
            'rules': {'league': league, 'cp_cap': cap, 'max_level': level_cap, 'cup_id': cup},
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

        started = time.perf_counter()
        try:
            result = self.client.strategy('detail', payload, include_engine_sources=True)
            if result['status'] != 'calculated' or result['gamemaster_hash'] != self.data_version:
                raise DirectMatrixError('Detail result or data version mismatch')
            loaded = result['engine_sources']
            if type(loaded) is not dict or not loaded or any(
                self.source_hashes.get(name) != digest for name, digest in loaded.items()
            ):
                raise DirectMatrixError('Loaded engine source version mismatch')
            outcome = OUTCOMES[result['outcome']]
            terminal = [_terminal_state(state) for state in _items(result['terminal'], 'terminal', 2, 2)]
            shields_used = [_integer(value, 'shields used', 0, 2)
                            for value in _items(result['shields_used'], 'shields used', 2, 2)]
            damage = []
            for item in _items(result['damage'], 'damage', 2, 2):
                _object(item, 'damage totals', ('fast', 'charged'))
                damage.append({key: _integer(item[key], 'damage total', 0, 10000)
                               for key in ('fast', 'charged')})
            executed_moves = [_resolved_move(event, index)
                              for index, event in enumerate(_items(result['events'], 'resolved moves', 0, 2000))]
            return {
                'schema': RESULT_SCHEMA, 'status': 'partial' if outcome in ('timeout', 'boundary') else 'complete',
                'battle_key': _json_hash(spec), 'spec': spec,
                'versions': {'engine': self.engine_version, 'game_data': self.data_version},
                'outcome': outcome, 'rating': _integer(result['rating'], 'rating', 0, 1000), 'terminal': terminal,
                'shields_used': shields_used, 'damage': damage,
                'executed_moves': executed_moves, 'action_results': [],
                'turns': _integer(result['turns'], 'turns', 0, 10000),
                'simulation_elapsed_ms': _integer(result['elapsed_ms'], 'elapsed time', 0, 1000000),
                'compute_wall_ms': (time.perf_counter() - started) * 1000,
            }
        except (DirectMatrixError, OSError, KeyError, TypeError, ValueError):
            return self._error('failed', 'The pinned battle engine did not return a compatible result')

    @staticmethod
    def _error(status, message):
        return {'schema': RESULT_SCHEMA, 'status': status, 'error': {'message': message}}
