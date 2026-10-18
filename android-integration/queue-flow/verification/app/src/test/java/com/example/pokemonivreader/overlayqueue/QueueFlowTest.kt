package com.example.pokemonivreader.overlayqueue

import org.junit.Assert.*
import org.junit.Test

class QueueFlowTest {
    @Test fun completionSkipAndRepeatedBack() {
        val flow = OverlayQueueFlow()
        val ids = listOf(1L, 2L, 3L)
        flow.advance(1, true)
        assertEquals(listOf(2L, 3L), flow.visible(ids, setOf(1)))
        flow.advance(2, false)
        assertEquals(listOf(3L), flow.visible(ids, setOf(1)))
        assertEquals(2L, flow.back(ids, setOf(1)))
        assertEquals(listOf(2L, 3L), flow.visible(ids, setOf(1)))
        assertEquals(1L, flow.back(ids, setOf(1)))
        assertEquals(listOf(1L, 2L, 3L), flow.visible(ids, setOf(1)))
        assertNull(flow.back(ids, setOf(1)))
    }
    @Test fun persistenceAndLegacyRecovery() {
        val original = OverlayQueueFlow()
        original.advance(1, true); original.advance(2, false)
        val restored = OverlayQueueFlow(original.skipped.toList(), original.history.toList(), original.reviewId)
        assertEquals(listOf(3L), restored.visible(listOf(1L, 2L, 3L), setOf(1)))
        assertEquals(2L, restored.back(listOf(1L, 2L, 3L), setOf(1)))
        val legacy = OverlayQueueFlow()
        assertEquals(2L, legacy.back(listOf(1L, 2L), setOf(1, 2)))
        assertEquals(1L, legacy.back(listOf(1L, 2L), setOf(1, 2)))
        assertNull(legacy.back(listOf(1L, 2L), setOf(1, 2)))
    }
    @Test fun cleanupPreservesIdentity() {
        val cases = mapOf(
            "Wooper&paldea&shadow&3attack&2defense&3hp&cp458&!favorite" to "Wooper&paldea&shadow",
            "Quagsire&!shadow&!purified&0attack&3defense&3hp&cp-1500" to "Quagsire&!shadow&!purified",
            "Raichu (Alolan)&purified&cp123&favorite" to "Raichu&alola&purified",
            "Mr. Mime&galar&shadow&1attack&cp200-300" to "Mr. Mime&galar&shadow",
            "Nidoran♀&1attack&1defense&1hp&cp100-" to "Nidoran♀",
            "Growlithe (Hisuian) (Shadow)&4attack&4defense&4hp" to "Growlithe&hisui&shadow",
            "Zigzagoon (Galarian)&cp5" to "Zigzagoon&galar",
            "Wooper (Paldean)&cp458" to "Wooper&paldea",
            "ウパー&パルデア&しゃどう&cp458" to "ウパー&パルデア&しゃどう"
        )
        for ((input, expected) in cases) assertEquals(input, expected, OverlayCleanupSearch.base(input))
        assertEquals(listOf("Wooper&paldea&shadow&favorite", "Wooper&paldea&shadow&!favorite", "Wooper&paldea&shadow"),
            OverlayCleanupSearch.expressions("Wooper&paldea&shadow"))
        assertNull(OverlayCleanupSearch.base("Wooper,Quagsire&shadow"))
        assertNull(OverlayCleanupSearch.base("&shadow"))
    }
}
