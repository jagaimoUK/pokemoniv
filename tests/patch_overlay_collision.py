from pathlib import Path
from hashlib import sha256
p=Path("demo/app/src/main/java/com/example/pokemonivreader/overlayqueue/OverlayCopyQueueController.kt")
s=p.read_text(encoding="utf-8")
base_hash="5588f235c5232e2e67c64be5a726fa7422e0fcd894f390f1255582fa8a469705"
new_hash="8e6f0097c7891cfe1acea41a4ae60204ef0b40d0a4066ee0a1106a6887b7c062"
assert sha256(s.encode()).hexdigest()==base_hash, "Unexpected overlay baseline"
def once(before,after):
    global s
    assert s.count(before)==1, "Expected anchor not unique: "+before[:80]
    s=s.replace(before,after,1)
once("    private val store = OverlayQueueStore(app)\n", """    private val store = OverlayQueueStore(app)
    // Position is independent from the OCR button. Keep a normalized location across rotations.
    private val placement = app.getSharedPreferences("overlay_queue_placement", Context.MODE_PRIVATE)
""")
once("""        val params = overlayParams(dp(56), dp(55), Gravity.TOP or Gravity.START, dp(6), dp(150))
        try {
""","""        // OCR's existing IV bubble starts on the LEFT (x=12dp, y=185dp).
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
""")
once("""                            params.x = (startX + deltaX.toInt()).coerceAtLeast(0)
                            params.y = (startY + deltaY.toInt()).coerceAtLeast(0)
                            try { manager.updateViewLayout(label, params) } catch (_: Exception) {}
""","""                            params.x = (startX + deltaX.toInt()).coerceIn(0, maxX)
                            params.y = (startY + deltaY.toInt()).coerceIn(0, maxY)
                            try { manager.updateViewLayout(label, params) } catch (_: Exception) {}
""")
once("""                    MotionEvent.ACTION_UP -> {
                        if (!dragged) togglePanel()
                        return true
                    }
""","""                    MotionEvent.ACTION_UP -> {
                        if (dragged) {
                            placement.edit()
                                .putFloat("bubble_x_ratio", if (maxX == 0) 0f else params.x.toFloat() / maxX)
                                .putFloat("bubble_y_ratio", if (maxY == 0) 0f else params.y.toFloat() / maxY)
                                .apply()
                        } else togglePanel()
                        return true
                    }
""")
once("""        val width = min(screenWidth - dp(18), dp(440))
""","""        // Leave a tappable lane on the LEFT for the OCR IV bubble while this panel is open.
        // The queue stays on the RIGHT; collapse it with × before taking a screenshot.
        val width = min(dp(380), (screenWidth - dp(76)).coerceAtLeast(dp(205)))
            .coerceAtMost((screenWidth - dp(14)).coerceAtLeast(1))
""")
once("""        val params = overlayParams(width, WindowManager.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.CENTER_HORIZONTAL, 0, dp(58))
""","""        val params = overlayParams(width, WindowManager.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.END, dp(7), dp(58))
""")
assert sha256(s.encode()).hexdigest()==new_hash, "Generated source differs from packaged fix"
p.write_text(s,encoding="utf-8")
print("Collision avoidance patch SHA256 verified",new_hash)
