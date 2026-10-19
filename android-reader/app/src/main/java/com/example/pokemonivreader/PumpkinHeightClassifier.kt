package com.example.pokemonivreader

import java.text.Normalizer
import java.util.Locale

/**
 * Approximate Pumpkaboo/Gourgeist battle-form selection from the *HEIGHT* field.
 * The rule deliberately follows the user's approximate size-badge heuristic. Do not use
 * badges from weight, candy, the Pokémon name or any whole-screen OCR text.
 */
internal object PumpkinHeightClassifier {
    data class Decision(
        val form: String?,
        val badge: String,
        val heightSeen: Boolean,
        val message: String
    )

    private val height = Regex("""\d{1,3}(?:[.,]\d{1,3})?\s*(?:M|メートル)""", RegexOption.IGNORE_CASE)
    private val badges = Regex("""(?<![A-Z])(?:LXXL|XXS|XXL|XS|XL)(?![A-Z])""")

    fun classify(rawHeightOcr: String): Decision {
        val text = Normalizer.normalize(rawHeightOcr, Normalizer.Form.NFKC)
            .uppercase(Locale.ROOT)
            // OCR occasionally runs the badge and the m label together.
            .replace(Regex("""(?<=M)(?=XXS|XXL|XS|XL|LXXL)"""), " ")
        if (!height.containsMatchIn(text)) {
            return Decision(null, "未確認", false, "高さの数値（m）を認識できません")
        }
        val detected = badges.findAll(text).map { it.value }.toSet()
        val forms = detected.map {
            when (it) {
                "XXS", "XS" -> "small"
                "XL" -> "large"
                "XXL", "LXXL" -> "super"
                else -> error("Unexpected size badge")
            }
        }.toSet()
        if (forms.size > 1) {
            return Decision(null, detected.joinToString("/"), true, "高さ欄に複数のサイズ表記を検出しました")
        }
        val form = forms.singleOrNull() ?: "average"
        return Decision(form, detected.joinToString("/").ifBlank { "表示なし" }, true, "")
    }
}
