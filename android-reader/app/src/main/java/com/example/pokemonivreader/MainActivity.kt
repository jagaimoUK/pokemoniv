package com.example.pokemonivreader

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.Manifest
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.os.Build
import java.io.File
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.ActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

// Phase 1Aから維持する共通データ形式。
data class Iv(val attack: Int, val defense: Int, val hp: Int)

private const val PREF_NAME = "pokemon_iv_reader"
private const val KEY_NAME = "pokemon_name"
private const val KEY_IVS = "iv_list"
private const val BATCH_MAX_IMAGES = 20
// Phase 2A: 保存したパネル範囲をアプリ再起動後も使う。
private const val KEY_CROP_TEMPLATE = "crop_template_v1"
private const val KEY_COLOR_SENSITIVITY = "bar_color_sensitivity_v1"
private const val CROP_NUDGE_STEP = 0.005f // ±0.5% of the entire screenshot

// 全画面画像に対する相対座標。端末の解像度に依存しない。
private data class PointRatio(val x: Float, val y: Float)

/** 画面比率が近い画像でだけ再利用する。画面比率が違えば手動指定が必要。 */
private data class CropTemplate(
    val first: PointRatio,
    val second: PointRatio,
    val imageAspectRatio: Float
) {
    fun matches(bitmap: Bitmap): Boolean {
        if (!imageAspectRatio.isFinite() || imageAspectRatio <= 0f) return false
        val now = bitmap.width.toFloat() / bitmap.height
        return abs(now - imageAspectRatio) / imageAspectRatio <= 0.025f
    }

    fun hasValidCorners(bitmap: Bitmap): Boolean =
        listOf(first.x, first.y, second.x, second.y).all { it.isFinite() && it in 0f..1f } &&
            abs(second.x - first.x) * bitmap.width >= 100f &&
            abs(second.y - first.y) * bitmap.height >= 100f
}

private data class Recognition(
    val iv: Iv,
    val confident: Boolean,
    val barsY: List<Float>,
    val warnings: List<String>
)
private data class CropAndRecognition(val cropped: Bitmap, val reading: Recognition?)

/** One result for each image, even on failure. Nothing is automatically saved. */
private data class BatchEntry(
    val index: Int,
    val guessed: Iv?,
    val confident: Boolean,
    val message: String?,
    val attackText: String,
    val defenseText: String,
    val hpText: String,
    val confirmed: Boolean = false,
    val added: Boolean = false,
    val barsY: List<Float> = emptyList(),
    val diagnostic: String? = null
)

private fun validIv(entry: BatchEntry): Iv? {
    val a = entry.attackText.toIntOrNull()
    val d = entry.defenseText.toIntOrNull()
    val h = entry.hpText.toIntOrNull()
    if (a == null || d == null || h == null || a !in 0..15 || d !in 0..15 || h !in 0..15) {
        return null
    }
    return Iv(a, d, h)
}


class MainActivity : ComponentActivity() {
    // Refresh the list after a float-button capture while Pokémon GO is in front.
    private val ivRevision = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ReaderUiEnhancements.attach(this)
        setContent { MaterialTheme { IvReaderScreen(ivRevision.intValue) } }
    }

    override fun onResume() {
        super.onResume()
        ivRevision.intValue += 1
    }
}

