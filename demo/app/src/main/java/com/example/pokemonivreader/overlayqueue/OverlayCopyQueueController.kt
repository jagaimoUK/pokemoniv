package com.example.pokemonivreader.overlayqueue

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.roundToInt

/** Only the bounded panel receives touches. Outside taps pass through to GO. */
class OverlayCopyQueueController private constructor(private val app: Context) {
    companion object {
        @Volatile private var instance: OverlayCopyQueueController? = null
        fun get(context: Context): OverlayCopyQueueController = instance
            ?: synchronized(this) { instance ?: OverlayCopyQueueController(context.applicationContext).also { instance = it } }
    }
    private val store = OverlayQueueStore(app)
    private val placement = app.getSharedPreferences("overlay_queue_placement", Context.MODE_PRIVATE)
    private val manager = app.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var bubble: TextView? = null
    private var dropTarget: TextView? = null
    private var dropParams: WindowManager.LayoutParams? = null
    private var panel: LinearLayout? = null
    private var panelParams: WindowManager.LayoutParams? = null
    private var list: ListView? = null
    private var summary: TextView? = null
    private var adapter: QueueAdapter? = null
    private var rows: List<OverlayQueueStore.Item> = emptyList()

    // Retain the last visible item and exact pixel offset when the panel is collapsed.
    // A different import session starts at the top rather than an unrelated old row.
    private fun saveListScroll() {
        val currentList = list ?: return
        placement.edit()
            .putLong("scroll_session_id", store.currentSessionId)
            .putInt("scroll_row", currentList.firstVisiblePosition)
            .putInt("scroll_offset", currentList.getChildAt(0)?.top ?: 0)
            .apply()
    }

