"""Real ENOSPC rollback on an isolated Docker tmpfs.

Run ONLY with PVP_REAL_ENOSPC_ROOT pointing at a disposable <=4 MiB
filesystem; skipped in normal test runs and never touches production.
"""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pvpoke_battle_store import BattleStore
from pvpoke_ownership import Ownership


class RealENOSPCTests(unittest.TestCase):
    def test_owner_confirmation_rolls_back_then_restarts_after_real_disk_full(self):
        root_name = os.environ.get('PVP_REAL_ENOSPC_ROOT')
        if not root_name:
            self.skipTest('Requires explicitly configured disposable tiny tmpfs')
        root = Path(root_name).resolve(strict=True)
        total_bytes = os.statvfs(root).f_blocks * os.statvfs(root).f_frsize
        # Guard against a mistaken environment variable pointing to a real
        # large volume. This test may intentionally fill its temporary FS.
        self.assertLessEqual(total_bytes, 4 * 1024 * 1024, 'Refusing to fill a non-test filesystem')
        self.assertGreaterEqual(total_bytes, 1024 * 1024, 'Test filesystem too small')

        observed = {'species_id': 'quagsire',
                    'ivs': {'attack': 0, 'defense': 11, 'hp': 12}}
        for journal_mode in ('delete', 'wal'):
            with self.subTest(journal_mode=journal_mode), tempfile.TemporaryDirectory(dir=root) as tmp:
                path = Path(tmp) / 'owner.sqlite3'
                store = BattleStore(path)
                owner = Ownership(store, species_ids={'quagsire'})
                other = Ownership(BattleStore(path, owner_scope='other'), species_ids={'quagsire'})
                owner.register('subject', observed)
                before = owner.get('subject')
                before_ledger = owner.revision()

                with closing(sqlite3.connect(path)) as db:
                    actual, = db.execute(f'PRAGMA journal_mode={journal_mode}').fetchone()
                    self.assertEqual(actual, journal_mode)
                    with db:
                        db.execute('CREATE TABLE failure_payload (data BLOB)')
                        db.execute('''
                            CREATE TRIGGER fill_real_disk BEFORE INSERT
                            ON ownership_events_v1 BEGIN
                                INSERT INTO failure_payload VALUES (zeroblob(4194304));
                            END
                        ''')

                # Consumes some real tmpfs blocks. Deleting this dummy file
                # afterwards restores headroom for a legitimate retry.
                filler = Path(tmp) / 'removable-filler.bin'
                # Releasing more than half the tiny filesystem leaves room
                # for SQLite's own rollback recovery after an ENOSPC failure.
                filler.write_bytes(b'x' * (1280 * 1024))
                try:
                    with self.assertRaises(sqlite3.DatabaseError) as error:
                        owner.confirm('after-full', 'subject', expected_revision=0,
                                      state='confirmed_owned')
                    self.assertIn('full', str(error.exception).lower())
                finally:
                    filler.unlink(missing_ok=True)

                # Check a fresh connection, not a snapshot held by the writer.
                reopened = Ownership(BattleStore(path), species_ids={'quagsire'})
                self.assertEqual(reopened.get('subject'), before)
                self.assertEqual(reopened.revision(), before_ledger)
                self.assertEqual(reopened.history('subject'), [])
                self.assertIsNone(other.get('subject'))
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM failure_payload').fetchone()[0], 0)
                    with db:
                        db.execute('DROP TRIGGER fill_real_disk')

                # Recovery after the filesystem has room again, including
                # event idempotency and persistence across fresh connections.
                result = reopened.confirm('after-full', 'subject',
                                          expected_revision=0, state='confirmed_owned')
                self.assertEqual(result['new_state'], 'confirmed_owned')
                self.assertEqual(reopened.revision(), before_ledger + 1)
                self.assertEqual(len(reopened.history('subject')), 1)
                self.assertEqual(reopened.confirm('after-full', 'subject',
                                                  expected_revision=0,
                                                  state='confirmed_owned'), result)
                self.assertIsNone(other.get('subject'))


if __name__ == '__main__':
    unittest.main()