@Composable
private fun IvReaderScreen(ivRevision: Int) {
    val context = LocalContext.current
    val preferences = remember(context) {
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
    }
    var pokemonName by rememberSaveable {
        mutableStateOf(preferences.getString(KEY_NAME, "") ?: "")
    }
    var attackInput by rememberSaveable { mutableStateOf("") }
    var defenseInput by rememberSaveable { mutableStateOf("") }
    var hpInput by rememberSaveable { mutableStateOf("") }
    val ivList = remember(context) {
        mutableStateListOf<Iv>().apply { addAll(loadIvs(context)) }
    }
    LaunchedEffect(ivRevision) {
        val saved = loadIvs(context)
        ivList.clear()
        ivList.addAll(saved)
    }
    val canExport = pokemonName.isNotBlank() && ivList.isNotEmpty()
    var autoRecordRevision by remember { mutableIntStateOf(0) }
    var showAdvanced by rememberSaveable { mutableStateOf(false) }
    var catalogCount by remember { mutableIntStateOf(PokemonCatalog.get(context).speciesCount) }
    var catalogStatus by remember { mutableStateOf(CatalogUpdates.status(context)) }
    var catalogUpdating by remember { mutableStateOf(false) }
    val catalogScope = rememberCoroutineScope()
    suspend fun refreshCatalog(force: Boolean) {
        catalogUpdating = true
        try {
            catalogStatus = withContext(Dispatchers.IO) { CatalogUpdates.refresh(context,force) }
            catalogCount = PokemonCatalog.get(context).speciesCount
            autoRecordRevision++
        } finally { catalogUpdating = false }
    }
    LaunchedEffect(context) { refreshCatalog(false) }
    val autoRecords = remember(ivRevision, autoRecordRevision) { AutoIvRecords.load(context) }
    var selectedRecords by remember { mutableStateOf(emptySet<String>()) }
    var confirmDeleteAll by remember { mutableStateOf(false) }
    var actionMessage by rememberSaveable { mutableStateOf("") }
    var historyShadowBusy by remember { mutableStateOf(false) }
    val historyShadowScope = rememberCoroutineScope()
    fun changeHistoryShadow(state: ShadowRecognizer.State) {
        if (historyShadowBusy) return
        val keys = if (selectedRecords.isEmpty()) autoRecords.map { it.selectionKey }.toSet() else selectedRecords.toSet()
        if (keys.isEmpty()) return
        historyShadowBusy = true
        historyShadowScope.launch {
            try {
                val changed = withContext(Dispatchers.IO) { AutoIvRecords.setShadowMany(context, keys, state) }
                actionMessage = if (changed >= 0) "${changed}件を${state.label}に変更しました" else "一括変更を保存できませんでした。履歴を読み直してください"
                autoRecordRevision++
            } finally { historyShadowBusy = false }
        }
    }
    val canUndoDelete = remember(ivRevision, autoRecordRevision) { AutoIvRecords.canUndo(context) }
    var targetMode by remember {
        mutableStateOf(RankingEligibility.Mode.fromStored(preferences.getString(RankingEligibility.MODE_KEY, null)))
    }
    var shadowMode by remember {
        mutableStateOf(ShadowRecognizer.Mode.fromStored(preferences.getString(ShadowRecognizer.MODE_KEY, null)))
    }
    LaunchedEffect(autoRecords) {
        selectedRecords = selectedRecords.intersect(autoRecords.map { it.selectionKey }.toSet())
    }

    // Phase 1D: pick several screenshots in one operation. Keep only the calibration
    // image and the currently displayed crop in memory; decode others sequentially.
    val imageUris = remember { mutableStateListOf<Uri>() }
    var selectionVersion by remember { mutableStateOf(0) }
    var calibrationBitmap by remember { mutableStateOf<Bitmap?>(null) }
    var imageError by remember { mutableStateOf<String?>(null) }
    var loadingCalibration by remember { mutableStateOf(false) }
    val cropCorners = remember { mutableStateListOf<PointRatio>() }
    // 保存された範囲だけを再利用する。選択した画像自体は保存しない。
    var savedCropTemplate by remember(context) { mutableStateOf(loadCropTemplate(context)) }
    var cropMessage by remember { mutableStateOf<String?>(null) }
    // Rerun the active batch when corners are nudged without changing their count.
    var calibrationRevision by remember { mutableIntStateOf(0) }
    var colorSensitivity by remember(context) {
        val saved = preferences.getString(KEY_COLOR_SENSITIVITY, null)
        mutableStateOf(
            IvBarRecognizer.Sensitivity.entries.firstOrNull { it.name == saved }
                ?: IvBarRecognizer.Sensitivity.NORMAL
        )
    }

    val batchEntries = remember { mutableStateListOf<BatchEntry>() }
    var processing by remember { mutableStateOf(false) }
    var processed by remember { mutableStateOf(0) }
    fun nudgeCrop(dx: Float, dy: Float) {
        val bitmap = calibrationBitmap ?: return
        if (cropCorners.size != 2 || processing) return
        val points = cropCorners.map { PointRatio(it.x + dx, it.y + dy) }
        if (points.any { it.x !in 0f..1f || it.y !in 0f..1f }) {
            cropMessage = "画像の端を超えるため、これ以上動かせません。"
            return
        }
        val next = CropTemplate(points[0], points[1], bitmap.width.toFloat() / bitmap.height)
        if (!next.hasValidCorners(bitmap)) return
        cropCorners.clear()
        cropCorners.addAll(points)
        savedCropTemplate = next
        saveCropTemplate(context, next)
        cropMessage = "範囲を微調整しました。解析結果を更新しています。"
        calibrationRevision++
    }

    var selectedPreview by remember { mutableStateOf<Int?>(null) }
    var previewCrop by remember { mutableStateOf<Bitmap?>(null) }

    // Phase 1E: read up to 20 frames explicitly captured via notification.
    // Images are private to this app and share the Phase 1D calibration workflow.
    var localCaptureCount by remember { mutableIntStateOf(capturedImages(context).size) }
    var captureIssue by remember { mutableStateOf<String?>(null) }

    fun replaceImages(uris: List<Uri>) {
        if (uris.isEmpty()) return
        imageUris.clear()
        imageUris.addAll(uris.take(BATCH_MAX_IMAGES))
        cropCorners.clear()
        cropMessage = null
        batchEntries.clear()
        calibrationBitmap = null
        previewCrop = null
        selectedPreview = null
        imageError = null
        processed = 0
        processing = false
        selectionVersion++
    }

    val imagePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickMultipleVisualMedia(BATCH_MAX_IMAGES)
    ) { pickedUris: List<Uri> ->
        replaceImages(pickedUris)
    }

    val projectionManager = remember(context) {
        context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    }
    fun projectionConsentIntent(): Intent = if (Build.VERSION.SDK_INT >= 34) {
        // Full-display mode, because the user will switch from our app to Pokémon GO.
        projectionManager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
    } else {
        projectionManager.createScreenCaptureIntent()
    }
    val captureConsent = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result: ActivityResult ->
        val data = result.data
        if (result.resultCode == android.app.Activity.RESULT_OK && data != null) {
            captureIssue = null
            val service = Intent(context, ScreenCaptureService::class.java).apply {
                action = ScreenCaptureService.ACTION_START
                putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, data)
            }
            try {
                context.startForegroundService(service)
            } catch (e: Exception) {
                captureIssue = "開始できません: ${e.javaClass.simpleName}"
            }
        } else {
            captureIssue = "Androidの画面取得許可がキャンセルされました。"
        }
    }
    fun startOrShowCapture() {
        if(ScreenCaptureService.isSessionActive) {
            try {
                context.startService(Intent(context,ScreenCaptureService::class.java).apply {
                    action=ScreenCaptureService.ACTION_SHOW_OVERLAY
                })
                captureIssue=null
            } catch(e:Exception) { captureIssue="再表示できません: ${e.javaClass.simpleName}" }
        } else captureConsent.launch(projectionConsentIntent())
    }
    val notificationsPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            startOrShowCapture()
        } else {
            // Notification permission may be denied; overlay still works on supported Android versions.
            captureIssue = "通知は未許可です。フロート操作は引き続き試せますが、通知が表示されない場合があります。"
            startOrShowCapture()
        }
    }

    // Overlay permission is separate from screen-recording consent.
    val overlayPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (Settings.canDrawOverlays(context)) {
            if (Build.VERSION.SDK_INT >= 33 &&
                context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                notificationsPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                startOrShowCapture()
            }
        } else {
            captureIssue = "フロート表示の許可が必要です。設定で『他のアプリの上に表示』を有効にしてね。"
        }
    }

    LaunchedEffect(selectionVersion) {
        calibrationBitmap = null
        imageError = null
        val uri = imageUris.firstOrNull() ?: return@LaunchedEffect
        loadingCalibration = true
        try {
            val loaded = withContext(Dispatchers.IO) {
                decodeForAnalysis(context, uri)
            }
            calibrationBitmap = loaded
            // 前回と画面比率・パネル範囲が矛盾しない場合にだけ自動適用。
            val template = savedCropTemplate
            if (template != null) {
                if (template.matches(loaded) && template.hasValidCorners(loaded)) {
                    cropCorners.clear()
                    cropCorners.add(template.first)
                    cropCorners.add(template.second)
                    cropMessage = "保存したパネル範囲を自動適用しました。認識結果を必ず画像と確認してね。"
                } else {
                    cropMessage = "この画像は保存範囲と画面比率が違います。パネルを2回タップして指定してね。"
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            imageError = "最初の画像を読み込めません。画像を選び直してください。"
        } finally {
            loadingCalibration = false
        }
    }

    // Use normalized corners from the FIRST screenshot for every selected image.
    // Note: same proportions do not guarantee identical UI alignment; review is required.
    LaunchedEffect(selectionVersion, calibrationBitmap, cropCorners.size, calibrationRevision, colorSensitivity) {
        batchEntries.clear()
        processed = 0
        processing = false
        previewCrop = null
        selectedPreview = null
        val first = calibrationBitmap ?: return@LaunchedEffect
        if (cropCorners.size != 2) return@LaunchedEffect
        val p1 = cropCorners[0]
        val p2 = cropCorners[1]
        val allUris = imageUris.toList()
        processing = true
        try {
            allUris.forEachIndexed { idx, uri ->
                var otherBitmap: Bitmap? = null
                val entry = try {
                    val bitmap = if (idx == 0) first else withContext(Dispatchers.IO) {
                        decodeForAnalysis(context, uri)
                    }.also { otherBitmap = it }
                    val firstRatio = first.width.toFloat() / first.height
                    val currentRatio = bitmap.width.toFloat() / bitmap.height
                    if (abs(firstRatio - currentRatio) / firstRatio > 0.025f) {
                        BatchEntry(idx, null, false,
                            "画像の縦横比が1枚目と異なります。値を手入力してください。",
                            "", "", "")
                    } else {
                        val reading = withContext(Dispatchers.Default) {
                            val cropResult = cropAndRead(bitmap, p1, p2, colorSensitivity)
                            try {
                                cropResult.reading
                            } finally {
                                cropResult.cropped.recycle()
                            }
                        }
                        if (reading == null) {
                            BatchEntry(idx, null, false,
                                "バーの検出に失敗しました。画像を確認して手入力してください。",
                                "", "", "")
                        } else {
                            BatchEntry(idx, reading.iv, reading.confident,
                                if (reading.confident) null
                                else "認識に不確かな部分があります。画像と照合してください。",
                                reading.iv.attack.toString(),
                                reading.iv.defense.toString(),
                                reading.iv.hp.toString(),
                                barsY = reading.barsY,
                                diagnostic = if (reading.warnings.isEmpty())
                                    "3本のバーを検出しました（推定結果です）"
                                else reading.warnings.joinToString(" / "))
                        }
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                    BatchEntry(idx, null, false,
                        "画像を開けないか解析できませんでした。手入力してください。",
                        "", "", "")
                } finally {
                    // The calibration Bitmap remains on-screen; other Bitmaps do not.
                    otherBitmap?.recycle()
                }
                batchEntries.add(entry)
                processed = idx + 1
            }
        } finally {
            processing = false
        }
    }

    // Show one selected crop for manual visual verification, not all full images.
    LaunchedEffect(selectionVersion, selectedPreview, cropCorners.size, calibrationRevision) {
        previewCrop = null
        val idx = selectedPreview ?: return@LaunchedEffect
        if (cropCorners.size != 2 || idx !in imageUris.indices) return@LaunchedEffect
        var loadedBitmap: Bitmap? = null
        try {
            val bitmap = if (idx == 0) calibrationBitmap ?: return@LaunchedEffect
                else withContext(Dispatchers.IO) {
                    decodeForAnalysis(context, imageUris[idx])
                }.also { loadedBitmap = it }
            previewCrop = withContext(Dispatchers.Default) {
                cropOnly(bitmap, cropCorners[0], cropCorners[1])
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // The result row already explains how to enter values by hand.
        } finally {
            loadedBitmap?.recycle()
        }
    }

    fun deleteRecords(keys:Set<String>) {
        val deleted=AutoIvRecords.deleteMany(context,keys)
        actionMessage=if(deleted>=0) "${deleted}件を削除しました。直前の削除は取り消せます。" else "削除できませんでした"
        if(deleted>=0) selectedRecords=selectedRecords-keys
        autoRecordRevision++
    }

    if (confirmDeleteAll) {
        AlertDialog(
            onDismissRequest = { confirmDeleteAll = false },
            title = { Text("自動履歴を全削除") },
            text = { Text("${autoRecords.size}件の自動読み取り履歴を削除します。厳選コピーリストの保存履歴は消去しません。") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDeleteAll = false
                    deleteRecords(autoRecords.map { it.selectionKey }.toSet())
                }) { Text("すべて削除") }
            },
            dismissButton = {
                TextButton(onClick = { confirmDeleteAll = false }) { Text("キャンセル") }
            }
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().imePadding(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text("Pokémon GO 個体値リスト", style = MaterialTheme.typography.headlineSmall)
        }
        item {
            Button(
                onClick = {
                    if (!LowScoreWebShortcut.open(context)) {
                        actionMessage = "ブラウザを開けませんでした。厳選Webアプリを直接開いてください。"
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(24.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color(0xFF516C5D),
                    contentColor = Color(0xFFEAF3EB)
                )
            ) { Text("低スコア個体を一括検索（Web）") }
            Text("CP1500・7種類の役割別ランキング。検索結果は確認用で、ポケモンを自動削除しません。",
                style = MaterialTheme.typography.bodySmall)
        }
        if(actionMessage.isNotBlank()) { item { Text(actionMessage,style=MaterialTheme.typography.bodySmall) } }
        item {
            Text("自動読み取り履歴", style = MaterialTheme.typography.titleMedium)
            Row {
                RankingEligibility.Mode.entries.forEach { mode ->
                    TextButton(onClick = {
                        val saved = preferences.edit().putString(RankingEligibility.MODE_KEY, mode.name).commit()
                        if (saved) {
                            targetMode = mode
                            autoRecordRevision++
                        } else actionMessage = "対象モードを保存できませんでした"
                    }, enabled = targetMode != mode) { Text(mode.label) }
                }
            }
            Text("厳選対象: ${targetMode.label}" + if (targetMode == RankingEligibility.Mode.ALL_SPECIES)
                "（ランキング未掲載も含む・CP1500以下）" else "（overall総合70点以上・CP1500以下）",
                style = MaterialTheme.typography.bodySmall)
            Text("切り替えは保存済み履歴とコピー文章にも反映します。", style = MaterialTheme.typography.bodySmall)
            Text("自動モードは3フレームを比較して区分を決めます。不一致なら再読取してください。", style = MaterialTheme.typography.bodySmall)
            Row {
                ShadowRecognizer.Mode.entries.forEach { mode ->
                    TextButton(onClick = {
                        shadowMode = mode
                        preferences.edit().putString(ShadowRecognizer.MODE_KEY, mode.name).apply()
                    }, enabled = shadowMode != mode) { Text(mode.label) }
                }
            }
            Text("読み取りモード: ${shadowMode.label}" + when (shadowMode) {
                ShadowRecognizer.Mode.AUTO -> "（画像による推定。精度は検証中）"
                ShadowRecognizer.Mode.NORMAL_ONLY -> "：通常／リトレーン済みだけの一覧で使用"
                ShadowRecognizer.Mode.SHADOW_ONLY -> "：シャドウだけの一覧で使用"
            }, style = MaterialTheme.typography.bodySmall)
            Text("固定モードは次に変更するまで継続します。混在した一覧では自動を選んでください。", style = MaterialTheme.typography.bodySmall)
            Row {
                TextButton(onClick = { selectedRecords = autoRecords.map { it.selectionKey }.toSet() }, enabled = autoRecords.isNotEmpty()) { Text("全選択") }
                TextButton(onClick = { selectedRecords = emptySet() }, enabled = selectedRecords.isNotEmpty()) { Text("選択解除") }
                TextButton(onClick = { deleteRecords(selectedRecords.toSet()) }, enabled = selectedRecords.isNotEmpty()) { Text("選択${selectedRecords.size}件を削除") }
            }

            val shadowScopeCount = if (selectedRecords.isEmpty()) autoRecords.size else selectedRecords.size
            val shadowScopeLabel = if (selectedRecords.isEmpty()) "全${shadowScopeCount}件" else "選択${shadowScopeCount}件"
            Text("履歴を一括変更（未選択ならすべて、チェックがあれば選択分）", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { changeHistoryShadow(ShadowRecognizer.State.NORMAL) }, enabled = shadowScopeCount > 0 && !historyShadowBusy,
                    modifier = Modifier.weight(1f)) { Text("${shadowScopeLabel}を通常に") }
                Button(onClick = { changeHistoryShadow(ShadowRecognizer.State.SHADOW) }, enabled = shadowScopeCount > 0 && !historyShadowBusy,
                    modifier = Modifier.weight(1f)) { Text("${shadowScopeLabel}をシャドウに") }
            }
            if (historyShadowBusy) Text("まとめて変更しています…", style = MaterialTheme.typography.bodySmall)
            Text("ポケモン図鑑データ：${catalogCount}種類", style = MaterialTheme.typography.bodySmall)
            Text(catalogStatus, style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { catalogScope.launch { refreshCatalog(true) } }, enabled = !catalogUpdating) {
                Text(if (catalogUpdating) "図鑑を確認しています…" else "図鑑の更新を確認")
            }
            if (catalogCount < 500) {
                Text(
                    "図鑑が初期データのみです。tools/build_catalog.py で全種辞書を作成してください。",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
        if (autoRecords.isEmpty()) {
            item { Text("自動登録はまだありません。", style = MaterialTheme.typography.bodySmall) }
        } else {
            itemsIndexed(autoRecords) { index, row ->
                Column {
                    Row(horizontalArrangement = Arrangement.SpaceBetween,modifier = Modifier.fillMaxWidth()) {
                        Checkbox(checked = row.selectionKey in selectedRecords, onCheckedChange = { selected ->
                            selectedRecords = if (selected) selectedRecords + row.selectionKey else selectedRecords - row.selectionKey
                        })
                        val nameLabel = if (row.source == "要確認" || row.source.isBlank()) "名前未確認" else row.source
                        val cpLabel = if (row.cp > 0) "CP${row.cp}" else "CP未認識"
                        Text("${index+1}. $nameLabel  $cpLabel  ${row.iv}", modifier = Modifier.weight(1f))
                        TextButton(onClick = {
                            deleteRecords(setOf(row.selectionKey))
                        }) { Text("削除") }
                    }
                    Text("区分: ${row.shadow.label}" + if (row.shadow == ShadowRecognizer.State.UNKNOWN && row.shadowHint == "SHADOW")
                        "（紫のオーラからシャドウ候補）" else "", style = MaterialTheme.typography.bodySmall)
                    Row {
                        listOf(ShadowRecognizer.State.NORMAL, ShadowRecognizer.State.SHADOW, ShadowRecognizer.State.UNKNOWN).forEach { choice ->
                            TextButton(onClick = {
                                if (!AutoIvRecords.setShadow(context, index, row, choice)) {
                                    actionMessage = "保存できませんでした。履歴を読み直してください"
                                }
                                autoRecordRevision++
                            }, enabled = row.shadow != choice && !historyShadowBusy) {
                                Text(when (choice) {
                                    ShadowRecognizer.State.NORMAL -> "通常に変更"
                                    ShadowRecognizer.State.SHADOW -> "シャドウに変更"
                                    ShadowRecognizer.State.UNKNOWN -> "保留"
                                })
                            }
                        }
                    }
                    if (row.shadowDecision.isNotBlank()) Text(row.shadowDecision, style = MaterialTheme.typography.bodySmall)
                    if (row.genderRelevant) {
                        Text("性別: ${row.gender.label}", style = MaterialTheme.typography.bodySmall)
                        Row {
                            listOf(GenderRecognizer.Gender.MALE, GenderRecognizer.Gender.FEMALE, GenderRecognizer.Gender.UNKNOWN).forEach { choice ->
                                TextButton(onClick = {
                                    if (!AutoIvRecords.setGender(context, row, choice)) actionMessage = "性別を保存できませんでした"
                                    autoRecordRevision++
                                }, enabled = row.gender != choice) { Text(if(choice == GenderRecognizer.Gender.UNKNOWN) "性別保留" else choice.label) }
                            }
                        }
                    }
                    if (row.genderPending.isNotEmpty()) Text("性別条件の確認待ち: ${row.genderPending.joinToString("、")}", style = MaterialTheme.typography.bodySmall)
                    Text("厳選対象: ${row.targets.joinToString("、").ifBlank { "なし" }}",style = MaterialTheme.typography.bodySmall)
                    if (row.uncertain.isNotEmpty()) Text("CP判定保留: ${row.uncertain.joinToString("、")}",style = MaterialTheme.typography.bodySmall)
                    val pumpkinFamily = PumpkinForms.familyFromId(row.sourceId)
                        ?: PumpkinForms.familyFromText(row.nameOcr)
                    if (pumpkinFamily != null) {
                        val sizeNote = when (row.sizeDecision) {
                            "height" -> "Height OCR：${row.heightBadge}"
                            "manual" -> "手動で確定"
                            "weight" -> "旧Weight判定：再確認が必要"
                            else -> "Height未確認"
                        }
                        Text("サイズ：$sizeNote", style = MaterialTheme.typography.bodySmall,
                            color = if (row.sizeDecision == "weight") MaterialTheme.colorScheme.error
                                    else MaterialTheme.colorScheme.onSurfaceVariant)
                        // Four compact chips on ONE row instead of two rows of large buttons.
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.fillMaxWidth()) {
                            PumpkinForms.sizes.forEach { form ->
                                val selected = row.sourceId == "${pumpkinFamily}_$form" && row.sizeDecision in setOf("height", "manual")
                                FilterChip(
                                    selected = selected,
                                    onClick = {
                                        actionMessage = AutoIvRecords.selectPumpkinSize(context, row, form)
                                        autoRecordRevision++
                                    },
                                    label = { Text(PumpkinForms.sizeLabel(form), style = MaterialTheme.typography.labelSmall) },
                                    modifier = Modifier.weight(1f)
                                )
                            }
                        }
                    }
                    if (row.diagnostic.isNotBlank()) Text("確認: ${row.diagnostic}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                    if (row.nameOcr.isNotBlank() && (row.source == "要確認" || row.shadow == ShadowRecognizer.State.UNKNOWN)) {
                        Text("文字認識の結果: ${row.nameOcr.replace("\n", " / ").take(100)}", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        item {
            Button(
                onClick = {
                    val text = AutoIvRecords.prompt(autoRecords)
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("個体値厳選", text))
                    actionMessage = "進化先を含む厳選文章をコピーしたよ"
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = autoRecords.any { it.targets.isNotEmpty() }
            ) { Text("自動登録データをコピー（進化先別）") }
        }
        item {
            TextButton(
                onClick = { confirmDeleteAll = true },
                enabled = autoRecords.isNotEmpty(),
                modifier = Modifier.fillMaxWidth()
            ) { Text("自動履歴を全削除") }
            TextButton(
                onClick = {
                    val restored = AutoIvRecords.undoDelete(context)
                    actionMessage = if (restored >= 0) "${restored}件を復元しました" else "復元できませんでした"
                    autoRecordRevision++
                },
                enabled = canUndoDelete,
                modifier = Modifier.fillMaxWidth()
            ) { Text("直前の削除を取り消す") }
        }
        if (showAdvanced) {
        item {
            OutlinedTextField(
                value = pokemonName,
                onValueChange = { next ->
                    pokemonName = next
                    preferences.edit().putString(KEY_NAME, next).apply()
                },
                label = { Text("手入力用ポケモン名（自動登録では不要）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )
        }
        }
        item {
            Text("ワンタップ個体値登録（Phase 3A〜3C）", style = MaterialTheme.typography.titleMedium)
            Text(
                "評価パネルの範囲を初回だけ設定し、Pokémon GO上のIVボタンを押して読み取ります。",
                style = MaterialTheme.typography.bodySmall
            )
        }
        item {
            Button(
                onClick = {
                    captureIssue = null
                    if(ScreenCaptureService.isSessionActive && Settings.canDrawOverlays(context)) {
                        startOrShowCapture()
                    } else if (!Settings.canDrawOverlays(context)) {
                        overlayPermission.launch(
                            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:${context.packageName}"))
                        )
                    } else if (Build.VERSION.SDK_INT >= 33 &&
                        context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                        PackageManager.PERMISSION_GRANTED
                    ) {
                        notificationsPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                    } else {
                        startOrShowCapture()
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("フロートを開始・再表示") }
            Text("共有継続中は確認なしで再表示できます。共有を終了した後はAndroidの許可が必要です。",style=MaterialTheme.typography.bodySmall)
            TextButton(onClick={
                if(ScreenCaptureService.isSessionActive) context.startService(Intent(context,ScreenCaptureService::class.java).apply {
                    action=ScreenCaptureService.ACTION_HIDE_OVERLAY
                })
            }) { Text("フロートだけ隠す（画面共有を継続）") }
            Text("画像確保が出たら次へスワイプできます。CP・IVと保存済み／要確認をフロートで確認してください。",style=MaterialTheme.typography.bodySmall)
            captureIssue?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
        item {
            Button(
                onClick = {
                    context.startService(Intent(context, ScreenCaptureService::class.java).apply {
                        action = ScreenCaptureService.ACTION_STOP
                    })
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("画面共有を終了") }
        }
        item {
            TextButton(
                onClick = { showAdvanced = !showAdvanced },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (showAdvanced) "詳細設定・手入力を閉じる" else "詳細設定・画像選択・手入力を表示")
            }
        }
        if (showAdvanced) {
        item {
            Button(
                onClick = {
                    val files = capturedImages(context)
                    localCaptureCount = files.size
                    if (files.isEmpty()) {
                        actionMessage = "撮影画像がまだありません"
                    } else {
                        replaceImages(files.map(Uri::fromFile))
                        actionMessage = "${files.size}枚を読み込んだよ"
                    }
                    context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
                        .getString("capture_error", null)?.let { captureIssue = it }
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("撮影済み画像を読み込む（端末内：${localCaptureCount}枚）") }
            Text(
                "従来の通知撮影も利用できます。フロート撮影では認識結果だけを保存し、" +
                    "この『撮影済み画像を読み込む』は通知から撮った画像を確認する機能です。" +
                    "画面取得の終了はAndroid通知から操作してね。",
                style = MaterialTheme.typography.bodySmall
            )
        }
        item {
            Text("パネル範囲の再利用（Phase 2A）", style = MaterialTheme.typography.titleMedium)
            Text(
                "最初の画像で範囲を2回タップすると保存されます。次の撮影画像では同じ画面比率の場合に自動適用します。" +
                    "画面レイアウトやUI表示が変わったときは範囲を指定し直してください。",
                style = MaterialTheme.typography.bodySmall
            )
            if (savedCropTemplate != null) {
                Text("保存済みのパネル範囲あり", style = MaterialTheme.typography.bodyMedium)
                TextButton(onClick = {
                    clearCropTemplate(context)
                    savedCropTemplate = null
                    cropCorners.clear()
                    cropMessage = "保存範囲を削除しました。現在の画像はもう一度タップして指定してください。"
                }) { Text("保存範囲を削除して再設定") }
            } else {
                Text("まだパネル範囲は保存されていません。", style = MaterialTheme.typography.bodySmall)
            }
            cropMessage?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        }
        item {
            Text("画像から連続読み取り（Phase 2C）", style = MaterialTheme.typography.titleMedium)
            Text(
                "① 同じ端末・レイアウトのスクリーンショットを複数選択 → " +
                    "② 1枚目の白い個体値パネルを2回タップして囲む → " +
                    "③ すべての候補を画像と照合 → ④ 確認済みをまとめて追加。",
                style = MaterialTheme.typography.bodySmall
            )
        }
        item {
            Text("色判定の調整（Phase 2C）", style = MaterialTheme.typography.titleMedium)
            Text(
                "標準で読めない場合は『高感度』、背景を誤認識する場合は『厳しめ』を試してね。" +
                    "切替時は全画像を再解析するので、確認チェックは解除されます。",
                style = MaterialTheme.typography.bodySmall
            )
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(
                    IvBarRecognizer.Sensitivity.HIGH to "高感度",
                    IvBarRecognizer.Sensitivity.NORMAL to "標準",
                    IvBarRecognizer.Sensitivity.STRICT to "厳しめ"
                ).forEach { (mode, label) ->
                    TextButton(
                        enabled = !processing,
                        onClick = {
                            if (colorSensitivity != mode) {
                                colorSensitivity = mode
                                preferences.edit().putString(KEY_COLOR_SENSITIVITY, mode.name).apply()
                            }
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(if (colorSensitivity == mode) "● $label" else label)
                    }
                }
            }
        }
        item {
            Button(
                onClick = {
                    imagePicker.launch(
                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                    )
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("スクリーンショットを複数選択（最大${BATCH_MAX_IMAGES}枚）") }
            Text(
                "新しく選ぶと、前回の未登録の読み取り候補は消えます。登録済み個体値は残ります。",
                style = MaterialTheme.typography.bodySmall
            )
        }
        if (loadingCalibration) item { CircularProgressIndicator() }
        imageError?.let { error ->
            item { Text(error, color = MaterialTheme.colorScheme.error) }
        }
        calibrationBitmap?.let { bitmap ->
            item {
                Text(
                    "選択：${imageUris.size}枚。" + when (cropCorners.size) {
                        0 -> "1枚目の白い個体値パネルの左上をタップ"
                        1 -> "続いて右下をタップ"
                        else -> "範囲指定済み。位置が違う場合はやり直してね"
                    },
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            item {
                ImageWithCropCorners(bitmap, cropCorners) { point ->
                    if (!processing && cropCorners.size < 2) {
                        cropCorners.add(point)
                        if (cropCorners.size == 2) {
                            val candidate = CropTemplate(
                                cropCorners[0], cropCorners[1],
                                bitmap.width.toFloat() / bitmap.height
                            )
                            if (candidate.hasValidCorners(bitmap)) {
                                saveCropTemplate(context, candidate)
                                savedCropTemplate = candidate
                                cropMessage = "このパネル範囲を保存しました。次回の画像選択から再利用します。"
                            } else {
                                cropCorners.clear()
                                cropMessage = "選択範囲が小さすぎます。左上と右下を広めに指定してね。"
                            }
                        }
                    }
                }
            }
            if (cropCorners.size == 2) {
                item {
                    Text("検出位置の微調整（Phase 2C）", style = MaterialTheme.typography.titleSmall)
                    Text(
                        "矢印1回につき画像全体の0.5%動かします。調整した位置は次回も保存されます。" +
                            "解析結果と確認チェックは更新されます。",
                        style = MaterialTheme.typography.bodySmall
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        TextButton(
                            onClick = { nudgeCrop(-CROP_NUDGE_STEP, 0f) },
                            enabled = !processing,
                            modifier = Modifier.weight(1f)
                        ) { Text("← 左") }
                        TextButton(
                            onClick = { nudgeCrop(CROP_NUDGE_STEP, 0f) },
                            enabled = !processing,
                            modifier = Modifier.weight(1f)
                        ) { Text("右 →") }
                        TextButton(
                            onClick = { nudgeCrop(0f, -CROP_NUDGE_STEP) },
                            enabled = !processing,
                            modifier = Modifier.weight(1f)
                        ) { Text("↑ 上") }
                        TextButton(
                            onClick = { nudgeCrop(0f, CROP_NUDGE_STEP) },
                            enabled = !processing,
                            modifier = Modifier.weight(1f)
                        ) { Text("下 ↓") }
                    }
                }
            }
            if (cropCorners.isNotEmpty()) {
                item {
                    TextButton(
                        onClick = { cropCorners.clear() },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("この画像のパネル範囲を指定し直す（結果をリセット）") }
                }
            }
        }
        if (processing) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator()
                    Text("解析中：${processed} / ${imageUris.size}枚")
                }
            }
        }
        if (batchEntries.isNotEmpty()) {
            item {
                Text("画像ごとの読み取り結果", style = MaterialTheme.typography.titleMedium)
                Text(
                    "誤認識を防ぐため、自動登録はしません。画像を開いて数値を確認し、" +
                        "チェックした個体だけまとめて追加します。",
                    style = MaterialTheme.typography.bodySmall
                )
            }
            itemsIndexed(batchEntries, key = { _, entry -> entry.index }) { index, entry ->
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("画像 ${entry.index + 1} / ${imageUris.size}", style = MaterialTheme.typography.titleSmall)
                    Text(
                        when {
                            entry.added -> "登録済み"
                            entry.guessed == null -> "未検出：手入力が必要"
                            entry.confident -> "推定：${entry.guessed.attack},${entry.guessed.defense},${entry.guessed.hp}（要確認）"
                            else -> "推定：${entry.guessed.attack},${entry.guessed.defense},${entry.guessed.hp}（低確度）"
                        },
                        style = MaterialTheme.typography.bodyMedium
                    )
                    entry.message?.let {
                        Text(it, color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodySmall)
                    }
                    entry.diagnostic?.let {
                        Text("診断：$it", style = MaterialTheme.typography.bodySmall)
                    }
                    if (entry.barsY.isNotEmpty()) {
                        Text(
                            "検出位置（画像パネルの上から）：" +
                                entry.barsY.joinToString(" / ") { "${(it * 100f).roundToInt()}%" },
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                    TextButton(onClick = {
                        selectedPreview = if (selectedPreview == entry.index) null else entry.index
                    }) {
                        Text(if (selectedPreview == entry.index) "画像を閉じる" else "パネル画像を確認")
                    }
                    if (selectedPreview == entry.index) {
                        previewCrop?.let { crop ->
                            ImageWithDetectedBars(crop, entry.barsY)
                            Text(
                                "緑線はアプリがバーと判断した位置。実物とずれる場合は" +
                                    "範囲を微調整するか、指定し直してね。",
                                style = MaterialTheme.typography.bodySmall
                            )
                        } ?: Text("画像を読み込み中、または表示できませんでした。")
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        IvNumberField("攻撃", entry.attackText, { newValue ->
                            batchEntries[index] = entry.copy(
                                attackText = newValue, confirmed = false)
                        }, Modifier.weight(1f))
                        IvNumberField("防御", entry.defenseText, { newValue ->
                            batchEntries[index] = entry.copy(
                                defenseText = newValue, confirmed = false)
                        }, Modifier.weight(1f))
                        IvNumberField("HP", entry.hpText, { newValue ->
                            batchEntries[index] = entry.copy(
                                hpText = newValue, confirmed = false)
                        }, Modifier.weight(1f))
                    }
                    Row {
                        Checkbox(
                            checked = entry.confirmed || entry.added,
                            enabled = !entry.added && validIv(entry) != null,
                            onCheckedChange = { checked ->
                                batchEntries[index] = entry.copy(confirmed = checked)
                            }
                        )
                        Text(
                            if (entry.added) "一覧に追加済み" else "画像と照合して正しいと確認した",
                            modifier = Modifier.padding(top = 12.dp),
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
            item {
                val confirmedCount = batchEntries.count {
                    it.confirmed && !it.added && validIv(it) != null
                }
                Button(
                    onClick = {
                        if (pokemonName.isBlank()) {
                            actionMessage = "ポケモン名を入力してね"
                        } else {
                            val entries = batchEntries.filter {
                                it.confirmed && !it.added && validIv(it) != null
                            }
                            entries.forEach { candidate ->
                                val iv = validIv(candidate) ?: return@forEach
                                ivList.add(iv)
                                batchEntries[candidate.index] = candidate.copy(
                                    added = true, confirmed = false)
                            }
                            saveIvs(context, ivList)
                            actionMessage = "${entries.size}体を登録したよ"
                        }
                    },
                    enabled = confirmedCount > 0 && pokemonName.isNotBlank(),
                    modifier = Modifier.fillMaxWidth()
                ) { Text("確認済み${confirmedCount}体を一覧に追加") }
            }
        }
        item {
            Text("手入力（Phase 1A）", style = MaterialTheme.typography.titleMedium)
            Text("1つのリストは同じポケモン用だよ。別の種類を扱う前には一覧を空にしてね。",
                style = MaterialTheme.typography.bodySmall)
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                IvNumberField("攻撃", attackInput, { attackInput = it }, Modifier.weight(1f))
                IvNumberField("防御", defenseInput, { defenseInput = it }, Modifier.weight(1f))
                IvNumberField("HP", hpInput, { hpInput = it }, Modifier.weight(1f))
            }
        }
        item {
            Button(
                onClick = {
                    val a = attackInput.toIntOrNull()
                    val d = defenseInput.toIntOrNull()
                    val h = hpInput.toIntOrNull()
                    if (pokemonName.isBlank()) {
                        actionMessage = "ポケモン名を入力してね"
                    } else if (a == null || d == null || h == null ||
                        a !in 0..15 || d !in 0..15 || h !in 0..15
                    ) {
                        actionMessage = "個体値は0～15の整数を入力してね"
                    } else {
                        ivList.add(Iv(a, d, h))
                        saveIvs(context, ivList)
                        attackInput = ""
                        defenseInput = ""
                        hpInput = ""
                        actionMessage = "一覧に追加したよ"
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("手入力の個体値を追加") }
        }
        item {
            Text("登録済み：${ivList.size}体", style = MaterialTheme.typography.titleMedium)
        }
        if (ivList.isEmpty()) item { Text("個体値はまだ登録されていません。") }
        itemsIndexed(ivList) { index, iv ->
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${index + 1}.  ${iv.attack},${iv.defense},${iv.hp}",
                    modifier = Modifier.weight(1f).padding(top = 12.dp))
                TextButton(onClick = {
                    ivList.removeAt(index)
                    saveIvs(context, ivList)
                }) { Text("削除") }
            }
        }
        item {
            Button(
                onClick = {
                    val text = buildPrompt(pokemonName, ivList)
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("個体値厳選", text))
                    actionMessage = "コピーしたよ！"
                },
                enabled = canExport,
                modifier = Modifier.fillMaxWidth()
            ) { Text("ChatGPT用文章をコピー") }
        }
        item {
            Button(
                onClick = {
                    val intent = Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(Intent.EXTRA_TEXT, buildPrompt(pokemonName, ivList))
                    }
                    context.startActivity(Intent.createChooser(intent, "文章を共有"))
                },
                enabled = canExport,
                modifier = Modifier.fillMaxWidth()
            ) { Text("ChatGPTなどへ共有") }
        }
        if (ivList.isNotEmpty()) {
            item {
                TextButton(
                    onClick = {
                        ivList.clear()
                        saveIvs(context, ivList)
                    }, modifier = Modifier.fillMaxWidth()
                ) { Text("一覧をすべて削除") }
            }
        }
        item {
            Text(
                "※ フロート登録は認識エンジンの高確度判定に基づきますが、誤認識がゼロという保証はありません。" +
                    "登録後は一覧を確認し、誤りは削除して手入力で修正してください。",
                style = MaterialTheme.typography.bodySmall
            )
        }
        } // 詳細設定の表示ここまで
    }
}

/** 画像全体を縮小表示し、ユーザーの2回のタップを元画像の比率座標に変換する。 */
@Composable
private fun ImageWithCropCorners(
    bitmap: Bitmap,
    corners: List<PointRatio>,
    onCorner: (PointRatio) -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(460.dp)
            .background(Color(0xFF252525), RoundedCornerShape(8.dp))
    ) {
        Image(
            bitmap = bitmap.asImageBitmap(),
            contentDescription = "スクリーンショット。個体値パネルの左上と右下をタップ",
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Fit
        )
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(bitmap, corners.size) {
                    detectTapGestures { tap ->
                        val viewWidth = size.width.toFloat()
                        val viewHeight = size.height.toFloat()
                        val scale = min(viewWidth / bitmap.width, viewHeight / bitmap.height)
                        val imageWidth = bitmap.width * scale
                        val imageHeight = bitmap.height * scale
                        val startX = (viewWidth - imageWidth) / 2f
                        val startY = (viewHeight - imageHeight) / 2f
                        if (tap.x in startX..(startX + imageWidth) &&
                            tap.y in startY..(startY + imageHeight)
                        ) {
                            onCorner(
                                PointRatio(
                                    ((tap.x - startX) / imageWidth).coerceIn(0f, 1f),
                                    ((tap.y - startY) / imageHeight).coerceIn(0f, 1f)
                                )
                            )
                        }
                    }
                }
        ) {
            val scale = min(size.width / bitmap.width, size.height / bitmap.height)
            val imageWidth = bitmap.width * scale
            val imageHeight = bitmap.height * scale
            val startX = (size.width - imageWidth) / 2f
            val startY = (size.height - imageHeight) / 2f
            val positions = corners.map {
                Offset(startX + it.x * imageWidth, startY + it.y * imageHeight)
            }
            positions.forEach { p ->
                drawCircle(Color.Cyan, radius = 9.dp.toPx(), center = p)
                drawCircle(Color.Black, radius = 9.dp.toPx(), center = p, style = Stroke(2.dp.toPx()))
            }
            if (positions.size == 2) {
                val a = positions[0]
                val b = positions[1]
                drawRect(
                    color = Color.Cyan,
                    topLeft = Offset(min(a.x, b.x), min(a.y, b.y)),
                    size = Size(abs(a.x - b.x), abs(a.y - b.y)),
                    style = Stroke(width = 3.dp.toPx())
                )
            }
        }
    }
}

/** Phase 2C: visual guide for which lines the algorithm judged to be the three bars. */
@Composable
private fun ImageWithDetectedBars(bitmap: Bitmap, barY: List<Float>) {
    Box(modifier = Modifier.fillMaxWidth().height(210.dp)) {
        Image(
            bitmap = bitmap.asImageBitmap(),
            contentDescription = "個体値パネルの認識位置確認",
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Fit
        )
        Canvas(modifier = Modifier.fillMaxSize()) {
            val scale = min(size.width / bitmap.width, size.height / bitmap.height)
            val imageW = bitmap.width * scale
            val imageH = bitmap.height * scale
            val x0 = (size.width - imageW) / 2f
            val y0 = (size.height - imageH) / 2f
            barY.forEach { fraction ->
                val y = y0 + imageH * fraction.coerceIn(0f, 1f)
                drawLine(
                    color = Color(0xFF29E35C),
                    start = Offset(x0, y),
                    end = Offset(x0 + imageW, y),
                    strokeWidth = 2.dp.toPx()
                )
            }
        }
    }
}

/** Read only our app-private, previously captured PNG files, oldest first. */
private fun capturedImages(context: Context): List<File> =
    File(context.filesDir, ScreenCaptureService.CAPTURE_DIR)
        .listFiles { f -> f.isFile && f.name.startsWith("capture_") && f.name.endsWith(".png") }
        ?.sortedBy { it.name }
        ?.takeLast(BATCH_MAX_IMAGES)
        ?: emptyList()

/** 高解像度スクリーンショットでもメモリ使用量を抑える。ピクセル参照可能なSOFTWAREにする。 */
private fun decodeForAnalysis(context: Context, uri: Uri): Bitmap {
    val source = if (uri.scheme == "file") {
        val path = uri.path ?: throw IllegalArgumentException("No image path")
        val file = File(path)
        // Direct capture images are only read from this app's private directory.
        val root = File(context.filesDir, ScreenCaptureService.CAPTURE_DIR).canonicalFile
        require(file.canonicalFile.parentFile == root) { "Invalid local capture path" }
        ImageDecoder.createSource(file)
    } else {
        ImageDecoder.createSource(context.contentResolver, uri)
    }
    return ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        val longer = max(info.size.width, info.size.height)
        var sample = 1
        while (longer / sample > 2600) sample *= 2
        if (sample > 1) decoder.setTargetSampleSize(sample)
    }
}

/** Crop with a common normalized rectangle; used by both analysis and review. */
private fun cropOnly(bitmap: Bitmap, p1: PointRatio, p2: PointRatio): Bitmap {
    val left = (min(p1.x, p2.x) * bitmap.width).roundToInt().coerceIn(0, bitmap.width - 1)
    val right = (max(p1.x, p2.x) * bitmap.width).roundToInt().coerceIn(left + 1, bitmap.width)
    val top = (min(p1.y, p2.y) * bitmap.height).roundToInt().coerceIn(0, bitmap.height - 1)
    val bottom = (max(p1.y, p2.y) * bitmap.height).roundToInt().coerceIn(top + 1, bitmap.height)
    val roi = Rect(left, top, right, bottom)
    require(roi.width() >= 100 && roi.height() >= 100) { "範囲が小さすぎます" }
    return Bitmap.createBitmap(bitmap, roi.left, roi.top, roi.width(), roi.height())
}

/** Crop panel and find three bar fill levels. */
private fun cropAndRead(
    bitmap: Bitmap, p1: PointRatio, p2: PointRatio,
    sensitivity: IvBarRecognizer.Sensitivity
): CropAndRecognition {
    val cropped = cropOnly(bitmap, p1, p2)
    return CropAndRecognition(cropped, findIvBars(cropped, sensitivity))
}

/**
 * Phase 2C: 色感度と診断情報を独立した認識エンジンから受け取る。
 * UI・保存・画面取得を変更せず、認識アルゴリズムだけ交換できる。
 */
private fun findIvBars(bitmap: Bitmap, sensitivity: IvBarRecognizer.Sensitivity): Recognition? {
    val w = bitmap.width
    val h = bitmap.height
    if (w < 100 || h < 100) return null
    val pixels = IntArray(w * h)
    bitmap.getPixels(pixels, 0, w, 0, 0, w, h)
    val result = IvBarRecognizer.read(pixels, w, h, sensitivity) ?: return null
    return Recognition(
        Iv(result.attack, result.defense, result.hp),
        result.reliable,
        result.barCenters,
        result.warnings
    )
}

@Composable
private fun IvNumberField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    OutlinedTextField(
        value = value,
        onValueChange = { next ->
            if (next.length <= 2 && next.all { it in '0'..'9' }) onValueChange(next)
        },
        label = { Text(label) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = modifier
    )
}

private fun buildPrompt(name: String, ivs: List<Iv>): String = buildString {
    appendLine("個体値厳選")
    appendLine()
    appendLine(IvSelectionText.targetName(name))
    ivs.forEach { iv -> appendLine("${iv.attack},${iv.defense},${iv.hp}") }
}.trimEnd()

private fun saveIvs(context: Context, ivs: List<Iv>) {
    val json = JSONArray()
    ivs.forEach { iv ->
        json.put(JSONObject().apply {
            put("attack", iv.attack)
            put("defense", iv.defense)
            put("hp", iv.hp)
        })
    }
    context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        .edit().putString(KEY_IVS, json.toString()).apply()
}

private fun loadIvs(context: Context): List<Iv> {
    val saved = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        .getString(KEY_IVS, "[]") ?: "[]"
    return try {
        val json = JSONArray(saved)
        buildList {
            for (i in 0 until json.length()) {
                val item = json.getJSONObject(i)
                val iv = Iv(item.getInt("attack"), item.getInt("defense"), item.getInt("hp"))
                if (iv.attack in 0..15 && iv.defense in 0..15 && iv.hp in 0..15) add(iv)
            }
        }
    } catch (_: Exception) {
        emptyList()
    }
}


/** Phase 2A: パネルの2点だけ保存。画像本体はここには保存しない。 */
private fun saveCropTemplate(context: Context, template: CropTemplate) {
    val json = JSONObject().apply {
        put("x1", template.first.x.toDouble())
        put("y1", template.first.y.toDouble())
        put("x2", template.second.x.toDouble())
        put("y2", template.second.y.toDouble())
        put("aspect", template.imageAspectRatio.toDouble())
    }
    context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        .edit().putString(KEY_CROP_TEMPLATE, json.toString()).apply()
}

private fun loadCropTemplate(context: Context): CropTemplate? {
    val raw = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        .getString(KEY_CROP_TEMPLATE, null) ?: return null
    return try {
        val json = JSONObject(raw)
        val crop = CropTemplate(
            PointRatio(json.getDouble("x1").toFloat(), json.getDouble("y1").toFloat()),
            PointRatio(json.getDouble("x2").toFloat(), json.getDouble("y2").toFloat()),
            json.getDouble("aspect").toFloat()
        )
        if (crop.imageAspectRatio.isFinite() && crop.imageAspectRatio > 0f &&
            listOf(crop.first.x, crop.first.y, crop.second.x, crop.second.y)
                .all { it.isFinite() && it in 0f..1f }
        ) crop else null
    } catch (_: Exception) {
        null
    }
}

private fun clearCropTemplate(context: Context) {
    context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        .edit().remove(KEY_CROP_TEMPLATE).apply()
}
