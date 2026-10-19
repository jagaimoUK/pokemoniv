package com.example.pokemonivreader

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions
import com.google.android.gms.tasks.Task
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.text.Text

/** Local OCR of name, CP and the visible type-label band. */
internal object ScreenTextRecognizer {
    data class TextResult(
        val cp: Int?,
        val nameText: String,
        val diagnostic: String,
        val rawNameText: String = "",
        val rawTypeText: String = "",
        val types: Set<String> = emptySet(),
        val rawShadowText: String = "",
        val purifyAction: Boolean = false,
        val heightText: String = "",
        val typesComplete: Boolean = false,
        val typeBadgeCount: Int? = null
    )
    private val recognizer by lazy {
        TextRecognition.getClient(JapaneseTextRecognizerOptions.Builder().build())
    }
    private val cpPattern = Regex("(?:CP|ＣＰ)\\s*[:：]?\\s*([0-9０-９]{1,5})", RegexOption.IGNORE_CASE)
    // Read the appraisal sentence, never the editable nickname above the panel.
    private val caughtPattern = Regex(
        """\bThis\s+(.{1,80}?)\s+was\s+caught\s+on\b""",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
    )

    internal fun extractCaughtName(raw: String): String? {
        val normalized = java.text.Normalizer.normalize(raw, java.text.Normalizer.Form.NFKC)
            .replace('\u00a0', ' ')
        val names = caughtPattern.findAll(normalized).map {
            it.groupValues[1].replace(Regex("\\s+"), " ").trim()
        }.filter { it.isNotBlank() }.distinct().toList()
        // If the anchors are missing or there are two different names, keep it pending.
        return names.singleOrNull()
    }

    private val typeNames = mapOf(
        "normal" to "ノーマル", "fire" to "ほのお", "water" to "みず",
        "electric" to "でんき", "grass" to "くさ", "ice" to "こおり",
        "fighting" to "かくとう", "poison" to "どく", "ground" to "じめん",
        "flying" to "ひこう", "psychic" to "エスパー", "bug" to "むし",
        "rock" to "いわ", "ghost" to "ゴースト", "dragon" to "ドラゴン",
        "dark" to "あく", "steel" to "はがね", "fairy" to "フェアリー"
    )

    internal fun extractTypes(raw: String): Set<String> {
        val text = java.text.Normalizer.normalize(raw, java.text.Normalizer.Form.NFKC)
        val matches = typeNames.filter { (english, japanese) ->
            listOf(english, japanese).any { word ->
                Regex("(?<![\\p{L}])${Regex.escape(word)}(?![\\p{L}])", RegexOption.IGNORE_CASE)
                    .containsMatchIn(text)
            }
        }.keys.toSet()
        // Three or more distinct labels cannot describe one Pokémon.
        return matches.takeIf { it.size <= 2 } ?: emptySet()
    }

    internal var callbackExecutor: java.util.concurrent.Executor = java.util.concurrent.Executors.newSingleThreadExecutor { r ->
        Thread(r, "IvReaderOcrResults").apply { isDaemon = true }
    }

    fun warmUp() {
        val crop = Bitmap.createBitmap(32,32,Bitmap.Config.ARGB_8888)
        try { recognizer.process(InputImage.fromBitmap(crop,0)).addOnCompleteListener(callbackExecutor) { crop.recycle() } }
        catch (_: Exception) { crop.recycle() }
    }

    internal fun extractCp(raw: String, allowBare: Boolean = false): Int? {
        val normalized=java.text.Normalizer.normalize(raw,java.text.Normalizer.Form.NFKC)
        val labeled=Regex("""C\s*P\s*[:.：]?\s*([0-9]{1,5})(?![0-9])""",RegexOption.IGNORE_CASE)
            .findAll(normalized).map{it.groupValues[1].toIntOrNull()}.toList()
        if(labeled.isNotEmpty())return labeled.distinct().singleOrNull()?.takeIf{it in 10..99999}
        if(!allowBare)return null
        return Regex("""^\s*([0-9]{1,5})\s*$""").find(normalized)?.groupValues?.get(1)
            ?.toIntOrNull()?.takeIf{it in 10..99999}
    }

