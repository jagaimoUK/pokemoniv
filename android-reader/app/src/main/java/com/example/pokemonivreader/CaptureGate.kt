package com.example.pokemonivreader

/** Tiny screen signatures only; never keeps a screenshot after capture. */
internal class CaptureGate {
    data class Signature(val pixels: IntArray, val regions:IntArray=intArrayOf(pixels.size)) {
        fun same(other: Signature): Boolean {
            if (pixels.size != other.pixels.size || pixels.isEmpty()) return false
            if(!regions.contentEquals(other.regions))return false
            var offset=0
            for(size in regions) {
            var changed=0
            for(i in offset until offset+size) {
                val a=pixels[i];val b=other.pixels[i]
                val delta=kotlin.math.abs(((a ushr 16)and 255)-((b ushr 16)and 255)) +
                    kotlin.math.abs(((a ushr 8)and 255)-((b ushr 8)and 255)) + kotlin.math.abs((a and 255)-(b and 255))
                if(delta>48)changed++
            }
            if(changed>maxOf(1,(size*0.004).toInt()))return false
            offset+=size
            }
            return true
        }
    }
    data class Seen(val signature: Signature, val at:Long, val stable:Boolean)
    private var latest:Seen?=null
    @Synchronized fun observe(signature:Signature, at:Long):Seen {
        val old=latest
        val stable=old!=null && at>=old.at && at-old.at in 30..220 && old.signature.same(signature)
        return Seen(signature,at,stable).also{latest=it}
    }
    @Synchronized fun current(at:Long):Seen? = latest?.takeIf{at-it.at in 0..180}
    // A quiet display may stop producing frames. Always compare with a fresh
    // frame after the tap, even when the last quiet signature is older.
    @Synchronized fun forTap(at:Long):Seen? = latest?.takeIf{at>=it.at && (it.stable || at-it.at>=80L)}
    @Synchronized fun clear(){latest=null}
}

/** Multiple immutable snapshots may finish out of order; only the latest tap paints the bubble. */
internal class ScanPipeline(private val capacity:Int=4) {
    private var next=0L
    private var newest=0L
    private val jobs=mutableSetOf<Long>()
    @Synchronized fun begin():Long? {
        if(jobs.size>=capacity)return null
        return (++next).also{newest=it;jobs+=it}
    }
    @Synchronized fun finish(id:Long){jobs-=id}
    @Synchronized fun isNewest(id:Long)=id==newest
    @Synchronized fun size()=jobs.size
    @Synchronized fun reject(){newest=++next}
    @Synchronized fun clear(){jobs.clear();newest=++next}
}
