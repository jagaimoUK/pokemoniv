package com.example.pokemonivreader

import android.content.Context
import android.graphics.Bitmap
import android.media.Image
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Phase 3E: read IV instantly, then OCR name/CP asynchronously before saving. */
internal object OverlayIvProcessor {
    private const val PREFS = "pokemon_iv_reader"
    private const val RECORDS_KEY = "auto_iv_records_v1"

    enum class Phase { SNAPSHOT, CP_READY, SAVED, REVIEW, FAILED }
    data class Outcome(val text: String, val added: Boolean, val displayIv: String? = null,
                       val displayCp: Int? = null, val phase: Phase = if(added) Phase.SAVED else Phase.FAILED)
    internal var worker: java.util.concurrent.Executor = java.util.concurrent.Executors.newSingleThreadExecutor { r ->
        Thread(r,"IvReaderStorage").apply { isDaemon=true }
    }

    /**
     * Store one result even if OCR fails. Such entries remain unconfirmed and
     * have empty targets, so AutoIvRecords.prompt() cannot silently export them.
     */
    fun process(context: Context, frame: Image,
                shadowFrames: List<ShadowRecognizer.Evidence> = emptyList(),
                shadowProvider: () -> List<ShadowRecognizer.Evidence> = { shadowFrames },
                onCaptured: () -> Unit = {}, onProgress: (Outcome) -> Unit = {},
                scanModeOverride: ShadowRecognizer.Mode? = null, done: (Outcome) -> Unit) {
        var observedCp: Int? = null
        fun finish(outcome: Outcome) = done(outcome.copy(displayCp=outcome.displayCp ?: observedCp))
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val scanMode = scanModeOverride ?: ShadowRecognizer.Mode.fromStored(prefs.getString(ShadowRecognizer.MODE_KEY, null))
        val raw = prefs.getString("crop_template_v1", null)
            ?: return finish(Outcome("先に評価パネルを範囲指定してね", false))
        val cfg = try { JSONObject(raw) } catch (_: Exception) {
            return finish(Outcome("評価パネルの設定を読み直してね", false))
        }
        val coordinates = listOf("x1", "y1", "x2", "y2").map { cfg.optDouble(it, Double.NaN) }
        val ratio = cfg.optDouble("aspect", Double.NaN)
        if (coordinates.any { !it.isFinite() || it !in 0.0..1.0 } || !ratio.isFinite() || ratio <= 0.0) {
            return finish(Outcome("パネルの設定が無効", false))
        }
        if (abs(frame.width.toDouble() / frame.height - ratio) / ratio > 0.025) {
            return finish(Outcome("画面の向き・比率が変わりました", false))
        }
        val (x1, y1, x2, y2) = coordinates
        val l = (min(x1, x2) * frame.width).roundToInt().coerceIn(0, frame.width - 1)
        val r = (max(x1, x2) * frame.width).roundToInt().coerceIn(l + 1, frame.width)
        val t = (min(y1, y2) * frame.height).roundToInt().coerceIn(0, frame.height - 1)
        val b = (max(y1, y2) * frame.height).roundToInt().coerceIn(t + 1, frame.height)
        if (r - l < 100 || b - t < 100) return finish(Outcome("範囲が狭すぎます", false))

        val panel = copyRegion(frame, l, t, r - l, b - t)
        val sensitivity = IvBarRecognizer.Sensitivity.entries.firstOrNull {
            it.name == prefs.getString("bar_color_sensitivity_v1", null)
        } ?: IvBarRecognizer.Sensitivity.NORMAL
        val pixels = IntArray(panel.width * panel.height)
        try {
            panel.getPixels(pixels, 0, panel.width, 0, 0, panel.width, panel.height)
        } finally {
            panel.recycle()
        }
        val result = IvBarRecognizer.read(pixels, r - l, b - t, sensitivity)
            ?: return finish(Outcome("個体値のバーを検出できません", false))
        val ivText = "${result.attack},${result.defense},${result.hp}"
        val displayIvText=if(result.reliable)ivText else "$ivText ?"

        // This is an IV-only pending record. Only the status changes after OCR;
        // it is never inserted a second time when name/CP recognition succeeds.
        val recordId = java.util.UUID.randomUUID().toString()
        val record = JSONObject().apply {
            put("recordId", recordId)
            put("sourceId", "")
            put("source", "要確認")
            put("cp", 0) // 0 means unknown, NOT a real Pokémon CP.
            put("attack", result.attack)
            put("defense", result.defense)
            put("hp", result.hp)
            put("targets", JSONArray())
            put("borderline", JSONArray())
            put("excluded", JSONArray())
            put("status", "pending")
            put("recognitionReady", false)
            put("ivReliable", result.reliable)
            put("shadowState", ShadowRecognizer.State.UNKNOWN.name)
            put("shadowMethod", "unknown")
            put("diagnostic", if (result.reliable) "名前・CPを読み取り中" else "個体値の確度が低い")
            put("capturedAt", System.currentTimeMillis())
        }
        // Create bitmap copies before the ImageReader image is closed. OCR is async.
        val cpCrop: Bitmap
        val cpFallback: Bitmap
        val nameCrop: Bitmap
        val typeCrop: Bitmap
        val shadowCrop: Bitmap
        val heightCrop: Bitmap
        var aura = ShadowRecognizer.Evidence(false, "オーラ未解析")
        var genderReading = GenderRecognizer.Result(GenderRecognizer.Gender.UNKNOWN, "性別未解析")
        val crops = mutableListOf<Bitmap>()
        try {
            cpCrop = copyNormalized(frame, 0.27, 0.035, 0.75, 0.115).also { crops += it }
            cpFallback = copyNormalized(frame, 0.18, 0.02, 0.82, 0.22).also { crops += it }
            // Bottom appraisal speech bubble: "This <species> was caught on ...".
            // Verified against the 1220 x 2712 reference screenshot (2026-10-15).
            // Keep the whole line width so long names and wrapping are not clipped.
            nameCrop = copyNormalized(frame, 0.02, 0.89, 0.98, 0.995).also { crops += it }
            // Covers the central type labels with/without the Remote Trade badge.
            // A hidden or partially recognized label is never guessed from color.
            typeCrop = copyNormalized(frame, 0.30, 0.50, 0.70, 0.62).also { crops += it }
            // Right-hand Height field only (m and its adjacent XS/XL/XXL badge). Excludes Weight on the left.
            heightCrop = copyNormalized(frame, 0.665, 0.505, 0.985, 0.635).also { crops += it }
            // Fixed action-button band. Nicknames/caught text cannot confirm shadow.
            shadowCrop = copyNormalized(frame, 0.04, 0.72, 0.47, 0.83).also { crops += it }
            aura = shadowFrames.lastOrNull() ?: inspectShadowFrame(frame)
            genderReading = inspectGenderFrame(frame)
        } catch (e: Exception) {
            crops.forEach { it.recycle() }
            record.put("diagnostic", "文字の画像切り出しに失敗")
            val saved=AutoIvRecords.save(context, recordId, record, insert=true)
            return finish(Outcome(if(saved) "$ivText / 個体値のみ仮保存（画像切り出し失敗）" else "保存に失敗", false, displayIvText))
        }

        // Every Bitmap below belongs to THIS frame. The game can move while OCR runs.
        onCaptured()
        onProgress(Outcome("画像を確保しました", false, displayIvText, phase=Phase.SNAPSHOT))
        worker.execute {
        if (!AutoIvRecords.save(context, recordId, record, insert=true)) {
            crops.forEach { it.recycle() }
            finish(Outcome("個体値の保存に失敗",false,displayIvText));return@execute
        }
        try {
            ScreenTextRecognizer.recognize(nameCrop, cpCrop, typeCrop, shadowCrop, cpFallback, heightCrop,
                needsTypes = { name -> PumpkinForms.familyFromText(name) == null &&
                    PokemonCatalog.get(context).recognize(name, observedGender=genderReading.gender).species==null },
                cpReady = { cp ->
                    observedCp=cp
                    onProgress(Outcome(if(cp==null) "CPを読み取れません" else "CPを認識しました",false,displayIvText,cp,Phase.CP_READY))
                }) { ocr ->
                try {
                    val decision = if (scanModeOverride != null) ReaderShadowControls.decide(scanMode, ocr.purifyAction, shadowProvider())
                        else ShadowRecognizer.decide(scanMode, ocr.purifyAction, shadowProvider())
                    val shadow = decision.state
                    record.put("gender", genderReading.gender.name)
                    record.put("genderMethod", if (genderReading.gender == GenderRecognizer.Gender.UNKNOWN) "unknown" else "icon")
                    record.put("genderEvidence", genderReading.diagnostic)
                    record.put("shadowState", shadow.name)
                    record.put("shadowMethod", decision.method)
                    record.put("shadowDecision", decision.diagnostic)
                    record.put("shadowSuggestion", if (aura.suggestedShadow) "SHADOW" else "")
                    record.put("shadowEvidence", decision.diagnostic + " / " + aura.diagnostic)
                    if (ocr.cp != null) record.put("cp", ocr.cp)
                    record.put("nameCandidate", ocr.nameText)
                    // Existing UI already shows nameOcr for unresolved records.
                    record.put("nameOcr", "抽出: ${ocr.nameText.ifBlank { "未認識" }}" +
                        "\nタイプOCR: ${ocr.rawTypeText.take(45).ifBlank { "未認識" }}" +
                        "\n判定タイプ: ${ocr.types.joinToString("/").ifBlank { "なし" }}" +
                        "\n${ocr.rawNameText.take(300)}")
                    record.put("typeOcr", ocr.rawTypeText.take(300))
                    record.put("observedTypes", JSONArray(ocr.types.toList()))
                    record.put("observedTypesComplete", ocr.typesComplete)
                    record.put("typeBadgeCount", ocr.typeBadgeCount ?: 0)
                    if (PumpkinForms.familyFromText(ocr.nameText) == null) record.put("formMethod", "catalog_types_v2")
                    val catalog = PokemonCatalog.get(context)
                    record.put("catalogCount", catalog.speciesCount)
                    val pumpkin = PumpkinForms.familyFromText(ocr.nameText)
                    val size = pumpkin?.let { PumpkinHeightClassifier.classify(ocr.heightText) }
                    if (size != null) {
                        record.put("heightOcr", ocr.heightText.take(250))
                        record.put("heightBadge", size.badge)
                        record.put("sizeDecision", if (size.form == null) "unresolved" else "height")
                    }
                    val resolution = if (pumpkin == null) {
                        catalog.recognize(ocr.nameText, ocr.types, genderReading.gender, ocr.typesComplete)
                    } else {
                        val id = size?.form?.let { "${pumpkin}_$it" }
                            ?: PumpkinForms.explicitId(ocr.nameText)
                        val found = id?.let(catalog::findById)
                        PokemonCatalog.Resolution(found, if (found == null)
                            size?.message?.ifBlank { "サイズ別図鑑が見つかりません" }
                                ?: "サイズを特定できません" else "")
                    }
                    val species = resolution.species
                    if (species != null) {
                        record.put("source", species.displayName)
                        record.put("sourceId", species.id)
                    }
                    if (ocr.cp == null || species == null) {
                        val reason = listOfNotNull(
                            if (ocr.cp == null) "CP未認識" else null,
                            if (species == null) {
                                if (ocr.nameText.isBlank()) ocr.diagnostic.ifBlank {
                                    "下側の捕獲文から名前を抽出できません"
                                } else resolution.message
                            } else null
                        ).joinToString(" / ")
                        record.put("diagnostic", reason)
                        val updated = saveRecord(context, recordId, record)
                        val note = if (updated) "要確認として仮保存" else "仮保存済み・更新失敗"
                        return@recognize finish(Outcome("$ivText / $reason：$note", false, displayIvText, ocr.cp, Phase.REVIEW))
                    }
                    // No ambiguity: valid IV, recognized species/form, and numeric CP.
                    val evaluation = catalog.evaluate(
                        species, ocr.cp, intArrayOf(result.attack, result.defense, result.hp), shadow, genderReading.gender
                    )
                    record.put("targets", JSONArray(evaluation.eligible))
                    record.put("borderline", JSONArray(evaluation.borderline))
                    record.put("excluded", JSONArray(evaluation.excluded))
                    record.put("genderPending", JSONArray(evaluation.genderPending))
                    record.put("recognitionReady", true)
                    record.put("status", if (shadow == ShadowRecognizer.State.UNKNOWN) "pending" else "confirmed")
                    record.put("diagnostic", catalog.rankingProblem)
                    val saved = saveRecord(context, recordId, record)
                    if (!saved) {
                        return@recognize finish(Outcome("$ivText / 正式登録への更新に失敗", false, displayIvText))
                    }
                    val eligible = evaluation.eligible.joinToString("、")
                        .ifEmpty { catalog.rankingProblem.ifBlank { if (shadow == ShadowRecognizer.State.UNKNOWN) "判定が不一致のため再読取してください" else if (RankingEligibility.get(context).mode == RankingEligibility.Mode.ALL_SPECIES) "CP1500以下の候補なし" else "総合70以上・CP1500以下の候補なし" } }
                    val uncertain = if (evaluation.borderline.isNotEmpty()) {
                        " / 判定保留:${evaluation.borderline.joinToString("、")}" 
                    } else ""
                    val sexNote = if (evaluation.genderPending.isNotEmpty()) " / 性別条件の未確認あり" else ""
                    val shadowLabel = if (shadow == ShadowRecognizer.State.SHADOW) "シャドウ" else
                        if (aura.suggestedShadow) "再読取が必要" else if (shadow == ShadowRecognizer.State.NORMAL) "通常" else "再読取が必要"
                    finish(Outcome("$ivText | ${species.displayName} CP${ocr.cp} [$shadowLabel] → $eligible$uncertain$sexNote", true,
                            OverlayEligibilityBadge.decorate(
                                displayIvText,
                                OverlayEligibilityBadge.classify(
                                    ranked70Mode = RankingEligibility.get(context).mode == RankingEligibility.Mode.RANKED_70,
                                    rankingReady = catalog.rankingProblem.isBlank(),
                                    shadowKnown = shadow != ShadowRecognizer.State.UNKNOWN,
                                    eligibleCount = evaluation.eligible.size,
                                    borderlineCount = evaluation.borderline.size,
                                    genderPendingCount = evaluation.genderPending.size
                                ),
                                true
                            ), ocr.cp,
                        if(shadow==ShadowRecognizer.State.UNKNOWN || evaluation.genderPending.isNotEmpty() || !result.reliable) Phase.REVIEW else Phase.SAVED))
                } catch (e: Exception) {
                    record.put("status", "pending")
                    record.put("targets", JSONArray())
                    record.put("diagnostic", "処理エラー：${e.javaClass.simpleName}")
                    saveRecord(context, recordId, record)
                    finish(Outcome("$ivText / 個体値のみ仮保存（解析エラー）", false, displayIvText))
                }
            }
        } catch (e: Exception) {
            record.put("diagnostic", "OCR開始失敗：${e.javaClass.simpleName}")
            saveRecord(context, recordId, record)
            finish(Outcome("$ivText / 個体値のみ仮保存（OCR開始失敗）", false, displayIvText))
        }
        }
    }

