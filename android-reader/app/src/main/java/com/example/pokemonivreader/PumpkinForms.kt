package com.example.pokemonivreader

import java.text.Normalizer

/** Battle-stat varieties, not the generic XXS/XS/M/XL/XXL size badge. */
internal object PumpkinForms {
    val sizes = listOf("small", "average", "large", "super")
    private val words = mapOf(
        "small" to listOf("こだましゅ", "コダマシュ", "小玉種", "ちいさい", "小さい"),
        "average" to listOf("ちゅうだましゅ", "チュウダマシュ", "中玉種", "ふつう", "普通"),
        "large" to listOf("おおだましゅ", "オオダマシュ", "大玉種", "おおきい", "大きい"),
        "super" to listOf("ぎがだましゅ", "ギガだましゅ", "ギガダマシュ", "ギガ玉種", "とくだい", "特大")
    )
    private val english = mapOf(
        "small" to listOf("small", "xs"),
        "average" to listOf("average", "medium", "normal", "standard"),
        "large" to listOf("large", "xl"),
        "super" to listOf("super", "jumbo", "xxl")
    )
    fun familyFromId(id: String): String? = id.substringBefore('_').takeIf { it == "pumpkaboo" || it == "gourgeist" }
    fun familyFromText(text: String): String? {
        val cleaned = normalize(text)
        val families = listOfNotNull(
            "pumpkaboo".takeIf { cleaned.contains("バケッチャ") || cleaned.contains(it) },
            "gourgeist".takeIf { cleaned.contains("パンプジン") || cleaned.contains(it) }
        )
        return families.singleOrNull()
    }
    fun displayName(id: String): String? {
        val family = familyFromId(id) ?: return null
        val form = id.substringAfter('_', "")
        if (form !in sizes) return null
        val base = if (family == "pumpkaboo") "バケッチャ" else "パンプジン"
        return "$base（${formLabel(form)}）"
    }
    fun formLabel(form: String): String = when (form) {
        "small" -> "こだましゅ"
        "average" -> "ちゅうだましゅ"
        "large" -> "おおだましゅ"
        "super" -> "ギガだましゅ"
        else -> form
    }
    fun sizeLabel(form: String): String = when (form) {
        "small" -> "XS"
        "average" -> "通常"
        "large" -> "XL"
        "super" -> "XXL"
        else -> "?"
    }
    private fun normalize(text: String): String = Normalizer.normalize(text, Normalizer.Form.NFKC).lowercase()

    /** Detect only explicit variety text. An isolated generic XL/XXL badge does
     * NOT establish the variety and therefore cannot trigger auto-registration.
     */
    fun explicitId(text: String): String? {
        val family = familyFromText(text) ?: return null
        val normalized = normalize(text)
        val candidates = mutableSetOf<String>()
        val noGaps = normalized.replace(Regex("[\\s・･()（）_-]+"), "")
        for ((form, aliases) in words) {
            if (aliases.any { noGaps.contains(normalize(it).replace(Regex("[\\s・･]+"), "")) }) candidates += form
        }
        // English form labels must appear on the SAME line as the Pokémon name,
        // not elsewhere on the appraisal screen as height/weight labels.
        val familyWords = if (family == "pumpkaboo") listOf("pumpkaboo", "バケッチャ")
                          else listOf("gourgeist", "パンプジン")
        normalized.lines().forEach { line ->
            val compact = line.replace(Regex("[\\s・･()（）_-]+"), "")
            if (familyWords.none { compact.contains(it) }) return@forEach
            val afterName = familyWords.firstNotNullOfOrNull { word ->
                val offset = compact.indexOf(word)
                if (offset >= 0) compact.substring(offset + word.length) else null
            } ?: ""
            for ((form, aliases) in english) {
                if (aliases.any { alias ->
                        val matching = afterName.removePrefix("の")
                        matching.startsWith(alias) && (alias.length > 2 || matching.length == alias.length)
                    }) candidates += form
            }
        }
        return candidates.singleOrNull()?.let { "${family}_$it" }
    }
}
