package com.example.pokemonivreader

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.Normalizer
import java.util.Locale

/** Local, offline catalog. Generate full catalog with tools/build_catalog.py.
 * Form differences are NEVER silently inferred from Japanese base names.
 */
internal class PokemonCatalog private constructor(array: JSONArray, rankingProvider: () -> RankingEligibility) {
    constructor(context: Context) : this(CatalogUpdates.read(context), { RankingEligibility.get(context) })
    /** Data-only index, also used to verify an update before activation. */
    internal constructor(array: JSONArray) : this(array, { error("評価にはランキングが必要です") })
    data class Species(
        val id: String,
        val japanese: String,
        val form: String,
        val stats: EvolutionMath.Stats,
        val evolvesTo: List<String>,
        val label: String = "",
        val englishNames: List<String> = emptyList(),
        val types: Set<String> = emptySet(),
        val gender: GenderRecognizer.Gender = GenderRecognizer.Gender.UNKNOWN,
        val nextGender: Map<String, GenderRecognizer.Gender> = emptyMap(),
        val evolutionNote: String = ""
    ) {
        val displayName: String get() = PumpkinForms.displayName(id) ?: label.ifBlank {
            if (form == "normal") japanese else "$japanese（${formLabel(form)}）"
        }
    }
    data class Resolution(val species: Species?, val message: String)
    data class EvolutionDecision(
        val eligible: List<String>,
        val borderline: List<String>,
        val excluded: List<String>,
        val genderPending: List<String> = emptyList()
    )
    private val byId: Map<String, Species>
    private val byName: Map<String, List<Species>>
    private val byEnglishName: Map<String, List<Species>>
    private val byDisplayName: Map<String, List<Species>>
    private val ranking by lazy(rankingProvider)
    val rankingProblem: String get() = ranking.problem
    val speciesCount: Int get() = byId.size

