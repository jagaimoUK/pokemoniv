-- Original overlay_copy_queue.db v1 schema, preserved for migration tests.
CREATE TABLE sessions (_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL);
CREATE TABLE items (
           _id INTEGER PRIMARY KEY AUTOINCREMENT,
           session_id INTEGER NOT NULL,
           sequence INTEGER NOT NULL,
           search_text TEXT NOT NULL,
           nickname TEXT NOT NULL,
           search_copied INTEGER NOT NULL DEFAULT 0,
           nickname_copied INTEGER NOT NULL DEFAULT 0,
           search_copied_at INTEGER,
           nickname_copied_at INTEGER,
           search_copy_count INTEGER NOT NULL DEFAULT 0,
           nickname_copy_count INTEGER NOT NULL DEFAULT 0,
           UNIQUE(session_id, sequence),
           FOREIGN KEY(session_id) REFERENCES sessions(_id)
        );
CREATE INDEX ix_queue_items_session ON items(session_id, sequence);
