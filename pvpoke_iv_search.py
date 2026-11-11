"""Bounded, resumable IV search for one fixed build and explicit matchup slots."""
import json
import math
import re
import sqlite3
import subprocess
import threading
from bisect import bisect_right
from collections import Counter
from pathlib import Path

from pvpoke_battle_service import _canonical_json, _json_hash
from pvpoke_battle_store import BattleStoreError
from pvpoke_calculation_version import content_hash
from pvpoke_child_env import child_environment
from pvpoke_direct_backend import DirectMatrixError
from pvpoke_iv_modes import _cp, _levels, select_opponent_ivs
from pvpoke_missing_analysis import AnalysisUnavailable, battle_facts
from pvpoke_role_evaluation import _definition, _meets, condition_id

SCHEMA = 'important-iv-search-v1'
RAW_IV_COUNT = 4096
MAX_CONDITIONS = 6
MAX_STEP_BATTLES = 32
CLOSE_RATING_MARGIN = 25
MAX_PLAN_BYTES = 96 * 1024
IV_KEYS = ('attack', 'defense', 'hp')
ROOT = Path(__file__).resolve().parent
PROFILER = ROOT / 'pvpoke_iv_boundaries.js'
STEP_LOCK = threading.Lock()
BOUNDARY_NAMES = ('hp', 'cmp', 'breakpoint', 'bulkpoint',
                  'charged_1', 'charged_2', 'incoming_charged_1', 'incoming_charged_2')


def _ivs(index):
    return index >> 8, (index >> 4) & 15, index & 15


def _neighbors(index):
    for value, shift in zip(_ivs(index), (8, 4, 0)):
        if value > 0:
            yield index - (1 << shift)
        if value < 15:
            yield index + (1 << shift)


def _bitset(indices):
    bits = bytearray(512)
    for index in indices:
        bits[index // 8] |= 1 << (index % 8)
    return bits.hex()


def _pool(service, template, floors):
    candidate = template['combatants'][0]
    pokemon = service.species[candidate['species_id']]
    base = pokemon['baseStats']
    levels = _levels(pokemon, service.cpms, template['rules']['max_level'])
    cp_cap = template['rules']['cp_cap']
    fast, charged = candidate['moves']['fast'], candidate['moves']['charged']
    rows, stats = {}, {}
    for index in range(RAW_IV_COUNT):
        a, d, h = ivs = _ivs(index)
        if any(value < floor for value, floor in zip(ivs, floors)):
            continue
        # CP is nondecreasing with level for a fixed IV tuple.
        pos = bisect_right(levels, cp_cap, key=lambda level: _cp(base, level[1], *ivs))
        if not pos:
            continue
        level, cpm = levels[pos - 1]
        rows[index] = dict(species=candidate['species_id'], fast=fast, charged1=charged[0],
                           charged2=charged[1], atk=a, hp=h, level=level,
                           cp=_cp(base, cpm, *ivs), **{'def': d})
        hp = 10 if pokemon.get('dex') == 292 else max(10, math.floor((base['hp'] + h) * cpm))
        stats[index] = ((base['atk'] + a) * cpm, (base['def'] + d) * cpm, hp)
    return rows, stats


def _profiles(service, rows, conditions):
    request = {'gamemaster_path': str(service.client.gamemaster),
               'candidates': list(rows.values()), 'conditions': conditions}
    try:
        proc = subprocess.run(['node', str(PROFILER)], input=_canonical_json(request),
                              capture_output=True, check=True, timeout=20,
                              env=child_environment({'PVP_PVPOKE_SOURCE': str(service.client.source)}))
        profiles = json.loads(proc.stdout)
        if (type(profiles) is not list or len(profiles) != len(rows) or
                any(type(cells) is not list or len(cells) != len(conditions) or
                    any(type(cell) is not list or len(cell) != len(BOUNDARY_NAMES) or
                        any(type(n) is not int or abs(n) > 10000 for n in cell) for cell in cells)
                    for cells in profiles)):
            raise ValueError('Invalid static profile')
        return {index: tuple(map(tuple, cells)) for index, cells in zip(rows, profiles)}
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError) as exc:
        raise AnalysisUnavailable('Could not calculate static IV boundaries') from exc


