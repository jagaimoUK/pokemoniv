"""Native scripted battles with a separate, owner-scoped trace cache."""
import json
import math
import re
import sqlite3
import subprocess
from pathlib import Path
from time import perf_counter, time

from pvpoke_battle_service import (
    MAX_REQUEST_BYTES, RESULT_SCHEMA, SPEC_SCHEMA, UnsupportedBattle, _battle_metrics, _boolean,
    _canonical_json, _identifier, _integer, _items, _json_hash, _move, _object, _reject_constant,
    _terminal_state, _unique_object, _validate_script,
)
from pvpoke_battle_store import BattleStoreError
from pvpoke_calculation_version import content_hash
from pvpoke_child_env import child_environment
from pvpoke_direct_backend import DirectMatrixError

SCHEMA = 'sandbox-result-v1'
RUNNER = Path(__file__).resolve().with_name('pvpoke_sandbox_runner.js')
MAX_TRACE_BYTES = 1536 * 1024
MAX_TURN = 500
SCRIPTED_POLICIES = {'shield': ['manual', 'manual']}
OUTCOMES = ('self_win', 'opponent_win', 'simultaneous_ko', 'timeout')
TABLE = 'sandbox_results_v1'


def _action_id(value):
    return _identifier(value, 'action ID', r'[A-Za-z0-9_-]{1,64}')


def _states(value):
    normalized = [_terminal_state(state) for state in _items(value, 'sandbox states', 2, 2)]
    if normalized != value:
        raise ValueError('Unexpected sandbox state')
    return normalized


def _reason(value):
    return _identifier(value, 'action reason', r'[a-z0-9_]{1,64}')


def _action_results(results, actions, turns):
    actual = {}
    for row in _items(results, 'sandbox actions', len(actions), len(actions)):
        _object(row, 'sandbox action result', ('action_id', 'requested_turn', 'status'),
                ('reason', 'executed_turn'))
        aid = _action_id(row['action_id'])
        if aid not in actions or aid in actual or row['requested_turn'] != actions[aid]['turn']:
            raise ValueError('Unknown or duplicate sandbox action')
        if row['status'] == 'executed':
            if 'reason' in row or row.get('executed_turn') != row['requested_turn'] or row['executed_turn'] > turns:
                raise ValueError('Unexpected executed turn')
        elif row['status'] in ('rejected', 'not_reached'):
            if 'executed_turn' in row or (row['status'] == 'not_reached') != (row['requested_turn'] > turns):
                raise ValueError('Unexpected rejected turn')
            _reason(row.get('reason'))
        else:
            raise ValueError('Unknown sandbox action status')
        actual[aid] = row
    return actual


def _validate_action_link(event, actions, actual):
    aid = event.get('action_id')
    if aid is None:
        return
    _action_id(aid)
    action = actions.get(aid)
    if (action is None or actual[aid]['status'] != 'executed' or event['turn'] < action['turn']
            or any(event.get(field) != action.get(field) for field in ('actor', 'kind', 'move_id'))):
        raise ValueError('Unexpected executed action link')


def _shield_results(results, decisions, events):
    requested = {item['action_id']: item for item in decisions}
    resolved = {event['action_id']: event for event in events
                if event['kind'] == 'charged' and 'action_id' in event}
    seen = set()
    for row in _items(results, 'shield results', len(requested), len(requested)):
        _object(row, 'shield result', ('action_id', 'defender', 'requested', 'used'), ('reason',))
        aid = _action_id(row['action_id'])
        if aid not in requested or aid in seen:
            raise ValueError('Unknown or duplicate shield result')
        seen.add(aid)
        decision = requested[aid]
        event = resolved.get(aid)
        if row['defender'] != decision['defender'] or row['requested'] is not decision['use_shield']:
            raise ValueError('Shield result differs from requested decision')
        if row['used'] is not (event['shielded'] if event is not None else None):
            raise ValueError('Shield result differs from executed move')
        if row['used'] is not row['requested']:
            _reason(row.get('reason'))
        elif 'reason' in row:
            raise ValueError('Unexpected shield result reason')
    return results


