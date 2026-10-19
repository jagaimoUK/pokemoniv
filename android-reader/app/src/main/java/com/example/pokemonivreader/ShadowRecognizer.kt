package com.example.pokemonivreader

import java.text.Normalizer
import kotlin.math.max
import kotlin.math.min

/** Offline heuristic classification. Automatic results remain estimates, not learned probabilities. */
internal object ShadowRecognizer {
    enum class State(val label: String) {
        UNKNOWN("未確認"), NORMAL("通常・リトレーン済み"), SHADOW("シャドウ");
        companion object {
            fun fromStored(value: String): State = entries.firstOrNull { it.name == value } ?: UNKNOWN
        }
    }
    const val MODE_KEY = "shadow_scan_mode_v1"
    enum class Mode(val label: String) {
        AUTO("自動"), NORMAL_ONLY("通常固定"), SHADOW_ONLY("シャドウ固定");
        companion object {
            fun fromStored(value: String?): Mode = entries.firstOrNull { it.name == value } ?: AUTO
        }
    }
    data class Evidence(val suggestedShadow: Boolean, val diagnostic: String,
                        val normalEvidence: Boolean = false, val usable: Boolean = false)
    data class Decision(val state: State, val method: String, val diagnostic: String)

    fun decide(mode: Mode, purify: Boolean, samples: List<Evidence>): Decision {
        if (purify && mode == Mode.NORMAL_ONLY)
            return Decision(State.UNKNOWN, "conflict", "通常固定とPURIFY表示が矛盾しています。設定と対象を確認してください")
        if (purify) return Decision(State.SHADOW, "purify_ocr", "PURIFY／リトレーン表示から自動判定")
        if (mode == Mode.SHADOW_ONLY) return Decision(State.SHADOW, "fixed_shadow", "シャドウ固定で登録")
        if (mode == Mode.NORMAL_ONLY) return Decision(State.NORMAL, "fixed_normal", "通常固定で登録")
        val shadow = samples.count { it.usable && it.suggestedShadow }
        val normal = samples.count { it.usable && it.normalEvidence }
        return when {
            samples.size >= 3 && shadow >= 2 && normal == 0 ->
                Decision(State.SHADOW, "aura_vote", "3フレーム中${shadow}枚でオーラを検出：シャドウ自動判定（推定）")
            samples.size >= 3 && normal >= 2 && shadow == 0 ->
                Decision(State.NORMAL, "normal_vote", "3フレーム中${normal}枚で通常側の条件を検出：通常自動判定（推定）")
            else -> Decision(State.UNKNOWN, "inconclusive", "自動判定が一致しません。画面を静止して再読取、または固定モードを使用してください")
        }
    }

    fun targetName(name: String, state: State): String =
        if (state == State.SHADOW) "$name (シャドウ)" else name

    /** Only the fixed action-button crop is passed here, never the nickname. */
    fun hasPurifyAction(raw: String): Boolean {
        val text = Normalizer.normalize(raw, Normalizer.Form.NFKC)
        return Regex("(?m)^\\s*PURIFY(?:\\s*$|[ \\t]+(?=[0-9,]))", RegexOption.IGNORE_CASE).containsMatchIn(text) ||
            Regex("(?m)^\\s*リトレーン(?:\\s*$|[ \\t]+(?=[0-9,]))").containsMatchIn(text)
    }

    /** Input is the model/aura band: x=14..82%, y=12..35% of the screen.
     * Sample an approximately 144x96 grid, independent of screen resolution.
     * Red eyes are deliberately not used (ordinary Bulbasaur has red eyes).
     */
    fun inspect(pixels: IntArray, width: Int, height: Int): Evidence {
        if (width < 16 || height < 16 || pixels.size < width * height) {
            return Evidence(false, "オーラ画像を解析できません")
        }
        val stepX = max(1, width / 144)
        val stepY = max(1, height / 96)
        val cells = IntArray(12 * 8)
        val totals = IntArray(cells.size)
        val palette = mutableSetOf<Int>()
        var vivid = 0
        var hits = 0
        var samples = 0
        for (y in 0 until height step stepY) for (x in 0 until width step stepX) {
            val color = pixels[y * width + x]
            val r = ((color ushr 16) and 255) / 255.0
            val g = ((color ushr 8) and 255) / 255.0
            val b = (color and 255) / 255.0
            val high = max(r, max(g, b))
            val low = min(r, min(g, b))
            val delta = high - low
            val hue = when {
                delta == 0.0 -> 0.0
                high == r -> (60.0 * ((g - b) / delta) + 360.0) % 360.0
                high == g -> 60.0 * ((b - r) / delta + 2.0)
                else -> 60.0 * ((r - g) / delta + 4.0)
            }
            val saturation = if (high == 0.0) 0.0 else delta / high
            palette += (((color ushr 21) and 7) shl 6) or (((color ushr 13) and 7) shl 3) or ((color ushr 5) and 7)
            if (saturation > 0.20 && high > 0.16) vivid++
            val cell = min(7, y * 8 / height) * 12 + min(11, x * 12 / width)
            totals[cell]++
            samples++
            if (hue in 258.0..312.0 && saturation in 0.25..0.95 && high in 0.19..0.95) {
                cells[cell]++
                hits++
            }
        }
        val coverage = hits.toDouble() / samples.coerceAtLeast(1)
        val active = cells.indices.filter { totals[it] > 0 && cells[it].toDouble() / totals[it] >= 0.20 }
        val left = active.count { it % 12 < 5 }
        val right = active.count { it % 12 > 6 }
        val rows = active.map { it / 12 }.distinct().size
        val usable = palette.size >= 12 && vivid.toDouble() / samples.coerceAtLeast(1) > 0.12
        // Uniform violet backgrounds fail the upper coverage bound. Localized
        // violet bodies can still pass: this must remain a user-confirmed hint.
        val suggested = usable && coverage in 0.035..0.48 && left >= 2 && right >= 2 && rows >= 3
        return Evidence(suggested,
            "紫色の分布=${(coverage * 1000).toInt() / 10.0}% 左$left/右$right 帯$rows：" +
                if (suggested) "シャドウ側の特徴（推定）"
                else "紫色の分布だけではシャドウと判定できません",
            normalEvidence = usable && coverage <= 0.006 && active.size <= 1, usable = usable)
    }
}
