package com.example.pokemonivreader

import android.content.Context
import android.content.Intent
import android.net.Uri

/** Web-based ranking scores stay current without another native app release.
 *  This shortcut sends no OCR history, IV or private identifiers to the Web URL. */
object LowScoreWebShortcut {
    const val URL = "https://pokemoniv-production.up.railway.app/app?tool=low-score"

    fun open(context: Context): Boolean = try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(URL))
            .addCategory(Intent.CATEGORY_BROWSABLE)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (_: Exception) {
        false
    }
}
