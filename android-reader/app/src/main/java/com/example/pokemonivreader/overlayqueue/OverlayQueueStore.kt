package com.example.pokemonivreader.overlayqueue

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/** SQLite lets us copy one item without rewriting a 1,000-item preference blob. */
class OverlayQueueStore(context: Context) :
    SQLiteOpenHelper(context.applicationContext, "overlay_copy_queue.db", null, 2) {

    data class Session(val id: Long, val createdAt: Long, val count: Int)
    data class Item(
        val id: Long, val sequence: Int, val search: String, val nickname: String,
        val searchCopied: Boolean, val nicknameCopied: Boolean,
        val searchCopyCount: Int, val nicknameCopyCount: Int, val ivs: String? = null
    ) {
        val complete: Boolean get() = searchCopied && nicknameCopied
        val speciesLabel: String get() = search.substringBefore('&').take(48)
    }
    data class Progress(val total: Int, val searchDone: Int, val nicknameDone: Int, val complete: Int)
    enum class Filter { PENDING, ALL, COMPLETE, SEARCH_PENDING, NICK_PENDING }
    private val prefs = context.applicationContext.getSharedPreferences("overlay_copy_queue_settings", Context.MODE_PRIVATE)
    var currentSessionId: Long
        get() = prefs.getLong("session_id", -1L)
        set(value) { prefs.edit().putLong("session_id", value).apply() }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE sessions (_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL)")
        db.execSQL("""CREATE TABLE items (
           _id INTEGER PRIMARY KEY AUTOINCREMENT,
           session_id INTEGER NOT NULL,
           sequence INTEGER NOT NULL,
           search_text TEXT NOT NULL,
           nickname TEXT NOT NULL,
           ivs TEXT,
           search_copied INTEGER NOT NULL DEFAULT 0,
           nickname_copied INTEGER NOT NULL DEFAULT 0,
           search_copied_at INTEGER,
           nickname_copied_at INTEGER,
           search_copy_count INTEGER NOT NULL DEFAULT 0,
           nickname_copy_count INTEGER NOT NULL DEFAULT 0,
           UNIQUE(session_id, sequence),
           FOREIGN KEY(session_id) REFERENCES sessions(_id)
        )""")
        db.execSQL("CREATE INDEX ix_queue_items_session ON items(session_id, sequence)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Preserve existing data; future versions must use explicit migrations.
        if (oldVersion < 2) db.execSQL("ALTER TABLE items ADD COLUMN ivs TEXT")
    }

    @Synchronized fun importPairs(pairs: List<OverlayPair>): Long {
        require(pairs.isNotEmpty())
        val db = writableDatabase
        db.beginTransaction()
        try {
            val id = db.insertOrThrow("sessions", null, ContentValues().apply {
                put("created_at", System.currentTimeMillis())
            })
            val statement = db.compileStatement("""INSERT INTO items
                (session_id, sequence, search_text, nickname, ivs, nickname_copied) VALUES (?, ?, ?, ?, ?, ?)""")
            pairs.forEachIndexed { i, pair ->
                statement.clearBindings()
                statement.bindLong(1, id)
                statement.bindLong(2, (i + 1).toLong())
                statement.bindString(3, pair.searchText)
                statement.bindString(4, pair.nickname)
                if (pair.ivs == null) statement.bindNull(5) else statement.bindString(5, pair.ivs)
                // Search-only entries require only the search-copy check.
                statement.bindLong(6, if (pair.nickname.isBlank()) 1L else 0L)
                statement.executeInsert()
            }
            db.setTransactionSuccessful()
            currentSessionId = id
            return id
        } finally { db.endTransaction() }
    }

    @Synchronized fun sessions(): List<Session> {
        val list = mutableListOf<Session>()
        readableDatabase.rawQuery("""SELECT s._id, s.created_at, COUNT(i._id)
                FROM sessions s LEFT JOIN items i ON i.session_id=s._id
                GROUP BY s._id ORDER BY s._id DESC""", null).use { c ->
            while (c.moveToNext()) list.add(Session(c.getLong(0), c.getLong(1), c.getInt(2)))
        }
        return list
    }

    @Synchronized fun progress(id: Long = currentSessionId): Progress {
        if (id < 0) return Progress(0, 0, 0, 0)
        readableDatabase.rawQuery("""SELECT COUNT(*),
            COALESCE(SUM(search_copied),0), COALESCE(SUM(nickname_copied),0),
            COALESCE(SUM(CASE WHEN search_copied=1 AND nickname_copied=1 THEN 1 ELSE 0 END),0)
            FROM items WHERE session_id=?""", arrayOf(id.toString())).use { c ->
            c.moveToFirst()
            return Progress(c.getInt(0), c.getInt(1), c.getInt(2), c.getInt(3))
        }
    }

    @Synchronized fun items(
        id: Long = currentSessionId,
        filter: Filter = Filter.PENDING,
        term: String = ""
    ): List<Item> {
        if (id < 0) return emptyList()
        val filterSql = when (filter) {
            Filter.PENDING -> " AND (search_copied=0 OR nickname_copied=0)"
            Filter.ALL -> ""
            Filter.COMPLETE -> " AND search_copied=1 AND nickname_copied=1"
            Filter.SEARCH_PENDING -> " AND search_copied=0"
            Filter.NICK_PENDING -> " AND nickname_copied=0"
        }
        val rows = mutableListOf<Item>()
        readableDatabase.rawQuery("""SELECT _id, sequence, search_text, nickname,
            search_copied, nickname_copied, search_copy_count, nickname_copy_count, ivs
            FROM items WHERE session_id=? $filterSql ORDER BY sequence""",
            arrayOf(id.toString())).use { c ->
            while (c.moveToNext()) {
                val item = Item(
                    c.getLong(0), c.getInt(1), c.getString(2), c.getString(3),
                    c.getInt(4) != 0, c.getInt(5) != 0, c.getInt(6), c.getInt(7), if (c.isNull(8)) null else c.getString(8)
                )
                if (term.isBlank() || item.search.contains(term, ignoreCase = true)
                    || item.nickname.contains(term, ignoreCase = true)
                    || item.speciesLabel.contains(term, ignoreCase = true)) rows.add(item)
            }
        }
        return rows
    }

    @Synchronized fun setCopied(itemId: Long, isSearch: Boolean, copied: Boolean) {
        val field = if (isSearch) "search" else "nickname"
        // item ownership scoped to active session prevents stale panel buttons mutating another session.
        val timestamp = if (copied) System.currentTimeMillis() else null
        val values = ContentValues().apply {
            put("${field}_copied", if (copied) 1 else 0)
            if (copied) put("${field}_copied_at", timestamp)
        }
        val db = writableDatabase
        db.beginTransaction()
        try {
            if (copied) {
                db.execSQL("""UPDATE items SET ${field}_copy_count=${field}_copy_count+1
                    WHERE _id=? AND session_id=?""", arrayOf(itemId, currentSessionId))
            }
            db.update("items", values, "_id=? AND session_id=?",
                arrayOf(itemId.toString(), currentSessionId.toString()))
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    @Synchronized fun resetProgress(id: Long = currentSessionId) {
        if (id < 0) return
        writableDatabase.execSQL("""UPDATE items SET search_copied=0, nickname_copied=0
            WHERE session_id=?""", arrayOf(id))
        // Copy counts/timestamps intentionally retained as history.
    }
}
