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

/** Only the bounded panel receives touches. Outside taps collapse it and reach GO. */
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
    private var panel: LinearLayout? = null
    private var list: ListView? = null
    private var summary: TextView? = null
    private var adapter: QueueAdapter? = null
    private var rows: List<OverlayQueueStore.Item> = emptyList()
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
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
        PixelFormat.TRANSLUCENT
    ).apply {
        gravity = Gravity.TOP or Gravity.START; this.x = x; this.y = y
        // Android 12+ allows touches through an untrusted overlay at <=0.8 opacity.
        // Only one of bubble/panel is visible, so their opacity never accumulates.
        alpha = .8f
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
                            p.x = (startX + dx.toInt()).coerceIn(0, maxX); p.y = (startY + dy.toInt()).coerceIn(0, maxY)
                            try { manager.updateViewLayout(v, p) } catch (_: Exception) {}
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        v.removeCallbacks(longPress)
                        if (dragged) placement.edit()
                            .putFloat("bubble_x_ratio", if (maxX == 0) 0f else p.x.toFloat() / maxX)
                            .putFloat("bubble_y_ratio", if (maxY == 0) 0f else p.y.toFloat() / maxY).apply()
                        else if (v.isPressed && bubble != null) v.performClick()
                        v.isPressed = false; return true
                    }
                    MotionEvent.ACTION_CANCEL -> { v.removeCallbacks(longPress); v.isPressed = false; return true }
                }
                return false
            }
        })
        return true
    }
    fun openPanel() {
        if (!show() || panel != null) return
        val m = app.resources.displayMetrics
        val width = min(dp(240), (m.widthPixels * .62f).toInt()).coerceAtLeast(1)
        val height = min(dp(280), (m.heightPixels * .32f).toInt()).coerceAtLeast(1)
        val root = LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(6), dp(4), dp(6), dp(4))
            background = background(Color.rgb(24, 31, 41))
            setOnTouchListener { _, event ->
                if (event.actionMasked == MotionEvent.ACTION_OUTSIDE) { closePanel(); false } else false
            }
        }
        val header = LinearLayout(app).apply { orientation = LinearLayout.HORIZONTAL }
        header.addView(label("厳選リスト"), LinearLayout.LayoutParams(0, dp(34), 1f))
        header.addView(button("終了") { hide() }, LinearLayout.LayoutParams(dp(48), dp(34)))
        root.addView(header)
        summary = label("").also { root.addView(it, LinearLayout.LayoutParams(-1, dp(25))) }
        val l = ListView(app).apply { dividerHeight = dp(1); cacheColorHint = Color.TRANSPARENT }
        list = l; adapter = QueueAdapter(); l.adapter = adapter
        root.addView(l, LinearLayout.LayoutParams(-1, 0, 1f))
        val p = params(width, height, (m.widthPixels - width - dp(5)).coerceAtLeast(0), dp(58))
        try {
            // Hide the bubble before adding the panel (Android touch opacity limit).
            bubble?.visibility = View.GONE
            manager.addView(root, p); panel = root; refresh()
        } catch (e: Exception) { bubble?.visibility = View.VISIBLE; toast("一覧を表示できません: ${e.localizedMessage}") }
    }
    fun closePanel() {
        panel?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        panel = null; list = null; summary = null; adapter = null; rows = emptyList()
        bubble?.visibility = View.VISIBLE
    }
    fun togglePanel() { if (panel == null) openPanel() else closePanel() }
    /** Stop both windows; leave SQLite history and the independent OCR service intact. */
    fun hide() {
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
    private fun copy(item: OverlayQueueStore.Item, search: Boolean) {
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
                b.setOnClickListener { copy(item, isSearch) }
                b.setOnLongClickListener { store.setCopied(item.id, isSearch, false); refresh(); true }
            }
            return root
        }
    }
}