def _prioritize(profiles, stats, condition_count, default_index=None):
    by_condition = [[set() for _ in BOUNDARY_NAMES] for _ in range(condition_count)]
    scores = Counter()
    frequencies = Counter(profiles.values())
    for index, cells in profiles.items():
        for shift, value in zip((8, 4, 0), _ivs(index)):
            other = index + (1 << shift)
            if value == 15 or other not in profiles:
                continue
            for slot, (a, b) in enumerate(zip(cells, profiles[other])):
                for kind, (before, after) in enumerate(zip(a, b)):
                    if before != after:
                        by_condition[slot][kind].update((index, other))
                        # Give the first (most important) condition greater weight.
                        scores[index] += condition_count - slot
                        scores[other] += condition_count - slot
    ranked = sorted(profiles, key=lambda idx: (frequencies[profiles[idx]], -scores[idx], idx))
    anchors = [max(stats, key=lambda idx: stats[idx][axis]) for axis in range(3)]
    anchors.insert(0, max(stats, key=lambda idx: math.prod(stats[idx])))
    if default_index in profiles:
        anchors.insert(0, default_index)
    # Sample distinct signatures first. These groups are scheduling hints only.
    seen, front, back = set(), [], []
    for idx in ranked:
        signature = profiles[idx]
        (back if signature in seen else front).append(idx)
        seen.add(signature)
    return list(dict.fromkeys(anchors + front + back)), [
        {name: _bitset(indices) for name, indices in zip(BOUNDARY_NAMES, flags)} for flags in by_condition
    ]


