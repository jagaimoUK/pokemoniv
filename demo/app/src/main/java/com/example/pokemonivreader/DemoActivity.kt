package com.example.pokemonivreader

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.example.pokemonivreader.overlayqueue.OverlayCopyQueueController
import com.example.pokemonivreader.overlayqueue.OverlayCopyQueueImportActivity

/** Isolated build/test harness, not a replacement for the actual OCR app. */
class DemoActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
        }
        layout.addView(TextView(this).apply {
            text = "厳選コピーリスト確認用\n既存の読み取りアプリとは別のビルド確認用です。"
            textSize = 18f
        })
        layout.addView(Button(this).apply {
            text = "取り込み画面"
            setOnClickListener { startActivity(Intent(this@DemoActivity, OverlayCopyQueueImportActivity::class.java)) }
        })
        layout.addView(Button(this).apply {
            text = "オーバーレイを表示"
            setOnClickListener {
                val overlay = OverlayCopyQueueController.get(this@DemoActivity)
                if (!overlay.show()) startActivity(Intent(this@DemoActivity, OverlayCopyQueueImportActivity::class.java))
                else overlay.openPanel()
            }
        })
        setContentView(layout)
    }
}
