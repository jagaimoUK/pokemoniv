"""Evaluate a declared matchup role using current, owner-scoped battle evidence."""
import json
import re
import sqlite3
import time

from pvpoke_battle_service import _canonical_json, _json_hash
from pvpoke_battle_store import BattleStoreError
from pvpoke_missing_analysis import AnalysisUnavailable, MAX_MATCHUPS, MissingAnalysis, _versions

EVALUATION_SCHEMA = 'missing-role-evaluation-v1'
TABLE = 'missing_role_evaluations_v1'
HASH_PATTERN = r'[a-f0-9]{64}'
OUTCOMES = ('self_win', 'opponent_win', 'simultaneous_ko')
METRIC_LIMITS = {
    'hp': 10000, 'energy': 100, 'fast_damage': 10000, 'charged_damage': 10000,
    'charged_moves_resolved': 2000, 'shields_forced': 2, 'shields_remaining': 2,
}
MAX_SNAPSHOT_BYTES = 192 * 1024


def condition_id(normalized, *, full_hp=False):
    """Identify a slot shared across builds from a server-normalized battle spec.

    Pass full_hp for a role requiring each candidate to start at its own maximum.
    The caller selects an anchor; evaluation verifies that each build starts full.
    """
    candidate, opponent = normalized['combatants']
    initial = candidate['initial']
    if full_hp:
        initial = {**initial, 'hp': 'full'}
    slot = {key: value for key, value in normalized.items()
            if key not in ('combatants', 'calculation_version')}
    return _json_hash([slot, initial, opponent])


def _hash(value):
    if type(value) is not str or not re.fullmatch(HASH_PATTERN, value):
        raise ValueError('Invalid role snapshot or condition ID')
    return value


def _definition(value):
    fields = {'role_id', 'revision', 'meta_snapshot', 'priority', 'requirements'}
    if type(value) is not dict or value.keys() != fields:
        raise ValueError('Invalid role definition')
    role_id = value['role_id']
    if type(role_id) is not str or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', role_id):
        raise ValueError('Invalid role ID')
    if type(value['revision']) is not int or not 1 <= value['revision'] < 2**63:
        raise ValueError('Invalid role revision')
    if type(value['priority']) is not int or not 0 <= value['priority'] <= 1000:
        raise ValueError('Invalid role priority')
    _hash(value['meta_snapshot'])
    requirements = value['requirements']
    if type(requirements) is not dict or not 1 <= len(requirements) <= MAX_MATCHUPS:
        raise ValueError('A role requires 1–128 exact battle conditions')
    normalized = {}
    for slot, test in requirements.items():
        _hash(slot)
        if type(test) is not dict or not test or test.keys() - {'outcomes', 'minimum'}:
            raise ValueError('Invalid role requirement')
        entry = {}
        if 'outcomes' in test:
            allowed = test['outcomes']
            if (type(allowed) is not list or not 1 <= len(allowed) <= len(OUTCOMES)
                    or any(item not in OUTCOMES for item in allowed) or len(set(allowed)) != len(allowed)):
                raise ValueError('Invalid role outcomes')
            entry['outcomes'] = sorted(allowed)
        if 'minimum' in test:
            minimum = test['minimum']
            if (type(minimum) is not dict or not minimum or minimum.keys() - METRIC_LIMITS.keys()
                    or any(type(n) is not int or not 0 <= n <= METRIC_LIMITS[key]
                           for key, n in minimum.items())):
                raise ValueError('Invalid minimum role metrics')
            entry['minimum'] = dict(minimum)
        normalized[slot] = entry
    return {**value, 'requirements': normalized}


def _meets(requirement, facts):
    if 'outcomes' in requirement and facts['outcome'] not in requirement['outcomes']:
        return False
    metrics = {
        'hp': facts['terminal'][0]['hp'], 'energy': facts['terminal'][0]['energy_points'],
        'fast_damage': facts['damage'][0]['fast'], 'charged_damage': facts['damage'][0]['charged'],
        'charged_moves_resolved': facts['charged_moves_resolved'][0],
        'shields_forced': facts['shields_used'][1], 'shields_remaining': facts['terminal'][0]['shields'],
    }
    return all(metrics[key] >= n for key, n in requirement.get('minimum', {}).items())


