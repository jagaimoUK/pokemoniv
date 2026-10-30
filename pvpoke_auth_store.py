"""Durable per-credential revocation. Store fingerprints, never bearer values."""
import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class CredentialStore:
    def __init__(self, path=None):
        base = os.environ.get('PVP_ARCHIVE_DIR') or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
        self.path = Path(path or os.environ.get('PVP_AUTH_DB') or
                         (Path(base) / 'pvpoke_archives/auth.sqlite3' if base else
                          Path.home() / 'pvpoke_automation/auth.sqlite3'))

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS credentials ('
                   'id TEXT PRIMARY KEY, kind TEXT NOT NULL, expires INTEGER NOT NULL, '
                   'revoked INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL)')
        self.path.chmod(0o600)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def fingerprint(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def active(self, value, kind, expires):
        """Accept signed legacy credentials too; never resurrect a revoked row."""
        ident = self.fingerprint(value)
        with self._connect() as db:
            row = db.execute('SELECT revoked FROM credentials WHERE id=? AND kind=?',
                             (ident, kind)).fetchone()
            if row is not None:
                return row[0] == 0
            db.execute('DELETE FROM credentials WHERE expires <= ?', (int(time.time()),))
            db.execute('INSERT OR IGNORE INTO credentials (id,kind,expires,created) VALUES (?,?,?,?)',
                       (ident, kind, expires, int(time.time())))
            row = db.execute('SELECT revoked FROM credentials WHERE id=? AND kind=?',
                             (ident, kind)).fetchone()
        return row is not None and row[0] == 0

    def revoke(self, ident, kind):
        with self._connect() as db:
            db.execute('UPDATE credentials SET revoked=1 WHERE id=? AND kind=?', (ident, kind))

    def list_active(self, kind):
        with self._connect() as db:
            rows = db.execute('SELECT id,created,expires FROM credentials '
                              'WHERE kind=? AND revoked=0 AND expires>? ORDER BY created DESC',
                              (kind, int(time.time()))).fetchall()
        return [dict(zip(('id', 'created', 'expires'), row)) for row in rows]
