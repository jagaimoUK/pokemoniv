"""Owner-scoped, append-only Great League selection snapshots."""
import json
import re

from pvpoke_battle_service import _canonical_json, _integer, _items, _object
from pvpoke_ownership import Ownership, OwnershipConflict, _id, _now

ACTIONS = ('selection_save', 'selection_latest', 'selection_history', 'selection_pool')
FORM = r'[a-z0-9_\-]{1,100}'
IV = r'(?:[0-9]|1[0-5])/(?:[0-9]|1[0-5])/(?:[0-9]|1[0-5])'
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS selection_snapshots_v1 (
        revision INTEGER PRIMARY KEY,
        owner_scope TEXT NOT NULL, species_id TEXT NOT NULL,
        request_id TEXT NOT NULL, saved_at TEXT NOT NULL, body BLOB NOT NULL,
        UNIQUE (owner_scope, request_id)
    )""",
    """CREATE INDEX IF NOT EXISTS selection_latest_v1
       ON selection_snapshots_v1(owner_scope, species_id, revision DESC)""",
    """CREATE TABLE IF NOT EXISTS selection_instances_v1 (
        revision INTEGER NOT NULL, instance_id TEXT NOT NULL,
        PRIMARY KEY (revision, instance_id)
    ) WITHOUT ROWID""",
    """CREATE INDEX IF NOT EXISTS selection_history_v1
       ON selection_instances_v1(instance_id, revision DESC)""",
)


def _text(value, limit):
    if type(value) is not str or len(value) > limit:
        raise ValueError('Invalid selection text')
    return value


def _hash(value):
    if value is not None:
        _id(value, r'[0-9a-f]{64}')
    return value


def _species(value):
    return _id(value, FORM)


def _candidate(value):
    _object(value, 'selection candidate', ('ivs', 'role', 'moves', 'evidence'),
            ('instance_id', 'goal'))
    ivs = _id(value['ivs'], IV)
    if value['role'] not in ('important', 'alternative'):
        raise ValueError('Invalid selection role')
    moves = [_id(m, r'[A-Z0-9_]{1,100}') for m in _items(value['moves'], 'moves', 3, 3)]
    evidence = [_text(item, 240) for item in _items(value['evidence'], 'evidence', 0, 3)]
    instance_id = value.get('instance_id')
    goal = _text(value.get('goal', ''), 400)
    if instance_id is not None:
        _id(instance_id)
    elif goal:
        raise ValueError('A goal requires a confirmed individual')
    return dict(ivs=ivs, role=value['role'], moves=moves, evidence=evidence,
                instance_id=instance_id, goal=goal)


def _save(store, payload, species_ids):
    _object(payload, 'selection save',
            ('action', 'species_id', 'request_id', 'meta_sha256', 'calculation_version',
             'policy_version', 'candidates'))
    species = _species(payload['species_id'])
    if species not in species_ids:
        raise ValueError('Unknown selection form')
    request_id = _id(payload['request_id'])
    rows = [_candidate(row) for row in _items(payload['candidates'], 'candidates', 0, 4096)]
    linked = [row for row in rows if row['instance_id'] is not None]
    if len({row['instance_id'] for row in linked}) != len(linked):
        raise ValueError('The same individual occurs more than once')
    body = _canonical_json(dict(
        species_id=species, league='great', cp_cap=1500,
        meta_sha256=_hash(payload['meta_sha256']),
        calculation_version=_hash(payload['calculation_version']),
        policy_version=_text(payload['policy_version'], 80), candidates=rows))
    inventory = Ownership(store)
    with store._writer(critical=True) as db:
        for statement in SCHEMA:
            db.execute(statement)
        existing = db.execute(
            'SELECT revision, body FROM selection_snapshots_v1 WHERE owner_scope=? AND request_id=?',
            (store.owner_scope, request_id)).fetchone()
        if existing is not None:
            if existing[1] != body:
                raise OwnershipConflict('Selection request ID already used')
            return {'revision': existing[0]}
        for row in linked:
            record = inventory._instance(db, row['instance_id']) if inventory._exists(db) else None
            if record is None or record['state'] != 'confirmed_owned':
                raise ValueError('Select a confirmed individual from inventory')
            ivs = '/'.join(str(record['ivs'][name]) for name in ('attack', 'defense', 'hp'))
            if ivs != row['ivs']:
                raise ValueError('Selected individual IVs do not match the evaluation')
        cursor = db.execute(
            'INSERT INTO selection_snapshots_v1(owner_scope,species_id,request_id,saved_at,body) VALUES (?,?,?,?,?)',
            (store.owner_scope, species, request_id, _now(), body))
        revision = cursor.lastrowid
        db.executemany('INSERT INTO selection_instances_v1 VALUES (?,?)',
                       ((revision, row['instance_id']) for row in linked))
        return {'revision': revision}


def _latest_row(db, owner, species):
    return db.execute(
        """SELECT revision,saved_at,body FROM selection_snapshots_v1
           WHERE owner_scope=? AND species_id=? ORDER BY revision DESC LIMIT 1""",
        (owner, species)).fetchone()


def _pool(db, owner, species_ids):
    snapshots = {}
    for species in species_ids:
        row = _latest_row(db, owner, species)
        if row is None:
            continue
        snapshot = json.loads(row[2])
        if (snapshot['species_id'], snapshot['league'], snapshot['cp_cap']) != (species, 'great', 1500):
            raise ValueError('Saved selection form or league differs')
        candidates = snapshot['candidates']
        snapshots[species] = {
            'revision': row[0],
            'ivs': list(dict.fromkeys(candidate['ivs'] for candidate in candidates)),
            'links': [{key: candidate[key] for key in ('ivs', 'instance_id', 'goal')}
                      for candidate in candidates if candidate['instance_id'] is not None],
        }
    return {'snapshots': snapshots}


def app_operation(store, payload, species_ids=()):
    action = payload['action']
    if action == 'selection_save':
        return _save(store, payload, species_ids)
    if action == 'selection_latest':
        _object(payload, 'latest selection', ('action', 'species_id'))
        key = _species(payload['species_id'])
    elif action == 'selection_pool':
        _object(payload, 'selection pool', ('action', 'species_ids'))
        keys = dict.fromkeys(_species(value) for value in _items(payload['species_ids'], 'forms', 1, 128))
    elif action == 'selection_history':
        _object(payload, 'individual evaluation history', ('action', 'instance_id'), ('before',))
        key = _id(payload['instance_id'])
        before = _integer(payload.get('before', (1 << 63) - 1), 'before', 1, (1 << 63) - 1)
    else:
        raise ValueError('Unknown selection operation')
    empty = {'selection_latest': {'snapshot': None}, 'selection_pool': {'snapshots': {}},
             'selection_history': {'items': [], 'next_before': None}}[action]
    if not store.path.exists():
        return empty
    with store._reader() as db:
        if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='selection_snapshots_v1'").fetchone():
            return empty
        if action == 'selection_pool':
            return _pool(db, store.owner_scope, keys)
        if action == 'selection_latest':
            row = _latest_row(db, store.owner_scope, key)
            return {'snapshot': dict(revision=row[0], saved_at=row[1], **json.loads(row[2])) if row else None}
        rows = db.execute(
            """SELECT s.revision,s.saved_at,s.body FROM selection_instances_v1 AS i
               JOIN selection_snapshots_v1 AS s USING(revision)
               WHERE i.instance_id=? AND s.owner_scope=? AND s.revision<?
               ORDER BY s.revision DESC LIMIT 21""", (key, store.owner_scope, before)).fetchall()
        items = []
        for revision, saved_at, body in rows[:20]:
            snapshot = json.loads(body)
            evaluation = next(c for c in snapshot.pop('candidates') if c['instance_id'] == key)
            items.append(dict(revision=revision, saved_at=saved_at, **snapshot, evaluation=evaluation))
        return {'items': items, 'next_before': items[-1]['revision'] if len(rows) > 20 else None}
