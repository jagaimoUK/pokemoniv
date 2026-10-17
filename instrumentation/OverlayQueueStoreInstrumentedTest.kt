package com.example.pokemonivreader.overlayqueue

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class OverlayQueueStoreInstrumentedTest {
    @Test
    fun progressAndCopyCountsSurviveDatabaseReopen() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        context.deleteDatabase("overlay_copy_queue.db")
        context.getSharedPreferences("overlay_copy_queue_settings", android.content.Context.MODE_PRIVATE)
            .edit().clear().commit()
        var store = OverlayQueueStore(context)
        val pairs = (0 until 1000).map {
            OverlayPair("Quagsire&0attack&3defense&3hp", "AQuag>Cor01")
        }
        val firstSession = store.importPairs(pairs)
        assertEquals(1000, store.progress().total)
        assertEquals(1000, store.items(firstSession, OverlayQueueStore.Filter.ALL).size)
        assertEquals(1000, store.items(firstSession, OverlayQueueStore.Filter.PENDING).size)
        val first = store.items(firstSession, OverlayQueueStore.Filter.ALL).first()
        store.setCopied(first.id, true, true)
        store.setCopied(first.id, false, true)
        var p = store.progress()
        assertEquals(1, p.searchDone)
        assertEquals(1, p.nicknameDone)
        assertEquals(1, p.complete)
        assertEquals(999, store.items(firstSession, OverlayQueueStore.Filter.PENDING).size)
        store.setCopied(first.id, true, true)
        val copied = store.items(firstSession, OverlayQueueStore.Filter.ALL).first()
        assertEquals(2, copied.searchCopyCount)
        assertEquals(1, copied.nicknameCopyCount)
        store.setCopied(first.id, true, false)
        p=store.progress()
        assertEquals(0, p.complete)
        assertEquals(1, p.nicknameDone)
        val reopenedId = store.currentSessionId
        store.close()
        store = OverlayQueueStore(context)
        assertEquals(reopenedId, store.currentSessionId)
        assertEquals(2, store.items(firstSession, OverlayQueueStore.Filter.ALL).first().searchCopyCount)
        assertFalse(store.items(firstSession, OverlayQueueStore.Filter.ALL).first().searchCopied)
        val secondSession = store.importPairs(pairs.take(500))
        assertEquals(500, store.progress().total)
        assertEquals(1000, store.progress(firstSession).total)
        assertEquals(2, store.sessions().size)
        assertEquals(500, store.items(secondSession, OverlayQueueStore.Filter.ALL).size)
        store.resetProgress(firstSession)
        assertEquals(0, store.progress(firstSession).nicknameDone)
        assertEquals(2, store.items(firstSession, OverlayQueueStore.Filter.ALL).first().searchCopyCount)
        store.close()
    }
}
