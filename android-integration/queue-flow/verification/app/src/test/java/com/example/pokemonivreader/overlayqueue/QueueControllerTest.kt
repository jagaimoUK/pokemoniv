package com.example.pokemonivreader.overlayqueue

import android.content.ClipboardManager
import android.content.Context
import android.widget.ListView
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class QueueControllerTest {
    private lateinit var controller: OverlayCopyQueueController
    private lateinit var store: OverlayQueueStore
    private val app get() = RuntimeEnvironment.getApplication()
    private fun field(name: String) = controller.javaClass.getDeclaredField(name).apply { isAccessible = true }
    private fun refresh() = controller.javaClass.getDeclaredMethod("refresh").apply { isAccessible = true }.invoke(controller)
    private fun action(name: String) = controller.javaClass.getDeclaredMethod(name).apply { isAccessible = true }.invoke(controller)
    @Suppress("UNCHECKED_CAST") private fun rows() = field("rows").get(controller) as List<OverlayQueueStore.Item>
    private fun copy(item: OverlayQueueStore.Item, search: Boolean) {
        controller.javaClass.getDeclaredMethod("copy", OverlayQueueStore.Item::class.java, Boolean::class.javaPrimitiveType)
            .apply { isAccessible = true }.invoke(controller, item, search)
    }
    @Before fun setup() {
        app.deleteDatabase("overlay_copy_queue.db")
        app.getSharedPreferences("overlay_queue_placement", Context.MODE_PRIVATE).edit().clear().commit()
        controller = OverlayCopyQueueController.get(app)
        store = field("store").get(controller) as OverlayQueueStore
        store.importPairs(listOf(
            OverlayPair("Wooper&paldea&shadow&3attack&2defense&3hp&cp458&!favorite", "AWoop", "15/10/12"),
            OverlayPair("Wooper&paldea&shadow&1attack&2defense&3hp&cp100", "BWoop", "1/10/12"),
            OverlayPair("Quagsire&!shadow&!purified&0attack&3defense&3hp&cp717", "AQuag", "0/11/12")
        ))
        field("list").set(controller, ListView(app))
        refresh()
    }
    @After fun teardown() { controller.destroy() }
    @Test fun bothCopiesDisappearEitherOrderAndCanReturn() {
        val first = rows().first()
        copy(first, true)
        assertEquals(3, rows().size)
        copy(rows().first(), false)
        assertEquals(2, rows().size)
        assertEquals(1, store.progress().complete)
        assertEquals("AWoop", (app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip!!.getItemAt(0).text.toString())
        action("previousIndividual")
        assertEquals(first.id, rows().first().id)
        assertTrue(rows().first().complete)
        copy(rows().first(), true)
        assertEquals(3, rows().size)
        copy(rows().first(), false)
        assertEquals(2, rows().size)
        val second = rows().first()
        copy(second, false); assertEquals(2, rows().size)
        copy(rows().first(), true); assertEquals(1, rows().size)
        assertEquals(2, store.progress().complete)
    }
    @Test fun skippedItemAndSessionStateSurviveRecreation() {
        val firstId = rows().first().id
        copy(rows().first(), true)
        action("nextIndividual")
        assertEquals(2, rows().size)
        assertEquals(0, store.progress().complete)
        controller.destroy()
        controller = OverlayCopyQueueController.get(app)
        store = field("store").get(controller) as OverlayQueueStore
        field("list").set(controller, ListView(app)); refresh()
        assertEquals(2, rows().size)
        action("previousIndividual")
        assertEquals(firstId, rows().first().id)
        assertTrue(rows().first().searchCopied)
        assertFalse(rows().first().nicknameCopied)
        store.importPairs(listOf(OverlayPair("Pikachu&cp10", "APika")))
        refresh()
        assertEquals(1, rows().size)
        assertEquals("Pikachu&cp10", rows().first().search)
    }
    @Test fun cleanupIsUniqueSurvivesCompletionAndDoesNotCheckItems() {
        @Suppress("UNCHECKED_CAST")
        val bases = field("cleanupBases").get(controller) as List<String>
        assertEquals(listOf("Wooper&paldea&shadow", "Quagsire&!shadow&!purified"), bases)
        controller.javaClass.getDeclaredMethod("copyCleanup", String::class.java).apply { isAccessible = true }
            .invoke(controller, "Wooper&paldea&shadow&favorite")
        assertEquals(0, store.progress().searchDone)
        assertEquals(0, store.progress().nicknameDone)
        while (rows().isNotEmpty()) { copy(rows().first(), true); copy(rows().first(), false) }
        assertEquals(0, rows().size)
        assertEquals(bases, field("cleanupBases").get(controller))
        action("previousIndividual")
        assertEquals(1, rows().size)
        assertTrue(rows().first().complete)
    }
}
