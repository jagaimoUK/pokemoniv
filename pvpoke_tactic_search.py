"""Bounded, resumable fixed-script Sandbox search. Internal only, not an HTTP route.

All results are theoretical counterfactuals, not claims of live PvP reproducibility.
The opponent may change responses; the candidate's self actions never change in response.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from pathlib import Path
from time import monotonic, time

from pvpoke_battle_service import _canonical_json, _integer, _json_hash
from pvpoke_battle_store import BattleStoreError
from pvpoke_calculation_version import content_hash
from pvpoke_sandbox import SandboxService

SCHEMA = 'tactic-search-v1'
TABLE = 'tactic_searches_v1'
RESULT_TABLE = 'tactic_search_cells_v1'
MAX_CANDIDATES = 64
MAX_STEP = 8
MAX_STEP_WALL_SECONDS = 30
MAX_PLAN_BYTES = 192 * 1024
MAX_CELL_BYTES = 4 * 1024
STEP_LOCK = threading.Lock()


class TacticSearchError(ValueError):
    """Search data, checkpoint, or calculation could not be safely used."""


def _move_data(sandbox):
    # This fixed GameMaster is the same trusted file used by the running calculation.
    raw = sandbox.standard.client.gamemaster.read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise TacticSearchError('GameMaster exceeds safety limit')
    return {item['moveId']: item for item in json.loads(raw)['moves']}


def _first_possible_turn(spec, moves, *, actor=1, charged_slot=1):
    """Earliest *energy-only lower bound*, not a guaranteed executable turn.

    A native battle may delay or prevent the move through cooldown, KO, CMP or
    opponent actions. Every suggested turn is validated by the native runner.
    """
    combatant = spec['combatants'][actor]
    charge = moves[combatant['moves']['charged'][charged_slot]]
    fast = moves[combatant['moves']['fast']]
    cost, gain, turns = charge['energy'], fast['energyGain'], fast['turns']
    if (type(cost) is not int or type(gain) is not int or type(turns) is not int
            or not 0 <= cost <= 100 or not 1 <= turns <= 5):
        raise TacticSearchError('Unrecognized native move timings')
    needed = max(0, cost - combatant['initial']['energy'])
    if needed and not 0 < gain <= 100:
        return None
    turn = 1 + (math.ceil(needed / gain) * turns if needed else 0)
    return turn if turn <= 500 else None


def _followup_charge_turn(spec, moves, *, first_slot, second_slot, first_turn):
    """Energy-only lower bound for a second charged move after post-charge lock.

    This is intentionally conservative about claims: no schedule is labelled
    legal unless the native trace proves both actions actually executed.
    """
    combatant = spec['combatants'][0]
    fast = moves[combatant['moves']['fast']]
    first = moves[combatant['moves']['charged'][first_slot]]
    second = moves[combatant['moves']['charged'][second_slot]]
    gain, duration = fast['energyGain'], fast['turns']
    if not 0 < gain <= 100 or not 1 <= duration <= 5:
        return None
    first_fasts = (first_turn - 1) // duration
    available = min(100, combatant['initial']['energy'] + first_fasts * gain)
    remainder = max(0, available - first['energy'])
    additional = math.ceil(max(0, second['energy'] - remainder) / gain)
    second_turn = first_turn + 2 + additional * duration
    return second_turn if second_turn <= 500 else None


def _candidates(sandbox, spec):
    moves = _move_data(sandbox)
    seed_actions = spec['actions']
    seed_decisions = spec['shield_decisions']
    opponent_actions = [action for action in seed_actions if action['actor'] == 1]
    self_actions = [action for action in seed_actions if action['actor'] == 0]
    seen, candidates = set(), []
    profiles = [('original', self_actions)]
    used_ids = {action['id'] for action in seed_actions}
    busy = {(action['actor'], action['turn']) for action in seed_actions}
    charge_moves = spec['combatants'][0]['moves']['charged']
    fast = moves[spec['combatants'][0]['moves']['fast']]
    duration = fast['turns']

    def add_profile(name, schedule):
        if all(1 <= turn <= 500 and (0, turn) not in busy and aid not in used_ids
               for aid, turn, _, _ in schedule) and len(set(turn for _, turn, _, _ in schedule)) == len(schedule):
            additional = [{'id': aid, 'actor': 0, 'turn': turn, 'kind': kind,
                           **({'move_id': move} if move is not None else {})}
                          for aid, turn, kind, move in schedule]
            profiles.append((name, self_actions + additional))

    # Prefer a credible energy lower bound over hard-coded early charged turns.
    # Delayed throws explicitly sample banking one or two extra fast moves.
    first_turns = []
    for slot, move_id in enumerate(charge_moves):
        earliest = _first_possible_turn(spec, moves, actor=0, charged_slot=slot)
        first_turns.append(earliest)
        if earliest is None:
            continue
        for bank in (0, 1, 2):
            turn = earliest + bank * duration
            add_profile(f'charged_{slot}_bank{bank}', [
                (f'search_self_{slot}_{bank}', turn, 'charged', move_id)
            ])

    # Two throws can make a different role possible than a single early throw.
    # Include same move twice and both permutations of mixed moves.
    for first_slot in range(len(charge_moves)):
        earliest = first_turns[first_slot]
        if earliest is None:
            continue
        for second_slot in range(len(charge_moves)):
            second_turn = _followup_charge_turn(
                spec, moves, first_slot=first_slot, second_slot=second_slot,
                first_turn=earliest)
            if second_turn is None:
                continue
            add_profile(f'double_{first_slot}_{second_slot}', [
                (f'search_double_{first_slot}_{second_slot}_a', earliest, 'charged',
                 charge_moves[first_slot]),
                (f'search_double_{first_slot}_{second_slot}_b', second_turn, 'charged',
                 charge_moves[second_slot]),
            ])

    wait_turns = [1]
    if first_turns[0] is not None:
        wait_turns.append(first_turns[0])
    for turn in dict.fromkeys(wait_turns):
        add_profile(f'wait_t{turn}', [(f'search_wait_{turn}', turn, 'wait', None)])

    alternate = _first_possible_turn(spec, moves)
    alt_id = 'search_opponent_alternate'
    for strategy, mine in profiles:
        shared = sorted(opponent_actions + mine, key=lambda action: (action['turn'], action['actor']))
        active = {action['id'] for action in shared}
        original = [decision for decision in seed_decisions if decision['action_id'] in active]
        charged_self = [action for action in mine if action['kind'] == 'charged']
        variations = [('original', shared, original)]

        if charged_self:
            for choice in (False, True):
                if choice and spec['combatants'][1]['initial']['shields'] == 0:
                    continue
                adjusted = [d for d in original if d['action_id'] not in
                            {a['id'] for a in charged_self}]
                adjusted += [{'action_id': a['id'], 'defender': 1, 'use_shield': choice}
                             for a in charged_self]
                variations.append(('shield_yes' if choice else 'shield_no', shared, adjusted))

        if (alternate is not None and (1, alternate) not in busy and alt_id not in active and
                alt_id not in used_ids):
            altered = shared + [{'id': alt_id, 'actor': 1, 'turn': alternate, 'kind': 'charged',
                                 'move_id': spec['combatants'][1]['moves']['charged'][1]}]
            variations.append(('alternate_charged', altered, original))
            if spec['combatants'][0]['initial']['shields'] > 0:
                variations.append(('alternate_charged_self_shield', altered, original + [
                    {'action_id': alt_id, 'defender': 0, 'use_shield': True}]))

        for response, actions, decisions in variations:
            raw = {**spec, 'actions': sorted(actions, key=lambda a: (a['turn'], a['actor'])),
                   'shield_decisions': sorted(decisions, key=lambda d: d['action_id'])}
            normalized, _ = sandbox.prepare(raw)
            fingerprint = _json_hash([normalized['actions'], normalized['shield_decisions']])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            candidates.append({'strategy': strategy, 'response': response, 'spec': normalized,
                               'self_actions': [a['id'] for a in mine],
                               'opponent_alternate_id': alt_id if response == 'alternate_charged' else None})
            if len(candidates) == MAX_CANDIDATES:
                return candidates
    return candidates

class TacticSearch:
    """Checkpoint each candidate separately; a restarted process reuses saved Sandbox cells."""

    def __init__(self, standard):
        self.sandbox = SandboxService(standard)
        self.store = self.sandbox.store

    def _version(self):
        self.sandbox._check_inputs()
        return _json_hash([self.sandbox.calculation_version, content_hash(Path(__file__))])

    def start(self, request):
        spec, _ = self.sandbox.prepare(request)
        candidates = _candidates(self.sandbox, spec)
        if not candidates:
            raise TacticSearchError('No supported tactics')
        plan = {'schema': SCHEMA, 'version': self._version(), 'seed': spec, 'candidates': candidates}
        body = _canonical_json(plan)
        if len(body) > MAX_PLAN_BYTES:
            raise TacticSearchError('Tactic plan exceeds size limit')
        search_id = _json_hash(plan)
        try:
            with self.store._writer() as db:
                db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
                    owner_scope TEXT NOT NULL, search_id TEXT NOT NULL, body BLOB NOT NULL,
                    digest TEXT NOT NULL, next_index INTEGER NOT NULL,
                    PRIMARY KEY (owner_scope, search_id)
                ) WITHOUT ROWID''')
                db.execute(f'''CREATE TABLE IF NOT EXISTS {RESULT_TABLE} (
                    owner_scope TEXT NOT NULL, search_id TEXT NOT NULL, cell_index INTEGER NOT NULL,
                    body BLOB NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY (owner_scope, search_id, cell_index)
                ) WITHOUT ROWID''')
                row = db.execute(f'SELECT body, digest FROM {TABLE} WHERE owner_scope=? AND search_id=?',
                                 (self.store.owner_scope, search_id)).fetchone()
                if row is None:
                    db.execute(f'INSERT INTO {TABLE} VALUES (?, ?, ?, ?, 0)',
                               (self.store.owner_scope, search_id, body, _json_hash(plan)))
                elif row != (body, _json_hash(plan)):
                    raise TacticSearchError('Conflicting tactic plan')
        except (sqlite3.Error, OSError, BattleStoreError) as exc:
            raise TacticSearchError('Could not persist tactic search') from exc
        return search_id

    def _load(self, search_id):
        if type(search_id) is not str or not re.fullmatch(r'[a-f0-9]{64}', search_id):
            raise ValueError('Invalid tactic search ID')
        if not self.store.path.exists():
            return None
        try:
            with self.store._reader() as db:
                table = db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',
                                   ('table', TABLE)).fetchone()
                if table is None:
                    return None
                row = db.execute(f'SELECT body, digest, next_index FROM {TABLE} WHERE owner_scope=? AND search_id=?',
                                 (self.store.owner_scope, search_id)).fetchone()
                if row is None:
                    return None
                body, digest, offset = row
                if type(body) is not bytes or len(body) > MAX_PLAN_BYTES:
                    raise ValueError('Invalid tactic plan size')
                plan = json.loads(body)
                count = len(plan['candidates'])
                if (_canonical_json(plan) != body or _json_hash(plan) != digest or
                        _json_hash(plan) != search_id or plan['schema'] != SCHEMA or
                        not 1 <= count <= MAX_CANDIDATES or type(offset) is not int or
                        not 0 <= offset <= count):
                    raise ValueError('Invalid tactic plan or cursor')
                rows = db.execute(f'''SELECT cell_index, body, digest FROM {RESULT_TABLE}
                    WHERE owner_scope=? AND search_id=? ORDER BY cell_index''',
                    (self.store.owner_scope, search_id)).fetchall()
                if len(rows) != offset:
                    raise ValueError('Tactic checkpoint differs from saved cells')
                cells = []
                for index, data, checksum in rows:
                    if index != len(cells) or type(data) is not bytes or len(data) > MAX_CELL_BYTES:
                        raise ValueError('Invalid tactic cell')
                    cell = json.loads(data)
                    if (_canonical_json(cell) != data or _json_hash(cell) != checksum or
                            cell['index'] != index or cell['candidate_key'] !=
                            _json_hash(plan['candidates'][index]['spec'])):
                        raise ValueError('Corrupt tactic cell')
                    cells.append(cell)
                return plan, offset, cells
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise TacticSearchError('Could not read tactic search checkpoint') from exc

    @staticmethod
    def _progress(search_id, plan, cells, *, attempts=0, cache_hits=0, blocked=None):
        count = len(plan['candidates'])
        completed = sum(cell['status'] == 'complete' for cell in cells)
        valid = sum(cell['status'] == 'complete' and cell['all_self_executed'] and
                    cell['opponent_response_executed'] and
                    cell.get('all_requested_shields_honored', False) for cell in cells)
        exhausted = len(cells) == count
        state = ('blocked' if blocked else 'complete' if exhausted and completed == count
                 else 'partial' if cells else 'unknown')
        return {'search_id': search_id, 'state': state, 'version': plan['version'],
                'coverage': {'planned_scripts': count, 'attempted_scripts': len(cells),
                             'complete_scripts': completed, 'fully_executed_scripts': valid,
                             'remaining_scripts': count - len(cells), 'scheduled_exhausted': exhausted},
                'attempts_this_step': attempts, 'cache_hits_this_step': cache_hits,
                'incomplete_reason': blocked or (None if exhausted and completed == count else 'unverified_scripts'),
                'results': cells, 'information_model': 'fixed_script_counterfactual',
                'live_reproducibility': 'not_verified'}

    def step(self, search_id, *, budget=0):
        if type(budget) is not int or not 0 <= budget <= MAX_STEP:
            raise ValueError('Tactic step budget must be between 0 and 8')
        with STEP_LOCK:
            saved = self._load(search_id)
            if saved is None:
                return None
            plan, offset, cells = saved
            if plan['version'] != self._version():
                return {**self._progress(search_id, plan, cells), 'state': 'stale',
                        'incomplete_reason': 'calculation_or_search_version_changed'}
            calls = hits = 0
            started = monotonic()
            blocked = None
            for index in range(offset, min(len(plan['candidates']), offset + budget)):
                if monotonic() - started >= MAX_STEP_WALL_SECONDS:
                    break
                candidate = plan['candidates'][index]
                spec, _ = self.sandbox.prepare(candidate['spec'])
                if spec != candidate['spec']:
                    blocked = 'normalized_conditions_changed'
                    break
                key = _json_hash(spec)
                try:
                    cached = self.sandbox._get(key, spec)
                except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                    blocked = 'stored_sandbox_evidence_unavailable'
                    break
                result = self.sandbox.simulate(spec)
                calls += 1
                if cached is not None:
                    hits += 1
                if result['status'] not in ('complete', 'partial'):
                    blocked = 'sandbox_' + result['status']
                    break
                summary = result['summary']
                actions = {a['action_id']: a['status'] for a in summary['action_results']}
                required_self = candidate['self_actions']
                alternate = candidate['opponent_alternate_id']
                cell = {'index': index, 'candidate_key': key, 'battle_key': summary['battle_key'],
                        'strategy': candidate['strategy'], 'response': candidate['response'],
                        'status': result['status'], 'outcome': summary['outcome'],
                        'all_self_executed': all(actions.get(a) == 'executed' for a in required_self),
                        'opponent_response_executed': alternate is None or
                        actions.get(alternate) == 'executed',
                        'all_requested_shields_honored': all(
                            row['used'] is row['requested'] for row in result['shield_results']),
                        'evidence_class': 'theoretical_script_only',
                        'simulator_cached': cached is not None}
                body = _canonical_json(cell)
                if len(body) > MAX_CELL_BYTES:
                    raise TacticSearchError('Tactic evidence exceeds size limit')
                try:
                    with self.store._writer() as db:
                        row = db.execute(f'SELECT next_index FROM {TABLE} WHERE owner_scope=? AND search_id=?',
                                         (self.store.owner_scope, search_id)).fetchone()
                        if row != (index,):
                            raise TacticSearchError('Tactic cursor updated concurrently')
                        db.execute(f'INSERT INTO {RESULT_TABLE} VALUES (?, ?, ?, ?, ?)',
                                   (self.store.owner_scope, search_id, index, body, _json_hash(cell)))
                        db.execute(f'UPDATE {TABLE} SET next_index=? WHERE owner_scope=? AND search_id=?',
                                   (index + 1, self.store.owner_scope, search_id))
                except (sqlite3.Error, OSError, BattleStoreError) as exc:
                    raise TacticSearchError('Could not persist tactic checkpoint') from exc
                cells.append(cell)
            return self._progress(search_id, plan, cells, attempts=calls, cache_hits=hits, blocked=blocked)
