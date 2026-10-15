package com.example.pokemonivreader

/** IV text v1: the transfer format shared with the selection application's importer.
 * Keep stored/ranking names unchanged; convert display names only at export.
 * Compatibility examples live in contracts/iv-text-v1.tsv in both projects.
 */
internal object IvSelectionText {
    data class Group(val targets: List<String>, val ivs: List<String>)
    private val shadowSuffix = Regex("\\s*[（(]\\s*シャドウ\\s*[）)]$")

    fun targetName(name: String): String {
        val value = name.trim()
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