def _assess(evidence, requirements):
    by_build = {}
    for cell in evidence['cells']:
        slots = by_build.setdefault(cell['build_id'], {})
        ids = [condition_id(cell['spec'])]
        if cell.get('starts_at_full_hp'):
            ids.append(condition_id(cell['spec'], full_hp=True))
        for slot in ids:
            if slot in requirements:
                slots[slot] = cell
    candidates = []
    for build, slots in sorted(by_build.items()):
        checks = {}
        owned = None
        for slot, cell in sorted(slots.items()):
            state = cell['state']
            meets = _meets(requirements[slot], cell['facts']) if state == 'complete' else None
            checks[slot] = {'state': state, 'meets': meets, 'battle_key': cell['battle_key']}
            instances = {match['instance_id'] for match in cell['inventory_matches']
                         if match['state'] == 'confirmed_owned' and match['build_match'] == 'exact'}
            owned = instances if owned is None else owned & instances
        values = [check['meets'] for check in checks.values()]
        evidence_complete = len(checks) == len(requirements) and None not in values
        meets = False if False in values else True if evidence_complete else None
        candidates.append({'build_id': build, 'meets': meets, 'checks': checks,
                           'evidence_complete': evidence_complete,
                           'confirmed_instances': sorted(owned) if meets else []})
    if any(item['confirmed_instances'] for item in candidates):
        state = 'covered'
    elif any(item['meets'] is True for item in candidates):
        state = 'ownership_confirmation_needed'
    elif not candidates or any(not item['evidence_complete'] for item in candidates):
        state = 'evidence_pending'
    else:
        # Bounded to the builds declared by this plan. No inventory absence is implied.
        state = 'gap'
    return state, candidates


class RoleEvaluation:
    """Persist immutable, versioned snapshots without invoking a battle engine."""

    def __init__(self, store):
        self.store = store
        self.analysis = MissingAnalysis(store)

    def history(self, evaluation_id):
        """Read one historical snapshot in this owner's scope."""
        _hash(evaluation_id)
        try:
            if not self.store.path.exists():
                return None
            with self.store._reader() as db:
                if not db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',
                                  ('table', TABLE)).fetchone():
                    return None
                row = db.execute('''SELECT body, digest, created_at FROM missing_role_evaluations_v1
                    WHERE owner_scope=? AND evaluation_id=?''', (self.store.owner_scope, evaluation_id)).fetchone()
            if row is None:
                return None
            payload, digest, created_at = row
            if type(payload) is not bytes or len(payload) > MAX_SNAPSHOT_BYTES:
                raise ValueError('Invalid role evaluation snapshot')
            value = json.loads(payload)
            if (value['schema'] != EVALUATION_SCHEMA or value['evaluation_id'] != evaluation_id
                    or _json_hash(value) != digest):
                raise ValueError('Invalid role evaluation checksum')
            return {**value, 'created_at': created_at}
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise AnalysisUnavailable('Could not read role evaluation') from exc

    def evaluate(self, analysis_id, definition, *, active_versions, normalizer=None):
        role = _definition(definition)
        versions = _versions(active_versions)
        evidence = self.analysis.evidence(analysis_id, active_versions=versions, normalizer=normalizer)
        if evidence is None:
            return None
        source = {
            'analysis_id': analysis_id, 'active_versions': versions, 'plan_versions': evidence['versions'],
            'ledger_revision': evidence['ledger_revision'], 'definition': role,
            'evidence_state': evidence['state'],
            'evidence_digest': _json_hash(evidence['cells']),
        }
        evaluation_id = _json_hash([EVALUATION_SCHEMA, source])
        previous = self.history(evaluation_id)
        if previous is not None:
            return previous

        state, candidates = _assess(evidence, role['requirements'])
        snapshot = {'schema': EVALUATION_SCHEMA, 'evaluation_id': evaluation_id, **source,
                    'state': state, 'scope': 'analysis_plan', 'candidates': candidates}
        data = _canonical_json(snapshot)
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise AnalysisUnavailable('Role evaluation exceeds snapshot size limit')
        try:
            with self.store._writer() as db:
                db.execute('''CREATE TABLE IF NOT EXISTS missing_role_evaluations_v1 (
                    owner_scope TEXT NOT NULL, evaluation_id TEXT NOT NULL,
                    body BLOB NOT NULL, digest TEXT NOT NULL, created_at INTEGER NOT NULL,
                    PRIMARY KEY (owner_scope, evaluation_id)
                ) WITHOUT ROWID''')
                db.execute('''INSERT INTO missing_role_evaluations_v1 VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(owner_scope, evaluation_id) DO NOTHING''',
                    (self.store.owner_scope, evaluation_id, data, _json_hash(snapshot), int(time.time())))
        except (sqlite3.Error, OSError, BattleStoreError) as exc:
            raise AnalysisUnavailable('Could not save role evaluation') from exc
        return self.history(evaluation_id)
