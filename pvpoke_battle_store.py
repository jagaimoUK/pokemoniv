"""Opt-in persistent storage for complete standard battle results."""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from pvpoke_archive import archive_dir
from pvpoke_battle_service import _canonical_json, validate_complete_result

SCHEMA_VERSION = 1
APPLICATION_ID = 0x50564252  # PVBR
MAX_DB_BYTES = 32 * 1024 * 1024
# Keep headroom for explicit ownership and other user-authored records.
RESERVED_DB_PAGE_FRACTION = 8
NONCRITICAL_DISK_RESERVE_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 512 * 1024
COMPLETENESS = 'standard-summary-v1'
SINGLE_OWNER = 'local-owner'

CREATE_RESULTS = """
    CREATE TABLE battle_results (
        owner_scope TEXT NOT NULL,
        battle_key TEXT NOT NULL,
        completeness TEXT NOT NULL,
        result_json BLOB NOT NULL,
        result_sha256 TEXT NOT NULL,
        saved_at INTEGER NOT NULL,
        PRIMARY KEY (owner_scope, battle_key, completeness)
    ) WITHOUT ROWID
"""


class BattleStoreError(ValueError):
    """A record or store cannot be safely used."""


class BattleStore:
    """Bind storage to a trusted server owner. No request fields select this scope."""

    def __init__(self, path: Path, *, owner_scope: str = SINGLE_OWNER, max_bytes: int = MAX_DB_BYTES):
        if type(owner_scope) is not str or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', owner_scope):
            raise ValueError('Invalid server owner scope')
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_DB_BYTES:
            raise ValueError('Invalid battle database size limit')
        self.path = Path(path)
        self.owner_scope = owner_scope
        self.max_bytes = max_bytes

    @classmethod
    def from_volume(cls):
        """Use the configured persistent archive root; never fall back to scratch."""
        if not (os.environ.get('PVP_ARCHIVE_DIR') or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')):
            raise BattleStoreError('A persistent archive root is required')
        return cls(archive_dir(Path('.')) / 'battle_analysis.sqlite3')

    @staticmethod
    def _version(db):
        return (db.execute('PRAGMA application_id').fetchone()[0],
                db.execute('PRAGMA user_version').fetchone()[0])

    def _migrate(self, db):
        version = self._version(db)
        if version == (APPLICATION_ID, SCHEMA_VERSION):
            return
        if version != (0, 0) or db.execute('SELECT 1 FROM sqlite_schema LIMIT 1').fetchone():
            raise BattleStoreError('Unrecognized battle database version')
        db.execute(CREATE_RESULTS)
        db.execute(f'PRAGMA application_id = {APPLICATION_ID}')
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')

    def _row(self, db, key):
        return db.execute(
            '''SELECT result_json, result_sha256 FROM battle_results
               WHERE owner_scope = ? AND battle_key = ? AND completeness = ?''',
            (self.owner_scope, key, COMPLETENESS),
        ).fetchone()

    @staticmethod
    def _decode(row, key, spec, versions):
        payload, checksum = row
        if (type(payload) is not bytes or len(payload) > MAX_RESULT_BYTES
                or hashlib.sha256(payload).hexdigest() != checksum):
            raise BattleStoreError('Battle result checksum or size mismatch')
        try:
            result = json.loads(payload)
            if _canonical_json(result) != payload:
                raise ValueError('Noncanonical battle result JSON')
            validate_complete_result(result, key, spec, versions)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise BattleStoreError('Invalid stored battle result') from exc
        return result

    @contextmanager
    def _reader(self):
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.25)) as db, db:
            db.execute('BEGIN')
            if self._version(db) != (APPLICATION_ID, SCHEMA_VERSION):
                raise BattleStoreError('Unrecognized battle database version')
            yield db

    @contextmanager
    def _writer(self, *, critical=False):
        """Keep a SQLite quota and disk reserve for important user records.

        Recalculable writes cannot consume the last 1/8 of SQLite pages
        or the last 8 MiB of disk free space. Critical writes may use this
        reserve. Other processes can still exhaust the filesystem; nothing
        here deletes existing data.
        """
        if type(critical) is not bool:
            raise ValueError('Invalid battle writer priority')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not critical:
            if shutil.disk_usage(self.path.parent).free <= NONCRITICAL_DISK_RESERVE_BYTES:
                raise BattleStoreError('Noncritical battle writes paused to protect disk space')
            # An externally enabled WAL can exceed the main DB page quota even
            # while its page_count is tiny. Stop expendable cache writes, never
            # delete or truncate another process's WAL or user records.
            try:
                wal_bytes = self.path.with_name(self.path.name + '-wal').stat().st_size
            except FileNotFoundError:
                wal_bytes = 0
            if wal_bytes > self.max_bytes:
                raise BattleStoreError('Noncritical battle writes paused: oversized SQLite WAL')
        with closing(sqlite3.connect(self.path, timeout=0.25)) as db, db:
            total_pages = self.max_bytes // db.execute('PRAGMA page_size').fetchone()[0]
            if total_pages < 2:
                raise BattleStoreError('Battle database size limit is too small')
            reserve = total_pages // RESERVED_DB_PAGE_FRACTION if total_pages >= 16 else 0
            pages = total_pages if critical else total_pages - reserve
            db.execute(f'PRAGMA max_page_count = {pages}')
            # SQLite cannot reduce max_page_count below an already allocated DB.
            if db.execute('PRAGMA page_count').fetchone()[0] > pages:
                raise BattleStoreError('Battle database reserved capacity is exhausted')
            db.execute('BEGIN IMMEDIATE')
            self._migrate(db)
            yield db
            if db.execute('PRAGMA page_count').fetchone()[0] > pages:
                raise BattleStoreError('Battle database exceeds its write quota')

    def get(self, key, spec, versions, *, completeness=COMPLETENESS):
        """Return a validated summary, or None when this owner has no matching row."""
        if completeness != COMPLETENESS:
            return None
        try:
            self.path.stat()
        except FileNotFoundError:
            return None
        with self._reader() as db:
            row = self._row(db, key)
            return None if row is None else self._decode(row, key, spec, versions)

    def put(self, key, spec, versions, result):
        """Commit a complete result. Identical concurrent inserts are idempotent."""
        validate_complete_result(result, key, spec, versions)
        payload = _canonical_json(result)
        if len(payload) > MAX_RESULT_BYTES:
            raise BattleStoreError('Battle result exceeds the row size limit')
        with self._writer() as db:
            row = self._row(db, key)
            if row is not None:
                previous = self._decode(row, key, spec, versions)
                # Execution timing varies even when the battle result is identical.
                if {**previous, 'compute_wall_ms': 0} != {**result, 'compute_wall_ms': 0}:
                    raise BattleStoreError('Conflicting result for the same battle key')
                return
            db.execute(
                '''INSERT INTO battle_results
                   (owner_scope, battle_key, completeness, result_json, result_sha256, saved_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (self.owner_scope, key, COMPLETENESS, payload, hashlib.sha256(payload).hexdigest(), int(time.time())),
            )