    init {
        val list = mutableListOf<Species>()
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val stats = item.optJSONArray("stats") ?: continue
            if (stats.length() < 3) continue
            val evolutions = item.optJSONArray("next") ?: JSONArray()
            val english = item.optJSONArray("englishNames") ?: JSONArray()
            val types = item.optJSONArray("types") ?: JSONArray()
            list += Species(
                item.optString("id"), item.optString("ja"), item.optString("form", "normal"),
                EvolutionMath.Stats(stats.optInt(0), stats.optInt(1), stats.optInt(2)),
                (0 until evolutions.length()).map { evolutions.optString(it) },
                item.optString("display"),
                (0 until english.length()).map { english.optString(it) }.filter(String::isNotBlank),
                (0 until types.length()).map { types.optString(it) }.filter(String::isNotBlank).toSet(),
                GenderRecognizer.Gender.fromStored(item.optString("gender")),
                item.optJSONObject("nextGender")?.let { rules ->
                    rules.keys().asSequence().associateWith { GenderRecognizer.Gender.fromStored(rules.optString(it)) }
                } ?: emptyMap(), item.optString("evolutionNote")
            )
        }
        byId = list.filter { it.id.isNotBlank() && it.japanese.isNotBlank() }.associateBy { it.id }
        byName = byId.values.groupBy { normalize(it.japanese) }
        byDisplayName = byId.values.groupBy { normalize(it.displayName) }
        // Explicit aliases cover punctuation and forms. Base English names map
        // to ALL corresponding forms, so a bare name never guesses a form.
        // Old nine-species dictionaries remain compatible via their English IDs.
        byEnglishName = byId.values.flatMap { species ->
            val baseId = if (species.form in setOf("alolan", "galarian", "hisuian", "paldean")) {
                species.id.removeSuffix("_${species.form}")
            } else species.id
            species.englishNames.ifEmpty { listOf(baseId) }
                .map { normalizeEnglish(it) to species }
        }.groupBy({ it.first }, { it.second }).mapValues { (_, values) -> values.distinctBy { it.id } }
    }

    fun findById(id: String): Species? = byId[id]

    fun hasGenderForms(name: String): Boolean = byName[normalize(name)].orEmpty()
        .map { it.gender }.filter { it in setOf(GenderRecognizer.Gender.MALE, GenderRecognizer.Gender.FEMALE) }.distinct().size > 1

    fun requiresGender(id: String): Boolean {
        val visited = mutableSetOf<String>()
        fun walk(s: Species): Boolean {
            if (!visited.add(s.id)) return false
            return hasGenderForms(s.japanese) || s.nextGender.isNotEmpty() || s.evolvesTo.any { byId[it]?.let(::walk) == true }
        }
        return byId[id]?.let(::walk) == true
    }

    fun recognize(ocr: String, observedTypes: Set<String> = emptySet(),
                  observedGender: GenderRecognizer.Gender = GenderRecognizer.Gender.UNKNOWN,
                  observedTypesComplete: Boolean = false): Resolution {
        val cleaned = normalize(ocr)
        if (cleaned.isBlank()) return Resolution(null, "名前が読み取れませんでした")
        if (PumpkinForms.familyFromText(ocr) != null) {
            val id = PumpkinForms.explicitId(ocr)
                ?: return Resolution(null, "バケッチャ・パンプジンのサイズ未確認。Height OCRまたは履歴から確定してください")
            return Resolution(byId[id], if (id in byId) "" else "サイズ別フォームが図鑑にありません")
        }
        // Exact English match only: "Mewtwo" must never resolve to "Mew".
        // Never guess a normal form when regional variants share the same name.
        val englishCandidates = byEnglishName[normalizeEnglish(ocr)].orEmpty()
        if (englishCandidates.isNotEmpty()) {
            return resolveCandidates(englishCandidates, observedTypes, observedGender, observedTypesComplete)
        }
        val explicit = byDisplayName[cleaned].orEmpty().filter { cleaned != normalize(it.japanese) }
        if (explicit.size == 1) return resolveCandidates(explicit, observedTypes, observedGender, observedTypesComplete)
        val form = when {
            cleaned.contains("アローラ") -> "alolan"
            cleaned.contains("ガラル") -> "galarian"
            cleaned.contains("ヒスイ") -> "hisuian"
            cleaned.contains("パルデア") -> "paldean"
            else -> null
        }
        // Prefer longest species name to prevent substring collisions.
        val matches = byName.entries.filter { (name, _) -> cleaned.contains(name) }
            .sortedByDescending { it.key.length }
        val longest = matches.firstOrNull()?.key ?: return Resolution(
            null,
            if (speciesCount < 500) "図鑑が${speciesCount}種類しかありません（全種辞書の生成が必要）"
            else "図鑑の名前と一致しません（読み取り文字またはニックネームを確認）"
        )
        val candidates = byName[longest].orEmpty().filter { form == null || it.form == form }
        return resolveCandidates(candidates, observedTypes, observedGender, observedTypesComplete)
    }

    /** Observed types may be partial (the trainer often hides the second icon).
     * A partial observation is accepted only when it leaves exactly one form.
     */
    private fun resolveCandidates(candidates: List<Species>, observedTypes: Set<String>, observedGender: GenderRecognizer.Gender, observedTypesComplete: Boolean): Resolution {
        if (candidates.isEmpty()) return Resolution(null, "姿が辞書と一致しません")
        val compatible = candidates.filter {
            (observedTypes.isEmpty() || if (observedTypesComplete) it.types == observedTypes
                else it.types.isNotEmpty() && it.types.containsAll(observedTypes)) &&
                (observedGender == GenderRecognizer.Gender.UNKNOWN || it.gender == GenderRecognizer.Gender.UNKNOWN || it.gender == observedGender)
        }
        if (compatible.size == 1) return Resolution(compatible.single(), "")
        val genderSplit = candidates.map { it.gender }.distinct().size > 1
        val message = when {
            genderSplit && observedGender == GenderRecognizer.Gender.UNKNOWN -> "性別記号を読み取れずオス／メスを区別できません"
            compatible.isEmpty() && observedGender != GenderRecognizer.Gender.UNKNOWN -> "読み取った性別・タイプと図鑑が一致しません"
            observedTypes.isEmpty() -> "タイプ表示を読み取れず地方・フォルムを区別できません"
            compatible.isEmpty() -> "読み取ったタイプと図鑑が一致しません（${observedTypes.joinToString("/")}）"
            else -> "タイプだけでは地方・フォルムを区別できません（${observedTypes.joinToString("/")}）"
        }
        return Resolution(null, "$message：${candidates.joinToString { it.displayName }}")
    }

    /** The selection mode controls only score eligibility; CP and form stay unchanged. */
    fun evaluate(current: Species, cp: Int, iv: IntArray,
                 shadow: ShadowRecognizer.State = ShadowRecognizer.State.NORMAL,
                 gender: GenderRecognizer.Gender = GenderRecognizer.Gender.UNKNOWN): EvolutionDecision {
        if (shadow == ShadowRecognizer.State.UNKNOWN) return EvolutionDecision(emptyList(), emptyList(), emptyList())
        val effectiveGender = if (gender == GenderRecognizer.Gender.UNKNOWN) current.gender else gender
        if (current.gender != GenderRecognizer.Gender.UNKNOWN && effectiveGender != current.gender)
            return EvolutionDecision(emptyList(), emptyList(), emptyList())
        val selectionMode = ranking.mode
        val eligible = mutableListOf<String>()
        val borderline = mutableListOf<String>()
        val excluded = mutableListOf<String>()
        val genderPending = mutableListOf<String>()
        val seen = mutableSetOf<String>()
        fun traverse(s: Species, sexUncertain: Boolean = false) {
            if (!seen.add(s.id)) return
            val bounds = if (s.id == current.id) {
                EvolutionMath.Bounds(cp, cp)
            } else EvolutionMath.evolvedCp(cp, iv, current.stats, s.stats)
            val target = ShadowRecognizer.targetName(s.displayName, shadow)
            if (!ranking.allows(target, selectionMode)) {
                excluded += target
            } else {
                when (bounds?.verdict() ?: "UNCERTAIN") {
                    "OVER" -> excluded += target
                    else -> if (sexUncertain) genderPending += target
                        else if (bounds?.verdict() == "OK") eligible += target else borderline += target
                }
            }
            // Never stop the evolution walk just because this stage scores <70.
            s.evolvesTo.forEach { id -> byId[id]?.let { child ->
                val required = s.nextGender[id] ?: GenderRecognizer.Gender.UNKNOWN
                if (required == GenderRecognizer.Gender.UNKNOWN || effectiveGender == required || effectiveGender == GenderRecognizer.Gender.UNKNOWN) {
                    traverse(child, sexUncertain || required != GenderRecognizer.Gender.UNKNOWN && effectiveGender == GenderRecognizer.Gender.UNKNOWN)
                } else excluded += ShadowRecognizer.targetName(child.displayName, shadow)
            } }
        }
        traverse(current)
        return EvolutionDecision(eligible, borderline, excluded, genderPending)
    }

    companion object {
        @Volatile private var cached: PokemonCatalog? = null
        fun get(context: Context): PokemonCatalog = cached ?: synchronized(this) {
            cached ?: PokemonCatalog(context.applicationContext).also { cached = it }
        }
        @Synchronized fun invalidate() { cached = null }
        fun normalize(s: String): String = Normalizer.normalize(s, Normalizer.Form.NFKC)
            .replace(Regex("[\\s・･_\\-]+"), "")
            .replace("ポケモン", "")
        private fun normalizeEnglish(s: String): String =
            Normalizer.normalize(Normalizer.normalize(s, Normalizer.Form.NFKC), Normalizer.Form.NFD)
                .replace(Regex("\\p{M}+"), "")
                .lowercase(Locale.ROOT)
                .replace(Regex("[\\s._'’:\\-]+"), "")
        fun formLabel(form: String): String = when (form) {
            "alolan" -> "アローラ"
            "galarian" -> "ガラル"
            "hisuian" -> "ヒスイ"
            "paldean" -> "パルデア"
            "small", "average", "large", "super" -> PumpkinForms.formLabel(form)
            else -> form
        }
    }
}
