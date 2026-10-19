package com.example.pokemonivreader

import android.content.Context
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URL
import java.security.MessageDigest
import javax.net.ssl.HttpsURLConnection

/** Fixed HTTPS data sources only. No screenshots, history or device data is sent. */
internal object CatalogUpdates {
    private const val POKEMON = "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster/pokemon.json"
    private const val NAMES = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv"
    private const val DAY = 24*60*60*1000L
    private const val RETRY = 60*60*1000L
    private val fileLock = Any()
    private val updateLock = Any()
    private fun file(context:Context) = AtomicFile(File(context.filesDir,"pokemon_catalog_auto_v1.json"))
    private fun bundled(context:Context) = context.assets.open("pokemon_catalog.json").bufferedReader().use { JSONArray(it.readText()) }
    fun read(context:Context):JSONArray = synchronized(fileLock) {
        val base=bundled(context)
        try {
            val document=file(context).openRead().bufferedReader().use { JSONObject(it.readText()) }
            require(document.getInt("schema") == 1)
            val entries=document.getJSONArray("entries")
            require(document.getString("sha256") == digest(entries.toString()))
            CatalogData.validate(entries)
            // Cached entries preserve their stable IDs; newer bundled metadata wins.
            val cached=CatalogData.rows(entries).associateByTo(linkedMapOf()) { it.getString("id") }
            CatalogData.rows(base).forEach { p ->
                val latest=cached[p.getString("id")]
                if(latest != null) for(key in listOf("stats","types","dex"))
                    if(latest.has(key)) p.put(key,latest.get(key))
                cached[p.getString("id")] = p
            }
            JSONArray(cached.values.toList())
        } catch (_:Exception) { base }
    }
    fun status(context:Context):String = context.getSharedPreferences("catalog_updates",Context.MODE_PRIVATE)
        .getString("status","地方の姿の図鑑を自動更新します（通信できないときは保存済みデータを使用）").orEmpty()
    fun refresh(context:Context, force:Boolean=false):String = synchronized(updateLock) {
        val prefs=context.getSharedPreferences("catalog_updates",Context.MODE_PRIVATE)
        val now=System.currentTimeMillis()
        if(!force && (now-prefs.getLong("success",0) in 0 until DAY || now-prefs.getLong("attempt",0) in 0 until RETRY)) return@synchronized status(context)
        prefs.edit().putLong("attempt",now).apply()
        try {
            val base=read(context)
            val entries=CatalogData.merge(base,JSONArray(download(POKEMON)),CatalogData.japaneseNames(download(NAMES)))
            PokemonCatalog(entries) // Build all name/form indexes before publishing the cache.
            val document=JSONObject().put("schema",1).put("fetchedAt",now)
                .put("sha256",digest(entries.toString())).put("entries",entries)
            synchronized(fileLock) {
                val atomic=file(context); val stream=atomic.startWrite()
                try { stream.write(document.toString().toByteArray(Charsets.UTF_8)); atomic.finishWrite(stream) }
                catch(e:Exception) { atomic.failWrite(stream); throw e }
            }
            RankingEligibility.invalidate()
            PokemonCatalog.invalidate()
            val message="地方の姿の図鑑：更新を確認しました（${entries.length()}種類）"
            prefs.edit().putLong("success",now).putString("status",message).apply()
            message
        } catch (_:Exception) {
            val message="図鑑の更新を確認できませんでした。保存済みデータで読み取れます（次回自動で再試行）"
            prefs.edit().putString("status",message).apply()
            message
        }
    }
    private fun digest(text:String)=MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun download(address:String):String {
        val connection=URL(address).openConnection() as HttpsURLConnection
        connection.connectTimeout=15000; connection.readTimeout=15000; connection.instanceFollowRedirects=false
        connection.setRequestProperty("User-Agent","PokemonIVReader-Catalog/2")
        try {
            require(connection.responseCode == 200)
            return connection.inputStream.use { input ->
                val output=java.io.ByteArrayOutputStream()
                val buffer=ByteArray(8192)
                while(true) {
                    val count=input.read(buffer)
                    if(count < 0) break
                    require(output.size()+count <= 8*1024*1024)
                    output.write(buffer,0,count)
                }
                output.toString("UTF-8").removePrefix("\uFEFF")
            }
        } finally { connection.disconnect() }
    }
}
