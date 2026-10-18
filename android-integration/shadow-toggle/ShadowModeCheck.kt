package com.example.pokemonivreader
fun main() {
    val empty = emptyList<ShadowRecognizer.Evidence>()
    check(ReaderShadowControls.decide(ShadowRecognizer.Mode.NORMAL_ONLY, true, empty).state == ShadowRecognizer.State.NORMAL)
    check(ReaderShadowControls.decide(ShadowRecognizer.Mode.SHADOW_ONLY, false, empty).state == ShadowRecognizer.State.SHADOW)
    check(ReaderShadowControls.decide(ShadowRecognizer.Mode.AUTO, true, empty).state == ShadowRecognizer.State.SHADOW)
    check(ReaderShadowControls.decide(ShadowRecognizer.Mode.AUTO, false, empty).state == ShadowRecognizer.State.UNKNOWN)
    println("Manual normal/shadow override, automatic mode: PASS")
}
