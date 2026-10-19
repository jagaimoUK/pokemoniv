package com.example.pokemonivreader

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.graphics.PixelFormat
import android.graphics.Point
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.view.WindowManager
import android.view.Gravity
import android.view.MotionEvent
import android.provider.Settings
import android.widget.TextView
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONObject
import kotlin.math.min
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.abs

/**
 * Phase 3D: one-tap fast scan with a persistent floating button.
 * The overlay stays visible, but scanning is blocked if it overlaps the panel.
 * The notification's legacy capture action still saves a PNG for manual review;
 * floating-button scanning keeps no screenshot, only the IV result.
 */
class ScreenCaptureService : Service() {
    companion object {
        const val ACTION_START = "com.example.pokemonivreader.START_CAPTURE"
        const val ACTION_SHOW_OVERLAY = "com.example.pokemonivreader.SHOW_OVERLAY"
        const val ACTION_HIDE_OVERLAY = "com.example.pokemonivreader.HIDE_OVERLAY"
        @Volatile var isSessionActive = false
            private set
        const val ACTION_CAPTURE = "com.example.pokemonivreader.CAPTURE_ONE"
        const val ACTION_STOP = "com.example.pokemonivreader.STOP_CAPTURE"
        const val EXTRA_RESULT_CODE = "capture_result_code"
        const val EXTRA_RESULT_DATA = "capture_result_data"
        const val CAPTURE_DIR = "direct_captures"
        const val MAX_CAPTURES = 20
        private const val NOTIFICATION_ID = 1815
        private const val CHANNEL_ID = "iv_screen_capture"
    }

    private val main = Handler(Looper.getMainLooper())
    private val capturePending = AtomicBoolean(false)
    private val shadowBurst = ShadowBurst()
    private val captureGate = CaptureGate()
    private val pipeline = ScanPipeline(4)
    @Volatile private var activeCaptureId = 0L
    @Volatile private var expectedScene: CaptureGate.Signature? = null
    @Volatile private var overlayVisible = false
    private var lastObservedAt = 0L
    private var previousScene: CaptureGate.Signature? = null
    private var panelCoordinates: DoubleArray? = null
    private var panelRaw: String? = null
    private var reviewCount=0
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var captureThread: HandlerThread? = null
    private var hasStopped = false
    private var captureCount = 0
    private var scheduled = false
    // Keep the overlay visible during capture. Do not scan if it overlaps
    // the saved appraisal-panel rectangle; this avoids contaminated values.
    private var overlay: TextView? = null
    private var shadowOverlayRoot: android.widget.LinearLayout? = null
    @Volatile private var activeShadowMode = ShadowRecognizer.Mode.AUTO
    private var overlayLayout: WindowManager.LayoutParams? = null
    @Volatile private var captureByOverlay = false
    private val scanInProgress = AtomicBoolean(false)
    @Volatile private var scanStartedAt = 0L
    private val scanTimeout = Runnable {
        val id=activeCaptureId
        if(id!=0L) {
            releaseCapture(id)
            pipeline.finish(id)
            if(pipeline.isNewest(id)) showScanResult("画像未確保・再読取",false)
        }
    }

