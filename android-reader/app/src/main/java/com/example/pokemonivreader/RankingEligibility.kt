package com.example.pokemonivreader

import android.content.Context
import org.json.JSONObject
import org.json.JSONArray
import java.text.Normalizer
import java.util.Locale

/** Offline eligibility from the supplied OVERALL CSV, not role-specific scores. */
internal class RankingEligibility private constructor(context: Context) {
    private val scores: Map<String, Double>
    private val preferences = context.applicationContext.getSharedPreferences("pokemon_iv_reader", Context.MODE_PRIVATE)
    private val dataProblem: String
    val mode: Mode get() = Mode.fromStored(preferences.getString(MODE_KEY, null))
    val problem: String get() = if (mode == Mode.ALL_SPECIES) {
        if (catalogTargets.isEmpty()) "全種モード用の図鑑データを読み込めません" else ""
    } else dataProblem

    // ALL_SPECIES skips ranking coverage, but still accepts only catalogued targets.
    private val catalogTargets: Set<String> by lazy {
        try {
            val entries = CatalogUpdates.read(context.applicationContext)
            buildSet {
                for (i in 0 until entries.length()) {
                    val entry = entries.optJSONObject(i) ?: continue
                    val japanese = entry.optString("ja")
                    if (entry.optString("id").isBlank() || japanese.isBlank()) continue
                    val form = entry.optString("form", "normal")
                    val name = entry.optString("display").ifBlank {
                        if (form == "normal") japanese else "$japanese（${PokemonCatalog.formLabel(form)}）"
                    }
                    add(normalize(name))
                    add(normalize(ShadowRecognizer.targetName(name, ShadowRecognizer.State.SHADOW)))
                }
            }
        } catch (_: Exception) { emptySet() }
    }

    init {
        var failure = ""
        scores = try {
            val data = context.assets.open("pvpoke_overall_1500.json").bufferedReader().use {
                JSONObject(it.readText())
            }
            require(data.getInt("schemaVersion") == 1)
            require(data.getInt("cpCap") == 1500)
            require(data.getString("category") == "overall")
            require(data.getDouble("minimumScore") == MINIMUM_SCORE)
            val entries = data.getJSONArray("entries")
            require(entries.length() == data.getInt("entryCount") && entries.length() > 0)
            val parsed = mutableMapOf<String, Double>()
            for (i in 0 until entries.length()) {
                val entry = entries.getJSONObject(i)
                val key = normalize(entry.getString("name"))
                val score = entry.getDouble("score")
                require(key.isNotBlank() && score.isFinite() && score in 0.0..100.0)
                require(key !in parsed) // No accidental normal/form/shadow collisions.
                parsed[key] = score
            }
            // A sex label may be explicit in the app while the supplied CSV uses
            // an unlabelled male name (Oinkologne). Preserve that exact score.
            val catalog = CatalogUpdates.read(context)
            for (i in 0 until catalog.length()) {
                val entry = catalog.optJSONObject(i) ?: continue
                val label = entry.optString("display")
                val original = entry.optString("rankingName")
                if (label.isNotBlank() && original.isNotBlank()) {
                    for (suffix in listOf("", " (シャドウ)")) parsed[normalize(original+suffix)]?.let { score -> parsed[normalize(label+suffix)] = score }
                }
            }
            parsed.toMap()
        } catch (_: Exception) {
            failure = "総合ランキングデータを読み込めません。アプリを更新してください"
            emptyMap()
        }
        dataProblem = failure
    }

    fun allows(name: String, selectedMode: Mode = mode): Boolean {
        if (selectedMode == Mode.ALL_SPECIES) return normalize(name) in catalogTargets
        val score = scores[normalize(name)] ?: return false
        return score >= MINIMUM_SCORE
    }

    enum class Mode(val label: String) {
        RANKED_70("70点以上"), ALL_SPECIES("全種");
        companion object {
            fun fromStored(value: String?): Mode = entries.firstOrNull { it.name == value } ?: RANKED_70
        }
    }

    companion object {
        const val MODE_KEY = "target_selection_mode_v1"
        private const val MINIMUM_SCORE = 70.0
        @Volatile private var cached: RankingEligibility? = null

        fun get(context: Context): RankingEligibility = cached ?: synchronized(this) {
            cached ?: RankingEligibility(context.applicationContext).also { cached = it }
        }

        @Synchronized fun invalidate() { cached = null }

        // AutoIvRecords.load() initializes this policy before the UI can export.
        // A missing/uninitialized policy never exports unchecked species.
        fun allowsLoaded(name: String): Boolean = cached?.allows(name) == true

        private fun normalize(value: String): String =
            Normalizer.normalize(value, Normalizer.Form.NFKC)
                .lowercase(Locale.ROOT)
                .replace(Regex("[\\s・･]+"), "")
    }
}
