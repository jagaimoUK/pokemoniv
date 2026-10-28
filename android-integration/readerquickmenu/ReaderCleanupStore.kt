package com.example.pokemonivreader.readerquickmenu

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Private, local search-only queue for the reader overlay.
 * This never writes to the recommendation/nickname queue or OCR history.
 */
class ReaderCleanupStore(context: Context) {
    private val prefs = context.getSharedPreferences("reader_cleanup_search_v1", Context.MODE_PRIVATE)

    /** Validate the COMPLETE incoming batch before replacing the previous one. */
    fun importPayload(raw: String): Int {
        val queries = parse(raw)
        check(prefs.edit().putString("payload", raw).commit()) { "検索式を保存できませんでした" }
        return queries.size
    }

    fun queries(): List<String> {
        val raw = prefs.getString("payload", null) ?: return emptyList()
        return try { parse(raw) } catch (_: Exception) { emptyList() }
    }

    companion object {
        fun isCleanupPayload(raw: String): Boolean =
            raw.trimStart().startsWith("{") &&
                try { JSONObject(raw).optString("format") == "pokemoniv-search-queue-v1" }
                catch (_: Exception) { false }

        fun parse(raw: String): List<String> {
            require(raw.length in 1..2_000_000) { "データが大きすぎます" }
            val obj = JSONObject(raw)
            require(obj.getString("format") == "pokemoniv-search-queue-v1") { "対応していない形式です" }
            val items: JSONArray = obj.getJSONArray("items")
            require(items.length() in 1..10000) { "検索式は1〜10000件です" }
            return (0 until items.length()).map { index ->
                val item = items.getJSONObject(index)
                val query = item.getString("search")
                require(query.isNotBlank() && query.length <= 2000 &&
                    query.none { it == '\n' || it == '\r' }) { "検索式が不正です" }
                // The cleanup format must NEVER carry a nickname.
                require(!item.has("nickname")) { "非厳選データには名前を含めないでください" }
                query
            }
        }
    }
}
