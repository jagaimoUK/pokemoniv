package com.example.pokemonivreader

/** Display-only classification based on existing offline PvPoke overall 70+ logic. */
internal object OverlayEligibilityBadge {
    enum class Verdict { ELIGIBLE, EXCLUDED, REVIEW, ALL_SPECIES }

    fun classify(
        ranked70Mode: Boolean,
        rankingReady: Boolean,
        shadowKnown: Boolean,
        eligibleCount: Int,
        borderlineCount: Int,
        genderPendingCount: Int
    ): Verdict = when {
        !rankingReady || !shadowKnown -> Verdict.REVIEW
        !ranked70Mode -> Verdict.ALL_SPECIES
        eligibleCount > 0 -> Verdict.ELIGIBLE
        borderlineCount > 0 || genderPendingCount > 0 -> Verdict.REVIEW
        else -> Verdict.EXCLUDED
    }

    /** Compact suffix: do not add new lines or modify the stored IV value. */
    fun decorate(displayIv: String, verdict: Verdict, hasIv: Boolean): String {
        if (!hasIv) return displayIv
        val base = listOf(" 対象外", " 確認中", " 全種")
            .firstOrNull(displayIv::endsWith)?.let { displayIv.removeSuffix(it) } ?: displayIv
        return when (verdict) {
            Verdict.ELIGIBLE -> base
            Verdict.EXCLUDED -> "$base 対象外"
            Verdict.REVIEW -> "$base 確認中"
            Verdict.ALL_SPECIES -> "$base 全種"
        }
    }
}