def _trace(events, actions, actual, turns):
    last_turn = 0
    starts = set()
    for sequence, event in enumerate(_items(events, 'sandbox trace', 0, 3000)):
        _object(event, 'sandbox trace event',
                ('sequence', 'turn', 'phase', 'actor', 'kind', 'before', 'after'),
                ('move_id', 'action_id', 'actual_damage'))
        _integer(event['sequence'], 'trace sequence', sequence, sequence)
        last_turn = _integer(event['turn'], 'trace turn', max(1, last_turn), turns)
        _integer(event['actor'], 'actor', 0, 1)
        phase, kind = event['phase'], event['kind']
        if phase not in ('start', 'resolve', 'effects') or kind not in ('fast', 'charged', 'wait'):
            raise ValueError('Unknown sandbox phase or kind')
        if kind != 'wait':
            _move(event.get('move_id'))
        elif 'move_id' in event or phase != 'start':
            raise ValueError('Invalid wait trace')
        if phase == 'resolve':
            _integer(event.get('actual_damage'), 'resolved damage', 0, 10000)
        elif 'actual_damage' in event:
            raise ValueError('Damage belongs to the resolution phase')
        _states(event['before'])
        _states(event['after'])
        if 'action_id' in event:
            _validate_action_link(event, actions, actual)
            if phase == 'start':
                aid = event['action_id']
                if aid in starts or event['turn'] != actual[aid]['executed_turn']:
                    raise ValueError('Action start differs from executed turn')
                starts.add(aid)
    if starts != {aid for aid, result in actual.items() if result['status'] == 'executed'}:
        raise ValueError('Sandbox trace omits a started action')
    return events


def _validate_cached_sandbox(value, key, spec, versions):
    """Revalidate persisted results as untrusted structured evidence.

    A matching checksum detects accidental byte corruption, not internally
    inconsistent or deliberately rehashed battle facts.
    """
    _object(value, 'saved Sandbox result',
            ('schema', 'status', 'summary', 'trace', 'initial', 'shield_results',
             'information_model', 'effects_model'))
    summary = _object(value['summary'], 'saved Sandbox summary',
                      ('schema', 'status', 'battle_key', 'spec', 'versions', 'outcome',
                       'rating', 'terminal', 'shields_used', 'damage',
                       'executed_moves', 'action_results', 'turns',
                       'simulation_elapsed_ms', 'compute_wall_ms'))
    if (value['schema'] != SCHEMA or value['status'] != 'complete'
            or summary['schema'] != RESULT_SCHEMA or summary['status'] != 'complete'
            or summary['battle_key'] != key or key != _json_hash(spec)
            or summary['spec'] != spec or summary['versions'] != versions
            or summary['outcome'] not in OUTCOMES[:3]
            or value['information_model'] != 'fixed_script'
            or value['effects_model'] != 'pvpoke_native_deterministic'):
        raise ValueError('Stored Sandbox metadata is inconsistent')
    initial = _states(value['initial'])
    terminal = _states(summary['terminal'])
    for actual, requested in zip(initial, (side['initial'] for side in spec['combatants'])):
        if (actual['hp'], actual['energy_points'], actual['shields'], actual['buffs']) != (
                requested['hp'], requested['energy'], requested['shields'], requested['stages']):
            raise ValueError('Stored Sandbox initial conditions differ')
    hp = [side['hp'] for side in terminal]
    outcome = ('simultaneous_ko' if hp == [0, 0] else 'self_win' if hp[1] == 0 else
               'opponent_win' if hp[0] == 0 else 'timeout')
    if outcome != summary['outcome']:
        raise ValueError('Stored Sandbox outcome differs from HP')
    turns = _integer(summary['turns'], 'saved Sandbox turns', 1, MAX_TURN)
    timing = summary['compute_wall_ms']
    if type(timing) not in (int, float) or not math.isfinite(timing) or timing < 0:
        raise ValueError('Invalid Sandbox compute time')
    actions = {row['id']: row for row in spec['actions']}
    actual = _action_results(summary['action_results'], actions, turns)
    events = _items(summary['executed_moves'], 'saved Sandbox resolved moves', 0, 2000)
    unsigned_events = []
    for event in events:
        _object(event, 'saved resolved move',
                ('index', 'turn', 'actor', 'kind', 'move_id', 'damage',
                 'shielded', 'target_hp'), ('action_id',))
        _validate_action_link(event, actions, actual)
        unsigned_events.append({field: val for field, val in event.items()
                                if field != 'action_id'})
    normalized = _battle_metrics({**summary, 'executed_moves': unsigned_events},
                                 events_field='executed_moves', elapsed_field='simulation_elapsed_ms')
    for field, result in normalized.items():
        if field != 'executed_moves' and summary[field] != result:
            raise ValueError('Stored Sandbox metrics differ')
    if [before['shields'] - after['shields'] for before, after in zip(initial, terminal)] != summary['shields_used']:
        raise ValueError('Stored Sandbox shield totals differ')
    observed_damage = [{kind: sum(event['damage'] for event in events
                                  if event['actor'] == actor and event['kind'] == kind)
                        for kind in ('fast', 'charged')} for actor in (0, 1)]
    if summary['damage'] != observed_damage:
        raise ValueError('Stored Sandbox damage totals differ')
    _shield_results(value['shield_results'], spec['shield_decisions'], events)
    trace = _trace(value['trace'], actions, actual, turns)
    resolved = [entry for entry in trace if entry['phase'] == 'resolve']
    if len(resolved) != len(events):
        raise ValueError('Saved Sandbox trace is missing resolved moves')
    for step, event in zip(resolved, events):
        if any(step.get(field) != event.get(field) for field in (
                'turn', 'actor', 'kind', 'move_id', 'action_id')) or step['actual_damage'] != event['damage']:
            raise ValueError('Stored Sandbox trace disagrees with resolved move')