    @Synchronized private fun releaseCapture(id:Long) {
        if(activeCaptureId!=id) return
        activeCaptureId=0L
        capturePending.set(false)
        captureByOverlay=false
        scanInProgress.set(false)
        expectedScene=null
        main.removeCallbacks(scanTimeout)
    }


    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            // Android can stop projection when the user revokes access, locks the
            // device, or another capture session begins.
            closeProjection(stopProjection = false)
            stopSelf()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                if (projection == null) {
                    val code = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
                    @Suppress("DEPRECATION")
                    val data = if (Build.VERSION.SDK_INT >= 33) {
                        intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
                    } else {
                        intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
                    }
                    if (code == 0 || data == null) {
                        stopSelf()
                        return START_NOT_STICKY
                    }
                    // Required order for targetSdk 34+: consent -> foreground service
                    // of type mediaProjection -> getMediaProjection -> createVirtualDisplay.
                    try {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            startForeground(
                                NOTIFICATION_ID,
                                notification("画面取得中。Pokémon GOで通知から撮影できます"),
                                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
                            )
                        } else {
                            startForeground(NOTIFICATION_ID, notification("画面取得中"))
                        }
                        startProjection(code, data)
                    } catch (e: Exception) {
                        getSharedPreferences("pokemon_iv_reader", Context.MODE_PRIVATE)
                            .edit().putString("capture_error", e.javaClass.simpleName + ": " + (e.message ?: ""))
                            .apply()
                        closeProjection(stopProjection = true)
                        stopSelf()
                    }
                }
            }
            ACTION_SHOW_OVERLAY -> {
                if(projection!=null) showOverlay() else stopSelf()
            }
            ACTION_HIDE_OVERLAY -> removeOverlay()
            ACTION_CAPTURE -> {
                if (projection != null && !scheduled && !capturePending.get()) {
                    scheduled = true
                    updateNotification("2秒後に撮影します。通知を閉じてゲーム画面に戻ってね")
                    main.postDelayed({
                        scheduled = false
                        if (projection != null) {
                            capturePending.set(true)
                            // Prevent a permanent wait if the virtual display stops producing frames.
                            main.postDelayed({
                                if (capturePending.getAndSet(false)) {
                                    updateNotification("撮影できませんでした。画面取得を開始し直してね")
                                }
                            }, 4500L)
                        }
                    }, 2200L)
                }
            }
            ACTION_STOP -> {
                closeProjection(stopProjection = true)
                stopSelf()
            }
            else -> stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun startProjection(resultCode: Int, data: Intent) {
        val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val current = manager.getMediaProjection(resultCode, data)
            ?: throw IllegalStateException("画面取得の許可を取得できませんでした")
        projection = current
        current.registerCallback(projectionCallback, main)

        @Suppress("DEPRECATION")
        val windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        @Suppress("DEPRECATION")
        val size = Point().also { windowManager.defaultDisplay.getRealSize(it) }
        val width = size.x
        val height = size.y
        require(width > 0 && height > 0) { "Invalid display size" }

        val dpi = resources.displayMetrics.densityDpi
        val imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3)
        reader = imageReader
        val thread = HandlerThread("PokemonIVScreenCapture").apply { start() }
        captureThread = thread
        imageReader.setOnImageAvailableListener({ source ->
            val image=try { source.acquireLatestImage() } catch (_:Exception){null}
            if(image!=null) try {
                val now=SystemClock.elapsedRealtime()
                var signature:CaptureGate.Signature?=null
                if(overlayVisible && (now-lastObservedAt>=40L || captureByOverlay)) {
                    refreshPanel()
                    signature=OverlayIvProcessor.sceneSignature(image,panelCoordinates)
                    if(previousScene?.same(signature)!=true) shadowBurst.reset()
                    if(now-lastObservedAt>=40L) {
                        captureGate.observe(signature,now)
                        lastObservedAt=now
                        if(shadowBurst.needsSample(now)) shadowBurst.offer(now,OverlayIvProcessor.inspectShadowFrame(image))
                    }
                    previousScene=signature
                }
                if(capturePending.compareAndSet(true,false)) {
                    if(captureByOverlay) {
                        val id=activeCaptureId
                        val started=scanStartedAt
                        val expected=expectedScene
                        if(id!=0L && expected!=null && signature!=null && expected.same(signature)) {
                            val samples=shadowBurst.latest()
                            val capturedShadowMode = activeShadowMode
                            try {
                                OverlayIvProcessor.process(this,image,samples,
                                    scanModeOverride=capturedShadowMode,
                                    onCaptured={ releaseCapture(id) },
                                    onProgress={ progress -> main.post {
                                        if(!hasStopped && pipeline.isNewest(id)) showScanResult(progress,now-started)
                                    }}
                                ) { outcome ->
                                    releaseCapture(id)
                                    pipeline.finish(id)
                                    main.post {
                                        if(!hasStopped) {
                                            if(outcome.phase==OverlayIvProcessor.Phase.REVIEW || outcome.phase==OverlayIvProcessor.Phase.FAILED) reviewCount++
                                            if(pipeline.isNewest(id)) showScanResult(outcome,SystemClock.elapsedRealtime()-started)
                                            else refreshReviewBadge()
                                        }
                                    }
                                }
                            } catch(e:Exception) {
                                releaseCapture(id);pipeline.finish(id)
                                main.post { if(!hasStopped && pipeline.isNewest(id)) showScanResult("解析失敗・再読取",false) }
                            }
                        } else {
                            releaseCapture(id);pipeline.finish(id)
                            main.post { if(!hasStopped && pipeline.isNewest(id)) showScanResult("切替中・再読取",false) }
                        }
                    } else saveCapture(image)
                }
            } catch(e:Exception) {
                val id=activeCaptureId
                if(id!=0L) {releaseCapture(id);pipeline.finish(id)}
                main.post { if(!hasStopped && (id==0L || pipeline.isNewest(id))) showScanResult("取得失敗・再読取",false) }
            } finally { image.close() }
        }, Handler(thread.looper))

        virtualDisplay = current.createVirtualDisplay(
            "PokemonIVReaderCapture", width, height, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader.surface, null, main
        )
        getSharedPreferences("pokemon_iv_reader", Context.MODE_PRIVATE)
            .edit().remove("capture_error").apply()
        isSessionActive=true
        OverlayIvProcessor.worker.execute { ScreenTextRecognizer.warmUp() }
        showOverlay()
        updateNotification("IVボタンで自動登録。終了は通知から操作")
    }

    private fun refreshPanel() {
        val raw=getSharedPreferences("pokemon_iv_reader",Context.MODE_PRIVATE).getString("crop_template_v1",null)
        if(raw==panelRaw)return
        panelRaw=raw
        panelCoordinates = try {
            raw?.let { value -> JSONObject(value).let { cfg ->
                doubleArrayOf(cfg.getDouble("x1"),cfg.getDouble("y1"),cfg.getDouble("x2"),cfg.getDouble("y2"))
            }}?.takeIf { values -> values.all{it.isFinite() && it in 0.0..1.0} }?.let { v ->
                doubleArrayOf(min(v[0],v[2]),min(v[1],v[3]),max(v[0],v[2]),max(v[1],v[3]))
            }
        } catch (_:Exception) { null }
        captureGate.clear();shadowBurst.reset();previousScene=null
    }

    /** Movable CP / IV / status bubble. */
    private fun showOverlay() {
        if (overlay != null || !Settings.canDrawOverlays(this)) return
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val density = resources.displayMetrics.density
        val button = TextView(this).apply {
            text = "CP —\nIV —\nタップで読取"
            textSize = 12f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setPadding((12 * density).toInt(), 0, (12 * density).toInt(), 0)
            minWidth = (90 * density).toInt()
            minHeight = (70 * density).toInt()
            background = GradientDrawable().apply {
                setColor(Color.rgb(66, 84, 76))
                cornerRadius = 28f * density
            }
            contentDescription = "個体値を読み取って登録"
        }
        val params = WindowManager.LayoutParams(
            (110 * density).toInt(),
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = (12 * density).toInt()
            y = ((reader?.height ?: resources.displayMetrics.heightPixels) * 0.37).toInt()
        }
        val shadowRoot = ReaderShadowControls.wrap(this, button)
        var startRawX = 0f
        var startRawY = 0f
        var windowX = 0
        var windowY = 0
        var moved = false
        button.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    startRawX = event.rawX
                    startRawY = event.rawY
                    windowX = params.x
                    windowY = params.y
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - startRawX
                    val dy = event.rawY - startRawY
                    if (abs(dx) > 12f * density || abs(dy) > 12f * density) moved = true
                    if (moved) {
                        params.x = (windowX + dx).toInt().coerceAtLeast(0)
                        params.y = (windowY + dy).toInt().coerceAtLeast(0)
                        try { wm.updateViewLayout(shadowRoot, params) } catch (_: Exception) {}
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!moved) requestOverlayCapture()
                    true
                }
                else -> true
            }
        }
        try {
            wm.addView(shadowRoot, params)
            shadowOverlayRoot = shadowRoot
            overlayVisible = true
            overlay = button
            overlayLayout = params
        } catch (e: Exception) {
            updateNotification("フロート表示失敗。許可を確認してください")
        }
    }

    /** One tap: capture immediately without removing or hiding the floating button. */
    @Synchronized private fun requestOverlayCapture() {
        if(projection==null) return
        if(scheduled || capturePending.get() || scanInProgress.get()) {
            overlay?.text="画像確保中\n少し待ってね"
            return
        }
        pipeline.reject()
        if(overlayOverlapsCrop()) {
            showScanResult("ボタンを読取範囲の外へ",false);return
        }
        val now=SystemClock.elapsedRealtime()
        val scene=captureGate.forTap(now)
        if(scene==null) {
            showScanResult("切替中・再読取",false);return
        }
        val id=pipeline.begin()
        if(id==null) {
            overlay?.text="解析中 ${pipeline.size()}件\n完了後に再タップ"
            return
        }
        activeShadowMode = ReaderShadowControls.mode(this)
        activeCaptureId=id
        expectedScene=scene.signature
        scanStartedAt=now
        scanInProgress.set(true)
        captureByOverlay=true
        overlay?.text="CP —\nIV —\n画像確保中"
        refreshReviewBadge()
        capturePending.set(true)
        main.postDelayed(scanTimeout,1500L)
    }

    private fun overlayOverlapsCrop(): Boolean {
        val bubble = shadowOverlayRoot ?: return false
        val frameReader = reader ?: return false
        val raw = getSharedPreferences("pokemon_iv_reader", Context.MODE_PRIVATE)
            .getString("crop_template_v1", null) ?: return false
        val config = try { JSONObject(raw) } catch (_: Exception) { return false }
        val x1 = config.optDouble("x1", Double.NaN)
        val x2 = config.optDouble("x2", Double.NaN)
        val y1 = config.optDouble("y1", Double.NaN)
        val y2 = config.optDouble("y2", Double.NaN)
        if (listOf(x1, x2, y1, y2).any { !it.isFinite() || it !in 0.0..1.0 }) return false
        val panel = Rect(
            (min(x1, x2) * frameReader.width).roundToInt(),
            (min(y1, y2) * frameReader.height).roundToInt(),
            (max(x1, x2) * frameReader.width).roundToInt(),
            (max(y1, y2) * frameReader.height).roundToInt()
        )
        val xy = IntArray(2)
        bubble.getLocationOnScreen(xy)
        val margin = (12 * resources.displayMetrics.density).roundToInt()
        val button = Rect(xy[0] - margin, xy[1] - margin,
            xy[0] + bubble.width + margin, xy[1] + bubble.height + margin)
        val protected=listOf(panel, Rect((.18*frameReader.width).toInt(),(.02*frameReader.height).toInt(),(.82*frameReader.width).toInt(),(.22*frameReader.height).toInt()),
            Rect((.02*frameReader.width).toInt(),(.89*frameReader.height).toInt(),(.98*frameReader.width).toInt(),frameReader.height),
            Rect((.30*frameReader.width).toInt(),(.50*frameReader.height).toInt(),(.70*frameReader.width).toInt(),(.62*frameReader.height).toInt()),
            Rect((.80*frameReader.width).toInt(),(.40*frameReader.height).toInt(),(.94*frameReader.width).toInt(),(.47*frameReader.height).toInt()),
            Rect((.04*frameReader.width).toInt(),(.72*frameReader.height).toInt(),(.47*frameReader.width).toInt(),(.83*frameReader.height).toInt()),
            Rect((.14*frameReader.width).toInt(),(.12*frameReader.height).toInt(),(.82*frameReader.width).toInt(),(.35*frameReader.height).toInt()))
        return protected.any { Rect.intersects(it,button) }
    }

    private fun showScanResult(outcome: OverlayIvProcessor.Outcome, elapsedMs: Long) {
        overlay?.let { button ->
            val status=when(outcome.phase) {
                OverlayIvProcessor.Phase.SNAPSHOT -> "画像確保・解析中"
                OverlayIvProcessor.Phase.CP_READY -> if(outcome.displayCp==null) "CP未認識・再読取" else "CP認識・解析中"
                OverlayIvProcessor.Phase.SAVED -> "保存済み"
                OverlayIvProcessor.Phase.REVIEW -> "要確認・再読取"
                OverlayIvProcessor.Phase.FAILED -> outcome.text.take(22)
            }
            button.text="CP ${outcome.displayCp ?: "—"}\nIV ${outcome.displayIv ?: "—"}\n$status"
            button.textSize=11f
            (button.background as? GradientDrawable)?.setColor(when(outcome.phase) {
                OverlayIvProcessor.Phase.SAVED -> Color.rgb(72, 94, 79)
                OverlayIvProcessor.Phase.REVIEW,OverlayIvProcessor.Phase.FAILED -> Color.rgb(101, 94, 78)
                else -> Color.rgb(66, 84, 76)
            })
            button.contentDescription=button.text.toString()+"。"+outcome.text
        }
        refreshReviewBadge()
        if(outcome.phase!=OverlayIvProcessor.Phase.SNAPSHOT && outcome.phase!=OverlayIvProcessor.Phase.CP_READY)
            updateNotification("${outcome.text} (${elapsedMs}ms)")
    }

    private fun refreshReviewBadge() {
        overlay?.let { button ->
            val base=button.text.toString().substringBefore("\n要確認発生")
            button.text=base+if(reviewCount>0) "\n要確認発生 ${reviewCount}件" else ""
        }
    }

    private fun showScanResult(message: String, added: Boolean) {
        showScanResult(OverlayIvProcessor.Outcome(message, added),
            SystemClock.elapsedRealtime() - scanStartedAt)
    }

    private fun removeOverlay() {
        overlayVisible=false
        captureGate.clear()
        shadowBurst.reset()
        previousScene=null
        lastObservedAt=0L
        shadowOverlayRoot?.let { view ->
            try {
                (getSystemService(Context.WINDOW_SERVICE) as WindowManager).removeView(view)
            } catch (_: Exception) {}
        }
        shadowOverlayRoot = null
        overlay = null
        overlayLayout = null
    }

    private fun saveCapture(image: Image) {
        val plane = image.planes.firstOrNull() ?: return
        if (plane.pixelStride != 4 || plane.rowStride % 4 != 0) {
            throw IllegalStateException("Unsupported image stride")
        }
        val width = image.width
        val height = image.height
        val rowSize = width * 4
        require(plane.rowStride >= rowSize) { "Invalid row stride" }
        // ImageReader buffers may omit padding on the LAST row. Copy only real
        // pixels row-by-row to avoid BufferUnderflowException on some devices.
        val packed = ByteBuffer.allocateDirect(rowSize * height)
        val source = plane.buffer
        val line = ByteArray(rowSize)
        for (y in 0 until height) {
            source.position(y * plane.rowStride)
            source.get(line)
            packed.put(line)
        }
        packed.flip()
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        try {
            bitmap.copyPixelsFromBuffer(packed)
            val dir = File(filesDir, CAPTURE_DIR).apply { mkdirs() }
            val name = "capture_${System.currentTimeMillis()}_${SystemClock.uptimeMillis()}.png"
            val destination = File(dir, name)
            try {
                FileOutputStream(destination).use { output ->
                    if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                        throw IllegalStateException("PNG encode failed")
                    }
                }
            } catch (e: Exception) {
                destination.delete()
                throw e
            }
            trimCaptureFiles(dir)
            captureCount++
            main.post { updateNotification("${captureCount}枚撮影済み。アプリへ戻って読み込めます") }
        } finally {
            bitmap.recycle()
        }
    }

    private fun trimCaptureFiles(dir: File) {
        dir.listFiles { file -> file.isFile && file.name.endsWith(".png") }
            ?.sortedBy { it.name }
            ?.dropLast(MAX_CAPTURES)
            ?.forEach { it.delete() }
    }

    private fun createChannel() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "個体値画面の撮影", NotificationManager.IMPORTANCE_LOW)
        )
    }

    private fun serviceAction(action: String, requestCode: Int): PendingIntent {
        val intent = Intent(this, ScreenCaptureService::class.java).apply { this.action = action }
        return PendingIntent.getService(
            this, requestCode, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun notification(message: String): Notification {
        val open = PendingIntent.getActivity(
            this, 101, Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            }, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("PokemonIVReader：画面取得中")
            .setContentText(message)
            .setStyle(Notification.BigTextStyle().bigText(message))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(android.R.drawable.ic_menu_camera, "2秒後に撮影", serviceAction(ACTION_CAPTURE, 102))
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "共有を終了", serviceAction(ACTION_STOP, 103))
            .build()
    }

    private fun updateNotification(message: String) {
        if (!hasStopped) {
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .notify(NOTIFICATION_ID, notification(message))
        }
    }

    private fun closeProjection(stopProjection: Boolean) {
        if (hasStopped) return
        hasStopped = true
        isSessionActive=false
        pipeline.clear()
        activeCaptureId=0L
        captureGate.clear()
        capturePending.set(false)
        shadowBurst.reset()
        main.removeCallbacks(scanTimeout)
        scanInProgress.set(false)
        captureByOverlay = false
        scheduled = false
        removeOverlay()

        // Take ownership of the old resources before an async callback can
        // arrive. The callback is delivered on captureThread, not the UI thread.
        val oldReader = reader
        reader = null
        val oldDisplay = virtualDisplay
        virtualDisplay = null
        val oldThread = captureThread
        captureThread = null
        val oldProjection = projection
        projection = null

        // Stop scheduling new frame callbacks and stop the image producer.
        // Do NOT close ImageReader here while its worker callback may still
        // hold an Image or access a native buffer.
        try { oldReader?.setOnImageAvailableListener(null, null) } catch (_: Exception) {}
        try { oldDisplay?.release() } catch (_: Exception) {}

        if (oldThread != null) {
            val posted = try {
                Handler(oldThread.looper).post {
                    // Runs on the same thread as OnImageAvailableListener.
                    // All previously queued frame callbacks can finish first.
                    try { oldReader?.close() } catch (_: Exception) {}
                    oldThread.quitSafely()
                }
            } catch (_: Exception) {
                false
            }
            if (!posted) {
                try { oldReader?.close() } catch (_: Exception) {}
                oldThread.quitSafely()
            }
        } else {
            try { oldReader?.close() } catch (_: Exception) {}
        }

        if (oldProjection != null) {
            if (stopProjection) {
                try { oldProjection.stop() } catch (_: Exception) {}
            }
            try { oldProjection.unregisterCallback(projectionCallback) } catch (_: Exception) {}
        }
    }

    override fun onDestroy() {
        closeProjection(stopProjection = true)
        super.onDestroy()
    }
}
