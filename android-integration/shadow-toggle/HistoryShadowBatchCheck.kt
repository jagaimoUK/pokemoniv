package com.example.pokemonivreader

import org.json.JSONArray
import org.json.JSONObject

fun main() {
    fun entries() = JSONArray().apply {
        for (id in listOf("a", "b", "c")) put(JSONObject().apply {
            put("recordId", id); put("cp", 717); put("attack", 0); put("defense", 11); put("hp", 12)
            put("gender", "FEMALE"); put("sourceId", "wooper"); put("sizeDecision", "manual")
            put("shadowState", "SHADOW"); put("customField", "retain")
            put("targets", JSONArray(listOf("old")))
        })
    }
    val keyOf: (JSONObject) -> String = { "id:" + it.getString("recordId") }
    val refresh: (JSONObject) -> Unit = { it.put("targets", JSONArray(listOf("evaluated:" + it.getString("shadowState")))) }
    val rows = entries()
    val untouched = rows.getJSONObject(2).toString()
    check(HistoryShadowBatch.update(rows, setOf("id:a", "id:b"), ShadowRecognizer.State.NORMAL, keyOf, refresh) == 2)
    for (i in 0..1) {
        val row = rows.getJSONObject(i)
        check(row.getString("shadowState") == "NORMAL" && row.getString("shadowMethod") == "manual")
        check(row.getInt("cp") == 717 && row.getInt("attack") == 0 && row.getInt("defense") == 11 && row.getInt("hp") == 12)
        check(row.getString("gender") == "FEMALE" && row.getString("sizeDecision") == "manual" && row.getString("customField") == "retain")
        check(row.getJSONArray("targets").getString(0) == "evaluated:NORMAL")
    }
    check(rows.getJSONObject(2).toString() == untouched)
    check(HistoryShadowBatch.update(rows, setOf("id:a", "id:b", "id:c"), ShadowRecognizer.State.SHADOW, keyOf, refresh) == 3)
    check((0..2).all { rows.getJSONObject(it).getString("shadowState") == "SHADOW" })
    val before = rows.toString()
    check(HistoryShadowBatch.update(rows, setOf("id:a", "id:deleted"), ShadowRecognizer.State.NORMAL, keyOf, refresh) == -1)
    check(rows.toString() == before)
    try {
        HistoryShadowBatch.update(rows, setOf("id:a", "id:b"), ShadowRecognizer.State.NORMAL, keyOf) {
            if (it.getString("recordId") == "b") error("simulated recalculation failure")
            refresh(it)
        }
        error("Expected recalculation failure")
    } catch (e: IllegalStateException) { check(e.message == "simulated recalculation failure") }
    check(rows.toString() == before)
    check(HistoryShadowBatch.update(rows, emptySet(), ShadowRecognizer.State.NORMAL, keyOf, refresh) == 0)
    check(HistoryShadowBatch.update(rows, setOf("id:a"), ShadowRecognizer.State.UNKNOWN, keyOf, refresh) == -1)
    val duplicate = JSONArray().put(JSONObject().put("recordId", "a")).put(JSONObject().put("recordId", "a"))
    check(HistoryShadowBatch.update(duplicate, setOf("id:a"), ShadowRecognizer.State.NORMAL, keyOf, refresh) == -1)
    println("History batch: selected/all, preserved IV/CP/metadata, refreshed targets, stale IDs, duplicate IDs and failure atomicity: PASS")
}