class SandboxService:
    """Run a fixed vendor engine with no standard shield or action hooks."""

    def __init__(self, standard):
        if standard.store is None:
            raise ValueError('Sandbox requires an owner-scoped battle store')
        self.standard = standard
        self.store = standard.store
        self.versions = {
            'engine': _json_hash([standard.versions['engine'], self._adapter_version()]),
            'game_data': standard.versions['game_data'],
        }
        self.calculation_version = _json_hash([self.versions['engine'], self.versions['game_data']])

    @staticmethod
    def _adapter_version():
        return _json_hash([content_hash(path) for path in (Path(__file__), RUNNER)])

    def _check_inputs(self):
        self.standard._check_inputs()
        if self.versions['engine'] != _json_hash([self.standard.versions['engine'], self._adapter_version()]):
            raise DirectMatrixError('Sandbox inputs changed during calculation')

    def prepare(self, request):
        if type(request) in (str, bytes):
            if len(request) > MAX_REQUEST_BYTES or (
                    type(request) is str and len(request.encode('utf-8')) > MAX_REQUEST_BYTES):
                raise ValueError('Battle JSON is too large')
            request = json.loads(request, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        _object(request, 'sandbox battle', ('schema', 'rules', 'mode', 'combatants'),
                ('calculation_version', 'actions', 'shield_decisions', 'policies'))
        if request['schema'] != SPEC_SCHEMA or request['mode'] != 'sandbox':
            raise UnsupportedBattle('Sandbox mode and battle-spec-v1 are required')
        if 'calculation_version' in request and request['calculation_version'] != self.calculation_version:
            raise UnsupportedBattle('Sandbox calculation version differs')
        if 'policies' in request and request['policies'] != SCRIPTED_POLICIES:
            raise UnsupportedBattle('Sandbox supports per-action defender decisions only')
        actions = _items(request.get('actions', []), 'sandbox actions', 0, 1000)
        decisions = _items(request.get('shield_decisions', []), 'sandbox shield decisions', 0, 1000)
        _validate_script(actions, decisions)
        base, payload = self.standard._prepare({
            'schema': SPEC_SCHEMA, 'mode': 'standard', 'rules': request['rules'], 'combatants': request['combatants'],
        })
        for combatant in base['combatants']:
            species = combatant['species_id']
            data = self.standard.species[species]
            if (data.get('formChange') or data.get('originalFormId') not in (None, '', species)
                    or re.match(r'^(aegislash|cramorant|minior)(?:_|$)', species)):
                raise UnsupportedBattle('Dynamic forms are outside the Sandbox contract')
        for action in actions:
            moves = base['combatants'][int(action['actor'])]['moves']
            if (action['kind'] == 'fast' and action['move_id'] != moves['fast'] or
                    action['kind'] == 'charged' and action['move_id'] not in moves['charged']):
                raise ValueError('A requested move is not equipped')
        actions = sorted(({**action, 'actor': int(action['actor']), 'turn': int(action['turn'])}
                          for action in actions), key=lambda action: (action['turn'], action['actor']))
        decisions = sorted(({**item, 'defender': int(item['defender'])} for item in decisions),
                           key=lambda item: item['action_id'])
        spec = {**base, 'mode': 'sandbox', 'calculation_version': self.calculation_version,
                'actions': actions, 'shield_decisions': decisions, 'policies': {'shield': ['manual', 'manual']}}
        return spec, {**{field: payload[field] for field in ('self', 'opponent', 'initial', 'shields')},
                      'actions': actions, 'shield_decisions': decisions}

    def _result(self, spec, key, result, wall_ms):
        _object(result, 'native sandbox result',
                ('initial', 'terminal', 'turns', 'elapsed_ms', 'outcome', 'rating', 'damage', 'shields_used',
                 'events', 'action_results', 'shield_results', 'trace'))
        outcome = result['outcome']
        if outcome not in OUTCOMES:
            raise ValueError('Unknown Sandbox outcome')
        status = 'partial' if outcome == 'timeout' else 'complete'
        initial = _states(result['initial'])
        terminal = _states(result['terminal'])
        if any((state['hp'], state['energy_points'], state['shields']) !=
               (initial_spec['hp'], initial_spec['energy'], initial_spec['shields'])
               for state, initial_spec in zip(initial, (side['initial'] for side in spec['combatants']))):
            raise ValueError('Initial Sandbox state differs from specification')
        hp = [state['hp'] for state in terminal]
        expected = ('simultaneous_ko' if hp == [0, 0] else 'self_win' if hp[1] == 0 else
                    'opponent_win' if hp[0] == 0 else 'timeout')
        if outcome != expected:
            raise ValueError('Sandbox outcome differs from terminal HP')
        turns = _integer(result['turns'], 'Sandbox turns', 1, MAX_TURN)
        actions = {item['id']: item for item in spec['actions']}
        actual = _action_results(result['action_results'], actions, turns)
        events = _items(result['events'], 'Sandbox resolved moves', 0, 2000)
        standard_moves = []
        for event in events:
            _validate_action_link(event, actions, actual)
            standard_moves.append({field: value for field, value in event.items() if field != 'action_id'})
        summary = _battle_metrics({**result, 'events': standard_moves}, events_field='events', elapsed_field='elapsed_ms')
        for normalized, original in zip(summary['executed_moves'], events):
            if normalized['turn'] > turns:
                raise ValueError('Move resolved beyond Sandbox duration')
            if 'action_id' in original:
                normalized['action_id'] = _action_id(original['action_id'])
        if summary['shields_used'] != [before['shields'] - after['shields']
                                        for before, after in zip(initial, terminal)]:
            raise ValueError('Sandbox shield totals are inconsistent')
        shields = _shield_results(result['shield_results'], spec['shield_decisions'], events)
        trace = _trace(result['trace'], actions, actual, turns)
        summary.update(schema=RESULT_SCHEMA, status=status, spec=spec, battle_key=key,
                       versions=dict(self.versions), outcome=outcome,
                       compute_wall_ms=wall_ms, action_results=list(actual.values()))
        return {'schema': SCHEMA, 'status': status, 'summary': summary, 'trace': trace,
                'initial': initial, 'shield_results': shields, 'information_model': 'fixed_script',
                'effects_model': 'pvpoke_native_deterministic'}

    def _cached(self, db, key, spec):
        row = db.execute('''SELECT body, digest FROM sandbox_results_v1
                           WHERE owner_scope=? AND battle_key=?''', (self.store.owner_scope, key)).fetchone()
        if row is None:
            return None
        body, digest = row
        if type(body) is not bytes or len(body) > MAX_TRACE_BYTES:
            raise BattleStoreError('Invalid stored Sandbox trace')
        try:
            value = json.loads(body, object_pairs_hook=_unique_object,
                               parse_constant=_reject_constant)
            if _canonical_json(value) != body or _json_hash(value) != digest:
                raise ValueError('Stored Sandbox checksum or encoding mismatch')
            _validate_cached_sandbox(value, key, spec, self.versions)
        except (ValueError, KeyError, TypeError, RecursionError, OverflowError) as exc:
            raise BattleStoreError('Stored Sandbox result is invalid') from exc
        return value

    def _get(self, key, spec):
        if not self.store.path.exists():
            return None
        with self.store._reader() as db:
            if not db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',
                              ('table', TABLE)).fetchone():
                return None
            return self._cached(db, key, spec)

    def _save(self, key, spec, value):
        data = _canonical_json(value)
        if len(data) > MAX_TRACE_BYTES:
            raise BattleStoreError('Sandbox trace exceeds size limit')
        with self.store._writer() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS sandbox_results_v1 (
                owner_scope TEXT NOT NULL, battle_key TEXT NOT NULL, body BLOB NOT NULL,
                digest TEXT NOT NULL, saved_at INTEGER NOT NULL, PRIMARY KEY(owner_scope, battle_key)
            ) WITHOUT ROWID''')
            previous = self._cached(db, key, spec)
            if previous is not None:
                previous['summary']['compute_wall_ms'] = value['summary']['compute_wall_ms']
                if previous != value:
                    raise BattleStoreError('Conflicting native Sandbox result')
                return
            db.execute('INSERT INTO sandbox_results_v1 VALUES (?, ?, ?, ?, ?)',
                       (self.store.owner_scope, key, data, _json_hash(value), int(time())))

    def simulate(self, request):
        try:
            spec, payload = self.prepare(request)
        except UnsupportedBattle as exc:
            return {'schema': SCHEMA, 'status': 'unsupported', 'error': {'message': str(exc)}}
        except (ValueError, RecursionError, UnicodeError):
            return {'schema': SCHEMA, 'status': 'invalid', 'error': {'message': 'Invalid Sandbox battle request'}}
        key = _json_hash(spec)
        try:
            self._check_inputs()
            saved = self._get(key, spec)
            if saved is not None:
                self._check_inputs()
                return saved
            started = perf_counter()
            proc = subprocess.run(['node', str(RUNNER)], input=_canonical_json({
                **payload, 'gamemaster_path': str(self.standard.client.gamemaster),
            }), capture_output=True, check=True, timeout=20, env=child_environment({
                'PVP_PVPOKE_SOURCE': str(self.standard.client.source),
            }))
            if len(proc.stdout) > MAX_TRACE_BYTES:
                raise ValueError('Sandbox output is too large')
            value = self._result(spec, key, json.loads(proc.stdout), (perf_counter() - started) * 1000)
            self._check_inputs()
            if value['status'] == 'complete':
                self._save(key, spec, value)
            return value
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 3 and exc.stderr.strip() == b'unsupported_dynamic_form':
                return {'schema': SCHEMA, 'status': 'unsupported',
                        'error': {'message': 'Dynamic forms are outside the Sandbox contract'}}
        except (OSError, subprocess.SubprocessError, sqlite3.Error, DirectMatrixError, ValueError,
                KeyError, TypeError, RecursionError):
            pass
        return {'schema': SCHEMA, 'status': 'failed', 'error': {'message': 'Sandbox calculation unavailable'}}
