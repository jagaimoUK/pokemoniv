package com.example.pokemonivreader

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Shared record store for capture callbacks and manual shadow confirmation. */
internal object AutoIvRecords {
    private const val KEY = "auto_iv_records_v1"
    private val lock = Any()
    private const val UNDO_KEY = "auto_iv_records_delete_undo_v1"
    data class Row(
        val source: String, val cp: Int, val a: Int, val d: Int, val h: Int,
        val targets: List<String>, val uncertain: List<String>,
        val diagnostic: String, val nameOcr: String,
        val shadow: ShadowRecognizer.State = ShadowRecognizer.State.UNKNOWN,
        val shadowHint: String = "", val shadowEvidence: String = "",
        val recordId: String = "", val ready: Boolean = false,
        val selectionKey: String = "", val shadowDecision: String = "",
        val gender: GenderRecognizer.Gender = GenderRecognizer.Gender.UNKNOWN,
        val genderPending: List<String> = emptyList(), val genderRelevant: Boolean = false,
        val sourceId: String = "", val heightOcr: String = "", val heightBadge: String = "",
        val sizeDecision: String = "", val legacyWeightBadge: String = ""
    ) {
        val iv: String get() = "$a,$d,$h"
    }
    private fun selectionKey(item: JSONObject): String = item.optString("recordId").takeIf(String::isNotBlank)
        ?.let { "id:$it" } ?: "legacy:${item}"

    private fun prefs(context: Context) = context.getSharedPreferences("pokemon_iv_reader", Context.MODE_PRIVATE)
    private fun records(context: Context): JSONArray = JSONArray(prefs(context).getString(KEY, "[]") ?: "[]")

    /** Single lock also prevents deletion being undone by a late OCR callback. */
    fun save(context: Context, recordId: String, incoming: JSONObject, insert: Boolean = false): Boolean = synchronized(lock) {
        try {
            val entries = records(context)
            val index = (0 until entries.length()).firstOrNull {
                entries.optJSONObject(it)?.optString("recordId") == recordId
            }
            if (index == null && !insert) return@synchronized false
            val updated = JSONObject(incoming.toString())
            val old = index?.let { entries.optJSONObject(it) }
            if (old?.optString("shadowMethod") == "manual") {
                updated.put("shadowState", old.optString("shadowState"))
                updated.put("shadowMethod", "manual")
                updated.put("shadowDecision", old.optString("shadowDecision"))
            }
            if (old?.optString("sizeDecision") == "manual") {
                // Never overwrite a manual size choice with a late OCR callback.
                updated.put("sourceId", old.optString("sourceId"))
                updated.put("source", old.optString("source"))
                updated.put("heightBadge", old.optString("heightBadge").ifBlank { old.optString("weightBadge") })
                updated.put("sizeDecision", "manual")
            }
            if (old?.optString("genderMethod") == "manual") {
                updated.put("gender", old.optString("gender"))
                updated.put("genderMethod", "manual")
            }
            refresh(context, updated)
            if (index != null) entries.put(index, updated) else entries.put(updated)
            prefs(context).edit().putString(KEY, entries.toString()).commit()
        } catch (_: Exception) { false }
    }

