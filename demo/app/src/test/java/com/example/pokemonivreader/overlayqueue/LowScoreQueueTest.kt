package com.example.pokemonivreader.overlayqueue

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class LowScoreQueueTest {
    @Test fun newSearchOnlyFormatNeverCreatesNickname() {
        val content = """{"format":"pokemoniv-search-queue-v1","items":[
            {"search":"アギルダー,マケンカニ&!shadow&cp-1500&!favorite"},
            {"search":"サメハダー&shadow&cp-1500&!favorite"}]}"""
        val rows = OverlayPairParser.parse(content)
        assertEquals(2, rows.size)
        assertEquals("", rows[0].nickname)
        assertEquals("低スコア検索 1", rows[0].ivs)
        assertEquals("サメハダー&shadow&cp-1500&!favorite", rows[1].searchText)
    }

    @Test fun searchOnlyQueueIsFinishedBySearchCopyAlone() {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("overlay_copy_queue.db")
        context.getSharedPreferences("overlay_copy_queue_settings", 0).edit().clear().commit()
        val store = OverlayQueueStore(context)
        try {
            store.importPairs(OverlayPairParser.parse(
                """{"format":"pokemoniv-search-queue-v1","items":[{"search":"アギルダー&!shadow&cp-1500"}]}"""))
            val row = store.items(filter=OverlayQueueStore.Filter.ALL).single()
            assertTrue(row.nicknameCopied)
            assertFalse(row.complete)
            store.setCopied(row.id, true, true)
            assertEquals(1, store.progress().complete)
            assertEquals(0, store.items(filter=OverlayQueueStore.Filter.PENDING).size)
        } finally {
            store.close()
            context.deleteDatabase("overlay_copy_queue.db")
        }
    }

    @Test fun legacyPairContractIsUnchanged() {
        val rows = OverlayPairParser.parse("Quagsire&0attack&3defense&3hp\\nAQuag>Cor01".replace("\\n", "\n"))
        assertEquals("AQuag>Cor01", rows.single().nickname)
        assertNull(rows.single().ivs)
    }
}
