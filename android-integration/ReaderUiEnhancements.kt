package com.example.pokemonivreader

import android.app.Activity
import android.app.AlertDialog
import android.app.Application
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.util.Base64
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/**
 * Additive, opt-in MainActivity integration. It never replaces OCR rendering
 * or the existing copy button. Call attach(this) after super.onCreate(...).
 */
internal object ReaderUiEnhancements {
    fun attach(activity: Activity) {
        val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        var lastTransfer = 0L
        val clipboardListener = ClipboardManager.OnPrimaryClipChangedListener {
            // Only exports produced by the IV reader qualify for automatic opening.
            val value = try {
                clipboard.primaryClip?.getItemAt(0)?.coerceToText(activity)?.toString()
            } catch (_: Exception) { null } ?: return@OnPrimaryClipChangedListener
            val normalized = value.trimStart('\uFEFF', ' ', '\n', '\r')
            if (!normalized.startsWith("個体値厳選") ||
                !Regex("(?m)^#\\s+\\S").containsMatchIn(normalized)) return@OnPrimaryClipChangedListener
            val now = SystemClock.elapsedRealtime()
            if (now - lastTransfer < 800L) return@OnPrimaryClipChangedListener
            lastTransfer = now
            // Keep the original clipboard data untouched. No API key is transferred.
            val bytes = normalized.toByteArray(Charsets.UTF_8)
            if (bytes.size > 24000) {
                Toast.makeText(activity, "データ量が多いため、自動転記できません。コピーした内容を貼り付けてください。", Toast.LENGTH_LONG).show()
                return@OnPrimaryClipChangedListener
            }
            val encoded = Base64.encodeToString(bytes,
                Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
            val uri = Uri.parse("https://pokemoniv-production.up.railway.app/app#ivdata=" + encoded)
            try {
                activity.startActivity(Intent(Intent.ACTION_VIEW, uri))
            } catch (_: Exception) {
                Toast.makeText(activity, "厳選アプリを開けませんでした。コピー内容は残っています。", Toast.LENGTH_LONG).show()
            }
        }
        clipboard.addPrimaryClipChangedListener(clipboardListener)

        var deleteButton: Button? = null
        val decor = activity.window.decorView
        val listener = object : ViewTreeObserver.OnGlobalLayoutListener {
            override fun onGlobalLayout() {
                if (deleteButton?.parent != null || activity.isFinishing || activity.isDestroyed) return
                val copy = findCopyButton(decor) ?: return
                // Insert in the same column immediately after the existing copy control.
                val parent = copy.parent as? LinearLayout ?: return
                val column: LinearLayout
                val after: View
                if (parent.orientation == LinearLayout.VERTICAL) {
                    column = parent; after = copy
                } else {
                    column = parent.parent as? LinearLayout ?: return
                    if (column.orientation != LinearLayout.VERTICAL) return
                    after = parent
                }
                val button = Button(activity).apply {
                    text = "自動履歴を全削除"
                    isAllCaps = false
                    contentDescription = "自動読み取り履歴をすべて削除。確認画面を表示"
                    setOnClickListener {
                        val count = AutoIvRecords.count(activity)
                        if (count < 0) {
                            Toast.makeText(activity, "履歴を確認できませんでした", Toast.LENGTH_SHORT).show()
                            return@setOnClickListener
                        }
                        if (count == 0) {
                            Toast.makeText(activity, "削除する自動履歴はありません", Toast.LENGTH_SHORT).show()
                            return@setOnClickListener
                        }
                        AlertDialog.Builder(activity)
                            .setTitle("自動履歴を全削除")
                            .setMessage("${count}件の自動登録履歴を削除します。厳選コピーリストの履歴は削除しません。")
                            .setNegativeButton("キャンセル", null)
                            .setPositiveButton("すべて削除") { _, _ ->
                                val removed = AutoIvRecords.deleteAll(activity)
                                Toast.makeText(activity,
                                    if (removed >= 0) "${removed}件を削除しました。履歴は画面を開き直すと更新されます。"
                                    else "削除に失敗しました。履歴は変更されていません。",
                                    Toast.LENGTH_LONG).show()
                            }.show()
                    }
                }
                val place = column.indexOfChild(after)
                if (place < 0) return
                column.addView(button, place + 1,
                    LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT))
                deleteButton = button
            }
        }
        decor.viewTreeObserver.addOnGlobalLayoutListener(listener)
        decor.post { listener.onGlobalLayout() }
        activity.application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(a: Activity, state: Bundle?) {}
            override fun onActivityStarted(a: Activity) {}
            override fun onActivityResumed(a: Activity) {}
            override fun onActivityPaused(a: Activity) {}
            override fun onActivityStopped(a: Activity) {}
            override fun onActivitySaveInstanceState(a: Activity, state: Bundle) {}
            override fun onActivityDestroyed(a: Activity) {
                if (a !== activity) return
                clipboard.removePrimaryClipChangedListener(clipboardListener)
                if (decor.viewTreeObserver.isAlive)
                    decor.viewTreeObserver.removeOnGlobalLayoutListener(listener)
                activity.application.unregisterActivityLifecycleCallbacks(this)
            }
        })
    }

    private fun findCopyButton(view: View): TextView? {
        if (view is Button && view.text?.contains("自動登録データをコピー") == true)
            return view
        if (view is ViewGroup) for (i in 0 until view.childCount) {
            findCopyButton(view.getChildAt(i))?.let { return it }
        }
        return null
    }
}
