package com.example.pokemonivreader

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Phase 2C: Pokémon GO appraisal bar recognition with adjustable color sensitivity.
 * This file deliberately has no Android dependencies so its pixel algorithm can
 * be exercised with plain Kotlin tests as well as called from an Android Bitmap.
 */
internal object IvBarRecognizer {
    enum class Sensitivity { HIGH, NORMAL, STRICT }

    internal data class Result(
        val attack: Int,
        val defense: Int,
        val hp: Int,
        val reliable: Boolean,
        /** Fractions of crop height (0..1), for the preview overlay. */
        val barCenters: List<Float> = emptyList(),
        /** Diagnostic messages; never treat a high-confidence prediction as ground truth. */
        val warnings: List<String> = emptyList()
    )

    // 0=background, 1=empty-bar material, 2=filled-bar material.
    private fun pixelType(pixel: Int, sensitivity: Sensitivity): Byte {
        val r = pixel ushr 16 and 255
        val g = pixel ushr 8 and 255
        val b = pixel and 255
        val maximum = max(r, max(g, b))
        val minimum = min(r, min(g, b))
        // Pink/red/orange. Hue dominance is used rather than exact RGB values.
        // The brightness tolerance helps with different screen brightness and compression.
        val redDifference = when (sensitivity) {
            Sensitivity.HIGH -> 18
            Sensitivity.NORMAL -> 27
            Sensitivity.STRICT -> 40
        }
        val blueDifference = when (sensitivity) {
            Sensitivity.HIGH -> 16
            Sensitivity.NORMAL -> 25
            Sensitivity.STRICT -> 38
        }
        val minRed = when (sensitivity) {
            Sensitivity.HIGH -> 115
            Sensitivity.NORMAL -> 135
            Sensitivity.STRICT -> 155
        }
        val fill = r >= minRed && r - g >= redDifference &&
                r - b >= blueDifference && g >= 32
        if (fill) return 2
        // Empty bars are light or mid gray. The pure-white appraisal panel is excluded.
        val maxGray = if (sensitivity == Sensitivity.HIGH) 254 else 247
        val gray = maximum in 125..maxGray && maximum - minimum <= 20
        return if (gray) 1 else 0
    }

    private data class Span(val left: Int, val right: Int, val pixels: Int) {
        val width get() = right - left + 1
        val mid get() = (left + right) / 2f
        val density get() = pixels.toFloat() / width
    }

    private data class Band(
        val spans: MutableList<Pair<Int, Span>> = mutableListOf()
    ) {
        val top get() = spans.first().first
        val bottom get() = spans.last().first
        val midY get() = (top + bottom) / 2f
        val height get() = bottom - top + 1
        val left get() = spans.map { it.second.left }.sorted()[spans.size / 2]
        val right get() = spans.map { it.second.right }.sorted()[spans.size / 2]
        val width get() = right - left + 1
        val midX get() = (left + right) / 2f
    }

