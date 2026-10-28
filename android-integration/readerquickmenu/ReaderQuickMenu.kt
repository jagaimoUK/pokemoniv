package com.example.pokemonivreader.readerquickmenu

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Compact view installed INSIDE the existing IV-reader overlay toolbar.
 * No independent SYSTEM_ALERT_WINDOW and no changes to MediaProjection/OCR.
 *
 * IMPORTANT: readMode/writeMode must point at the reader's EXISTING setting.
 * Never create a second mode preference with a potentially different meaning.
 * Call collapse() just before a screenshot is captured and when the host closes.
 */
class ReaderQuickMenu(
    private val context: Context,
    private val readMode: () -> Mode,
    private val writeMode: (Mode) -> Boolean,
    private val notice: (String) -> Unit,
    private val cleanup: ReaderCleanupStore = ReaderCleanupStore(context)
) {
    enum class Mode { SELECTION, ALL }

    private var panel: LinearLayout? = null
    private var selectionButton: Button? = null
    private var allButton: Button? = null
    private var copyButton: Button? = null
    private var indexLabel: TextView? = null
    private var prev: Button? = null
    private var next: Button? = null
    private var queries: List<String> = emptyList()
    private var currentIndex = 0

    private fun dp(n: Int) = (context.resources.displayMetrics.density * n + .5f).toInt()

    private fun background(color: Int): GradientDrawable =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(16).toFloat()
        }

    private fun button(label: String): Button = Button(context).apply {
        text = label
        isAllCaps = false
        minHeight = dp(44)
        textSize = 13f
        setTextColor(Color.rgb(230, 240, 233))
        background = background(Color.rgb(68, 90, 81))
    }

    /** Add this beside the existing IV button, not in a full-screen overlay. */
    fun attachTo(toolbar: LinearLayout): View {
        check(panel == null) { "メニューは二重に追加できません" }
        val wrapper = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.END
        }
        val trigger = TextView(context).apply {
            text = "⋯"
            textSize = 24f
            gravity = Gravity.CENTER
            contentDescription = "メニューを開く・閉じる"
            minWidth = dp(44)
            minHeight = dp(44)
            background = background(Color.rgb(67, 86, 78))
            setTextColor(Color.rgb(235, 242, 236))
            setOnClickListener {
                if (panel?.visibility == View.VISIBLE) collapse() else expand()
            }
        }
        wrapper.addView(trigger, LinearLayout.LayoutParams(dp(44), dp(44)))
        val body = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(9), dp(9), dp(9), dp(9))
            background = background(Color.rgb(38, 53, 47))
            visibility = View.GONE
        }
        panel = body
        val modes = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        selectionButton = button("厳選").also { b ->
            b.setOnClickListener { changeMode(Mode.SELECTION) }
            modes.addView(b, LinearLayout.LayoutParams(0, dp(44), 1f))
        }
        allButton = button("全体").also { b ->
            b.setOnClickListener { changeMode(Mode.ALL) }
            modes.addView(b, LinearLayout.LayoutParams(0, dp(44), 1f).apply { marginStart = dp(5) })
        }
        body.addView(modes)
        copyButton = button("非厳選個体をコピー").also { b ->
            b.setOnClickListener { copyCurrent() }
            body.addView(b, LinearLayout.LayoutParams(-1, dp(44)).apply { topMargin = dp(8) })
        }
        val navigation = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        prev = button("‹").also { b ->
            b.contentDescription = "前の検索式"
            b.setOnClickListener { currentIndex = (currentIndex - 1).coerceAtLeast(0); refresh() }
            navigation.addView(b, LinearLayout.LayoutParams(dp(44), dp(44)))
        }
        indexLabel = TextView(context).apply {
            gravity = Gravity.CENTER
            textSize = 12f
            setTextColor(Color.rgb(230, 240, 233))
        }.also { navigation.addView(it, LinearLayout.LayoutParams(0, dp(44), 1f)) }
        next = button("›").also { b ->
            b.contentDescription = "次の検索式"
            b.setOnClickListener { currentIndex = (currentIndex + 1).coerceAtMost(queries.lastIndex); refresh() }
            navigation.addView(b, LinearLayout.LayoutParams(dp(44), dp(44)))
        }
        body.addView(navigation)
        wrapper.addView(body, LinearLayout.LayoutParams(dp(224), ViewGroup.LayoutParams.WRAP_CONTENT))
        toolbar.addView(wrapper)
        return wrapper
    }

    private fun expand() {
        queries = cleanup.queries()
        currentIndex = currentIndex.coerceIn(0, (queries.size - 1).coerceAtLeast(0))
        refresh()
        panel?.visibility = View.VISIBLE
    }

    private fun changeMode(mode: Mode) {
        if (!writeMode(mode)) {
            notice("モードを切り替えられませんでした")
            return
        }
        if (readMode() != mode) {
            notice("設定の反映を確認できませんでした")
            return
        }
        collapse()
    }

    private fun refresh() {
        selectionButton?.background = background(Color.rgb(if (readMode() == Mode.SELECTION) 79 else 62, if (readMode() == Mode.SELECTION) 121 else 86, 91))
        allButton?.background = background(Color.rgb(if (readMode() == Mode.ALL) 79 else 62, if (readMode() == Mode.ALL) 121 else 86, 91))
        copyButton?.isEnabled = queries.isNotEmpty()
        indexLabel?.text = if (queries.isEmpty()) "0件" else (currentIndex + 1).toString() + " / " + queries.size
        val multiple = queries.size > 1
        prev?.visibility = if (multiple) View.VISIBLE else View.GONE
        next?.visibility = if (multiple) View.VISIBLE else View.GONE
        prev?.isEnabled = currentIndex > 0
        next?.isEnabled = currentIndex < queries.size - 1
    }

    private fun copyCurrent() {
        val value = queries.getOrNull(currentIndex) ?: return
        try {
            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("非厳選個体の検索式", value))
            collapse()
            notice("検索式をコピーしました。ゲーム内で対象を確認してください")
        } catch (_: Exception) {
            notice("コピーに失敗しました")
        }
    }

    /** Exposed for OCR start, host removal, and outside-tap handling. */
    fun collapse() { panel?.visibility = View.GONE }
}