    fun inspectGenderFrame(frame: Image): GenderRecognizer.Result = try {
        val crop = copyNormalized(frame, 0.80, 0.40, 0.94, 0.47)
        try {
            val pixels = IntArray(crop.width * crop.height)
            crop.getPixels(pixels, 0, crop.width, 0, 0, crop.width, crop.height)
            GenderRecognizer.read(pixels, crop.width, crop.height)
        } finally { crop.recycle() }
    } catch (_: Exception) { GenderRecognizer.Result(GenderRecognizer.Gender.UNKNOWN, "性別画像を解析できません") }

    fun inspectShadowFrame(frame: Image): ShadowRecognizer.Evidence = try {
        val sample=samplePixels(frame,0.14,0.12,0.82,0.35,144,96)
        ShadowRecognizer.inspect(sample,144,96)
    } catch (_:Exception) { ShadowRecognizer.Evidence(false,"オーラ画像を解析できません") }

    fun sceneSignature(frame: Image, panel: DoubleArray?): CaptureGate.Signature {
        val cp=samplePixels(frame,0.27,0.035,0.75,0.115,64,12).map { pixel ->
            // CP glyphs are white. Ignore moving colored scenery behind the text.
            if(((pixel ushr 16)and 255)>210 && ((pixel ushr 8)and 255)>210 && (pixel and 255)>210) -1 else 0xff000000.toInt()
        }.toIntArray()
        val name=samplePixels(frame,0.02,0.89,0.98,0.995,64,12)
        val iv=if(panel!=null && panel.size==4) samplePixels(frame,panel[0],panel[1],panel[2],panel[3],64,24) else IntArray(0)
        val gender=samplePixels(frame,0.80,0.40,0.94,0.47,24,12)
        val typeBand=samplePixels(frame,0.30,0.50,0.70,0.62,48,16)
        return CaptureGate.Signature(cp+name+iv+gender+typeBand,intArrayOf(cp.size,name.size,iv.size,gender.size,typeBand.size))
    }