    fun read(
        pixels: IntArray, width: Int, height: Int,
        sensitivity: Sensitivity = Sensitivity.NORMAL
    ): Result? {
        if (width < 100 || height < 100 || pixels.size.toLong() != width.toLong() * height) return null
        val types = ByteArray(pixels.size) { pixelType(pixels[it], sensitivity) }
        val minWidth = max(50, (width * 0.33f).roundToInt())
        val gap = max(2, (width * 0.012f).roundToInt())
        val bands = mutableListOf<Band>()

        // Detect long horizontal red/gray spans with short interruptions ignored.
        for (y in 0 until height) {
            var best: Span? = null
            var begin = -1
            var last = -1
            var pixelsFound = 0
            for (x in 0..width) {
                val isBar = x < width && types[y * width + x].toInt() != 0
                if (isBar) {
                    if (begin < 0) begin = x
                    last = x
                    pixelsFound++
                }
                if (begin >= 0 && (x == width || x - last > gap)) {
                    val span = Span(begin, last, pixelsFound)
                    if (span.width >= minWidth && span.density >= 0.64f &&
                        (best == null || span.width * span.density > best.width * best.density)
                    ) best = span
                    begin = -1
                    last = -1
                    pixelsFound = 0
                }
            }
            if (best == null) continue
            val previous = bands.lastOrNull()
            val previousSpan = previous?.spans?.lastOrNull()?.second
            if (previous != null && previousSpan != null &&
                y - previous.bottom <= 3 &&
                abs(best.mid - previousSpan.mid) <= width * 0.07f &&
                abs(best.width - previousSpan.width) <= width * 0.16f
            ) {
                previous.spans.add(y to best)
            } else {
                bands.add(Band(mutableListOf(y to best)))
            }
        }
        val plausible = bands.filter {
            it.spans.size >= 2 && it.height in 2..max(4, (height * 0.09f).roundToInt()) &&
                    it.width >= minWidth
        }
        if (plausible.size < 3) return null

        // Search for the three approximately parallel, evenly spaced bars.
        var bestTriple: List<Band>? = null
        var bestScore = Double.NEGATIVE_INFINITY
        // Limit combinatorial search if an unexpected UI has hundreds of gray lines.
        val candidates = plausible.sortedByDescending { it.width * it.spans.size }.take(40)
            .sortedBy { it.midY }
        for (i in 0 until candidates.size - 2) {
            for (j in i + 1 until candidates.size - 1) {
                for (k in j + 1 until candidates.size) {
                    val a = candidates[i]
                    val b = candidates[j]
                    val c = candidates[k]
                    val d1 = b.midY - a.midY
                    val d2 = c.midY - b.midY
                    if (min(d1, d2) < height * 0.07f ||
                        max(d1, d2) > height * 0.60f ||
                        max(d1, d2) / min(d1, d2) > 1.35f
                    ) continue
                    val triple = listOf(a, b, c)
                    val xRange = triple.maxOf { it.midX } - triple.minOf { it.midX }
                    val widthRange = triple.maxOf { it.width } - triple.minOf { it.width }
                    if (xRange > width * 0.07f || widthRange > width * 0.14f) continue
                    val strength = triple.sumOf { it.width.toDouble() * it.spans.size }
                    val score = strength - abs(d1 - d2) * width * 1.0 -
                            xRange * height * 0.65 - widthRange * height * 0.45
                    if (score > bestScore) {
                        bestScore = score
                        bestTriple = triple
                    }
                }
            }
        }
        val bars = bestTriple ?: return null
        val sharedLeft = bars.map { it.left }.sorted()[1]
        val sharedRight = bars.map { it.right }.sorted()[1]
        val barWidth = sharedRight - sharedLeft + 1
        if (barWidth < minWidth) return null

        val warnings = mutableSetOf<String>()
        val values = bars.map { band ->
            val cells = BooleanArray(15)
            val cellWidth = barWidth.toFloat() / 15f
            val yRadius = max(1, min(4, band.height / 4))
            for (cell in 0 until 15) {
                var red = 0
                var gray = 0
                // Center of the cell, plus nearby points; avoid borders between blocks.
                for (portion in floatArrayOf(0.35f, 0.50f, 0.65f)) {
                    val x = (sharedLeft + (cell + portion) * cellWidth).roundToInt()
                        .coerceIn(0, width - 1)
                    for (dy in -yRadius..yRadius) {
                        val y = band.midY.roundToInt() + dy
                        if (y !in 0 until height) continue
                        when (types[y * width + x].toInt()) {
                            2 -> red++
                            1 -> gray++
                        }
                    }
                }
                val useful = red + gray
                if (useful < (3 * (2 * yRadius + 1)) * 0.40f) {
                    warnings.add("バーの色を判定できない部分があります")
                }
                // Low material availability means the row was probably not a bar at all.
                if (useful == 0) return null
                val fill = red.toFloat() / useful
                if (fill in 0.22f..0.78f) warnings.add("色の境界があいまいです")
                cells[cell] = fill >= 0.5f
            }
            val value = cells.takeWhile { it }.size
            // The colored region must be a prefix; no separated later colored pieces.
            if (cells.drop(value).any { it }) warnings.add("塗りつぶしが途中で途切れています")
            value
        }
        // An all-zero reading might instead be the gray UI background. Flag for manual review.
        if (values.all { it == 0 }) warnings.add("すべて0です。背景を読み取った可能性があります")
        // Detect obvious geometric instability, even when the colors look sharp.
        val gaps = bars.zipWithNext { a, b -> b.midY - a.midY }
        if (abs(gaps[0] - gaps[1]) > min(gaps[0], gaps[1]) * 0.13f) {
            warnings.add("バーの間隔が均等ではありません")
        }
        return Result(
            values[0], values[1], values[2], warnings.isEmpty(),
            bars.map { (it.midY / height).coerceIn(0f, 1f) },
            warnings.toList()
        )
    }
}
