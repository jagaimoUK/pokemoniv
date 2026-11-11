"""Internal plans and read-only evidence for missing-IV analysis.

Plans pin exact normalized matchups and versions. BattleStore remains the
source of facts. No ownership, recommendation, or role judgement is inferred.
"""
import json
import re
import sqlite3
import time

from pvpoke_battle_service import _canonical_json, _json_hash
from pvpoke_battle_store import BattleStore, BattleStoreError, COMPLETENESS

MAX_MATCHUPS = 128
MAX_PLAN_BYTES = 512 * 1024
PLAN_SCHEMA = 'missing-analysis-plan-v1'
PLAN_TABLE = 'missing_analysis_plans_v1'


class AnalysisUnavailable(ValueError):
    """A plan could not be loaded or saved safely."""


def _versions(value):
    if type(value) is not dict or set(value) != {'engine', 'game_data'} or any(
        type(item) is not str or not re.fullmatch(r'[0-9a-f]{64}', item) for item in value.values()
    ):
        raise ValueError('Invalid analysis calculation versions')
    return dict(value)


class MissingAnalysis:
    """An internal reader bound to the server-owned BattleStore scope."""

    def __init__(self, store: BattleStore):
        self.store = store

    def save_plan(self, normalizer, requests):
        """Persist requested matchups without running a battle or mutating saved results."""
        if not isinstance(requests, (list, tuple)) or not 1 <= len(requests) <= MAX_MATCHUPS:
            raise ValueError('An analysis plan requires 1–128 matchups')
        versions = _versions(normalizer.versions)
        calculation_version = _json_hash([versions['engine'], versions['game_data']])
        specs = {}
        for request in requests:
            spec, _ = normalizer._prepare(request)
            if spec['calculation_version'] != calculation_version or spec['mode'] != 'standard':
                raise ValueError('Analysis requires standard matchups from one calculation version')
            specs[_json_hash(spec)] = spec
        plan = {'schema': PLAN_SCHEMA, 'versions': versions, 'specs': specs}
        data = _canonical_json(plan)
        if len(data) > MAX_PLAN_BYTES:
            raise ValueError('Analysis plan exceeds size limit')
        analysis_id = _json_hash(plan)
        try:
            with self.store._writer() as db:
                # The table has its own version. Existing BattleStore readers
                # still accept this v1 database and ignore the new table.
                db.execute('''CREATE TABLE IF NOT EXISTS missing_analysis_plans_v1 (
                    owner_scope TEXT NOT NULL, analysis_id TEXT NOT NULL,
                    plan_json BLOB NOT NULL, created_at INTEGER NOT NULL,
                    PRIMARY KEY (owner_scope, analysis_id)
                ) WITHOUT ROWID''')
                old = db.execute('''SELECT plan_json FROM missing_analysis_plans_v1
                    WHERE owner_scope = ? AND analysis_id = ?''',
                    (self.store.owner_scope, analysis_id)).fetchone()
                if old is None:
                    db.execute('''INSERT INTO missing_analysis_plans_v1 VALUES (?, ?, ?, ?)''',
                               (self.store.owner_scope, analysis_id, data, int(time.time())))
                elif old[0] != data:
                    raise AnalysisUnavailable('Conflicting analysis plan')
        except (sqlite3.Error, OSError, BattleStoreError) as exc:
            raise AnalysisUnavailable('Could not store analysis plan') from exc
        return analysis_id

    def evidence(self, analysis_id, *, active_versions):
        """Return coverage and per-matchup facts from a single SQLite snapshot."""
        if type(analysis_id) is not str or not re.fullmatch(r'[0-9a-f]{64}', analysis_id):
            raise ValueError('Invalid analysis ID')
        current = _versions(active_versions)
        try:
            if not self.store.path.exists():
                return None
            with self.store._reader() as db:
                if not db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?',
                                  ('table', PLAN_TABLE)).fetchone():
                    return None
                row = db.execute('''SELECT plan_json FROM missing_analysis_plans_v1
                    WHERE owner_scope = ? AND analysis_id = ?''',
                    (self.store.owner_scope, analysis_id)).fetchone()
                if row is None:
                    return None
                payload = row[0]
                if type(payload) is not bytes or len(payload) > MAX_PLAN_BYTES:
                    raise ValueError('Invalid plan payload')
                plan = json.loads(payload)
                if _json_hash(plan) != analysis_id or plan['schema'] != PLAN_SCHEMA:
                    raise ValueError('Invalid plan checksum or schema')
                versions = _versions(plan['versions'])
                cells = []
                completed = 0
                for key, spec in plan['specs'].items():
                    cell = {'battle_key': key, 'spec': spec, 'state': 'unknown', 'facts': None,
                            'ownership': 'unknown', 'recommendation': 'unreviewed'}
                    if versions != current:
                        cell['state'] = 'stale'
                    else:
                        saved = self.store._row(db, key)
                        if saved is not None:
                            try:
                                result = self.store._decode(saved, key, spec, versions)
                            except BattleStoreError:
                                cell['evidence_error'] = 'invalid_saved_result'
                            else:
                                cell['state'] = 'complete'
                                cell['completeness'] = COMPLETENESS
                                cell['facts'] = {field: result[field] for field in (
                                    'outcome', 'rating', 'terminal', 'shields_used', 'damage', 'turns',
                                )}
                                completed += 1
                    cells.append(cell)
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise AnalysisUnavailable('Could not read analysis evidence') from exc
        state = ('stale' if versions != current else 'complete' if completed == len(cells)
                 else 'partial' if completed else 'unknown')
        return {'analysis_id': analysis_id, 'versions': versions, 'state': state,
                'coverage': {'requested': len(cells), 'completed': completed}, 'cells': cells}
