package com.example.pokemonivreader.readerquickmenu

import android.app.Activity
import android.content.ClipboardManager
import android.content.Context
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ReaderQuickMenuTest {
    @Test fun payloadPersistsAndRejectedUpdateDoesNotErasePrevious() {
        val activity = Robolectric.buildActivity(Activity::class.java).setup().get()
        val store = ReaderCleanupStore(activity)
        val valid = """{"format":"pokemoniv-search-queue-v1","items":[{"search":"244,682&cp-1500&!favorite"},{"search":"Quagsire&cp717"}]}"""
        assertEquals(2, store.importPayload(valid))
        assertEquals(listOf("244,682&cp-1500&!favorite", "Quagsire&cp717"), ReaderCleanupStore(activity).queries())
        try {
            store.importPayload("""{"format":"pokemoniv-search-queue-v1","items":[{"search":"OK"},{"search":"bad\nline"}]}""")
            fail("Invalid payload must be rejected atomically")
        } catch (_: IllegalArgumentException) {}
        assertEquals(2, store.queries().size)
        assertFalse(ReaderCleanupStore.isCleanupPayload("""{"format":"pokemoniv-overlay-v2","items":[]}"""))
    }

    @Test fun ellipsisIsTheOnlyVisibleMenuControlUntilOpened() {
        val activity = Robolectric.buildActivity(Activity::class.java).setup().get()
        val toolbar = LinearLayout(activity)
        var mode = ReaderQuickMenu.Mode.SELECTION
        val menu = ReaderQuickMenu(activity, { mode }, { mode = it; true }, {})
        val wrapper = menu.attachTo(toolbar) as LinearLayout
        assertEquals("⋯", (wrapper.getChildAt(0) as TextView).text.toString())
        val panel = wrapper.getChildAt(1) as LinearLayout
        assertEquals(View.GONE, panel.visibility)
        (wrapper.getChildAt(0) as TextView).performClick()
        assertEquals(View.VISIBLE, panel.visibility)
        val modes = panel.getChildAt(0) as LinearLayout
        (modes.getChildAt(1) as Button).performClick()
        assertEquals(ReaderQuickMenu.Mode.ALL, mode)
        assertEquals(View.GONE, panel.visibility)
        (wrapper.getChildAt(0) as TextView).performClick()
        menu.collapse()
        assertEquals(View.GONE, panel.visibility)
    }

    @Test fun cleanupCopiesDirectlyWithoutNicknameQueue() {
        val activity = Robolectric.buildActivity(Activity::class.java).setup().get()
        val value = "244,682&cp-1500&!favorite"
        val payload = org.json.JSONObject()
            .put("format", "pokemoniv-search-queue-v1")
            .put("items", org.json.JSONArray().put(org.json.JSONObject().put("search", value)))
            .toString()
        ReaderCleanupStore(activity).importPayload(payload)
        val toolbar = LinearLayout(activity)
        val messages = mutableListOf<String>()
        val menu = ReaderQuickMenu(activity, { ReaderQuickMenu.Mode.SELECTION }, { true }, { messages.add(it) })
        val wrapper = menu.attachTo(toolbar) as LinearLayout
        (wrapper.getChildAt(0) as TextView).performClick()
        val panel = wrapper.getChildAt(1) as LinearLayout
        (panel.getChildAt(1) as Button).performClick()
        val clip = (activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip
        assertEquals(value, clip?.getItemAt(0)?.text.toString())
        assertEquals(View.GONE, panel.visibility)
        assertTrue(messages.last().contains("コピーしました"))
    }
}