    private fun restoreListScroll() {
        val currentList = list ?: return
        if (placement.getLong("scroll_session_id", -1L) != store.currentSessionId) return
        val position = placement.getInt("scroll_row", 0)
        val offset = placement.getInt("scroll_offset", 0)
        val session = store.currentSessionId
        currentList.post {
            if (list !== currentList || store.currentSessionId != session) return@post
            val count = currentList.adapter?.count ?: 0
            if (count > 0) currentList.setSelectionFromTop(position.coerceIn(0, count - 1), offset)
        }
    }
    private fun dp(n: Int) = (n * app.resources.displayMetrics.density + .5f).toInt()
    private fun toast(s: String) = Toast.makeText(app, s, Toast.LENGTH_SHORT).show()
    private fun background(color: Int) = GradientDrawable().apply { setColor(color); cornerRadius = dp(10).toFloat() }
    private fun label(s: String, size: Float = 12f) = TextView(app).apply {
        text = s; textSize = size; setTextColor(Color.WHITE)
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(3), dp(2), dp(3), dp(2))
    }
    private fun button(s: String, action: () -> Unit) = Button(app).apply {
        text = s; textSize = 12f; isAllCaps = false
        minWidth = 0; minimumWidth = 0; minHeight = 0; minimumHeight = 0
        setPadding(dp(3), 0, dp(3), 0); setTextColor(Color.WHITE)
        background = background(Color.rgb(55, 76, 99))
        setOnClickListener { action() }
    }
    private fun params(width: Int, height: Int, x: Int, y: Int) = WindowManager.LayoutParams(
        width, height,
        if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY else WindowManager.LayoutParams.TYPE_PHONE,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT
    ).apply {
        gravity = Gravity.TOP or Gravity.START; this.x = x; this.y = y
        // Android 12+ allows touches through an untrusted overlay at <=0.8 opacity.
        // Only one of bubble/panel is visible, so their opacity never accumulates.
        alpha = .8f
    }
    /** Show a temporary dismiss target only while the selection bubble is being dragged. */
    private fun showDropTarget() {
        if (dropTarget != null) return
        val m = app.resources.displayMetrics
        val size = dp(66)
        val p = params(size, size, ((m.widthPixels - size) / 2).coerceAtLeast(0),
            (m.heightPixels - size - dp(64)).coerceAtLeast(0)).apply {
            // This indicator must not steal touch events from the dragged bubble or the game.
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        }
        val view = label("×", 30f).apply {
            gravity = Gravity.CENTER
            contentDescription = "ここへ厳選アイコンを移動すると終了"
            background = background(Color.rgb(117, 38, 51))
            elevation = dp(6).toFloat()
        }
        try {
            manager.addView(view, p)
            dropTarget = view
            dropParams = p
        } catch (_: Exception) {
            dropTarget = null
            dropParams = null
        }
    }

    private fun isOverDropTarget(bubbleParams: WindowManager.LayoutParams): Boolean {
        val target = dropParams ?: return false
        val cx = bubbleParams.x + bubbleParams.width / 2
        val cy = bubbleParams.y + bubbleParams.height / 2
        return cx >= target.x && cx <= target.x + target.width &&
            cy >= target.y && cy <= target.y + target.height
    }

    private fun updateDropTarget(bubbleParams: WindowManager.LayoutParams) {
        val active = isOverDropTarget(bubbleParams)
        dropTarget?.background = background(if (active) Color.rgb(188, 51, 67) else Color.rgb(117, 38, 51))
        dropTarget?.text = if (active) "✓" else "×"
    }

    private fun hideDropTarget() {
        dropTarget?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        dropTarget = null
        dropParams = null
    }

    fun show(): Boolean {
        if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(app)) return false
        if (bubble != null) return true
        val metrics = app.resources.displayMetrics
        val maxX = (metrics.widthPixels - dp(48)).coerceAtLeast(0)
        val maxY = (metrics.heightPixels - dp(46)).coerceAtLeast(0)
        val x = (placement.getFloat("bubble_x_ratio", 1f).coerceIn(0f, 1f) * maxX).toInt()
        val ratioY = placement.getFloat("bubble_y_ratio", -1f)
        val y = if (ratioY < 0f) dp(150).coerceAtMost(maxY) else (ratioY.coerceIn(0f, 1f) * maxY).toInt()
        val v = label("厳選", 12f).apply {
            gravity = Gravity.CENTER; background = background(Color.rgb(30, 80, 120))
            contentDescription = "厳選リストを開く。長押しでオーバーレイ終了"
        }
        val p = params(dp(48), dp(46), x, y)
        try { manager.addView(v, p) } catch (e: Exception) { toast("表示できません: ${e.localizedMessage}"); return false }
        bubble = v
        v.setOnClickListener { togglePanel() }
        v.setOnLongClickListener { hide(); true }
        v.setOnTouchListener(object : View.OnTouchListener {
            var downX = 0f; var downY = 0f; var startX = 0; var startY = 0; var dragged = false
            val longPress = Runnable { if (!dragged) { v.isPressed = false; v.performLongClick() } }
            override fun onTouch(view: View, event: MotionEvent): Boolean {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        downX = event.rawX; downY = event.rawY; startX = p.x; startY = p.y; dragged = false
                        v.isPressed = true; v.postDelayed(longPress, android.view.ViewConfiguration.getLongPressTimeout().toLong())
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx = event.rawX - downX; val dy = event.rawY - downY
                        if (abs(dx) > dp(8) || abs(dy) > dp(8)) { dragged = true; v.removeCallbacks(longPress) }
                        if (dragged) {
                            showDropTarget()
                            p.x = (startX + dx.toInt()).coerceIn(0, maxX); p.y = (startY + dy.toInt()).coerceIn(0, maxY)
                            try { manager.updateViewLayout(v, p) } catch (_: Exception) {}
                            updateDropTarget(p)
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        v.removeCallbacks(longPress)
                        val remove = dragged && isOverDropTarget(p)
                        hideDropTarget()
                        if (remove) {
                            v.isPressed = false
                            hide()
                            return true
                        }
                        if (dragged) placement.edit()
                            .putFloat("bubble_x_ratio", if (maxX == 0) 0f else p.x.toFloat() / maxX)
                            .putFloat("bubble_y_ratio", if (maxY == 0) 0f else p.y.toFloat() / maxY).apply()
                        else if (v.isPressed && bubble != null) v.performClick()
                        v.isPressed = false; return true
                    }
                    MotionEvent.ACTION_CANCEL -> { hideDropTarget(); v.removeCallbacks(longPress); v.isPressed = false; return true }
                }
                return false
            }
        })
        return true
    }
    fun openPanel() {
        if (!show() || panel != null) return
        val m = app.resources.displayMetrics
        val defaultWidth = min(dp(240), (m.widthPixels * .62f).toInt()).coerceAtLeast(1)
        val defaultHeight = min(dp(280), (m.heightPixels * .32f).toInt()).coerceAtLeast(1)
        val density = m.density
        val width = (placement.getFloat("panel_width_dp", defaultWidth / density) * density).roundToInt()
        val height = (placement.getFloat("panel_height_dp", defaultHeight / density) * density).roundToInt()
        val p = params(width, height, 0, 0)
        clampPanel(p)
        p.x = (placement.getFloat("panel_x_ratio", 1f).coerceIn(0f, 1f) * (m.widthPixels - p.width - dp(10)).coerceAtLeast(0)).roundToInt() + dp(5)
        p.y = if (placement.contains("panel_y_ratio"))
            (placement.getFloat("panel_y_ratio", 0f).coerceIn(0f, 1f) * (m.heightPixels - p.height - dp(10)).coerceAtLeast(0)).roundToInt() + dp(5)
            else dp(58)
        clampPanel(p)
        val root = LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(6), dp(4), dp(6), dp(4))
            background = background(Color.rgb(24, 31, 41))
        }
        val header = LinearLayout(app).apply { orientation = LinearLayout.HORIZONTAL }
        val moveHandle = label("厳選リスト ↔").apply {
            tag = "overlay_move_handle"
            contentDescription = "ドラッグして一覧を移動"
            setOnClickListener { toast("上部をドラッグして移動できます") }
        }
        header.addView(moveHandle, LinearLayout.LayoutParams(0, dp(34), 1f))
        header.addView(button("×") { closePanel() }, LinearLayout.LayoutParams(dp(48), dp(34)))
        root.addView(header)
        summary = label("").also { root.addView(it, LinearLayout.LayoutParams(-1, dp(25))) }
        val l = ListView(app).apply { dividerHeight = dp(1); cacheColorHint = Color.TRANSPARENT }
        list = l; adapter = QueueAdapter(); l.adapter = adapter
        root.addView(l, LinearLayout.LayoutParams(-1, 0, 1f))
        val footer = LinearLayout(app).apply { orientation = LinearLayout.HORIZONTAL }
        val resizeHandle = label("↙", 20f).apply {
            tag = "overlay_resize_handle"
            gravity = Gravity.CENTER
            contentDescription = "ドラッグしてサイズ変更。左へ広げる、下へ伸ばす"
            setOnClickListener { toast("左下のつまみをドラッグしてサイズ変更できます") }
        }
        footer.addView(resizeHandle, LinearLayout.LayoutParams(dp(36), dp(30)))
        footer.addView(label("長押し: 再コピー", 10f), LinearLayout.LayoutParams(0, dp(30), 1f))
        root.addView(footer)
        attachPanelGesture(moveHandle, root, p, resize = false)
        attachPanelGesture(resizeHandle, root, p, resize = true)
        try {
            // Hide the bubble before adding the panel (Android touch opacity limit).
            bubble?.visibility = View.GONE
            manager.addView(root, p); panel = root; panelParams = p; refresh(); restoreListScroll()
        } catch (e: Exception) { bubble?.visibility = View.VISIBLE; toast("一覧を表示できません: ${e.localizedMessage}") }
    }
    private fun clampPanel(p: WindowManager.LayoutParams) {
        val m = app.resources.displayMetrics
        val margin = min(dp(5), min(m.widthPixels, m.heightPixels) / 4)
        val maxWidth = (m.widthPixels - margin * 2).coerceAtLeast(1)
        val maxHeight = min((m.heightPixels - margin * 2).coerceAtLeast(1), min(dp(640), (m.heightPixels * .8f).toInt()).coerceAtLeast(1))
        p.width = p.width.coerceIn(min(dp(196), maxWidth), maxWidth)
        p.height = p.height.coerceIn(min(dp(180), maxHeight), maxHeight)
        p.x = p.x.coerceIn(margin, (m.widthPixels - p.width - margin).coerceAtLeast(margin))
        p.y = p.y.coerceIn(margin, (m.heightPixels - p.height - margin).coerceAtLeast(margin))
    }
    private fun savePanel(p: WindowManager.LayoutParams) {
        val m = app.resources.displayMetrics
        val maxX = (m.widthPixels - p.width - dp(10)).coerceAtLeast(0)
        val maxY = (m.heightPixels - p.height - dp(10)).coerceAtLeast(0)
        placement.edit()
            .putFloat("panel_width_dp", p.width / m.density)
            .putFloat("panel_height_dp", p.height / m.density)
            .putFloat("panel_x_ratio", if (maxX == 0) 0f else ((p.x - dp(5)).toFloat() / maxX).coerceIn(0f, 1f))
            .putFloat("panel_y_ratio", if (maxY == 0) 0f else ((p.y - dp(5)).toFloat() / maxY).coerceIn(0f, 1f))
            .apply()
    }
    private fun attachPanelGesture(handle: View, root: View, p: WindowManager.LayoutParams, resize: Boolean) {
        handle.setOnTouchListener(object : View.OnTouchListener {
            var downX = 0f; var downY = 0f
            var startX = 0; var startY = 0; var startWidth = 0; var startHeight = 0
            var dragged = false
            override fun onTouch(v: View, event: MotionEvent): Boolean {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        downX = event.rawX; downY = event.rawY
                        startX = p.x; startY = p.y; startWidth = p.width; startHeight = p.height
                        dragged = false; return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val dx = event.rawX - downX; val dy = event.rawY - downY
                        if (abs(dx) > dp(5) || abs(dy) > dp(5)) dragged = true
                        if (dragged) {
                            // Bottom-left resizing grows toward the free area to the left
                            // when the panel starts against the right edge.
                            p.x = startX + dx.toInt()
                            p.y = if (resize) startY else startY + dy.toInt()
                            if (resize) {
                                p.width = startWidth - dx.toInt()
                                p.height = startHeight + dy.toInt()
                                clampPanel(p)
                                p.x = startX + startWidth - p.width
                                p.y = startY
                            }
                            clampPanel(p)
                            try { manager.updateViewLayout(root, p) } catch (_: Exception) {}
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        if (dragged) savePanel(p)
                        else if (event.actionMasked == MotionEvent.ACTION_UP) v.performClick()
                        return true
                    }
                }
                return false
            }
        })
    }
    fun closePanel() {
        saveListScroll()
        panel?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        panel = null; panelParams = null; list = null; summary = null; adapter = null; rows = emptyList()
        bubble?.visibility = View.VISIBLE
    }
    fun togglePanel() { if (panel == null) openPanel() else closePanel() }
    /** Stop both windows; leave SQLite history and the independent OCR service intact. */
    fun hide() {
        hideDropTarget()
        closePanel()
        bubble?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        bubble = null
    }
    fun destroy() { hide(); store.close(); instance = null }
    fun onImported() { if (panel != null) refresh() else show() }
    private fun refresh() {
        val position = list?.firstVisiblePosition ?: 0
        val top = list?.getChildAt(0)?.top ?: 0
        // Completed rows stay in place and remain available for repeated copying.
        rows = store.items(filter = OverlayQueueStore.Filter.ALL)
        val p = store.progress()
        summary?.text = "${p.total}件  検索✓${p.searchDone}  名前✓${p.nicknameDone}"
        adapter?.notifyDataSetChanged()
        if (rows.isNotEmpty()) list?.setSelectionFromTop(position.coerceAtMost(rows.lastIndex), top)
    }
    private fun toggleCopy(item: OverlayQueueStore.Item, search: Boolean) {
        // Resolve current state rather than a recycled row's captured snapshot.
        // Two quick taps must work even before ListView redraws the first check.
        val current = rows.firstOrNull { it.id == item.id } ?: return
        if (if (search) current.searchCopied else current.nicknameCopied) {
            try { store.setCopied(current.id, search, false); refresh() }
            catch (e: Exception) { toast("チェックを外せません: ${e.localizedMessage}") }
        } else copy(current, search)
    }
    private fun copy(item: OverlayQueueStore.Item, search: Boolean) {
        if (rows.none { it.id == item.id }) return
        try {
            (app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(
                ClipData.newPlainText(if (search) "検索式" else "ニックネーム", if (search) item.search else item.nickname))
        } catch (e: Exception) { toast("コピーできません: ${e.localizedMessage}"); return }
        try { store.setCopied(item.id, search, true); refresh() }
        catch (e: Exception) { toast("コピーしましたが記録できません: ${e.localizedMessage}") }
    }
    private data class Holder(val title: TextView, val search: Button, val nick: Button)
    private inner class QueueAdapter : BaseAdapter() {
        override fun getCount() = rows.size
        override fun getItem(position: Int) = rows[position]
        override fun getItemId(position: Int) = rows[position].id
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val root = convertView as? LinearLayout ?: LinearLayout(app).apply {
                orientation = LinearLayout.VERTICAL; setPadding(0, dp(2), 0, dp(5))
                val title = label("", 13f); addView(title, LinearLayout.LayoutParams(-1, dp(30)))
                val buttons = LinearLayout(app).apply { orientation = LinearLayout.HORIZONTAL }
                val a = button("検索式") {}; val b = button("名前") {}
                buttons.addView(a, LinearLayout.LayoutParams(0, dp(40), 1f).apply { marginEnd = dp(3) })
                buttons.addView(b, LinearLayout.LayoutParams(0, dp(40), 1f)); addView(buttons)
                tag = Holder(title, a, b)
            }
            val h = root.tag as Holder; val item = rows[position]
            val cp = Regex("(?:^|&)cp([0-9]+)(?:&|$)", RegexOption.IGNORE_CASE).find(item.search)?.groupValues?.get(1)
            h.title.text = "${item.ivs ?: OverlayPairParser.legacyIvLabel(item.search)}${cp?.let { "  CP$it" } ?: ""}"
            h.title.contentDescription = "${item.speciesLabel} ${h.title.text}"
            for ((b, isSearch) in listOf(h.search to true, h.nick to false)) {
                val done = if (isSearch) item.searchCopied else item.nicknameCopied
                b.text = (if (done) "✓ " else "") + if (isSearch) "検索式" else "名前"
                b.background = background(if (done) Color.rgb(24, 103, 68) else Color.rgb(55, 76, 99))
                b.contentDescription = if (done) "${b.text}。タップでチェック解除、長押しで再コピー"
                    else "${b.text}をコピー"
                b.setOnClickListener { toggleCopy(item, isSearch) }
                b.setOnLongClickListener { copy(item, isSearch); true }
            }
            return root
        }
    }
}
