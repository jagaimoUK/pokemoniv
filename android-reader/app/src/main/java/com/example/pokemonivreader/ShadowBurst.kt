package com.example.pokemonivreader

/** Small temporal vote buffer. No frames or screenshots are retained. */
internal class ShadowBurst {
    private val samples = mutableListOf<ShadowRecognizer.Evidence>()
    private var lastAt = Long.MIN_VALUE
    private var firstAt = Long.MIN_VALUE
    @Synchronized fun reset() {
        samples.clear()
        lastAt = Long.MIN_VALUE
        firstAt = Long.MIN_VALUE
    }
    @Synchronized fun needsSample(nowMs: Long): Boolean =
        lastAt == Long.MIN_VALUE || nowMs < lastAt || nowMs - lastAt >= 40L

    @Synchronized fun latest(): List<ShadowRecognizer.Evidence> = samples.toList()

    /** null means wait for another frame; accepted samples are >=40 ms apart. */
    @Synchronized fun offer(nowMs: Long, evidence: ShadowRecognizer.Evidence): List<ShadowRecognizer.Evidence>? {
        if (lastAt != Long.MIN_VALUE && (nowMs < lastAt || nowMs - lastAt > 1500L)) reset()
        if (lastAt != Long.MIN_VALUE && nowMs - lastAt < 40L) return null
        if (samples.isEmpty()) firstAt = nowMs
        lastAt = nowMs
        samples += evidence
        if(samples.size>3) samples.removeAt(0)
        return if (samples.size >= 3) samples.takeLast(3) else null
    }
}
