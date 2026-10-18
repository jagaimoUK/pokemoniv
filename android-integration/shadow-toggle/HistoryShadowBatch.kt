package com.example.pokemonivreader

import org.json.JSONArray
import org.json.JSONObject

/** Prepare all edited records before touching the array; the caller persists it once. */
internal object HistoryShadowBatch {
    fun update(
        entries: JSONArray,
        keys: Set<String>,
        state: ShadowRecognizer.State,
        keyOf: (JSONObject) -> String,
        refresh: (JSONObject) -> Unit
    ): Int {
        if (keys.isEmpty()) return 0
        if (state == ShadowRecognizer.State.UNKNOWN) return -1
        val selected = (0 until entries.length()).mapNotNull { index ->
            entries.optJSONObject(index)?.takeIf { keyOf(it) in keys }?.let { index to it }
        }
        if (selected.size != keys.size || selected.map { keyOf(it.second) }.toSet() != keys) return -1
        val staged = selected.map { (index, original) ->
            val item = JSONObject(original.toString())
            refresh(item) // Retain legacy readiness before recomputing targets.
            item.put("shadowState", state.name)
            item.put("shadowMethod", "manual")
            item.put("shadowDecision", "履歴を一括で${state.label}に変更")
            refresh(item)
            index to item
        }
        staged.forEach { (index, item) -> entries.put(index, item) }
        return staged.size
    }
}