    fun recognize(nameCrop: Bitmap, cpCrop: Bitmap, typeCrop: Bitmap? = null,
                  shadowCrop: Bitmap? = null, cpFallback: Bitmap? = null,
                  heightCrop: Bitmap? = null,
                  needsTypes: (String) -> Boolean = { true },
                  cpReady: (Int?) -> Unit = {}, done: (TextResult) -> Unit) {
        val jobs = mutableListOf<Task<Text>>()
        var typeImage: Bitmap? = null
        fun start(crop:Bitmap)=recognizer.process(InputImage.fromBitmap(crop,0))
        fun startType():Task<Text> {
            val crop=checkNotNull(typeCrop)
            val image=if(crop.width < 800) Bitmap.createScaledBitmap(crop,crop.width*2,crop.height*2,true) else crop
            typeImage=image
            return start(image)
        }
        fun recycle(){listOfNotNull(nameCrop,cpCrop,typeImage,shadowCrop,cpFallback,heightCrop).distinct().forEach{it.recycle()}}
        val cpTask:Task<Text>
        val nameTask:Task<Text>
        val shadowTask:Task<Text>?
        try {
            val firstCp=start(cpCrop).also{jobs+=it}
            cpTask=firstCp.continueWithTask(callbackExecutor) { task ->
                val raw=if(task.isSuccessful)task.result?.text.orEmpty() else ""
                if(extractCp(raw,true)!=null || cpFallback==null) task else start(cpFallback)
            }.also{jobs+=it}
            cpTask.addOnCompleteListener(callbackExecutor) { task ->
                val raw=if(task.isSuccessful)task.result?.text.orEmpty() else ""
                cpReady(extractCp(raw,true))
            }
            nameTask=start(nameCrop).also{jobs+=it}
            shadowTask=shadowCrop?.let{start(it).also{job->jobs+=job}}
        } catch (_:Exception) {
            Tasks.whenAllComplete(jobs).addOnCompleteListener(callbackExecutor) {
                recycle();done(TextResult(null,"","OCR開始失敗"))
            }
            return
        }
        Tasks.whenAllComplete(jobs).addOnCompleteListener(callbackExecutor) {
            val cpRaw=if(cpTask.isSuccessful)cpTask.result?.text.orEmpty() else ""
            val cp=extractCp(cpRaw,true)
            val nameRaw=if(nameTask.isSuccessful)nameTask.result?.text.orEmpty() else ""
            val name=extractCaughtName(nameRaw).orEmpty()
            val shadowRaw=if(shadowTask?.isSuccessful==true)shadowTask.result?.text.orEmpty() else ""
            val readTypes=typeCrop!=null && name.isNotBlank() && try { needsTypes(name) } catch (_:Exception) { false }
            // Count badges only when forms need type OCR; ordinary species stay fast.
            val badgeCount = if(readTypes && typeCrop != null) try {
                val pixels = IntArray(typeCrop.width*typeCrop.height)
                typeCrop.getPixels(pixels,0,typeCrop.width,0,0,typeCrop.width,typeCrop.height)
                TypeBandEvidence.count(pixels,typeCrop.width,typeCrop.height)
            } catch (_:Exception) { null } else null
            fun finish(typeRaw:String, heightRaw:String = "") {
                val types = extractTypes(typeRaw)
                recycle()
                done(TextResult(cp,name,when {
                    !cpTask.isSuccessful || !nameTask.isSuccessful -> "OCR処理に失敗"
                    nameRaw.isBlank() -> "ポケモン名を読み取れません"
                    name.isBlank() -> "下側の捕獲文から名前を抽出できません"
                    cp==null -> "CPを読み取れません"
                    else -> ""
                },nameRaw,typeRaw,extractTypes(typeRaw),shadowRaw,ShadowRecognizer.hasPurifyAction(shadowRaw),heightRaw,
                    badgeCount != null && badgeCount == types.size, badgeCount))
            }
            val readHeight=heightCrop!=null && PumpkinForms.familyFromText(name)!=null
            // Only the pumpkin family needs Height OCR. Avoid slowing other captures.
            if (readHeight) {
                try {
                    val heightTask = start(heightCrop!!)
                    if (typeCrop != null && readTypes) {
                        val typeTask = startType()
                        Tasks.whenAllComplete(listOf(heightTask, typeTask)).addOnCompleteListener(callbackExecutor) {
                            val typeRaw = if (typeTask.isSuccessful) typeTask.result?.text.orEmpty() else ""
                            val heightRaw = if (heightTask.isSuccessful) heightTask.result?.text.orEmpty() else ""
                            finish(typeRaw, heightRaw)
                        }
                    } else heightTask.addOnCompleteListener(callbackExecutor) { task ->
                        finish("", if(task.isSuccessful) task.result?.text.orEmpty() else "")
                    }
                } catch (_:Exception) { finish("") }
            } else if (typeCrop != null && readTypes) {
                try { startType().addOnCompleteListener(callbackExecutor) { task -> finish(if(task.isSuccessful)task.result?.text.orEmpty() else "") } }
                catch (_:Exception){finish("")}
            } else finish("")
        }
    }
}
