package com.example.pokemonivreader.overlayqueue

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import android.text.TextWatcher
import android.text.Editable
import java.text.DateFormat
import java.util.Date
import kotlin.math.abs
import kotlin.math.min

/** A single, compact, native-Android overlay. Its list is virtualized by ListView.
 * Safe to call from the existing application's Activity or OCR foreground Service.
 * No MediaProjection restart is needed for copying.
 */
class OverlayCopyQueueController private constructor(private val app: Context) {
    companion object {
        @Volatile private var instance: OverlayCopyQueueController? = null
        fun get(context: Context): OverlayCopyQueueController = instance
            ?: synchronized(this) { instance ?: OverlayCopyQueueController(context.applicationContext).also { instance = it } }
    }

    private val store = OverlayQueueStore(app)
    // Position is independent from the OCR button. Keep a normalized location across rotations.
    private val placement = app.getSharedPreferences("overlay_queue_placement", Context.MODE_PRIVATE)
    private val manager = app.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val white = Color.WHITE
    private val muted = Color.rgb(199, 205, 215)
    private val green = Color.rgb(103, 210, 148)
    private var bubble: TextView? = null
    private var bubbleParams: WindowManager.LayoutParams? = null
    private var panel: LinearLayout? = null
    private var list: ListView? = null
    private var title: TextView? = null
    private var summary: TextView? = null
    private var filterButton: Button? = null
    private var historyButton: Button? = null
    private var searchInput: EditText? = null
    private var adapter: QueueAdapter? = null
    private var rows: List<OverlayQueueStore.Item> = emptyList()
    private var sessions: List<OverlayQueueStore.Session> = emptyList()
    private var filter = OverlayQueueStore.Filter.PENDING
    private var searchTerm = ""
    private var showHistory = false
    private var resetConfirmationDeadline = 0L

    private fun dp(value: Int): Int = (value * app.resources.displayMetrics.density + 0.5f).toInt()
    private fun toast(text: String) = Toast.makeText(app, text, Toast.LENGTH_SHORT).show()

