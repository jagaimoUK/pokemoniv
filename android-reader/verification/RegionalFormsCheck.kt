package com.example.pokemonivreader

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.DataInputStream
import kotlin.math.hypot

fun main(args:Array<String>) {
    val root=File(args[0]); val original=JSONArray(File(root,"app/src/main/assets/pokemon_catalog.json").readText())
    CatalogData.validate(original)
    val catalog=PokemonCatalog(original)
    var checks=0
    fun expect(name:String, types:Set<String>, id:String?, complete:Boolean=false) {
        val found=catalog.recognize(name,types,observedTypesComplete=complete).species?.id
        check(found==id) { "$name $types complete=$complete: expected=$id actual=$found" }; checks++
    }
    for((name,normal,regional,base,extra) in listOf(
        listOf("Diglett","diglett","diglett_alolan","ground","steel"),
        listOf("Growlithe","growlithe","growlithe_hisuian","fire","rock"),
        listOf("Grimer","grimer","grimer_alolan","poison","dark"),
        listOf("Zigzagoon","zigzagoon","zigzagoon_galarian","normal","dark"))) {
        expect(name,emptySet(),null); expect(name,setOf(base),null)
        expect(name,setOf(base),normal,true); expect(name,setOf(base,extra),regional,true)
        expect(name,setOf(extra),regional); expect(name,setOf("fairy"),null)
        check(catalog.findById(regional)!!.evolvesTo.all { catalog.findById(it) != null }); checks++
    }
    expect("ディグダ",setOf("ground"),"diglett",true)
    expect("ディグダ（アローラ）",emptySet(),"diglett_alolan")
    expect("Hisuian Growlithe",emptySet(),"growlithe_hisuian")
    expect("Mewtwo",emptySet(),null)
    expect("Mewtwo (Armored)",emptySet(),"mewtwo_armored")
    expect("Tauros",setOf("fighting"),"tauros_combat",true)
    expect("Tauros",setOf("fighting"),null)
    expect("Tauros",setOf("fighting","water"),"tauros_aqua",true)
    // Same type forms must remain ambiguous, even with complete evidence.
    expect("Deoxys",setOf("psychic"),null,true)
    check(PumpkinForms.explicitId("バケッチャ（こだましゅ）")=="pumpkaboo_small"); checks++
    // Exercise every existing species/form group with exact, fully observed types.
    val groups=CatalogData.rows(original).groupBy { it.getString("ja") }
    for((name,variants) in groups) {
        if(PumpkinForms.familyFromText(name) != null) continue
        val typeSets=variants.map { p -> p.getJSONArray("types").let { a -> (0 until a.length()).map { a.getString(it) }.toSet() } }.distinct()
        for(ts in typeSets) {
            val matches=variants.filter { p -> p.getJSONArray("types").let { a -> (0 until a.length()).map { a.getString(it) }.toSet() } == ts }
            expect(name,ts,matches.singleOrNull()?.getString("id"),true)
        }
    }
    val upstream=JSONArray(File(args[1]).readText())
    val names=CatalogData.japaneseNames(File(args[2]).readText())
    val merged=CatalogData.merge(original,upstream,names)
    val ids=CatalogData.rows(merged).associateBy { it.getString("id") }
    for(p in CatalogData.rows(original)) {
        val updated=ids.getValue(p.getString("id"))
        for(key in listOf("gender","nextGender","evolutionNote","rankingName","display","next"))
            check(p.opt(key)?.toString()==updated.opt(key)?.toString()) { "Lost metadata ${p.getString("id")} $key" }
    }; checks++
    // Future regional form with a never-before-seen region: no Kotlin change.
    upstream.put(JSONObject().put("dex",50).put("speciesId","diglett_futureland").put("speciesName","Diglett (Futureland)")
        .put("released",true).put("baseStats",JSONObject().put("atk",109).put("def",78).put("hp",67))
        .put("types",JSONArray(listOf("ground","fairy"))))
    val future=PokemonCatalog(CatalogData.merge(original,upstream,names))
    check(future.recognize("Diglett",setOf("fairy")).species?.id=="diglett_futureland")
    check(future.recognize("Diglett (Futureland)").species?.id=="diglett_futureland")
    check(future.recognize("ディグダ（Futureland）").species?.id=="diglett_futureland"); checks+=3
    check(runCatching { CatalogData.merge(original,JSONArray(),names) }.isFailure); checks++
    check(runCatching { CatalogData.japaneseNames("invalid") }.isFailure); checks++
    // Synthetic badges exercise count and partial-visibility protection.
    fun image(xs:List<Int>, cut:Boolean=false):IntArray = IntArray(400*200) { i ->
        val x=i%400; val y=i/400
        if(xs.any { hypot((x-it).toDouble(),(y-60).toDouble())<30 && (!cut || x < it) }) 0xff60b859.toInt() else -1
    }
    check(TypeBandEvidence.count(image(listOf(200)),400,200)==1)
    check(TypeBandEvidence.count(image(listOf(150,250)),400,200)==2)
    check(TypeBandEvidence.count(image(listOf(150)),400,200)==null)
    check(TypeBandEvidence.count(image(listOf(200),true),400,200)==null)
    check(TypeBandEvidence.count(IntArray(400*200){-1},400,200)==null); checks+=5
    if(args[3] != "-") DataInputStream(File(args[3]).inputStream()).use { input ->
        val w=input.readInt(); val h=input.readInt(); val pixels=IntArray(w*h){ input.readInt() }
        check(TypeBandEvidence.count(pixels,w,h)==2) { "Reference screenshot: failed to count both badges" }; checks++
    }
    check(ScreenTextRecognizer.extractTypes("GROUND / STEEL") == setOf("ground","steel"))
    check(ScreenTextRecognizer.extractTypes("じめん / はがね") == setOf("ground","steel"))
    check(ScreenTextRecognizer.extractTypes("FIRE / ROCK / WATER").isEmpty())
    check(ScreenTextRecognizer.extractCp("CP 374") == 374)
    check(ScreenTextRecognizer.extractCaughtName("This Diglett was caught on 10/20/2026") == "Diglett"); checks+=5
    File(args[4]).writeText(merged.toString())
    println("PASS: $checks regional, update, metadata and badge checks; ${merged.length()} catalog entries")
}
