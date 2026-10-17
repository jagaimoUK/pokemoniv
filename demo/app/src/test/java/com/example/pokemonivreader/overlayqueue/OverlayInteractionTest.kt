package com.example.pokemonivreader.overlayqueue

import android.app.Application
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ListView
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSettings

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w400dp-h800dp-mdpi")
class OverlayInteractionTest {
    private lateinit var app: Application
    private lateinit var controller: OverlayCopyQueueController
    private lateinit var store: OverlayQueueStore
    private val search = "Wooper&0attack&3defense&3hp&cp717"

    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        ShadowSettings.setCanDrawOverlays(true)
        OverlayCopyQueueController.get(app).destroy()
        app.deleteDatabase("overlay_copy_queue.db")
        app.getSharedPreferences("overlay_queue_placement", Context.MODE_PRIVATE).edit().clear().commit()
        store = OverlayQueueStore(app)
        store.importPairs(listOf(OverlayPair(search, "AQuag>Cor01", "0/11/12")))
        controller = OverlayCopyQueueController.get(app)
        controller.openPanel()
    }
    @After fun cleanup() { controller.destroy(); store.close() }
    private fun field(name: String): Any? = controller.javaClass.getDeclaredField(name).apply { isAccessible = true }.get(controller)
    private fun root() = field("panel") as LinearLayout
    private fun params() = root().layoutParams as WindowManager.LayoutParams
    private fun buttons(v: View): List<Button> = if (v is Button) listOf(v) else if (v is ViewGroup)
        (0 until v.childCount).flatMap { buttons(v.getChildAt(it)) } else emptyList()
    private fun rowButton(name: String): Button {
        val list = field("list") as ListView
        return buttons(list.adapter.getView(0, null, list)).first { it.text.endsWith(name) }
    }
    private fun item() = store.items(filter = OverlayQueueStore.Filter.ALL).single()
    private fun gesture(handle: View, dx: Float, dy: Float) {
        val start = SystemClock.uptimeMillis()
        for ((action, x, y) in listOf(Triple(MotionEvent.ACTION_DOWN, 150f, 100f),
                Triple(MotionEvent.ACTION_MOVE, 150f + dx, 100f + dy),
                Triple(MotionEvent.ACTION_UP, 150f + dx, 100f + dy))) {
            val e = MotionEvent.obtain(start, start + 20, action, x, y, 0)
            handle.dispatchTouchEvent(e); e.recycle()
        }
    }
    @Test fun repeatTapUnchecksImmediatelyWithoutCopyingAgain() {
        val clipboard = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val button = rowButton("検索式")
        button.performClick()
        assertTrue(item().searchCopied); assertFalse(item().nicknameCopied)
        assertEquals(1, item().searchCopyCount)
        // Reuse the same row before any ListView redraw: stale listeners must still toggle.
        clipboard.setPrimaryClip(ClipData.newPlainText("other", "keep this"))
        button.performClick()
        assertFalse(item().searchCopied); assertEquals(1, item().searchCopyCount)
        assertEquals("keep this", clipboard.primaryClip!!.getItemAt(0).text.toString())
        button.performClick()
        assertTrue(item().searchCopied); assertEquals(2, item().searchCopyCount)
        button.performLongClick()
        assertTrue(item().searchCopied); assertEquals(3, item().searchCopyCount)
        assertEquals(search, clipboard.primaryClip!!.getItemAt(0).text.toString())
        val nick = rowButton("名前")
        nick.performClick(); nick.performClick()
        assertFalse(item().nicknameCopied); assertEquals(1, item().nicknameCopyCount)
        assertTrue(item().searchCopied)
    }
    @Test fun headerDragPersistsAfterControllerRecreation() {
        val initialX = params().x; val initialY = params().y
        gesture(root().findViewWithTag("overlay_move_handle"), -70f, 90f)
        val x = params().x; val y = params().y
        assertTrue(x < initialX); assertTrue(y > initialY)
        controller.destroy(); controller = OverlayCopyQueueController.get(app); controller.openPanel()
        assertEquals(x, params().x); assertEquals(y, params().y)
        assertTrue(params().flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE != 0)
    }
    @Test fun cornerResizeKeepsChecksAndRestoresSize() {
        rowButton("検索式").performClick()
        val width = params().width; val height = params().height
        gesture(root().findViewWithTag("overlay_resize_handle"), -65f, 100f)
        val w = params().width; val h = params().height
        assertTrue(w > width); assertTrue(h > height)
        assertTrue(item().searchCopied)
        controller.closePanel(); controller.openPanel()
        assertEquals(w, params().width); assertEquals(h, params().height)
        gesture(root().findViewWithTag("overlay_resize_handle"), 10000f, -10000f)
        assertTrue(params().width >= 196); assertTrue(params().height >= 180)
        assertInsideScreen()
        gesture(root().findViewWithTag("overlay_move_handle"), -10000f, 10000f)
        assertInsideScreen()
    }
    private fun assertInsideScreen() {
        val p = params(); val m = app.resources.displayMetrics
        assertTrue(p.x >= 0 && p.y >= 0)
        assertTrue(p.x + p.width <= m.widthPixels)
        assertTrue(p.y + p.height <= m.heightPixels)
    }
    @Test fun outsideTapStillCollapsesAndStopRemovesBubble() {
        val e = MotionEvent.obtain(0, 0, MotionEvent.ACTION_OUTSIDE, 0f, 0f, 0)
        root().dispatchTouchEvent(e); e.recycle()
        assertNull(field("panel")); assertNotNull(field("bubble"))
        controller.openPanel()
        buttons(root()).single { it.text == "終了" }.performClick()
        assertNull(field("panel")); assertNull(field("bubble"))
    }
}