    /** Always recompute with current CP/ranking and the SAME shadow status at every evolution. */
    private fun refresh(context: Context, item: JSONObject) {
        val catalog = PokemonCatalog.get(context)
        val state = ShadowRecognizer.State.fromStored(item.optString("shadowState"))
        var gender = GenderRecognizer.Gender.fromStored(item.optString("gender"))
        val oldSpecies = catalog.findById(item.optString("sourceId"))
        var species = oldSpecies ?: catalog.recognize(item.optString("source"), observedGender=gender).species
        val types = item.optJSONArray("observedTypes")?.let { a -> (0 until a.length()).map { a.optString(it) }.toSet() } ?: emptySet()
        val name = item.optString("nameCandidate").ifBlank { item.optString("source") }
        // Keep original OCR/name text separate from the sex-labelled display name.
        if (item.optString("nameCandidate").isBlank() && name.isNotBlank()) item.put("nameCandidate", name)
        if (species == null || item.optString("formMethod") == "catalog_types_v2" || oldSpecies?.let { catalog.hasGenderForms(it.japanese) } == true) {
            species = catalog.recognize(name, types, gender, item.optBoolean("observedTypesComplete",false)).species
        }
        if (species == null && item.optString("formMethod") == "catalog_types_v2") {
            item.put("sourceId", "")
            item.put("source", "要確認")
        }
        if (species != null) {
            if (gender == GenderRecognizer.Gender.UNKNOWN && species.gender != GenderRecognizer.Gender.UNKNOWN) {
                gender = species.gender
                item.put("gender", gender.name)
                item.put("genderMethod", "species")
            }
            item.put("sourceId", species.id)
            item.put("source", species.displayName)
        } else if (oldSpecies != null && catalog.hasGenderForms(oldSpecies.japanese)) {
            item.put("source", oldSpecies.japanese + "（性別未確認）")
        }
        if (species != null && species.gender != GenderRecognizer.Gender.UNKNOWN && gender != species.gender) species = null
        val iv = intArrayOf(item.optInt("attack", -1), item.optInt("defense", -1), item.optInt("hp", -1))
        // Old records are never assumed normal. Their recognized name/CP can
        // still be used after the user explicitly selects normal or shadow.
        val legacyReady = item.optString("status") == "confirmed" || (item.optJSONArray("targets")?.length() ?: 0) > 0
        val reliable = item.optBoolean("ivReliable", item.optBoolean("recognitionReady", legacyReady))
        item.put("ivReliable", reliable)
        // Weight-based classifications from older versions are not evidence for Height.
        // Keep the displayed old variety but block recommendations until corrected.
        val pumpkinUnverified = (PumpkinForms.familyFromId(item.optString("sourceId")) != null ||
            PumpkinForms.familyFromText(name) != null) &&
            item.optString("sizeDecision") !in setOf("height", "manual")
        val ready = reliable && !pumpkinUnverified && species != null && item.optInt("cp") > 0 && iv.all { it in 0..15 }
        item.put("recognitionReady", ready)
        val decision = if (ready && species != null) catalog.evaluate(species, item.optInt("cp"), iv, state, gender) else null
        item.put("targets", JSONArray(decision?.eligible ?: emptyList<String>()))
        item.put("borderline", JSONArray(decision?.borderline ?: emptyList<String>()))
        item.put("excluded", JSONArray(decision?.excluded ?: emptyList<String>()))
        item.put("genderPending", JSONArray(decision?.genderPending ?: emptyList<String>()))
        item.put("evolutionNote", species?.evolutionNote.orEmpty())
        item.put("genderRelevant", species?.let { catalog.requiresGender(it.id) } ?: (name.isNotBlank() &&
            catalog.recognize(name, types, GenderRecognizer.Gender.MALE).species?.id != catalog.recognize(name, types, GenderRecognizer.Gender.FEMALE).species?.id))
        item.put("status", if (ready && state != ShadowRecognizer.State.UNKNOWN) "confirmed" else "pending")
    }

    fun load(context: Context): List<Row> = synchronized(lock) {
        RankingEligibility.get(context)
        try {
            val entries = records(context)
            // Give old/duplicated UUID records stable distinct identities before selection.
            val ids = mutableSetOf<String>()
            var migrated = false
            for (n in 0 until entries.length()) {
                val item = entries.optJSONObject(n) ?: continue
                val id = item.optString("recordId")
                if (id.isBlank() || !ids.add(id)) {
                    val fresh = java.util.UUID.randomUUID().toString()
                    item.put("recordId", fresh)
                    ids += fresh
                    migrated = true
                }
            }
            if (migrated && !prefs(context).edit().putString(KEY, entries.toString()).commit()) return@synchronized emptyList()
            (0 until entries.length()).mapNotNull { n ->
                val item = entries.optJSONObject(n) ?: return@mapNotNull null
                val key = selectionKey(item)
                refresh(context, item) // Project without rewriting stored history.
                fun strings(key: String): List<String> {
                    val arr = item.optJSONArray(key) ?: return emptyList()
                    return (0 until arr.length()).map { arr.optString(it) }.filter(String::isNotBlank)
                }
                val state = ShadowRecognizer.State.fromStored(item.optString("shadowState"))
                val notes = listOf(item.optString("diagnostic"), item.optString("evolutionNote"), PokemonCatalog.get(context).rankingProblem,
                    if (state == ShadowRecognizer.State.UNKNOWN) "判定が不一致です。再読取または固定モードを使用してください" else "",
                    if (item.optString("sizeDecision") == "weight") "旧Weight判定です。Heightで再読取するか手動でサイズを確定してください"
                    else if ((PumpkinForms.familyFromId(item.optString("sourceId")) != null ||
                        PumpkinForms.familyFromText(item.optString("nameCandidate")) != null) &&
                        item.optString("sizeDecision") !in setOf("height", "manual"))
                        "サイズ未確認です。Heightで再読取するか手動でサイズを確定してください" else "")
                Row(item.optString("source"), item.optInt("cp"), item.optInt("attack"), item.optInt("defense"), item.optInt("hp"),
                    strings("targets"), strings("borderline"), notes.filter(String::isNotBlank).distinct().joinToString(" / "),
                    item.optString("nameOcr"), state, item.optString("shadowSuggestion"), item.optString("shadowEvidence"),
                    item.optString("recordId"), item.optBoolean("recognitionReady", false), key, item.optString("shadowDecision"), GenderRecognizer.Gender.fromStored(item.optString("gender")),
                    strings("genderPending"), item.optBoolean("genderRelevant",false),
                    item.optString("sourceId"), item.optString("heightOcr"), item.optString("heightBadge"),
                    item.optString("sizeDecision"), item.optString("weightBadge"))
            }
        } catch (_: Exception) { emptyList() }
    }