class IVSearch:
    """Use only the service's trusted owner, data paths and battle process."""

    def __init__(self, service):
        if service.store is None:
            raise ValueError('IV search requires persistent battle evidence')
        self.service = service
        self.store = service.store

    def _check_inputs(self):
        try:
            self.service._check_inputs()
            return _json_hash([content_hash(path) for path in (
                Path(__file__), PROFILER, ROOT / 'pvpoke_iv_modes.py',
            )])
        except (OSError, DirectMatrixError) as exc:
            raise AnalysisUnavailable('Active IV search inputs are unavailable') from exc

    def start(self, requests, *, iv_floors=(0, 0, 0)):
        """Plan IVs at their highest legal level. Put important matchups first."""
        if type(requests) not in (list, tuple) or not 1 <= len(requests) <= MAX_CONDITIONS:
            raise ValueError('IV search requires 1–6 explicit matchup conditions')
        if (type(iv_floors) not in (list, tuple) or len(iv_floors) != 3 or
                any(type(n) is not int or not 0 <= n <= 15 for n in iv_floors)):
            raise ValueError('Invalid IV floors')
        profiler = self._check_inputs()
        templates, conditions, slots = [], [], set()
        fixed = None
        for request in requests:
            spec, payload = self.service._prepare(request)
            candidate = spec['combatants'][0]
            full, _ = self.service._combatant({**candidate, 'initial': {**candidate['initial'], 'hp': 'full'}})
            if full['initial'] != candidate['initial']:
                raise ValueError('IV search requires full candidate HP')
            identity = (candidate['species_id'], candidate['moves'])
            if fixed is not None and fixed != identity:
                raise ValueError('IV search requires one species, form and moveset')
            fixed = identity
            slot = condition_id(spec, full_hp=True)
            if slot in slots:
                raise ValueError('Duplicate IV search condition')
            slots.add(slot)
            candidate['ivs'] = dict.fromkeys(IV_KEYS, 0)
            candidate['level'] = None
            candidate['initial']['hp'] = 'full'
            templates.append(spec)
            conditions.append({'opponent': payload['opponent'],
                               'buffs': [side['buffs'] for side in payload['initial']]})
        # Purified Pokémon have at least two points in each IV.
        floors = [max(n, 2) for n in iv_floors] if 'RETURN' in fixed[1]['charged'] else list(iv_floors)
        source = {'schema': SCHEMA, 'versions': dict(self.service.versions), 'profiler': profiler,
                  'templates': templates, 'floors': floors}
        search_id = _json_hash(source)
        if self._load(search_id) is not None:
            return search_id

        rows, stats = _pool(self.service, templates[0], floors)
        if not rows:
            raise ValueError('No eligible IVs fit the declared rules')
        profiles = _profiles(self.service, rows, conditions)
        if self._check_inputs() != profiler:
            raise AnalysisUnavailable('IV search implementation changed during calculation')
        try:
            a, d, h, _ = select_opponent_ivs(self.service.species[fixed[0]], self.service.cpms, 'default')
        except ValueError:
            default_index = None
        else:
            default_index = (a << 8) | (d << 4) | h
        order, boundaries = _prioritize(profiles, stats, len(conditions), default_index)
        plan = {'source': source, 'order': order, 'boundaries': boundaries}
        body = _canonical_json(plan)
        if len(body) > MAX_PLAN_BYTES:
            raise AnalysisUnavailable('IV search exceeds plan size limit')
        try:
            with self.store._writer() as db:
                db.execute('''CREATE TABLE IF NOT EXISTS important_iv_searches_v1 (
                    owner_scope TEXT NOT NULL, search_id TEXT NOT NULL, body BLOB NOT NULL,
                    digest TEXT NOT NULL, next_offset INTEGER NOT NULL,
                    PRIMARY KEY (owner_scope, search_id)
                ) WITHOUT ROWID''')
                db.execute('''INSERT INTO important_iv_searches_v1 VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(owner_scope, search_id) DO NOTHING''',
                    (self.store.owner_scope, search_id, body, _json_hash(plan)))
        except (sqlite3.Error, OSError, BattleStoreError) as exc:
            raise AnalysisUnavailable('Could not save IV search') from exc
        return search_id

    def _load(self, search_id):
        if type(search_id) is not str or not re.fullmatch(r'[a-f0-9]{64}', search_id):
            raise ValueError('Invalid IV search ID')
        try:
            if not self.store.path.exists():
                return None
            with self.store._reader() as db:
                if not db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',
                                  ('table', 'important_iv_searches_v1')).fetchone():
                    return None
                row = db.execute('''SELECT body, digest, next_offset FROM important_iv_searches_v1
                    WHERE owner_scope=? AND search_id=?''', (self.store.owner_scope, search_id)).fetchone()
            if row is None:
                return None
            payload, digest, offset = row
            if type(payload) is not bytes or len(payload) > MAX_PLAN_BYTES:
                raise ValueError('Invalid IV search payload')
            plan = json.loads(payload)
            slots = len(plan['source']['templates'])
            if (plan['source']['schema'] != SCHEMA or _json_hash(plan) != digest or
                    _json_hash(plan['source']) != search_id or not 0 <= offset < slots * len(plan['order'])):
                raise ValueError('Invalid IV search checksum or cursor')
            return plan, offset
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise AnalysisUnavailable('Could not read IV search') from exc

    def _scan(self, plan, offset, budget, requirements):
        source, order = plan['source'], plan['order']
        templates = source['templates']
        rows, stats = _pool(self.service, templates[0], source['floors'])
        if set(order) != rows.keys() or len(order) != len(rows):
            raise AnalysisUnavailable('Stored IV search eligibility differs')
        slots = [condition_id(spec, full_hp=True) for spec in templates]
        if requirements.keys() - set(slots):
            raise ValueError('Role requires a condition outside this IV search')
        checked = [set() for _ in slots]
        role_passes = [set() for _ in slots]
        tasks, close = [], []
        rank_by_index = {index: rank for rank, index in enumerate(order)} if budget >= 2 else {}
        total = len(slots) * len(order)

        def battle_spec(index, slot_index):
            template = templates[slot_index]
            base, opponent = template['combatants']
            candidate = {**base, 'ivs': dict(zip(IV_KEYS, _ivs(index))), 'level': rows[index]['level'],
                         'initial': {**base['initial'], 'hp': stats[index][2]}}
            return {**template, 'combatants': [candidate, opponent]}

        try:
            with self.store._reader() as db:
                for i in range(total):
                    position = (i + offset) % total
                    rank, slot_index = divmod(position, len(slots))
                    index = order[rank]
                    spec = battle_spec(index, slot_index)
                    key = _json_hash(spec)
                    row = self.store._row(db, key)
                    result = self.store._decode(row, key, spec, source['versions']) if row else None
                    if result is None:
                        if len(tasks) < budget:
                            tasks.append((position, spec))
                        continue
                    checked[slot_index].add(index)
                    if rank_by_index and abs(result['rating'] - 500) <= CLOSE_RATING_MARGIN:
                        close.append((abs(result['rating'] - 500), slot_index, index))
                    rule = requirements.get(slots[slot_index])
                    if rule is not None and _meets(rule, battle_facts(result)):
                        role_passes[slot_index].add(index)
        except (sqlite3.Error, OSError, BattleStoreError) as exc:
            raise AnalysisUnavailable('Could not read saved IV evidence') from exc
        all_checked = set.intersection(*checked)
        any_checked = set.union(*checked)
        qualifying = [i for i, slot in enumerate(slots) if slot in requirements]
        coverage = {
            'raw_iv_count': RAW_IV_COUNT, 'eligible_iv_count': len(rows), 'stat_iv_count': len(rows),
            'eligible_ivs': _bitset(rows), 'any_completed_ivs': _bitset(any_checked),
            'all_completed_ivs': _bitset(all_checked), 'all_completed_iv_count': len(all_checked),
            'qualifying_ivs': _bitset(set.intersection(*(role_passes[i] for i in qualifying))) if qualifying else None,
            'conditions': [{'id': slot, 'opponent': templates[i]['combatants'][1],
                            'self_initial': templates[i]['combatants'][0]['initial'],
                            'policies': templates[i]['policies'], 'boundaries': plan['boundaries'][i],
                            'completed_count': len(checked[i]), 'completed_ivs': _bitset(checked[i]),
                            'remaining_ivs': _bitset(rows.keys() - checked[i])} for i, slot in enumerate(slots)],
        }
        # Keep at least half the budget for the saved cursor. The rest can
        # verify unplayed neighboring IVs around observed close battles.
        next_offset = (tasks[-1][0] + 1) % total if tasks else offset
        if close and len(tasks) > 1:
            base_count = (len(tasks) + 1) // 2
            front = dict(tasks[:base_count])
            for _, slot_index, anchor in sorted(close, key=lambda item: (item[1], item[0], item[2])):
                for index in _neighbors(anchor):
                    if len(front) == len(tasks):
                        break
                    if index in rank_by_index and index not in checked[slot_index]:
                        position = rank_by_index[index] * len(slots) + slot_index
                        if position not in front:
                            front[position] = battle_spec(index, slot_index)
                if len(front) == len(tasks):
                    break
            selected = dict(front)
            for position, spec in tasks[base_count:]:
                if len(selected) == len(tasks):
                    break
                selected.setdefault(position, spec)
            # The cursor only skips the scheduled prefix; adaptive picks ahead
            # will be recognized as saved evidence on future steps.
            tasks = list(selected.items())
            next_offset = (tasks[base_count - 1][0] + 1) % total
        return coverage, tasks, next_offset

    def step(self, search_id, *, budget=0, role=None):
        """Read or advance a search. A positive budget limits new battle attempts."""
        if type(budget) is not int or not 0 <= budget <= MAX_STEP_BATTLES:
            raise ValueError('IV search step budget must be 0–32 battles')
        definition = _definition(role) if role is not None else None
        with STEP_LOCK:
            saved = self._load(search_id)
            if saved is None:
                return None
            plan, offset = saved
            source = plan['source']
            if source['versions'] != self.service.versions or source['profiler'] != self._check_inputs():
                return {'search_id': search_id, 'state': 'stale', 'coverage': None, 'new_battles': 0}
            requirements = definition['requirements'] if definition else {}
            coverage, tasks, next_offset = self._scan(plan, offset, budget, requirements)
            before = self.service.cache_stats['engine_calls']
            outcomes = Counter()
            if tasks:
                for _, spec in tasks:
                    errors = self.service.cache_stats['storage_errors']
                    result = self.service.simulate(spec)
                    if self.service.cache_stats['storage_errors'] != errors:
                        raise AnalysisUnavailable('Could not persist IV battle evidence')
                    outcomes[result['status']] += 1
                try:
                    with self.store._writer() as db:
                        db.execute('''UPDATE important_iv_searches_v1 SET next_offset=?
                            WHERE owner_scope=? AND search_id=? AND next_offset=?''',
                            (next_offset, self.store.owner_scope, search_id, offset))
                except (sqlite3.Error, OSError, BattleStoreError) as exc:
                    raise AnalysisUnavailable('Could not save IV search checkpoint') from exc
                coverage, _, _ = self._scan(plan, offset, 0, requirements)
            if source['profiler'] != self._check_inputs():
                raise AnalysisUnavailable('IV search implementation changed during search')
            complete = coverage['all_completed_iv_count'] == coverage['eligible_iv_count']
            state = 'complete' if complete else 'partial' if any(
                cell['completed_count'] for cell in coverage['conditions']) else 'unknown'
            return {'search_id': search_id, 'state': state, 'coverage': coverage,
                    'versions': source['versions'], 'candidate': source['templates'][0]['combatants'][0],
                    'rules': source['templates'][0]['rules'], 'iv_floors': source['floors'],
                    'role': definition, 'new_battles': self.service.cache_stats['engine_calls'] - before,
                    'attempt_outcomes': dict(outcomes),
                    'incomplete_reason': None if complete else 'unverified_conditions'}
