package com.example.pokemonivreader.overlayqueue

import android.accessibilityservice.AccessibilityService
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.ArrayDeque

/**
 * Optional, user-initiated text entry for Pokemon GO.
 *
 * Never scans other apps, taps screen coordinates, alters game files/network
 * traffic, or presses the final rename confirmation. If GO does not expose
 * a suitable accessibility node, the user must open the field manually.
 */
class GoTextInputAccessibilityService : AccessibilityService() {
    enum class Target { SEARCH, NICKNAME }

    companion object {
        private const val GO_PACKAGE = "com.nianticlabs.pokemongo"
        @Volatile private var active: GoTextInputAccessibilityService? = null

        fun isAvailable(): Boolean = active != null

        /** Returns false if the user has not enabled the optional service. */
        fun request(target: Target, value: String, onResult: (Boolean, String) -> Unit): Boolean {
            val service = active ?: return false
            if (value.isBlank() || value.length > 1024) {
                onResult(false, "入力文字列が空、または長すぎます")
                return true
            }
            service.main.post { service.runRequest(target, value, onResult) }
            return true
        }
    }

    private val main = Handler(Looper.getMainLooper())
    private var generation = 0

    override fun onServiceConnected() {
        super.onServiceConnected()
        active = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (active === this) active = null
        generation += 1
        main.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun runRequest(target: Target, value: String, result: (Boolean, String) -> Unit) {
        val requestId = ++generation
        fun complete(ok: Boolean, detail: String) {
            if (requestId == generation) result(ok, detail)
        }

        // An action is allowed only while GO is the active foreground window.
        val initial = rootInActiveWindow
        if (initial?.packageName?.toString() != GO_PACKAGE) {
            complete(false, "Pokémon GOを前面に表示してから押してください")
            return
        }

        var openedByService = false
        fun poll(remaining: Int) {
            if (requestId != generation) return
            val root = rootInActiveWindow
            if (root?.packageName?.toString() != GO_PACKAGE) {
                complete(false, "入力先がPokémon GOではないため中止しました")
                return
            }
            val editor = findEditor(root)
            val safeToWrite = when (target) {
                Target.SEARCH -> editor != null && !containsRenameDialog(root) &&
                    (openedByService || isSearchEditor(editor) || containsSearchContext(root))
                Target.NICKNAME -> editor != null &&
                    (openedByService || containsRenameDialog(root))
            }
            if (safeToWrite && editor != null) {
                if (writeText(editor, value)) {
                    complete(true, if (target == Target.SEARCH)
                        "検索式を入力しました。ゲーム内で確認してください"
                    else "名前を入力しました。ゲーム内で確認して保存してください")
                } else {
                    complete(false, "入力欄が外部からの文字入力に対応していません。手動で貼り付けてください")
                }
                return
            }

            if (!openedByService) {
                val trigger = when (target) {
                    Target.SEARCH -> findAction(root, ::isSearchTrigger)
                    Target.NICKNAME -> findAction(root, ::isRenameTrigger)
                }
                if (trigger != null && clickAncestor(trigger)) {
                    openedByService = true
                } else {
                    complete(false, if (target == Target.SEARCH)
                        "Searchを開いてから再度「検索入力」を押してください"
                    else "鉛筆マークを押して名前編集欄を開き、再度「名前入力」を押してください")
                    return
                }
            }
            if (remaining <= 0) {
                complete(false, "入力欄を確認できませんでした。従来のコピーボタンを使ってください")
                return
            }
            main.postDelayed({ poll(remaining - 1) }, 250L)
        }
        poll(8)
    }

    private fun writeText(editor: AccessibilityNodeInfo, value: String): Boolean {
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value)
        }
        // ACTION_SET_TEXT replaces the entire old nickname, not just a selection.
        return try {
            editor.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        } catch (_: Exception) {
            false
        }
    }

    private fun findEditor(root: AccessibilityNodeInfo): AccessibilityNodeInfo? =
        walk(root).firstOrNull {
            it.isEditable && (it.className?.toString()?.contains("EditText") == true ||
                it.actionList.any { a -> a.id == AccessibilityNodeInfo.ACTION_SET_TEXT })
        }

    private fun isSearchEditor(node: AccessibilityNodeInfo): Boolean {
        val hints = listOfNotNull(node.hintText?.toString(), node.contentDescription?.toString())
            .joinToString(" ").lowercase()
        return hints.contains("search") || hints.contains("検索")
    }

    private fun containsSearchContext(root: AccessibilityNodeInfo): Boolean =
        walk(root).any { node ->
            val s = description(node).lowercase()
            s == "search" || s == "検索" || s.contains("search pokémon") || s.contains("ポケモンを検索")
        }

    private fun containsRenameDialog(root: AccessibilityNodeInfo): Boolean =
        walk(root).any {
            val s = description(it).lowercase()
            s.contains("nickname") || s.contains("ニックネーム") ||
                s.contains("change name") || s.contains("名前を変更")
        }

    private fun isSearchTrigger(node: AccessibilityNodeInfo): Boolean {
        val name = description(node).lowercase().trim()
        return name == "search" || name == "検索" || name == "search pokémon" ||
            name == "ポケモンを検索"
    }

    private fun isRenameTrigger(node: AccessibilityNodeInfo): Boolean {
        val name = description(node).lowercase().trim()
        return name == "rename" || name == "edit nickname" ||
            name == "ニックネームを変更" || name == "名前を変更"
    }

    private fun description(node: AccessibilityNodeInfo): String =
        listOfNotNull(node.contentDescription?.toString(), node.text?.toString())
            .joinToString(" ")

    private fun findAction(
        root: AccessibilityNodeInfo,
        predicate: (AccessibilityNodeInfo) -> Boolean
    ): AccessibilityNodeInfo? = walk(root).firstOrNull(predicate)

    private fun clickAncestor(node: AccessibilityNodeInfo): Boolean {
        var current: AccessibilityNodeInfo? = node
        repeat(4) {
            val n = current ?: return false
            if (n.isClickable && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true
            current = n.parent
        }
        return false
    }

    private fun walk(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val found = ArrayList<AccessibilityNodeInfo>()
        val pending = ArrayDeque<AccessibilityNodeInfo>()
        pending.add(root)
        while (pending.isNotEmpty() && found.size < 250) {
            val node = pending.removeFirst()
            found.add(node)
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let(pending::addLast)
            }
        }
        return found
    }
}
