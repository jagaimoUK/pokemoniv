package com.example.pokemonivreader.overlayqueue

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.net.Uri
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** Import via Android Sharesheet, or paste while this Activity is foreground.
 * Never attempts to read the clipboard from an overlay/background Service.
 */
class OverlayCopyQueueImportActivity : Activity() {
    private lateinit var entry: EditText
    private lateinit var submit: Button
    private val store by lazy { OverlayQueueStore(this) }
    private fun dp(n: Int): Int = (resources.displayMetrics.density * n + .5f).toInt()
    private fun notifyUser(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "厳選リスト取り込み"
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }
        body.addView(TextView(this).apply {
            text = "Webの「オーバーレイ用にコピー」または「Androidへ送る」を使うと、個体値とCPも引き継げます。従来の検索式・名前の2行ペアも取り込めます。"
            textSize = 15f
        })
        entry = EditText(this).apply {
            hint = "検索式\nニックネーム\n検索式\nニックネーム…"
            minLines = 9
            maxLines = 16
            isSingleLine = false
            setTextIsSelectable(true)
            gravity = Gravity.TOP or Gravity.START
            setHorizontallyScrolling(false)
        }
        body.addView(entry, LinearLayout.LayoutParams(-1, dp(255)))
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val paste = Button(this).apply {
            text = "貼り付け"
            setOnClickListener {
                try {
                    val manager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    val clip = manager.primaryClip
                    val data = clip?.getItemAt(0)?.coerceToText(this@OverlayCopyQueueImportActivity)?.toString()
                    if (data.isNullOrEmpty()) notifyUser("クリップボードが空です") else entry.setText(data)
                } catch (e: Exception) { notifyUser("貼り付けに失敗しました: ${e.localizedMessage}") }
            }
        }
        buttons.addView(paste, LinearLayout.LayoutParams(0, dp(52), 1f))
        submit = Button(this).apply {
            text = "取り込む"
            setOnClickListener { import() }
        }
        buttons.addView(submit, LinearLayout.LayoutParams(0, dp(52), 1f))
        body.addView(buttons)
        body.addView(Button(this).apply {
            text = "オーバーレイを表示"
            setOnClickListener { showOrRequestOverlay() }
        })
        // Web-only ranking logic updates without reinstalling this Android APK.
        // Use the default browser; no API key or score data is bundled in Android.
        body.addView(Button(this).apply {
            text = "低スコア個体を検索（Web）"
            setTextColor(Color.rgb(232, 241, 234))
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(Color.rgb(73, 103, 91))
                cornerRadius = dp(24).toFloat()
            }
            setOnClickListener {
                val url = Uri.parse("https://pokemoniv-production.up.railway.app/app?tool=low-score")
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, url).addCategory(Intent.CATEGORY_BROWSABLE))
                } catch (_: Exception) {
                    notifyUser("ブラウザを開けませんでした。厳選Webアプリを直接開いてください。")
                }
            }
        })
        body.addView(Button(this).apply {
            text = "履歴から選ぶ"
            setOnClickListener {
                val sessions = store.sessions()
                if (sessions.isEmpty()) notifyUser("履歴がありません") else {
                    val labels = sessions.map { session ->
                        val date = java.text.DateFormat.getDateTimeInstance().format(java.util.Date(session.createdAt))
                        "$date / ${session.count}件"
                    }.toTypedArray()
                    AlertDialog.Builder(this@OverlayCopyQueueImportActivity).setTitle("取り込み履歴")
                        .setItems(labels) { _, index -> store.currentSessionId = sessions[index].id; showOrRequestOverlay() }
                        .setNegativeButton("戻る", null).show()
                }
            }
        })
        val closeButtons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        closeButtons.addView(Button(this).apply {
            text = "画面を閉じる"
            setOnClickListener { returnToGame() }
        }, LinearLayout.LayoutParams(0, dp(52), 1f))
        closeButtons.addView(Button(this).apply {
            text = "オーバーレイ終了"
            setOnClickListener { OverlayCopyQueueController.get(this@OverlayCopyQueueImportActivity).hide(); returnToGame() }
        }, LinearLayout.LayoutParams(0, dp(52), 1f))
        body.addView(closeButtons)
        val scroll = ScrollView(this)
        scroll.addView(body)
        setContentView(scroll)
        applySharedText(intent)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        applySharedText(intent)
    }
    private fun applySharedText(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND && intent.type?.startsWith("text/") == true) {
            val incoming = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
            if (!incoming.isNullOrBlank()) entry.setText(incoming)
        }
    }
    private fun showOrRequestOverlay() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            notifyUser("他のアプリの上に表示する権限を許可してください")
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")))
        } else {
            val controller = OverlayCopyQueueController.get(this)
            if (controller.show()) { returnToGame(); controller.openPanel() }
        }
    }
    private fun returnToGame() { moveTaskToBack(true); finish() }
    private fun import() {
        val raw = entry.text.toString()
        if (raw.length > 2_000_000) { notifyUser("入力が大きすぎます。分けて取り込んでください"); return }
        val parsed = try { OverlayPairParser.parse(raw) }
        catch (e: OverlayPairFormatException) { entry.error = e.message; notifyUser(e.message ?: "入力形式に問題があります"); return }
        if (parsed.size > 10_000) { notifyUser("1回の取り込み上限は10,000件です"); return }
        submit.isEnabled = false
        Thread {
            try {
                store.importPairs(parsed)
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    submit.isEnabled = true
                    notifyUser("${parsed.size}件を保存しました。チェック履歴は端末内に残ります")
                    OverlayCopyQueueController.get(this).onImported()
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
                        showOrRequestOverlay()
                    } else returnToGame()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    submit.isEnabled = true
                    notifyUser("保存に失敗しました: ${e.localizedMessage}")
                }
            }
        }.start()
    }
}
