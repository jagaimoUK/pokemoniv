from pathlib import Path
from hashlib import sha256

controller = Path("demo/app/src/main/java/com/example/pokemonivreader/overlayqueue/OverlayCopyQueueController.kt")
snapshot = Path("android-overlay-snapshot/OverlayCopyQueueController.kt")
s = controller.read_text(encoding="utf-8")
expected = "8e6f0097c7891cfe1acea41a4ae60204ef0b40d0a4066ee0a1106a6887b7c062"
assert sha256(s.encode("utf-8")).hexdigest() == expected, "Unexpected post-collision controller baseline"

def once(before, after):
    global s
    assert s.count(before) == 1, "Patch anchor is missing or duplicated: " + before[:90]
    s = s.replace(before, after, 1)

once('    private var resetConfirmationDeadline = 0L\n', '''    private var resetConfirmationDeadline = 0L

    // Scroll restoration is scoped to the current session, filter, search and history view.
    // Keep it in preferences so collapsing/reopening (even after Activity recreation) is stable.
    private fun scrollContextKey(): String =
        "${store.currentSessionId}|${showHistory}|${filter.name}|${searchTerm}"

    private fun saveScrollPosition() {
        val view = list ?: return
        placement.edit()
            .putString("panel_scroll_context", scrollContextKey())
            .putInt("panel_scroll_row", view.firstVisiblePosition)
            .putInt("panel_scroll_offset", view.getChildAt(0)?.top ?: 0)
            .apply()
    }

    private fun restoreScrollPosition() {
        val view = list ?: return
        val context = scrollContextKey()
        if (placement.getString("panel_scroll_context", null) != context) return
        val row = placement.getInt("panel_scroll_row", 0)
        val offset = placement.getInt("panel_scroll_offset", 0)
        // ListView positions should be applied after its adapter has laid out child rows.
        view.post {
            if (list !== view || scrollContextKey() != context) return@post
            val count = view.adapter?.count ?: 0
            if (count > 0) view.setSelectionFromTop(row.coerceIn(0, count - 1), offset)
        }
    }
''')
once('''        val params = overlayParams(width, WindowManager.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.END, dp(7), dp(58))
        try {
            manager.addView(root, params)
            panel = root
            refresh(true)
''', '''        val params = overlayParams(width, WindowManager.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.END, dp(7), dp(58)).apply {
            // Outside taps belong to Pokémon GO. Never subscribe to outside-touch dismissal.
            flags = flags and WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH.inv()
        }
        try {
            manager.addView(root, params)
            panel = root
            // Prevent the floating toggle from overlapping the list and closing it during paste.
            bubble?.visibility = View.GONE
            refresh(true)
            restoreScrollPosition()
''')
once('''    fun closePanel() {
        hideKeyboard()
        panel?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        panel = null
''', '''    fun closePanel() {
        saveScrollPosition()
        hideKeyboard()
        panel?.let { try { manager.removeView(it) } catch (_: Exception) {} }
        panel = null
        bubble?.visibility = View.VISIBLE
''')
assert s == snapshot.read_text(encoding="utf-8"), "CI output differs from reviewed controller"
assert "MotionEvent.ACTION_OUTSIDE" not in s
assert s.index("saveScrollPosition()\n        hideKeyboard()") < s.index("manager.removeView(it)")
assert "bubble?.visibility = View.GONE" in s and "bubble?.visibility = View.VISIBLE" in s
controller.write_text(s, encoding="utf-8")
print("Overlay UX patch verified; no outside-dismiss; saved scroll; bubble hidden while open")
