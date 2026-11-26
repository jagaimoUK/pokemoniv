"""Synchronize user-entered fields for explicitly confirmed inventory instances."""
import hashlib
import hmac
import json
import re
import secrets
import time

from pvpoke_auth_store import CredentialStore
from pvpoke_battle_service import _canonical_json, _object
from pvpoke_ownership import Ownership, OwnershipConflict, _id

WEB_PATH = '/app-api/individual-sync'
READER_PATH = '/app-api/reader-sync'
ACTIONS = ('individual_get', 'individual_patch')
KIND = 'individual-sync'
LIMITS = {'nickname': 12, 'memo': 400}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS individual_sync_fields_v1 (
        owner_scope TEXT NOT NULL, instance_id TEXT NOT NULL, field TEXT NOT NULL,
        revision INTEGER NOT NULL, value TEXT NOT NULL,
        PRIMARY KEY(owner_scope, instance_id, field)
    ) WITHOUT ROWID''',
    '''CREATE TABLE IF NOT EXISTS individual_sync_receipts_v1 (
        owner_scope TEXT NOT NULL, instance_id TEXT NOT NULL, request_id TEXT NOT NULL,
        digest TEXT NOT NULL, outcomes BLOB NOT NULL,
        PRIMARY KEY(owner_scope, instance_id, request_id)
    ) WITHOUT ROWID''',
)


class IndividualUnavailable(ValueError):
    """The current ownership ledger does not confirm the individual."""


class IndividualConnections:
    """Credentials authorize the reader endpoint for exactly one confirmed ID."""

    def __init__(self, api_key, store=None, ttl=30 * 86400):
        self.store = store or CredentialStore()
        self.ttl = ttl
        self.key = hashlib.sha256(('individual-sync-v1:' + api_key).encode()).digest()

    def _sign(self, payload):
        return hmac.new(self.key, payload.encode('ascii'), hashlib.sha256).hexdigest()

    def issue(self, instance_id):
        expires = int(time.time()) + self.ttl
        payload = f'is1.{expires}.{_id(instance_id)}.{secrets.token_urlsafe(18)}'
        token = payload + '.' + self._sign(payload)
        self.store.active(token, KIND, expires)
        return token

    def instance(self, header):
        if not header.startswith('Bearer '):
            return None
        token = header[7:]
        match = re.fullmatch(r'is1\.([0-9]{10,12})\.([A-Za-z0-9_-]{1,100})\.[A-Za-z0-9_-]{24}\.([0-9a-f]{64})', token)
        if match is None:
            return None
        expires, instance_id, signature = match.groups()
        now = int(time.time())
        if not now < int(expires) <= now + self.ttl:
            return None
        if not hmac.compare_digest(self._sign(token.rsplit('.', 1)[0]), signature):
            return None
        return instance_id if self.store.active(token, KIND, int(expires)) else None


def _confirmed(db, inventory, instance_id):
    record = inventory._instance(db, instance_id) if inventory._exists(db) else None
    if record is None or record['state'] != 'confirmed_owned':
        raise IndividualUnavailable('Confirmed individual required')
    return {key: record[key] for key in ('instance_id', 'species_id', 'ivs', 'current_cp')}


def _fields(db, owner, instance_id):
    fields = {field: {'revision': 0, 'value': ''} for field in LIMITS}
    if db.execute("SELECT 1 FROM sqlite_schema WHERE name='individual_sync_fields_v1'").fetchone():
        for field, revision, value in db.execute(
            'SELECT field,revision,value FROM individual_sync_fields_v1 WHERE owner_scope=? AND instance_id=?',
            (owner, instance_id),
        ):
            fields[field] = {'revision': revision, 'value': value}
    return fields


def _changes(value):
    if type(value) is not dict or not value or value.keys() - LIMITS.keys():
        raise ValueError('Invalid sync fields')
    for field, change in value.items():
        _object(change, 'sync field', ('revision', 'value'))
        revision, text = change['revision'], change['value']
        if type(revision) is not int or not 0 <= revision < (1 << 53) - 1:
            raise ValueError('Invalid field revision')
        if type(text) is not str or len(text) + sum(ord(char) > 0xFFFF for char in text) > LIMITS[field] or any(
                (ord(char) < 32 and (field == 'nickname' or char != '\n'))
                or 0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise ValueError('Invalid field value')
    return value


def app_operation(store, payload):
    action = payload.get('action')
    if action == 'individual_get':
        _object(payload, 'read individual', ('action', 'instance_id'))
    elif action == 'individual_patch':
        _object(payload, 'edit individual', ('action', 'instance_id', 'request_id', 'changes'))
    else:
        raise ValueError('Unknown sync operation')
    instance_id = _id(payload['instance_id'])
    owner = store.owner_scope
    inventory = Ownership(store)
    if action == 'individual_get':
        if not store.path.exists():
            raise IndividualUnavailable('Confirmed individual required')
        with store._reader() as db:
            return {'individual': _confirmed(db, inventory, instance_id),
                    'fields': _fields(db, owner, instance_id)}

    request_id = _id(payload['request_id'])
    changes = _changes(payload['changes'])
    digest = hashlib.sha256(_canonical_json(changes)).hexdigest()
    with store._writer(critical=True) as db:
        individual = _confirmed(db, inventory, instance_id)
        for statement in SCHEMA:
            db.execute(statement)
        opts = (owner, instance_id, request_id)
        receipt = db.execute(
            'SELECT digest,outcomes FROM individual_sync_receipts_v1 WHERE owner_scope=? AND instance_id=? AND request_id=?',
            opts).fetchone()
        fields = _fields(db, owner, instance_id)
        if receipt is not None:
            if receipt[0] != digest:
                raise OwnershipConflict('Request ID already used for different changes')
            outcomes = json.loads(receipt[1])
        else:
            outcomes = {}
            for field, change in changes.items():
                current = fields[field]
                if change['value'] == current['value']:
                    outcomes[field] = 'unchanged'
                elif change['revision'] != current['revision']:
                    outcomes[field] = 'conflict'
                else:
                    revision = current['revision'] + 1
                    db.execute('''INSERT INTO individual_sync_fields_v1 VALUES (?,?,?,?,?)
                                  ON CONFLICT(owner_scope,instance_id,field) DO UPDATE
                                  SET revision=excluded.revision,value=excluded.value''',
                               (owner, instance_id, field, revision, change['value']))
                    fields[field] = {'revision': revision, 'value': change['value']}
                    outcomes[field] = 'applied'
            db.execute('INSERT INTO individual_sync_receipts_v1 VALUES (?,?,?,?,?)',
                       (*opts, digest, _canonical_json(outcomes)))
        return {'individual': individual, 'fields': fields, 'request_id': request_id,
                'outcomes': outcomes}
