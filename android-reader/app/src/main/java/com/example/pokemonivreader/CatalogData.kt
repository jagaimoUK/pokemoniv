package com.example.pokemonivreader

import org.json.JSONArray
import org.json.JSONObject

/** Data-only conversion: no per-species or regional-species allowlist. */
internal object CatalogData {
    val types = setOf("normal","fire","water","electric","grass","ice","fighting","poison","ground",
        "flying","psychic","bug","rock","ghost","dragon","dark","steel","fairy")
    private val temporary = setOf("shadow","mega","primal","gigantamax","dynamax")
    private val translated = mapOf("Alolan" to "アローラ", "Galarian" to "ガラル", "Hisuian" to "ヒスイ", "Paldean" to "パルデア")
    fun rows(array: JSONArray): List<JSONObject> = (0 until array.length()).map { array.getJSONObject(it) }
    fun validate(array: JSONArray) {
        require(array.length() >= 500) { "図鑑の件数が不足しています" }
        val ids = mutableSetOf<String>()
        rows(array).forEach { p ->
            require(p.getString("id").matches(Regex("[a-z0-9_]+")) && ids.add(p.getString("id")))
            require(p.getString("ja").isNotBlank())
            val stats = p.getJSONArray("stats")
            require(stats.length() == 3 && (0..2).all { stats.getInt(it) in 1..1000 })
            val ts = p.getJSONArray("types")
            require(ts.length() in 1..2 && (0 until ts.length()).all { ts.getString(it) in types })
        }
    }
    fun japaneseNames(csv: String): Map<Int,String> {
        // RFC 4180 quoting, including commas, quotes and newlines inside fields.
        val rows = mutableListOf<List<String>>(); var row = mutableListOf<String>()
        val field = StringBuilder(); var quoted = false; var i = 0
        while (i < csv.length) {
            val c = csv[i++]
            when {
                c == '"' && quoted && i < csv.length && csv[i] == '"' -> { field.append('"'); i++ }
                c == '"' -> quoted = !quoted
                c == ',' && !quoted -> { row.add(field.toString()); field.setLength(0) }
                c == '\n' && !quoted -> { row.add(field.toString().trimEnd('\r')); rows.add(row); row=mutableListOf(); field.setLength(0) }
                else -> field.append(c)
            }
        }
        require(!quoted)
        if(field.isNotEmpty() || row.isNotEmpty()) { row.add(field.toString().trimEnd('\r')); rows.add(row) }
        require(rows.isNotEmpty())
        val header=rows.first().map { it.removePrefix("\uFEFF") }
        val dex=header.indexOf("pokemon_species_id"); val lang=header.indexOf("local_language_id"); val name=header.indexOf("name")
        require(minOf(dex,lang,name) >= 0)
        val result=mutableMapOf<Int,String>()
        for (language in listOf("1","11")) rows.drop(1).forEach { r ->
            val id=r.getOrNull(dex)?.toIntOrNull()
            if(id != null && r.getOrNull(lang) == language && !r.getOrNull(name).isNullOrBlank()) result[id]=r[name]
        }
        require(result.size >= 500)
        return result
    }
    fun merge(baseline: JSONArray, upstream: JSONArray, japanese: Map<Int,String>): JSONArray {
        validate(baseline)
        require(upstream.length() >= 500)
        val result=rows(baseline).associateByTo(linkedMapOf()) { it.getString("id") }
        var accepted=0
        rows(upstream).forEach { p ->
            val id=p.optString("speciesId"); val dex=p.optInt("dex")
            if(p.optBoolean("released",false).not() || id.isBlank() || id.split('_').any { it in temporary }) return@forEach
            val name=japanese[dex] ?: return@forEach
            val base=p.optJSONObject("baseStats") ?: return@forEach
            val ts=p.optJSONArray("types") ?: return@forEach
            val typeList=(0 until ts.length()).map { ts.optString(it) }.filter { it in types }.distinct()
            require(typeList.size in 1..2)
            val stats=listOf(base.getInt("atk"),base.getInt("def"),base.getInt("hp"))
            require(stats.all { it in 1..1000 })
            val old=result[id]
            val next=JSONObject(old?.toString() ?: "{}")
            val english=p.getString("speciesName")
            val rootName=english.substringBefore(" (")
            val qualifier=english.substringAfter(" (","").removeSuffix(")")
            val form=old?.optString("form")?.takeIf { it.isNotBlank() } ?: if(qualifier.isBlank()) "normal" else qualifier.lowercase(java.util.Locale.ROOT).replace(Regex("[^a-z0-9]+"),"_")
            next.put("id",id).put("dex",dex).put("ja",old?.optString("ja")?.takeIf { it.isNotBlank() } ?: name)
                .put("form",form).put("stats",JSONArray(stats)).put("types",JSONArray(typeList))
            val aliases=old?.optJSONArray("englishNames")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
            val formPrefix=qualifier.takeIf { it.isNotBlank() }?.let { "$it $rootName" }
            next.put("englishNames",JSONArray((aliases+listOfNotNull(rootName,english,id,formPrefix)).distinct()))
            if(old == null) {
                val label=translated[qualifier] ?: qualifier
                next.put("display",if(label.isBlank()) name else "$name（$label）")
                next.put("next",p.optJSONObject("family")?.optJSONArray("evolutions") ?: JSONArray())
            }
            result[id]=next; accepted++
        }
        require(accepted >= 500) { "取得データが不完全です" }
        val ids=result.keys
        result.values.forEach { p ->
            val a=p.optJSONArray("next") ?: JSONArray()
            p.put("next",JSONArray((0 until a.length()).map { a.getString(it) }.filter { it in ids }))
        }
        return JSONArray(result.values.toList()).also(::validate)
    }
}
