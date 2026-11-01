import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools import cloud_migration_backup as backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        self.bundle = self.base / 'backup'
        self.db = sqlite3.connect(self.source / 'team_builder.sqlite3')
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE parties(id TEXT PRIMARY KEY, content BLOB, revision INTEGER)')
        self.db.execute('INSERT INTO parties VALUES(?,?,?)', ('secret-id', b'\x00\xffdata', 2**60))
        self.db.commit()
        (self.source / 'unknown-important-data').write_bytes(b'preserve me')
        (self.source / 'empty').mkdir()
        with zipfile.ZipFile(self.source / 'latest.zip', 'w') as z:
            z.writestr('manifest.json', '{}')

    def make(self):
        return backup.backup({'volume': self.source}, self.bundle)

    def test_wal_snapshot_restore_counts_content_permissions_and_unknown_files(self):
        result = self.make()
        self.assertTrue(result['verified'])
        self.assertEqual(result['sqlite_databases'], 1)
        obj = backup.verify(self.bundle)
        self.assertFalse(any(x['path'].endswith('-wal') for x in obj['files']))
        row = next(x for x in obj['files'] if x['path'].endswith('sqlite3'))
        self.assertEqual(row['sqlite']['tables']['parties']['rows'], 1)
        self.assertNotIn('secret-id', json.dumps(obj))
        target = self.base / 'restored'
        backup.restore(self.bundle, target)
        with sqlite3.connect(target / 'volume/team_builder.sqlite3') as db:
            self.assertEqual(db.execute('SELECT * FROM parties').fetchone(), ('secret-id', b'\x00\xffdata', 2**60))
        self.assertTrue((target / 'volume/empty').is_dir())
        self.assertEqual((target / 'volume/unknown-important-data').read_bytes(), b'preserve me')
        self.assertEqual((target / 'volume/team_builder.sqlite3').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.db.execute('SELECT count(*) FROM parties').fetchone()[0], 1)

    def test_no_overwrite_or_recursive_backup(self):
        self.make()
        for action in (lambda: self.make(), lambda: backup.restore(self.bundle, self.source),
                       lambda: backup.backup({'v': self.source}, self.source / 'bad')):
            with self.assertRaises((FileExistsError, ValueError)):
                action()

    def test_publish_cannot_replace_a_concurrently_created_empty_directory(self):
        staging, destination = self.base / 'ready', self.base / 'already-created'
        staging.mkdir()
        (staging / 'content').write_bytes(b'keep')
        destination.mkdir()
        with self.assertRaises(FileExistsError):
            backup._publish_new_directory(staging, destination)
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual((staging / 'content').read_bytes(), b'keep')

    def test_corruption_and_extra_file_refused_before_restore(self):
        self.make()
        path = self.bundle / 'files/volume/unknown-important-data'
        path.write_bytes(b'wrong')
        with self.assertRaises(ValueError):
            backup.restore(self.bundle, self.base / 'restore')
        self.assertFalse((self.base / 'restore').exists())

    def test_zip_corruption_preserves_source_and_removes_failed_bundle(self):
        (self.source / 'latest.zip').write_bytes(b'not a zip')
        with self.assertRaises(zipfile.BadZipFile):
            self.make()
        self.assertTrue((self.source / 'latest.zip').exists())
        self.assertFalse(self.bundle.exists())

    def test_symlinks_and_overlapping_roots_refused(self):
        (self.source / 'link').symlink_to(self.base / 'outside')
        with self.assertRaises(ValueError):
            self.make()
        with self.assertRaises(ValueError):
            backup.backup({'v': self.source, 'w': self.source / 'empty'}, self.bundle)

    def test_manifest_traversal_and_duplicate_refused(self):
        self.make()
        path = self.bundle / 'manifest.json'
        obj = json.loads(path.read_text())
        obj['files'][0]['path'] = '../../outside'
        path.write_text(json.dumps(obj))
        (self.bundle / 'manifest.sha256').write_text(backup.digest(path))
        with self.assertRaises(ValueError):
            backup.verify(self.bundle)

    def test_manifest_checksum_refused(self):
        self.make()
        (self.bundle / 'manifest.json').write_text('{}')
        with self.assertRaises(ValueError):
            backup.verify(self.bundle)

    def test_sqlite_backup_timeout_leaves_original_usable(self):
        with self.assertRaises(TimeoutError):
            backup.sqlite_snapshot(self.source / 'team_builder.sqlite3', self.base / 'copy', timeout=-1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM parties').fetchone()[0], 1)

    def test_file_change_aborts_and_low_space_is_safe(self):
        with patch.object(backup.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaises(OSError):
                self.make()
        self.assertFalse(self.bundle.exists())


if __name__ == '__main__':
    unittest.main()
