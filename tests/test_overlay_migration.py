"""Exercise the real v1 schema and v2 migration with existing checked history."""
import io
from pathlib import Path
import re
import sqlite3
import tarfile
import unittest


class OverlayMigrationTests(unittest.TestCase):
    def test_v1_checks_counts_and_old_session_survive_upgrade(self):
        root = Path(__file__).resolve().parents[1]
        with tarfile.open(root / 'android-overlay-copy-demo.tar.xz', 'r:xz') as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith('/OverlayQueueStore.kt'))
            old = archive.extractfile(member).read().decode()
        current = (root / 'android-integration/overlayqueue/OverlayQueueStore.kt').read_text()
        db = sqlite3.connect(':memory:')
        for sql in re.findall(r'db.execSQL\((?:"""(.*?)"""|"([^"\n]*)")\)', old, re.S):
            value = sql[0] or sql[1]
            if value.startswith('CREATE '):
                db.execute(value)
        db.execute('INSERT INTO sessions (_id,created_at) VALUES (1,123)')
        db.execute('''INSERT INTO items(session_id,sequence,search_text,nickname,
                      search_copied,nickname_copied,search_copy_count,nickname_copy_count,search_copied_at)
                      VALUES (1,1,'Quagsire&0attack&3defense&3hp','AQuag>Cor01',1,0,3,0,456)''')
        migration = re.search(r'db.execSQL\("(ALTER TABLE [^"]+)"\)', current)[1]
        db.execute(migration)
        row = db.execute('SELECT search_copied,nickname_copied,search_copy_count,search_copied_at,ivs FROM items').fetchone()
        self.assertEqual(row, (1, 0, 3, 456, None))
        db.execute("INSERT INTO items(session_id,sequence,search_text,nickname,ivs) VALUES (1,2,'Wooper&cp717','A','0/11/12')")
        self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 2)
        self.assertEqual(db.execute('SELECT created_at FROM sessions').fetchone()[0], 123)


if __name__ == '__main__':
    unittest.main()