    /** Index fallback is for old records lacking UUIDs; verify identity before mutation. */
    fun setShadow(context: Context, index: Int, row: Row, state: ShadowRecognizer.State): Boolean = synchronized(lock) {
        try {
            val entries = records(context)
            val actual = if (row.recordId.isNotBlank()) (0 until entries.length()).firstOrNull {
                entries.optJSONObject(it)?.optString("recordId") == row.recordId
            } else index.takeIf { it in 0 until entries.length() }
            val item = actual?.let { entries.optJSONObject(it) } ?: return@synchronized false
            if (row.recordId.isBlank() && (item.optString("source") != row.source || item.optInt("cp") != row.cp ||
                item.optInt("attack") != row.a || item.optInt("defense") != row.d || item.optInt("hp") != row.h)) return@synchronized false
            // Establish legacy readiness before clearing old targets.
            refresh(context, item)
            item.put("shadowState", state.name)
            item.put("shadowMethod", "manual")
            item.put("shadowDecision", "手動で${state.label}に変更")
            refresh(context, item)
            entries.put(actual, item)
            prefs(context).edit().putString(KEY, entries.toString()).commit()
        } catch (_: Exception) { false }
    }

    /** All selected rows are validated and refreshed before one preference write. */
    fun setShadowMany(context: Context, keys: Set<String>, state: ShadowRecognizer.State): Int = synchronized(lock) {
        try {
            val entries = records(context)
            val changed = HistoryShadowBatch.update(entries, keys, state, ::selectionKey) { refresh(context, it) }
            if (changed <= 0) return@synchronized changed
            if (prefs(context).edit().putString(KEY, entries.toString()).commit()) changed else -1
        } catch (_: Exception) { -1 }
    }

    fun setGender(context: Context, row: Row, gender: GenderRecognizer.Gender): Boolean = synchronized(lock) {
        try {
            val entries = records(context)
            val index = (0 until entries.length()).firstOrNull { entries.optJSONObject(it)?.optString("recordId") == row.recordId }
                ?: return@synchronized false
            val item = entries.getJSONObject(index)
            item.put("gender", gender.name)
            item.put("genderMethod", "manual")
            refresh(context, item)
            entries.put(index,item)
            prefs(context).edit().putString(KEY,entries.toString()).commit()
        } catch (_: Exception) { false }
    }

    /** Manually correct one size without changing the shadow, gender or eligibility rules.
     * The record UUID is required; an old or deleted row cannot mutate a new one.
     */
    fun selectPumpkinSize(context: Context, row: Row, form: String): String = synchronized(lock) {
        if (form !in PumpkinForms.sizes) return@synchronized "サイズ指定が不正です"
        if (row.recordId.isBlank()) return@synchronized "履歴IDがありません。再読み込みしてください"
        try {
            val entries = records(context)
            val index = (0 until entries.length()).firstOrNull { i ->
                entries.optJSONObject(i)?.optString("recordId") == row.recordId
            } ?: return@synchronized "履歴が変更されています。再読み込みしてください"
            val item = entries.optJSONObject(index) ?: return@synchronized "履歴が見つかりません"
            val family = PumpkinForms.familyFromId(item.optString("sourceId"))
                ?: PumpkinForms.familyFromText(item.optString("nameCandidate"))
                ?: PumpkinForms.familyFromText(item.optString("nameOcr"))
                ?: return@synchronized "バケッチャ／パンプジンを確認できません"
            val species = PokemonCatalog.get(context).findById("${family}_$form")
                ?: return@synchronized "サイズ別図鑑がありません"
            item.put("sourceId", species.id)
            item.put("source", species.displayName)
            item.put("heightBadge", PumpkinForms.sizeLabel(form))
            item.put("sizeDecision", "manual")
            refresh(context, item)
            entries.put(index, item)
            if (!prefs(context).edit().putString(KEY, entries.toString()).commit())
                return@synchronized "サイズ変更を保存できませんでした"
            if (!item.optBoolean("recognitionReady", false))
                "${species.displayName}に変更しました（CP・個体値などの確認待ち）"
            else "${species.displayName}に変更しました"
        } catch (_: Exception) { "サイズ変更に失敗しました" }
    }

