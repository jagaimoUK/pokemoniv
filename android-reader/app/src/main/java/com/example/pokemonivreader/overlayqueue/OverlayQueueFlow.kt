package com.example.pokemonivreader.overlayqueue

/** Navigation never fabricates copy checks or deletes SQLite records. */
class OverlayQueueFlow(
    skipped: List<Long> = emptyList(),
    history: List<Long> = emptyList(),
    reviewId: Long? = null,
    reviewMask: Int = 0
) {
    val skipped = skipped.toMutableSet()
    val history = history.toMutableList()
    var reviewId: Long? = reviewId
        private set

    var reviewMask: Int = reviewMask and 3
        private set

    fun seedReview(searchCopied: Boolean, nicknameCopied: Boolean) {
        reviewMask = if (searchCopied && nicknameCopied) 0
            else (if (searchCopied) 1 else 0) or (if (nicknameCopied) 2 else 0)
    }

    fun marked(id: Long, search: Boolean, original: Boolean): Boolean =
        if (reviewId == id) (reviewMask and (if (search) 1 else 2)) != 0 else original

    fun markReview(id: Long, search: Boolean, copied: Boolean) {
        if (reviewId != id) return
        val bit = if (search) 1 else 2
        reviewMask = if (copied) reviewMask or bit else reviewMask and bit.inv()
    }

    fun visible(ids: List<Long>, complete: Set<Long>): List<Long> {
        val review = reviewId?.takeIf { it in ids }
        return listOfNotNull(review) + ids.filter { it != review && it !in complete && it !in skipped }
    }

    fun advance(id: Long, complete: Boolean) {
        if (!complete) skipped.add(id)
        if (history.lastOrNull() != id) history.add(id)
        reviewId = null
        reviewMask = 0
    }

    fun back(ids: List<Long>, complete: Set<Long>): Long? {
        // A reviewed, unfinished individual remains available after navigating further back.
        val valid = ids.toSet()
        while (history.isNotEmpty()) {
            val id = history.removeAt(history.lastIndex)
            if (id !in valid || id == reviewId) continue
            skipped.remove(id)
            reviewId = id
            reviewMask = 0
            return id
        }
        // Also recover the last completed individual from older app versions.
        val current = reviewId
        val boundary = if (current == null) ids.size else ids.indexOf(current)
        val id = ids.take(boundary.coerceAtLeast(0)).lastOrNull { it in complete } ?: return null
        reviewId = id
        reviewMask = 0
        return id
    }
}

/** Remove individual-only conditions; retain form, region, status and other restrictions. */
object OverlayCleanupSearch {
    private val iv = Regex("!?[0-4](?:-[0-4])?(?:attack|defense|hp)", RegexOption.IGNORE_CASE)
    private val cp = Regex("!?cp(?:[0-9]+(?:-[0-9]*)?|-[0-9]+)", RegexOption.IGNORE_CASE)
    private val stars = Regex("!?[0-4]\\*")
    private val regions = listOf(
        "Alolan" to "alola", "Galarian" to "galar", "Hisuian" to "hisui", "Paldean" to "paldea"
    )

    fun base(search: String): String? {
        val terms = search.split('&').map { it.trim() }
        // Keep unsupported compound expressions out of transfer shortcuts.
        if (terms.any { it.isEmpty() || it.any { c -> c in ",;:|\n\r" } }) return null
        var species = terms.first()
        if (species.startsWith('!') || species.startsWith('+') || species.all { it.isDigit() }) return null
        val extra = mutableListOf<String>()
        for ((form, region) in regions) {
            val pattern = Regex("\\s*\\($form\\)", RegexOption.IGNORE_CASE)
            if (pattern.containsMatchIn(species)) {
                species = species.replace(pattern, "").trim()
                extra.add(region)
            }
        }
        val shadow = Regex("\\s*\\(Shadow\\)", RegexOption.IGNORE_CASE)
        if (shadow.containsMatchIn(species)) {
            species = species.replace(shadow, "").trim()
            extra.add("shadow")
        }
        if (species.isBlank()) return null
        val identity = terms.drop(1).filterNot {
            iv.matches(it) || cp.matches(it) || stars.matches(it) ||
                it.equals("favorite", true) || it.equals("!favorite", true)
        }
        return (listOf(species) + extra + identity).distinctBy { it.lowercase(java.util.Locale.ROOT) }.joinToString("&")
    }

    fun expressions(base: String): List<String> = listOf("$base&favorite", "$base&!favorite", base)
}
