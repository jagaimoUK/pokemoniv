package com.example.pokemonivreader.overlayqueue

import org.json.JSONObject

/** The current PvPoke app export contract is exactly two lines per individual:
 *  Pokémon GO search expression, then nickname. Preserve both verbatim. */
data class OverlayPair(val searchText: String, val nickname: String, val ivs: String? = null)

class OverlayPairFormatException(message: String) : IllegalArgumentException(message)

object OverlayPairParser {
    private fun parseStructured(text: String): List<OverlayPair> {
        try {
            val root = JSONObject(text)
            val format = root.getString("format")
            if (format == "pokemoniv-search-queue-v1") {
                // Search-only batch. An empty nickname is intentional and must never
                // be replaced with a made-up nickname or exact IV values.
                val items = root.getJSONArray("items")
                require(items.length() in 1..10000) { "検索式は1〜10000件です" }
                return (0 until items.length()).map { i ->
                    val item = items.getJSONObject(i)
                    val search = item.getString("search")
                    require(search.isNotBlank() && search.length <= 2000 &&
                        search.none { it == '\n' || it == '\r' }) { "検索式が不正です" }
                    OverlayPair(search, "", null)
                }
            }
            require(format == "pokemoniv-overlay-v2") { "対応していない形式です" }
            val items = root.getJSONArray("items")
            require(items.length() in 1..10000) { "取り込みは1〜10000件です" }
            return (0 until items.length()).map { i ->
                val item = items.getJSONObject(i)
                val search = item.getString("search")
                val nickname = item.getString("nickname")
                val ivs = item.getString("ivs")
                require(search.isNotBlank() && search.length <= 2000 && search.none { it == '\n' || it == '\r' })
                require(nickname.isNotBlank() && nickname.length <= 100 && nickname.none { it == '\n' || it == '\r' })
                require(Regex("[0-9]{1,2}/[0-9]{1,2}/[0-9]{1,2}").matches(ivs) && ivs.split('/').all { it.toInt() in 0..15 }) { "個体値が不正です" }
                if (!item.isNull("cp")) {
                    val cp = item.getInt("cp")
                    require(cp in 1..10000 && search.split('&').any { it.equals("cp$cp", true) }) { "CPと検索式が一致しません" }
                }
                OverlayPair(search, nickname, ivs)
            }
        } catch (e: Exception) {
            throw OverlayPairFormatException("取り込み内容を確認してください: ${e.message}")
        }
    }

    /** Old two-line exports contain IV ranges only; never invent exact IVs. */
    fun legacyIvLabel(search: String): String {
        val buckets = listOf("0", "1〜5", "6〜10", "11〜14", "15")
        return listOf("attack" to "攻", "defense" to "防", "hp" to "HP").joinToString(" / ") { (key, label) ->
            val value = search.split('&').firstNotNullOfOrNull { Regex("([0-4])$key", RegexOption.IGNORE_CASE).matchEntire(it)?.groupValues?.get(1)?.toInt() }
            "$label${value?.let { buckets[it] } ?: "不明"}"
        }
    }

    fun parse(text: String): List<OverlayPair> {
        if (text.trimStart().startsWith("{")) return parseStructured(text)
        var normalized = text.replace("\r\n", "\n").replace('\r', '\n')
        // A single terminal newline is a line separator, not an empty record.
        if (normalized.endsWith("\n")) normalized = normalized.dropLast(1)
        if (normalized.isEmpty()) throw OverlayPairFormatException("入力が空です。検索式とニックネームを一括コピーしてください。")
        val lines = normalized.split('\n')
        if (lines.size % 2 != 0) {
            throw OverlayPairFormatException("全${lines.size}行です。検索式とニックネームを2行ずつ入力してください（${lines.size}行目を確認）。")
        }
        return buildList(lines.size / 2) {
            for (i in lines.indices step 2) {
                val search = lines[i]
                val nickname = lines[i + 1]
                if (search.isBlank()) throw OverlayPairFormatException("${i + 1}行目の検索式が空です。")
                if (nickname.isBlank()) throw OverlayPairFormatException("${i + 2}行目のニックネームが空です。")
                add(OverlayPair(search, nickname))
            }
        }
    }
}
