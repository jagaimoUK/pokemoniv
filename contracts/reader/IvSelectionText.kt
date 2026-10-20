package com.example.pokemonivreader

/** IV text v1: the transfer format shared with the selection application's importer.
 * Keep stored/ranking names unchanged; convert display names only at export.
 * Compatibility examples live in contracts/iv-text-v1.tsv in both projects.
 */
internal object IvSelectionText {
    data class Group(val targets: List<String>, val ivs: List<String>)
    private val shadowSuffix = Regex("\\s*[（(]\\s*シャドウ\\s*[）)]$")
    private val miniorForm = Regex(
        "^(?:メテノ|Minior)\\s*[（(]\\s*(コア(?:フォルム)?|流星(?:フォルム)?|Core|Meteor)\\s*[）)]$",
        RegexOption.IGNORE_CASE
    )

    fun targetName(name: String): String {
        val value = name.trim()
        // Stored source names stay untouched; only the exported heading is normalized.
        miniorForm.matchEntire(value)?.let { match ->
            return when (match.groupValues[1].lowercase()) {
                "core", "コア", "コアフォルム" -> "メテノ（コア）"
                else -> "メテノ（流星）"
            }
        }
        return if (shadowSuffix.containsMatchIn(value)) {
            "シャドウ" + value.replace(shadowSuffix, "").trim().removePrefix("シャドウ")
        } else value
    }

    fun prompt(groups: List<Group>): String = buildString {
        val populated = groups.filter { it.targets.isNotEmpty() && it.ivs.isNotEmpty() }
        if (populated.isEmpty()) return@buildString
        appendLine("個体値厳選")
        populated.forEach { group ->
            appendLine()
            appendLine("# ${group.targets.joinToString(" ") { targetName(it) }}")
            group.ivs.forEach { appendLine(it) }
        }
    }.trimEnd()
}