    private fun background(color: Int, radius: Int = 12): GradientDrawable = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(radius).toFloat()
    }
    private fun text(value: String, size: Float = 14f, color: Int = white): TextView = TextView(app).apply {
        setText(value)
        textSize = size
        setTextColor(color)
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(4), dp(3), dp(4), dp(3))
    }
    private fun button(value: String, onClick: (() -> Unit)? = null): Button = Button(app).apply {
        text = value
        textSize = 12f
        isAllCaps = false
        setTextColor(white)
        background = background(Color.rgb(65, 78, 100), 9)
        minHeight = dp(41)
        minimumHeight = dp(41)
        setPadding(dp(5), dp(5), dp(5), dp(5))
        if (onClick != null) setOnClickListener { onClick() }
    }
    private fun horizontal(): LinearLayout = LinearLayout(app).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }
    private fun weighted(): LinearLayout.LayoutParams = LinearLayout.LayoutParams(0, dp(43), 1f).apply {
        marginStart = dp(2)
        marginEnd = dp(2)
    }
    private fun overlayParams(width: Int, height: Int, gravity: Int, x: Int, y: Int) =
        WindowManager.LayoutParams(
            width, height,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else WindowManager.LayoutParams.TYPE_PHONE,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            this.gravity = gravity
            this.x = x
            this.y = y
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }

    /** Returns false if Android's overlay permission was not granted. */
    fun show(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(app)) return false
        if (bubble != null) return true
        val label = text("☷\n厳選", 12f).apply {
            gravity = Gravity.CENTER
            background = background(Color.rgb(45, 98, 139), 14)
            elevation = dp(6).toFloat()
        }
        // OCR's existing IV bubble starts on the LEFT (x=12dp, y=185dp).
        // Start the selection bubble on the RIGHT and restore any user-dragged position.
        val screenWidth = app.resources.displayMetrics.widthPixels
        val screenHeight = app.resources.displayMetrics.heightPixels
        val maxX = (screenWidth - dp(56)).coerceAtLeast(0)
        val maxY = (screenHeight - dp(55)).coerceAtLeast(0)
        val savedX = placement.getFloat("bubble_x_ratio", 1f).coerceIn(0f, 1f)
        val savedY = placement.getFloat("bubble_y_ratio", -1f)
        val x = (savedX * maxX).toInt().coerceIn(0, maxX)
        val y = if (savedY < 0f) dp(150).coerceAtMost(maxY)
                else (savedY.coerceIn(0f, 1f) * maxY).toInt().coerceIn(0, maxY)
        val params = overlayParams(dp(56), dp(55), Gravity.TOP or Gravity.START, x, y).apply {
            // The floating icon never needs the keyboard or input focus; Pokémon GO keeps focus.
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        }
        try {
            manager.addView(label, params)
        } catch (e: Exception) {
            toast("オーバーレイを表示できません: ${e.localizedMessage}")
            return false
        }
        bubble = label
        bubbleParams = params
        // Drag the bubble without triggering a click. A short tap toggles the list.
        label.setOnTouchListener(object : View.OnTouchListener {
            var downX = 0f; var downY = 0f
            var startX = 0; var startY = 0
            var dragged = false
            override fun onTouch(v: View, event: MotionEvent): Boolean {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        downX = event.rawX; downY = event.rawY
                        startX = params.x; startY = params.y
                        dragged = false
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val deltaX = event.rawX - downX; val deltaY = event.rawY - downY
                        if (abs(deltaX) > dp(8) || abs(deltaY) > dp(8)) dragged = true
                        if (dragged) {
                            params.x = (startX + deltaX.toInt()).coerceIn(0, maxX)
                            params.y = (startY + deltaY.toInt()).coerceIn(0, maxY)
                            try { manager.updateViewLayout(label, params) } catch (_: Exception) {}
                        }
                        return true
                    }
                    MotionEvent.ACTION_UP -> {
                        if (dragged) {
                            placement.edit()
                                .putFloat("bubble_x_ratio", if (maxX == 0) 0f else params.x.toFloat() / maxX)
                                .putFloat("bubble_y_ratio", if (maxY == 0) 0f else params.y.toFloat() / maxY)
                                .apply()
                        } else togglePanel()
                        return true
                    }
                    else -> return true
                }
            }
        })
        return true
    }

    fun openPanel() {
        if (!show() || panel != null) return
        val metrics = app.resources.displayMetrics
        val screenWidth = metrics.widthPixels
        val screenHeight = metrics.heightPixels
        // Leave a tappable lane on the LEFT for the OCR IV bubble while this panel is open.
        // The queue stays on the RIGHT; collapse it with × before taking a screenshot.
        val width = min(dp(380), (screenWidth - dp(76)).coerceAtLeast(dp(205)))
            .coerceAtMost((screenWidth - dp(14)).coerceAtLeast(1))
        val root = LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(8), dp(9), dp(8), dp(9))
            background = background(Color.rgb(30, 35, 44), 14)
            elevation = dp(8).toFloat()
        }
        val header = horizontal()
        title = text("厳選コピーリスト", 16f).apply { setTypeface(null, 1) }
        header.addView(title, LinearLayout.LayoutParams(0, dp(41), 1f))
        header.addView(button("×") { closePanel() }, LinearLayout.LayoutParams(dp(42), dp(41)))
        root.addView(header)
        summary = text("", 12f, muted)
        root.addView(summary)

        val tools = horizontal()
        tools.addView(button("取込") { launchImport() }, weighted())
        historyButton = button("履歴") {
            showHistory = !showHistory
            hideKeyboard()
            refresh(true)
        }
        tools.addView(historyButton, weighted())
        tools.addView(button("次の未完了") { nextIncomplete() }, LinearLayout.LayoutParams(0, dp(43), 1.5f))
        root.addView(tools)

        val filterRow = horizontal()
        filterButton = button("") { cycleFilter() }
        filterRow.addView(filterButton, LinearLayout.LayoutParams(0, dp(43), 1f))
        searchInput = EditText(app).apply {
            hint = "種名・検索式・名前で絞込"
            textSize = 12f
            setSingleLine(true)
            setTextColor(Color.WHITE)
            setHintTextColor(muted)
            background = background(Color.rgb(52, 61, 74), 7)
            setPadding(dp(7), dp(2), dp(7), dp(2))
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    searchTerm = s?.toString().orEmpty()
                    refresh(true)
                }
                override fun afterTextChanged(s: Editable?) {}
            })
        }
        filterRow.addView(searchInput, LinearLayout.LayoutParams(0, dp(40), 1.7f).apply { marginStart = dp(5) })
        root.addView(filterRow)

        val l = ListView(app).apply {
            cacheColorHint = Color.TRANSPARENT
            dividerHeight = dp(1)
            setBackgroundColor(Color.TRANSPARENT)
            isVerticalScrollBarEnabled = true
        }
        list = l
        adapter = QueueAdapter()
        l.adapter = adapter
        // Reserve enough of the Pokémon GO playfield by limiting the overlay's height.
        val availableListHeight = min(dp(410), (screenHeight * .45f).toInt())
        root.addView(l, LinearLayout.LayoutParams(-1, availableListHeight))
        val foot = horizontal()
        foot.addView(text("長押し: チェック解除", 11f, muted), LinearLayout.LayoutParams(0, dp(36), 1f))
        foot.addView(button("進捗リセット") { confirmReset() }, LinearLayout.LayoutParams(dp(105), dp(36)))
        root.addView(foot)

        val params = overlayParams(width, WindowManager.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.END, dp(7), dp(58))
        try {
            manager.addView(root, params)
            panel = root
            refresh(true)
        } catch (e: Exception) {
            toast("一覧を表示できません: ${e.localizedMessage}")
        }
    }

    fun closePanel() {
        hideKeyboard()
        panel?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        panel = null
        list = null
        title = null
        summary = null
        filterButton = null
        searchInput = null
        historyButton = null
        adapter = null
    }
    fun togglePanel() = if (panel != null) closePanel() else openPanel()
    fun destroy() {
        closePanel()
        bubble?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        bubble = null
        bubbleParams = null
        store.close()
        instance = null
    }
    private fun hideKeyboard() {
        searchInput?.let { field ->
            val imm = app.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
            imm.hideSoftInputFromWindow(field.windowToken, 0)
            field.clearFocus()
        }
    }
    private fun launchImport() {
        try {
            val intent = Intent(app, OverlayCopyQueueImportActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            app.startActivity(intent)
        } catch (e: Exception) { toast("取り込み画面を開けません: ${e.localizedMessage}") }
    }

    /** Call this from the import Activity after the database commit succeeds. */
    fun onImported() {
        showHistory = false
        filter = OverlayQueueStore.Filter.PENDING
        searchTerm = ""
        searchInput?.setText("")
        if (show()) {
            if (panel == null) openPanel() else refresh(true)
        }
    }

    private fun cycleFilter() {
        val variants = OverlayQueueStore.Filter.values()
        filter = variants[(variants.indexOf(filter) + 1) % variants.size]
        refresh(true)
    }
    private fun filterLabel(): String = when (filter) {
        OverlayQueueStore.Filter.PENDING -> "未完了 ▼"
        OverlayQueueStore.Filter.ALL -> "すべて ▼"
        OverlayQueueStore.Filter.COMPLETE -> "コピー済 ▼"
        OverlayQueueStore.Filter.SEARCH_PENDING -> "検索未コピー ▼"
        OverlayQueueStore.Filter.NICK_PENDING -> "名前未コピー ▼"
    }

    private fun refresh(resetScroll: Boolean = false) {
        val oldPosition = if (resetScroll) 0 else (list?.firstVisiblePosition ?: 0)
        val oldTop = if (resetScroll) 0 else (list?.getChildAt(0)?.top ?: 0)
        sessions = store.sessions()
        val id = store.currentSessionId
        val p = store.progress(id)
        rows = if (showHistory) emptyList() else store.items(id, filter, searchTerm)
        title?.text = if (showHistory) "履歴 (${sessions.size})" else "厳選コピーリスト"
        summary?.text = if (showHistory) "過去の取り込みを選択できます" else
            "全${p.total}件  検索✓${p.searchDone}  名前✓${p.nicknameDone}  両方✓${p.complete}"
        historyButton?.text = if (showHistory) "一覧" else "履歴"
        filterButton?.text = filterLabel()
        filterButton?.visibility = if (showHistory) View.GONE else View.VISIBLE
        searchInput?.visibility = if (showHistory) View.GONE else View.VISIBLE
        adapter?.notifyDataSetChanged()
        val size = if (showHistory) sessions.size else rows.size
        if (size > 0) list?.setSelectionFromTop(oldPosition.coerceAtMost(size - 1), oldTop)
    }

    private fun nextIncomplete() {
        val target = store.items(store.currentSessionId, OverlayQueueStore.Filter.PENDING)
        if (target.isEmpty()) { toast("すべてコピー済みです"); return }
        if (showHistory || filter == OverlayQueueStore.Filter.COMPLETE) {
            showHistory = false; filter = OverlayQueueStore.Filter.PENDING; searchTerm = ""
            searchInput?.setText("")
        }
        refresh()
        val lastVisible = rows.getOrNull(list?.lastVisiblePosition ?: 0)?.sequence ?: 0
        val next = target.firstOrNull { it.sequence > lastVisible } ?: target.first()
        var position = rows.indexOfFirst { it.id == next.id }
        if (position < 0) {
            filter = OverlayQueueStore.Filter.PENDING
            searchInput?.setText(""); searchTerm = ""
            refresh(true)
            position = rows.indexOfFirst { it.id == next.id }
        }
        if (position >= 0) list?.setSelection(position)
    }

    private fun confirmReset() {
        if (store.currentSessionId < 0) { toast("取り込みデータがありません"); return }
        val now = SystemClock.elapsedRealtime()
        if (now > resetConfirmationDeadline) {
            resetConfirmationDeadline = now + 8000L
            toast("このセッションのチェックを消すには8秒以内にもう一度押してください")
            return
        }
        resetConfirmationDeadline = 0L
        store.resetProgress()
        refresh(true)
        toast("チェックのみ初期化しました。コピー回数は保持されます。")
    }

    private fun copy(item: OverlayQueueStore.Item, isSearch: Boolean) {
        val value = if (isSearch) item.search else item.nickname
        try {
            val clipboard = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText(if (isSearch) "検索式" else "ニックネーム", value))
        } catch (e: Exception) {
            toast("コピーに失敗しました: ${e.localizedMessage}")
            return
        }
        try {
            store.setCopied(item.id, isSearch, true)
            refresh()
            toast(if (isSearch) "検索式をコピーしました" else "ニックネームをコピーしました")
        } catch (e: Exception) {
            toast("コピーしましたが履歴の保存に失敗しました: ${e.localizedMessage}")
        }
    }
    private fun uncheck(item: OverlayQueueStore.Item, isSearch: Boolean): Boolean {
        try {
            store.setCopied(item.id, isSearch, false)
            refresh()
            toast("チェックを解除しました（コピー回数は残ります）")
        } catch (e: Exception) { toast("解除に失敗しました: ${e.localizedMessage}") }
        return true
    }

    private data class ItemViewHolder(val header: TextView, val searchButton: Button, val nickButton: Button)
    private data class SessionViewHolder(val header: TextView, val open: Button)
    private inner class QueueAdapter : BaseAdapter() {
        override fun getCount(): Int = if (showHistory) sessions.size else rows.size
        override fun getItem(position: Int): Any = if (showHistory) sessions[position] else rows[position]
        override fun getItemId(position: Int): Long = when (val it = getItem(position)) {
            is OverlayQueueStore.Item -> it.id
            is OverlayQueueStore.Session -> it.id
            else -> position.toLong()
        }
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            if (showHistory) return sessionRow(position, convertView)
            return itemRow(position, convertView)
        }
        private fun itemRow(position: Int, recycled: View?): View {
            val container: LinearLayout
            val holder: ItemViewHolder
            if (recycled is LinearLayout && recycled.tag is ItemViewHolder) {
                container = recycled
                holder = recycled.tag as ItemViewHolder
            } else {
                container = LinearLayout(app).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(dp(4), dp(4), dp(4), dp(4))
                }
                val header = text("", 12f)
                container.addView(header, LinearLayout.LayoutParams(-1, dp(27)))
                val buttons = horizontal()
                val a = button("検索式")
                val b = button("名前")
                buttons.addView(a, weighted())
                buttons.addView(b, weighted())
                container.addView(buttons)
                holder = ItemViewHolder(header, a, b)
                container.tag = holder
            }
            val item = rows[position]
            holder.header.text = "${item.sequence}. ${item.speciesLabel}  ${item.nickname.take(26)}"
            holder.searchButton.text = if (item.searchCopied) "✓ 検索式" else "検索式"
            holder.nickButton.text = if (item.nicknameCopied) "✓ 名前" else "名前"
            holder.searchButton.background = background(if (item.searchCopied) Color.rgb(28, 112, 79) else Color.rgb(65, 78, 100), 9)
            holder.nickButton.background = background(if (item.nicknameCopied) Color.rgb(28, 112, 79) else Color.rgb(65, 78, 100), 9)
            holder.searchButton.setOnClickListener { copy(item, true) }
            holder.nickButton.setOnClickListener { copy(item, false) }
            holder.searchButton.setOnLongClickListener { uncheck(item, true) }
            holder.nickButton.setOnLongClickListener { uncheck(item, false) }
            return container
        }
        private fun sessionRow(position: Int, recycled: View?): View {
            val container: LinearLayout
            val holder: SessionViewHolder
            if (recycled is LinearLayout && recycled.tag is SessionViewHolder) {
                container = recycled; holder = recycled.tag as SessionViewHolder
            } else {
                container = horizontal().apply { setPadding(dp(4), dp(5), dp(4), dp(5)) }
                val label = text("", 12f)
                container.addView(label, LinearLayout.LayoutParams(0, dp(51), 1f))
                val open = button("開く")
                container.addView(open, LinearLayout.LayoutParams(dp(62), dp(43)))
                holder = SessionViewHolder(label, open)
                container.tag = holder
            }
            val session = sessions[position]
            val whenCreated = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
                .format(Date(session.createdAt))
            holder.header.text = "$whenCreated / ${session.count}件"
            holder.open.setOnClickListener {
                store.currentSessionId = session.id
                showHistory = false
                filter = OverlayQueueStore.Filter.PENDING
                refresh(true)
            }
            return container
        }
    }
}
