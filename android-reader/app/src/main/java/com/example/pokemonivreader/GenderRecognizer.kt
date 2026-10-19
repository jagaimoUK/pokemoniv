package com.example.pokemonivreader

/** Reads the fixed gender symbol beside the HP bar, not body shape or nickname. */
internal object GenderRecognizer {
    enum class Gender(val label: String) {
        UNKNOWN("未認識"), MALE("オス"), FEMALE("メス"), GENDERLESS("性別なし");
        companion object { fun fromStored(value: String): Gender = entries.firstOrNull { it.name == value } ?: UNKNOWN }
    }
    data class Result(val gender: Gender, val diagnostic: String)

    /** Icon crop: screen x=80..94%, y=40..47%. A ring plus upper-right
     * extension is male; a ring above a lower extension is female.
     * Missing/unrecognized geometry is UNKNOWN, never silently male.
     */
    fun read(pixels: IntArray, width: Int, height: Int): Result {
        if (width < 8 || height < 8 || pixels.size < width * height) return Result(Gender.UNKNOWN, "性別画像なし")
        val mask = BooleanArray(width * height)
        for (i in mask.indices) {
            val r = (pixels[i] ushr 16) and 255
            val g = (pixels[i] ushr 8) and 255
            val b = pixels[i] and 255
            mask[i] = r in 95..232 && g in 110..245 && b in 110..245 && g-r >= 5 && b-r >= 5 && kotlin.math.abs(g-b) <= 32
        }
        val visited = BooleanArray(mask.size)
        val queue = IntArray(mask.size)
        val candidates = mutableListOf<Gender>()
        for (start in mask.indices) {
            if (!mask[start] || visited[start]) continue
            var head = 0; var tail = 0
            queue[tail++] = start; visited[start] = true
            var left = width; var right = 0; var top = height; var bottom = 0
            val component = mutableListOf<Int>()
            while (head < tail) {
                val at = queue[head++]; component += at
                val x = at % width; val y = at / width
                left = minOf(left,x); right = maxOf(right,x); top = minOf(top,y); bottom = maxOf(bottom,y)
                fun add(next: Int) { if (mask[next] && !visited[next]) { visited[next]=true;queue[tail++]=next } }
                if (x>0) add(at-1); if(x+1<width) add(at+1)
                if (y>0) add(at-width); if(y+1<height) add(at+width)
            }
            val w=right-left+1; val h=bottom-top+1
            if (component.size < 20 || w<8 || h<8 || w>width*0.95 || h>height*0.95) continue
            if (component.size.toDouble()/(w*h) !in 0.18..0.78) continue
            val ink=BooleanArray(w*h)
            for(at in component) ink[(at/width-top)*w+(at%width-left)]=true
            val outside=BooleanArray(w*h)
            val localQueue=IntArray(w*h)
            var bestSize=0; var bestX=0.0; var bestY=0.0
            for(seed in ink.indices) {
                if(ink[seed] || outside[seed]) continue
                var qh=0;var qt=0;var border=false;var sumX=0L;var sumY=0L
                localQueue[qt++]=seed;outside[seed]=true
                while(qh<qt) {
                    val at=localQueue[qh++];val x=at%w;val y=at/w
                    sumX+=x;sumY+=y
                    if(x==0 || y==0 || x==w-1 || y==h-1) border=true
                    fun add(next:Int) {if(!ink[next] && !outside[next]){outside[next]=true;localQueue[qt++]=next}}
                    if(x>0)add(at-1);if(x+1<w)add(at+1);if(y>0)add(at-w);if(y+1<h)add(at+w)
                }
                if(!border && qt>bestSize){bestSize=qt;bestX=sumX.toDouble()/qt;bestY=sumY.toDouble()/qt}
            }
            if(bestSize < maxOf(5,(w*h*0.045).toInt())) continue
            val cx=bestX/(w-1);val cy=bestY/(h-1)
            when {
                cx in 0.20..0.48 && cy in 0.53..0.80 -> candidates += Gender.MALE
                cx in 0.33..0.67 && cy in 0.20..0.46 -> candidates += Gender.FEMALE
            }
        }
        val distinct=candidates.distinct()
        val gender=distinct.singleOrNull() ?: Gender.UNKNOWN
        return Result(gender, if(gender==Gender.UNKNOWN) "性別記号を一意に判別できません" else "性別記号の形状から${gender.label}と判定")
    }
}