    private fun samplePixels(frame:Image,x1:Double,y1:Double,x2:Double,y2:Double,w:Int,h:Int):IntArray {
        val plane=frame.planes.firstOrNull() ?: error("画像がありません")
        require(plane.pixelStride==4)
        val source=plane.buffer.duplicate()
        return IntArray(w*h){ n ->
            val x=((x1+(x2-x1)*(n%w+0.5)/w)*frame.width).toInt().coerceIn(0,frame.width-1)
            val y=((y1+(y2-y1)*(n/w+0.5)/h)*frame.height).toInt().coerceIn(0,frame.height-1)
            val at=y*plane.rowStride+x*4
            val r=source.get(at).toInt() and 255;val g=source.get(at+1).toInt() and 255;val b=source.get(at+2).toInt() and 255
            (255 shl 24) or (r shl 16) or (g shl 8) or b
        }
    }

    private fun saveRecord(context: Context, recordId: String, record: JSONObject): Boolean =
        AutoIvRecords.save(context, recordId, record)

    private fun copyNormalized(image:Image,x1:Double,y1:Double,x2:Double,y2:Double):Bitmap {
        val left = (x1*image.width).roundToInt().coerceIn(0,image.width-1)
        val right = (x2*image.width).roundToInt().coerceIn(left+1,image.width)
        val top = (y1*image.height).roundToInt().coerceIn(0,image.height-1)
        val bottom = (y2*image.height).roundToInt().coerceIn(top+1,image.height)
        return copyRegion(image,left,top,right-left,bottom-top)
    }

    private fun copyRegion(frame: Image,l:Int,t:Int,w:Int,h:Int):Bitmap {
        val plane = frame.planes.firstOrNull() ?: throw IllegalStateException("画像がありません")
        require(plane.pixelStride == 4 && plane.rowStride >= frame.width * 4)
        val rowBytes = w*4
        val source = plane.buffer.duplicate()
        val packed = ByteBuffer.allocateDirect(rowBytes*h)
        val row = ByteArray(rowBytes)
        for (y in t until t+h) {
            source.position(y*plane.rowStride+l*4)
            source.get(row)
            packed.put(row)
        }
        packed.flip()
        return Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888).apply {
            copyPixelsFromBuffer(packed)
        }
    }
}
