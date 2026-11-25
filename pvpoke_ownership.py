"""Owner-bound inventory and explicit confirmation events in the BattleStore DB."""
import hashlib
import json
import re
from datetime import datetime, timezone

from pvpoke_battle_service import _canonical_json, _json_hash

STATES = ('unknown', 'confirmed_owned', 'confirmed_absent')
MAX_REVISION = (1 << 63) - 2
ID_PATTERN = r'[a-zA-Z0-9_-]{1,100}'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS owned_instances_v1 (
        owner_scope TEXT NOT NULL, instance_id TEXT NOT NULL,
        species_id TEXT NOT NULL, iv_index INTEGER NOT NULL,
        body BLOB NOT NULL, digest TEXT NOT NULL,
        PRIMARY KEY (owner_scope, instance_id)
    ) WITHOUT ROWID''',
    '''CREATE INDEX IF NOT EXISTS owned_identity_v1
       ON owned_instances_v1 (owner_scope, species_id, iv_index)''',
    '''CREATE TABLE IF NOT EXISTS ownership_revisions_v1 (
        owner_scope TEXT PRIMARY KEY, revision INTEGER NOT NULL
    ) WITHOUT ROWID''',
    '''CREATE TABLE IF NOT EXISTS ownership_events_v1 (
        sequence INTEGER PRIMARY KEY, owner_scope TEXT NOT NULL, event_id TEXT NOT NULL,
        kind TEXT NOT NULL, target TEXT NOT NULL, request_hash TEXT NOT NULL,
        body BLOB NOT NULL, digest TEXT NOT NULL, UNIQUE (owner_scope, event_id)
    )''',
    '''CREATE INDEX IF NOT EXISTS ownership_event_history_v1
       ON ownership_events_v1 (owner_scope, kind, target, sequence)''',
)


class OwnershipConflict(ValueError):
    """An event or revision conflicts with an existing record."""


class OwnershipUnavailable(ValueError):
    """A stored inventory record cannot be trusted."""


def _id(value, pattern=ID_PATTERN):
    if type(value) is not str or not re.fullmatch(pattern, value):
        raise ValueError('Invalid inventory identifier')
    return value


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid inventory integer')
    return value


def _pack(record):
    body = _canonical_json(record)
    return body, hashlib.sha256(body).hexdigest()


def _unpack(row):
    body, digest = row
    if type(body) is not bytes or len(body) > 8192 or hashlib.sha256(body).hexdigest() != digest:
        raise OwnershipUnavailable('Invalid inventory record checksum')
    try:
        value = json.loads(body)
        if type(value) is not dict:
            raise ValueError('Expected an inventory object')
        return value
    except (ValueError, RecursionError) as exc:
        raise OwnershipUnavailable('Invalid inventory record') from exc


def _iv_index(ivs):
    return ivs['attack'] * 256 + ivs['defense'] * 16 + ivs['hp']


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def build_id(combatant):
    """Identify a simulation build independently of its opponent or initial conditions."""
    payload = {key: combatant[key] for key in ('species_id', 'ivs', 'level', 'moves')}
    if 'mega_level' in combatant and combatant['mega_level'] is not None:
        payload['mega_level'] = combatant['mega_level']
    return _json_hash(payload)


class Ownership:
    """Trust the server-bound store, catalogue and actor, never a request owner field."""

    def __init__(self, store, *, species_ids=(), actor=None):
        self.store = store
        self.species_ids = species_ids
        self.actor = _id(store.owner_scope if actor is None else actor)

    @property
    def owner(self):
        return self.store.owner_scope

    def _species(self, value):
        # The canonical catalogue ID includes regional form, shadow, etc.
        species = _id(value, r'[a-z0-9_]{1,100}')
        if species not in self.species_ids:
            raise ValueError('Unknown species or form')
        return species

    def _observation(self, value, *, partial=False):
        if type(value) is not dict or not {'species_id', 'ivs'} <= value.keys() or (
            value.keys() - {'species_id', 'ivs', 'current_cp', 'current_level', 'current_moves'}
        ):
            raise ValueError('Invalid inventory observation')
        ivs = value['ivs']
        if type(ivs) is not dict or set(ivs) != {'attack', 'defense', 'hp'}:
            raise ValueError('Invalid inventory IVs')
        result = {
            'species_id': self._species(value['species_id']),
            'ivs': {key: _int(number, 0, 15) for key, number in ivs.items()},
        }
        if not partial or 'current_cp' in value:
            cp = value.get('current_cp')
            result['current_cp'] = None if cp is None else _int(cp, 10, 10000)
        if not partial or 'current_level' in value:
            level = value.get('current_level')
            if level is not None and (type(level) not in (int, float)
                                      or not 1 <= level <= 51 or level * 2 % 1):
                raise ValueError('Invalid current level')
            result['current_level'] = None if level is None else float(level)
        if not partial or 'current_moves' in value:
            moves = value.get('current_moves')
            if moves is not None:
                if type(moves) is not dict or moves.keys() - {'fast', 'charged'}:
                    raise ValueError('Invalid current moves')
                fast, charged = moves.get('fast'), moves.get('charged')
                if charged is not None:
                    if type(charged) is not list or not 1 <= len(charged) <= 2:
                        raise ValueError('Invalid current charged moves')
                    charged = [_id(move, r'[A-Z0-9_]{1,100}') for move in charged]
                    if len(set(charged)) != len(charged):
                        raise ValueError('Duplicate current charged move')
                moves = {'fast': None if fast is None else _id(fast, r'[A-Z0-9_]{1,100}'),
                         'charged': charged}
            result['current_moves'] = moves
        return result

    @staticmethod
    def _ensure_tables(db):
        for statement in SCHEMA:
            db.execute(statement)

    @staticmethod
    def _exists(db):
        return db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='owned_instances_v1'").fetchone()

    def _revision(self, db):
        row = db.execute('SELECT revision FROM ownership_revisions_v1 WHERE owner_scope=?',
                         (self.owner,)).fetchone()
        return row[0] if row else 0

    def _advance(self, db):
        revision = _int(self._revision(db), 0, MAX_REVISION - 1) + 1
        db.execute('''INSERT INTO ownership_revisions_v1 VALUES (?, ?)
            ON CONFLICT(owner_scope) DO UPDATE SET revision=excluded.revision''', (self.owner, revision))
        return revision

    def _instance(self, db, instance_id):
        row = db.execute('SELECT body, digest FROM owned_instances_v1 WHERE owner_scope=? AND instance_id=?',
                         (self.owner, instance_id)).fetchone()
        if row is None:
            return None
        record = _unpack(row)
        if record.get('instance_id') != instance_id:
            raise OwnershipUnavailable('Inventory record identity mismatch')
        return record

    def revision(self):
        if not self.store.path.exists():
            return 0
        with self.store._reader() as db:
            return self._revision(db) if self._exists(db) else 0

    def get(self, instance_id):
        _id(instance_id)
        if not self.store.path.exists():
            return None
        with self.store._reader() as db:
            return self._instance(db, instance_id) if self._exists(db) else None

    def instances(self, *, after='', limit=128):
        if after != '':
            _id(after)
        _int(limit, 1, 512)
        if not self.store.path.exists():
            return []
        with self.store._reader() as db:
            if not self._exists(db):
                return []
            return [_unpack(row) for row in db.execute('''SELECT body, digest FROM owned_instances_v1
                WHERE owner_scope=? AND instance_id>? ORDER BY instance_id LIMIT ?''', (self.owner, after, limit))]

    def list_snapshot(self, *, after='', limit=64, species_id=None, state=None,
                      include_scopes=True, scope_limit=32):
        """Read owner-scoped ledger revision, instances and recent scopes in one SQLite snapshot."""
        if after != '':
            _id(after)
        _int(limit, 1, 128)
        if species_id is not None:
            species_id = self._species(species_id)
        if state is not None and state not in STATES:
            raise ValueError('Invalid ownership state filter')
        if type(include_scopes) is not bool:
            raise ValueError('Invalid include_scopes flag')
        _int(scope_limit, 1, 64)
        empty = {'ledger_revision': 0, 'items': [], 'has_more': False, 'next_after': None}
        if include_scopes:
            empty.update({'scopes': [], 'scopes_truncated': False})
        if not self.store.path.exists():
            return empty
        with self.store._reader() as db:
            if not self._exists(db):
                return empty
            ledger_revision = self._revision(db)
            scan_limit = 512 if state is not None else limit + 1
            if species_id is None:
                rows = db.execute('''SELECT instance_id, body, digest FROM owned_instances_v1
                    WHERE owner_scope=? AND instance_id>? ORDER BY instance_id LIMIT ?''',
                    (self.owner, after, scan_limit)).fetchall()
            else:
                rows = db.execute('''SELECT instance_id, body, digest FROM owned_instances_v1
                    WHERE owner_scope=? AND species_id=? AND instance_id>? ORDER BY instance_id LIMIT ?''',
                    (self.owner, species_id, after, scan_limit)).fetchall()
            items = []
            has_more = False
            next_after = None
            for row_id, body, digest in rows:
                record = _unpack((body, digest))
                if record.get('instance_id') != row_id:
                    raise OwnershipUnavailable('Inventory record identity mismatch')
                if state is not None and record.get('state') != state:
                    continue
                if len(items) < limit:
                    items.append(record)
                else:
                    has_more = True
                    next_after = items[-1]['instance_id'] if items else None
                    break
            if not has_more and state is not None and len(rows) == scan_limit:
                has_more = True
                next_after = rows[-1][0]
            result = {'ledger_revision': ledger_revision, 'items': items,
                      'has_more': has_more, 'next_after': next_after}
            if include_scopes:
                scope_rows = db.execute('''SELECT target, event_id, body, digest FROM ownership_events_v1
                    WHERE owner_scope=? AND kind='scope' ORDER BY sequence DESC LIMIT 257''',
                    (self.owner,)).fetchall()
                truncated = len(scope_rows) > 256
                latest_by_target = {}
                scopes = []
                for target, event_id, body, digest in scope_rows[:256]:
                    latest_by_target.setdefault(target, event_id)
                    event = _unpack((body, digest))
                    scope = event.get('scope')
                    if (event.get('event_id') != event_id or event.get('kind') != 'scope'
                            or not isinstance(scope, dict) or 'species_id' not in scope
                            or type(event.get('ledger_revision')) is not int):
                        raise OwnershipUnavailable('Invalid inventory scope event')
                    if species_id is not None and scope['species_id'] != species_id:
                        continue
                    current = (latest_by_target[target] == event_id
                               and event['ledger_revision'] == ledger_revision)
                    if len(scopes) < scope_limit:
                        scopes.append({**event, 'current': current})
                    else:
                        truncated = True
                result['scopes'] = scopes
                result['scopes_truncated'] = truncated
            return result

    def instance_history(self, instance_id, *, after_revision=0, limit=64):
        """Read one instance and its append-only event log in a single SQLite snapshot."""
        _id(instance_id)
        _int(after_revision, 0, MAX_REVISION)
        _int(limit, 1, 128)
        if not self.store.path.exists():
            return None
        with self.store._reader() as db:
            if not self._exists(db):
                return None
            record = self._instance(db, instance_id)
            if record is None:
                return None
            rows = db.execute('''SELECT body, digest FROM ownership_events_v1
                WHERE owner_scope=? AND kind='instance' AND target=? ORDER BY sequence LIMIT ? OFFSET ?''',
                (self.owner, instance_id, limit + 1, after_revision)).fetchall()
            events = [_unpack(row) for row in rows[:limit]]
            return {'instance': record, 'events': events, 'has_more': len(rows) > limit}

    def register(self, instance_id, observation):
        """Register an observed individual with no ownership confirmation."""
        _id(instance_id)
        fields = self._observation(observation)
        with self.store._writer(critical=True) as db:
            self._ensure_tables(db)
            old = self._instance(db, instance_id)
            if old is not None:
                if any(old[key] != value for key, value in fields.items()):
                    raise OwnershipConflict('Instance already has a different observation')
                return old
            record = {'instance_id': instance_id, **fields, 'state': 'unknown', 'revision': 0,
                      'confirmed_at': None, 'confirmed_by': None, 'source': 'manual'}
            db.execute('INSERT INTO owned_instances_v1 VALUES (?, ?, ?, ?, ?, ?)',
                       (self.owner, instance_id, fields['species_id'], _iv_index(fields['ivs']), *_pack(record)))
            self._advance(db)
            return record

    def _replay(self, db, event_id, request_hash, *, legacy_hashes=()):
        row = db.execute('''SELECT request_hash, body, digest FROM ownership_events_v1
            WHERE owner_scope=? AND event_id=?''', (self.owner, event_id)).fetchone()
        if row:
            if row[0] != request_hash and row[0] not in legacy_hashes:
                raise OwnershipConflict('Event ID already used for a different request')
            return _unpack(row[1:])
        return None

    def _append(self, db, event, target, request_hash):
        db.execute('''INSERT INTO ownership_events_v1 (owner_scope,event_id,kind,target,request_hash,body,digest)
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (self.owner, event['event_id'], event['kind'], target, request_hash, *_pack(event)))

    def confirm(self, event_id, instance_id, *, expected_revision, state, observation=None,
                register_if_missing=False, preserve_identity=False):
        """Apply one explicit manual confirmation, optionally updating current observed details."""
        _id(event_id)
        _id(instance_id)
        _int(expected_revision, 0, MAX_REVISION - 1)
        if state not in STATES:
            raise ValueError('Invalid ownership state')
        if type(preserve_identity) is not bool:
            raise ValueError('Invalid preserve_identity flag')
        fields = None if observation is None else self._observation(
            observation, partial=not register_if_missing)
        identity = ['instance', self.actor, instance_id, expected_revision, state, fields]
        legacy_hashes = ()
        if register_if_missing:
            if expected_revision != 0 or fields is None or state != 'confirmed_owned':
                raise ValueError('A new instance requires an explicit owned observation')
            identity.append('register')
        elif fields is not None:
            legacy_fields = self._observation(observation, partial=False)
            legacy_hashes = (
                _json_hash(['instance', self.actor, instance_id, expected_revision, state, fields]),
                _json_hash(['instance', self.actor, instance_id, expected_revision, state, legacy_fields]),
            )
            identity.append('partial-v1')
        request_hash = _json_hash(identity)
        with self.store._writer(critical=True) as db:
            self._ensure_tables(db)
            replay = self._replay(db, event_id, request_hash, legacy_hashes=legacy_hashes)
            if replay is not None:
                return replay
            previous = self._instance(db, instance_id)
            if register_if_missing and previous is None:
                previous = {'instance_id': instance_id, **fields, 'state': 'unknown', 'revision': 0}
                db.execute('INSERT INTO owned_instances_v1 VALUES (?, ?, ?, ?, ?, ?)',
                           (self.owner, instance_id, fields['species_id'], _iv_index(fields['ivs']), *_pack(previous)))
            elif register_if_missing:
                raise OwnershipConflict('Instance ID already exists')
            if previous is None or previous['revision'] != expected_revision:
                raise OwnershipConflict('Instance missing or revision changed')
            if preserve_identity and fields is not None and not register_if_missing:
                if any(previous[key] != fields[key] for key in ('species_id', 'ivs')):
                    raise OwnershipConflict('Observation conflicts with the individual identity')
            now = _now()
            record = {**previous, **(fields or {}), 'state': state, 'revision': expected_revision + 1,
                      'confirmed_at': now, 'confirmed_by': self.actor, 'source': 'manual'}
            event = {'event_id': event_id, 'kind': 'instance', 'instance_id': instance_id,
                     'previous_state': previous['state'], 'new_state': state,
                     'input_revision': expected_revision, 'output_revision': record['revision'],
                     'confirmed_at': now, 'confirmed_by': self.actor, 'source': 'manual', 'instance': record}
            db.execute('''UPDATE owned_instances_v1 SET species_id=?, iv_index=?, body=?, digest=?
                          WHERE owner_scope=? AND instance_id=?''',
                       (record['species_id'], _iv_index(record['ivs']), *_pack(record), self.owner, instance_id))
            self._advance(db)
            self._append(db, event, instance_id, request_hash)
            return event

    def confirm_scope(self, event_id, *, expected_ledger_revision, species_id, search, box_range,
                      complete, absence_confirmed):
        """Record explicit scope evidence, independent of individual confirmations."""
        _id(event_id)
        _int(expected_ledger_revision, 0, MAX_REVISION)
        species_id = self._species(species_id)
        if type(search) is not str or len(search) > 256 or any(ord(char) < 32 for char in search):
            raise ValueError('Invalid inventory search')
        if type(box_range) not in (list, tuple) or len(box_range) != 2:
            raise ValueError('Invalid inventory box range')
        first, last = (_int(value, 1, 100000) for value in box_range)
        if first > last or type(complete) is not bool or type(absence_confirmed) is not bool or (
            absence_confirmed and not complete
        ):
            raise ValueError('Invalid inventory scope confirmation')
        scope = {'species_id': species_id, 'search': search, 'box_range': [first, last]}
        target = _json_hash(scope)
        request_hash = _json_hash(['scope', self.actor, scope, expected_ledger_revision, complete, absence_confirmed])
        with self.store._writer(critical=True) as db:
            self._ensure_tables(db)
            replay = self._replay(db, event_id, request_hash)
            if replay is not None:
                return replay
            if self._revision(db) != expected_ledger_revision:
                raise OwnershipConflict('Inventory revision changed')
            event = {'event_id': event_id, 'kind': 'scope', 'scope': scope, 'complete': complete,
                     'absence_confirmed': absence_confirmed, 'ledger_revision': expected_ledger_revision,
                     'confirmed_at': _now(), 'confirmed_by': self.actor, 'source': 'manual'}
            self._append(db, event, target, request_hash)
            return event

    def scope_status(self, event_id):
        """Return historical scope evidence and whether it is the latest at this inventory revision."""
        _id(event_id)
        if not self.store.path.exists():
            return None
        with self.store._reader() as db:
            if not self._exists(db):
                return None
            row = db.execute('''SELECT target, body, digest FROM ownership_events_v1
                WHERE owner_scope=? AND event_id=? AND kind='scope' ''', (self.owner, event_id)).fetchone()
            if row is None:
                return None
            target, *payload = row
            event = _unpack(payload)
            latest, = db.execute('''SELECT event_id FROM ownership_events_v1
                WHERE owner_scope=? AND kind='scope' AND target=? ORDER BY sequence DESC LIMIT 1''',
                (self.owner, target)).fetchone()
            return {**event, 'current': latest == event_id and event['ledger_revision'] == self._revision(db)}

    def history(self, instance_id, *, after_revision=0, limit=128):
        _id(instance_id)
        _int(after_revision, 0, MAX_REVISION)
        _int(limit, 1, 512)
        if not self.store.path.exists():
            return []
        with self.store._reader() as db:
            if not self._exists(db):
                return []
            return [_unpack(row) for row in db.execute('''SELECT body, digest FROM ownership_events_v1
                WHERE owner_scope=? AND kind='instance' AND target=? ORDER BY sequence LIMIT ? OFFSET ?''',
                (self.owner, instance_id, limit, after_revision))]

    @staticmethod
    def _match_rows(rows, combatant, cp, *, species_catalog=None, cpms=None, rules=None, mega_level=3):
        from pvpoke_mega import (
            base_species_id,
            can_mega_evolve,
            evaluate_owned_for_mega,
            is_mega_form,
        )

        target_species = combatant['species_id']
        mega_mode = is_mega_form(target_species)
        base_id = base_species_id(target_species) if mega_mode else target_species
        matches = []
        for row in rows:
            record = _unpack(row)
            rec_species = record['species_id']
            is_direct = rec_species == target_species
            is_mega_link = mega_mode and can_mega_evolve(rec_species, target_species, species_catalog)
            if (not is_direct and not is_mega_link) or record['ivs'] != combatant['ivs']:
                raise OwnershipUnavailable('Inventory match index is inconsistent')
            moves = record['current_moves'] or {}
            mega_eval = None
            if is_mega_link:
                if species_catalog and base_id in species_catalog and target_species in species_catalog:
                    mega_eval = evaluate_owned_for_mega(
                        record,
                        mega_species_id=target_species,
                        base_stats=species_catalog[base_id]['baseStats'],
                        mega_stats=species_catalog[target_species]['baseStats'],
                        species_catalog=species_catalog,
                        target_level=combatant['level'],
                        cpms=cpms,
                        rules=rules,
                        mega_level=combatant.get('mega_level', mega_level),
                    )
                move_pairs = (
                    (moves.get('fast'), combatant['moves']['fast']),
                    (moves.get('charged'), combatant['moves']['charged']),
                )
                moves_mismatch = any(
                    actual is not None and expected is not None and actual != expected
                    for actual, expected in move_pairs
                )
                moves_missing = any(
                    actual is None or expected is None
                    for actual, expected in move_pairs
                )
                if mega_eval is None:
                    match = 'different' if moves_mismatch else 'unverified'
                elif mega_eval['eligible'] is False or mega_eval['needs_power_up'] is True:
                    match = 'different'
                elif mega_eval['eligible'] is None:
                    match = 'different' if moves_mismatch else 'unverified'
                elif mega_eval['needs_evolution']:
                    match = 'unverified'
                elif mega_eval['downscaled']:
                    match = 'different' if moves_mismatch else 'unverified'
                elif moves_mismatch:
                    match = 'different'
                else:
                    base_cap_cp = mega_eval['mega_theoretical']['base_equivalent_cp_at_target']
                    level_ok = (record['current_level'] is not None
                                and float(record['current_level']) == float(combatant['level']))
                    cp_ok = (record['current_cp'] is not None
                             and int(record['current_cp']) == int(base_cap_cp))
                    if (record['current_level'] is not None and not level_ok) or (
                        record['current_cp'] is not None and not cp_ok
                    ):
                        match = 'different'
                    elif not level_ok or not cp_ok or moves_missing:
                        match = 'unverified'
                    else:
                        match = 'exact'
            else:
                pairs = ((record['current_level'], combatant['level']), (record['current_cp'], cp),
                         (moves.get('fast'), combatant['moves']['fast']),
                         (moves.get('charged'), combatant['moves']['charged']))
                if any(actual is not None and expected is not None and actual != expected for actual, expected in pairs):
                    match = 'different'
                elif any(actual is None or expected is None for actual, expected in pairs):
                    match = 'unverified'
                else:
                    match = 'exact'
            entry = {'instance_id': record['instance_id'], 'state': record['state'],
                     'revision': record['revision'], 'build_match': match}
            if is_mega_link:
                entry['base_species_id'] = rec_species
                if mega_eval is not None:
                    entry['eligible'] = mega_eval['eligible']
                    if mega_eval.get('downscaled'):
                        entry['mega_downscaled'] = True
                    if mega_eval.get('needs_power_up'):
                        entry['needs_power_up'] = True
                    if mega_eval.get('needs_evolution'):
                        entry['needs_evolution'] = True
                    if mega_eval.get('reason') == 'cp_cap_rule_required':
                        entry['mega_rule_unverified'] = True
                else:
                    entry['mega_rule_unverified'] = True
            matches.append(entry)
        return matches

    def _matches(self, db, combatant, cp, *, species_catalog=None, cpms=None, rules=None, mega_level=3):
        """Show exact and uncertain candidates without converting absence into a build-wide fact."""
        from pvpoke_mega import eligible_pre_evolutions, is_mega_form

        species_id = combatant['species_id']
        iv_idx = _iv_index(combatant['ivs'])
        query_species = [species_id]
        if is_mega_form(species_id):
            for ancestor in eligible_pre_evolutions(species_id, species_catalog):
                if ancestor not in query_species:
                    query_species.append(ancestor)
        placeholders = ','.join('?' for _ in query_species)
        rows = list(db.execute(
            f'''SELECT body, digest FROM owned_instances_v1
                WHERE owner_scope=? AND species_id IN ({placeholders}) AND iv_index=? ORDER BY instance_id''',
            (self.owner, *query_species, iv_idx),
        ).fetchall())
        return self._match_rows(
            rows, combatant, cp, species_catalog=species_catalog, cpms=cpms, rules=rules, mega_level=mega_level,
        )

    def species_rows_by_iv(self, species_id, *, species_catalog=None):
        """Return validated inventory row pairs keyed by iv_index and confirmed-owned count."""
        from pvpoke_mega import eligible_pre_evolutions, is_mega_form

        species = self._species(species_id)
        query_species = [species]
        if is_mega_form(species):
            for ancestor in eligible_pre_evolutions(species, species_catalog):
                if ancestor in self.species_ids and ancestor not in query_species:
                    query_species.append(ancestor)
        if not self.store.path.exists():
            return {}, 0
        by_iv = {}
        confirmed_owned = 0
        with self.store._reader() as db:
            if not self._exists(db):
                return {}, 0
            placeholders = ','.join('?' for _ in query_species)
            for queried_species, iv_index, body, digest in db.execute(
                f'''SELECT species_id, iv_index, body, digest FROM owned_instances_v1
                    WHERE owner_scope=? AND species_id IN ({placeholders}) ORDER BY iv_index, instance_id''',
                (self.owner, *query_species),
            ):
                record = _unpack((body, digest))
                if record['species_id'] != queried_species or _iv_index(record['ivs']) != iv_index:
                    raise OwnershipUnavailable('Inventory match index is inconsistent')
                if record['state'] == 'confirmed_owned':
                    confirmed_owned += 1
                by_iv.setdefault(iv_index, []).append((body, digest))
        return by_iv, confirmed_owned