    /** A dialog submits a snapshot of selected identities, never shifting row indices. */
    fun deleteMany(context: Context, selected: Set<String>): Int = synchronized(lock) {
        if (selected.isEmpty()) return@synchronized 0
        try {
            val all = records(context)
            val next = JSONArray()
            val removed = JSONArray()
            for (i in 0 until all.length()) {
                val item = all.optJSONObject(i)
                if (item != null && selectionKey(item) in selected) {
                    removed.put(JSONObject().put("index", i).put("record", item))
                } else next.put(all.get(i))
            }
            if (removed.length() == 0) return@synchronized 0
            // The deletion and one-batch undo are committed atomically.
            if (prefs(context).edit().putString(KEY, next.toString())
                    .putString(UNDO_KEY, removed.toString()).commit()) removed.length() else -1
        } catch (_: Exception) { -1 }
    }

    /** Delete all records atomically and preserve a one-batch undo snapshot. */
    fun deleteAll(context: Context): Int = synchronized(lock) {
        try {
            val all = records(context)
            val keys = (0 until all.length()).mapNotNull { all.optJSONObject(it) }
                .map(::selectionKey).toSet()
            deleteMany(context, keys)
        } catch (_: Exception) { -1 }
    }
    fun count(context: Context): Int = synchronized(lock) {
        try { records(context).length() } catch (_: Exception) { -1 }
    }
    fun delete(context: Context, index: Int): Boolean = synchronized(lock) {
        try {
            val item = records(context).optJSONObject(index) ?: return@synchronized false
            deleteMany(context, setOf(selectionKey(item))) == 1
        } catch (_: Exception) { false }
    }

    fun canUndo(context: Context): Boolean = synchronized(lock) {
        try { JSONArray(prefs(context).getString(UNDO_KEY, "[]") ?: "[]").length() > 0 }
        catch (_: Exception) { false }
    }

    /** Restore only missing identities, preserving rows captured after deletion. */
    fun undoDelete(context: Context): Int = synchronized(lock) {
        try {
            val all = records(context)
            val saved = JSONArray(prefs(context).getString(UNDO_KEY, "[]") ?: "[]")
            if (saved.length() == 0) return@synchronized 0
            val items = (0 until all.length()).map { all.getJSONObject(it) }.toMutableList()
            val keys = items.map(::selectionKey).toMutableSet()
            var restored = 0
            for (i in 0 until saved.length()) {
                val entry = saved.getJSONObject(i)
                val item = entry.getJSONObject("record")
                if (keys.add(selectionKey(item))) {
                    items.add(entry.getInt("index").coerceIn(0, items.size), item)
                    restored++
                }
            }
            if (prefs(context).edit().putString(KEY, JSONArray(items).toString())
                    .putString(UNDO_KEY, "[]").commit()) restored else -1
        } catch (_: Exception) { -1 }
    }

    fun prompt(rows: List<Row>): String {
        val eligible = rows.filter { it.ready && it.shadow != ShadowRecognizer.State.UNKNOWN }.map { row ->
            row.copy(targets = row.targets.filter { name ->
                val shadowName = name.contains("シャドウ")
                shadowName == (row.shadow == ShadowRecognizer.State.SHADOW) && RankingEligibility.allowsLoaded(name)
            })
        }.filter { it.targets.isNotEmpty() }
        return IvSelectionText.prompt(eligible.groupBy { it.targets }.map { (key, values) ->
            IvSelectionText.Group(key, values.map {
                // Catalog IDs are PvPoke species IDs and avoid ambiguous form names.
                val source = if (it.sourceId.isNotBlank()) {
                    it.sourceId + if (it.shadow == ShadowRecognizer.State.SHADOW) "_shadow" else ""
                } else if (it.shadow == ShadowRecognizer.State.SHADOW)
                    "シャドウ" + IvSelectionText.targetName(it.source).removePrefix("シャドウ")
                    else it.source
                IvSelectionText.individual(it.iv, it.cp, source)
            })
        })
    }
}
