"""Owner-scoped Sandbox workspace and revisioned tactic snapshots."""
import json
import os
import sqlite3
import time

from pvpoke_battle_service import MAX_REQUEST_BYTES, _canonical_json, _identifier, _integer, _json_hash, _object
from pvpoke_sandbox import SandboxService
from pvpoke_tactic_search import TacticSearch

API_PATH = '/api/sandbox'
APP_PATH = '/app-api/sandbox'
PAGE_PATH = '/app/sandbox'
TABLE = 'sandbox_tactics_v1'
MAX_REVISION = 2**31 - 1
MAX_RECORD_BYTES = MAX_REQUEST_BYTES * 2


class TacticConflict(ValueError):
    """The tactic has a newer saved revision."""


class TacticUnavailable(ValueError):
    """The stored tactic cannot be safely read or written."""


def enabled():
    return os.environ.get('PVP_SANDBOX_ENABLED') == '1'


def search_enabled():
    return os.environ.get('PVP_TACTIC_SEARCH_ENABLED') == '1'


def _id(value):
    return _identifier(value, 'tactic ID', r'[a-f0-9]{32}')


class TacticStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _exists(db):
        return db.execute('SELECT 1 FROM sqlite_schema WHERE type=? AND name=?', ('table', TABLE)).fetchone()

    def list(self):
        if not self.store.path.exists():
            return []
        try:
            with self.store._reader() as db:
                if not self._exists(db):
                    return []
                rows = db.execute('''SELECT body, digest FROM sandbox_tactics_v1 AS tactics
                    WHERE owner_scope=? AND revision=(
                        SELECT MAX(revision) FROM sandbox_tactics_v1 AS latest
                        WHERE latest.owner_scope=tactics.owner_scope AND latest.tactic_id=tactics.tactic_id
                    ) ORDER BY saved_at DESC, tactic_id LIMIT 40''', (self.store.owner_scope,))
                return [{field: item[field] for field in ('tactic_id', 'revision', 'name', 'saved_at')}
                        for item in map(self._decode, rows)]
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise TacticUnavailable('Could not list saved tactics') from exc

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        body, digest = row
        if type(body) is not bytes or len(body) > MAX_RECORD_BYTES:
            raise ValueError('Invalid tactic payload')
        record = json.loads(body)
        if _json_hash(record) != digest or record['spec']['mode'] != 'sandbox':
            raise ValueError('Invalid saved tactic')
        return record

    def _load(self, db, tactic_id, revision=None):
        if revision is None:
            row = db.execute('''SELECT body, digest FROM sandbox_tactics_v1
                WHERE owner_scope=? AND tactic_id=? ORDER BY revision DESC LIMIT 1''',
                (self.store.owner_scope, tactic_id)).fetchone()
        else:
            row = db.execute('''SELECT body, digest FROM sandbox_tactics_v1
                WHERE owner_scope=? AND tactic_id=? AND revision=?''',
                (self.store.owner_scope, tactic_id, revision)).fetchone()
        record = self._decode(row)
        if record is not None and (record['tactic_id'] != tactic_id or
                                   revision is not None and record['revision'] != revision):
            raise ValueError('Mismatched tactic ID or revision')
        return record

    def load(self, tactic_id, revision=None, *, include_latest=False):
        tactic_id = _id(tactic_id)
        if revision is not None:
            revision = _integer(revision, 'revision', 1, MAX_REVISION)
        if not self.store.path.exists():
            return None
        try:
            with self.store._reader() as db:
                if not self._exists(db):
                    return None
                record = self._load(db, tactic_id, revision)
                if record is not None and include_latest:
                    latest = self._load(db, tactic_id) if revision is not None else record
                    return {**record, 'latest_revision': latest['revision']}
                return record
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise TacticUnavailable('Could not read saved tactic') from exc

    def save(self, sandbox, tactic_id, expected_revision, name, spec):
        tactic_id = _id(tactic_id)
        expected_revision = _integer(expected_revision, 'revision', 0, MAX_REVISION - 1)
        if type(name) is not str or not 1 <= len(name.strip()) <= 64 or any(ord(c) < 32 for c in name):
            raise ValueError('Tactic name must contain 1–64 characters')
        spec, _ = sandbox.prepare(spec)
        name = name.strip()
        record = {'tactic_id': tactic_id, 'revision': expected_revision + 1, 'name': name, 'spec': spec,
                  'saved_at': int(time.time())}
        try:
            with self.store._writer(critical=True) as db:
                db.execute('''CREATE TABLE IF NOT EXISTS sandbox_tactics_v1 (
                    owner_scope TEXT NOT NULL, tactic_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    body BLOB NOT NULL, digest TEXT NOT NULL, saved_at INTEGER NOT NULL,
                    PRIMARY KEY(owner_scope, tactic_id, revision)
                ) WITHOUT ROWID''')
                old = self._load(db, tactic_id)
                old_revision = old['revision'] if old else 0
                if old_revision == record['revision'] and old['name'] == name and old['spec'] == spec:
                    return old
                if old_revision != expected_revision:
                    raise TacticConflict('Saved tactic revision changed')
                data = _canonical_json(record)
                if len(data) > MAX_RECORD_BYTES:
                    raise TacticUnavailable('Saved tactic exceeds size limit')
                db.execute('INSERT INTO sandbox_tactics_v1 VALUES (?, ?, ?, ?, ?, ?)',
                           (self.store.owner_scope, tactic_id, record['revision'], data,
                            _json_hash(record), record['saved_at']))
        except TacticConflict:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise TacticUnavailable('Could not save tactic') from exc
        return record


def list_operation(store, payload):
    _object(payload, 'list tactics request', ('action',))
    return {'items': TacticStore(store).list()}


def app_operation(service, payload):
    action = payload.get('action')
    sandbox = SandboxService(service)
    if action == 'simulate':
        _object(payload, 'Sandbox request', ('action', 'spec'))
        return sandbox.simulate(payload['spec'])
    if action == 'standard':
        _object(payload, 'Standard comparison request', ('action', 'spec'))
        spec, _ = sandbox.prepare(payload['spec'])
        return service.simulate({'schema': spec['schema'], 'mode': 'standard', 'rules': spec['rules'],
                                 'combatants': spec['combatants']})
    if action in ('search_start', 'search_step'):
        if not search_enabled():
            raise TacticUnavailable('Tactic search is disabled')
        search = TacticSearch(service)
        if action == 'search_start':
            _object(payload, 'start tactic search', ('action', 'spec'))
            search_id = search.start(payload['spec'])
            return search.step(search_id, budget=0)
        _object(payload, 'advance tactic search', ('action', 'search_id', 'budget'))
        result = search.step(payload['search_id'], budget=payload['budget'])
        if result is None:
            raise ValueError('Unknown tactic search')
        return result
    tactics = TacticStore(service.store)
    if action == 'save':
        _object(payload, 'save tactic request', ('action', 'tactic_id', 'expected_revision', 'name', 'spec'))
        record = tactics.save(sandbox, payload['tactic_id'], payload['expected_revision'], payload['name'],
                              payload['spec'])
        return {**record, 'current': True, 'latest_revision': record['revision']}
    if action == 'load':
        _object(payload, 'load tactic request', ('action', 'tactic_id'), ('revision',))
        record = tactics.load(payload['tactic_id'], payload.get('revision'), include_latest=True)
        if record is None:
            raise ValueError('Saved tactic unavailable')
        return {**record, 'current': record['spec']['calculation_version'] == sandbox.calculation_version}
    raise ValueError('Unknown Sandbox operation')
