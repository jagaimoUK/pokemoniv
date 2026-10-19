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

/** Adds reader -> Web IV import and a non-destructive UI extension. */
internal object ReaderUiEnhancements {
    fun attach(activity: Activity) {
        val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        var lastTransfer = 0L
        val listener = ClipboardManager.OnPrimaryClipChangedListener {
            val value = try { clipboard.primaryClip?.getItemAt(0)?.coerceToText(activity)?.toString() }
                        catch (_: Exception) { null } ?: return@OnPrimaryClipChangedListener
            val normalized = value.trimStart('\uFEFF', ' ', '\n', '\r')
            if (!normalized.startsWith("個体値厳選") ||
                !Regex("(?m)^#\\s+\\S").containsMatchIn(normalized)) return@OnPrimaryClipChangedListener
            val now = SystemClock.elapsedRealtime()
            if (now - lastTransfer < 800L) return@OnPrimaryClipChangedListener
            lastTransfer = now
            val bytes = normalized.toByteArray(Charsets.UTF_8)
            if (bytes.size > 24000) {
                Toast.makeText(activity, "件数が多いため自動転記できません。コピーした内容を貼り付けてください。", Toast.LENGTH_LONG).show()
                return@OnPrimaryClipChangedListener
            }
            val payload = Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
            try {
                activity.startActivity(Intent(Intent.ACTION_VIEW,
                    Uri.parse("https://pokemoniv-production.up.railway.app/app#ivdata=" + payload)))
            } catch (_: Exception) {
                Toast.makeText(activity, "Webアプリを開けません。クリップボードのコピーは残っています。", Toast.LENGTH_LONG).show()
            }
        }
        clipboard.addPrimaryClipChangedListener(listener)
        var listening = true
        val decor = activity.window.decorView
        var clearButton: Button? = null
        val observer = object : ViewTreeObserver.OnGlobalLayoutListener {
            override fun onGlobalLayout() {
                if (clearButton?.parent != null || activity.isFinishing || activity.isDestroyed) return
                val copy = locateCopy(decor) ?: return
                // Climb through nested horizontal rows until a vertical layout is found.
                var after: View = copy
                var ancestor: ViewGroup? = copy.parent as? ViewGroup
                var column: LinearLayout? = null
                while (ancestor != null) {
                    if (ancestor is LinearLayout && ancestor.orientation == LinearLayout.VERTICAL) {
                        column = ancestor
                        break
                    }
                    after = ancestor
                    ancestor = ancestor.parent as? ViewGroup
                }
                val targetColumn = column ?: return
                val button = Button(activity).apply {
                    text = "自動履歴を全削除"
                    isAllCaps = false
                    setOnClickListener {
                        val count = AutoIvRecords.count(activity)
                        if (count <= 0) {
                            Toast.makeText(activity, if (count == 0) "削除する履歴はありません" else "履歴を確認できませんでした", Toast.LENGTH_SHORT).show()
                            return@setOnClickListener
                        }
                        AlertDialog.Builder(activity)
                            .setTitle("自動履歴を全削除")
                            .setMessage("${count}件の自動登録履歴を削除します。厳選コピーリストの履歴には影響しません。")
                            .setNegativeButton("キャンセル", null)
                            .setPositiveButton("すべて削除") { _, _ ->
                                val removed = AutoIvRecords.deleteAll(activity)
                                Toast.makeText(activity,
                                    if (removed >= 0) "${removed}件を削除しました。画面を再表示すると履歴に反映されます。"
                                    else "削除に失敗しました。履歴は変更されていません。",
                                    Toast.LENGTH_LONG).show()
                            }.show()
                    }
                }
                val index = targetColumn.indexOfChild(after)
                if (index >= 0) {
                    targetColumn.addView(button, index + 1,
                        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
                    clearButton = button
                }
            }
        }
        decor.viewTreeObserver.addOnGlobalLayoutListener(observer)
        decor.post { observer.onGlobalLayout() }
        activity.application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(a: Activity, state: Bundle?) {}
            override fun onActivityStarted(a: Activity) {}
            override fun onActivityResumed(a: Activity) {
                if (a === activity && !listening) {
                    clipboard.addPrimaryClipChangedListener(listener); listening = true
                }
            }
            override fun onActivityPaused(a: Activity) {
                if (a === activity && listening) {
                    clipboard.removePrimaryClipChangedListener(listener); listening = false
                }
            }
            override fun onActivityStopped(a: Activity) {}
            override fun onActivitySaveInstanceState(a: Activity, state: Bundle) {}
            override fun onActivityDestroyed(a: Activity) {
                if (a !== activity) return
                if (listening) clipboard.removePrimaryClipChangedListener(listener)
                if (decor.viewTreeObserver.isAlive) decor.viewTreeObserver.removeOnGlobalLayoutListener(observer)
                activity.application.unregisterActivityLifecycleCallbacks(this)
            }
        })
    }
    private fun locateCopy(view: View): TextView? {
        if (view is Button && view.text?.contains("自動登録データをコピー") == true) return view
        if (view is ViewGroup) for (i in 0 until view.childCount)
            locateCopy(view.getChildAt(i))?.let { return it }
        return null
    }
}
