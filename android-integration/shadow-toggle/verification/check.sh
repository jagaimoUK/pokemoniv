#!/usr/bin/env bash
set -euo pipefail
src="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fetch() { curl -fLsS --retry 2 "https://repo.maven.apache.org/maven2/$1" -o "$work/$2"; }
fetch org/jetbrains/kotlin/kotlin-compiler-embeddable/2.2.20/kotlin-compiler-embeddable-2.2.20.jar compiler.jar
fetch org/jetbrains/kotlin/kotlin-stdlib/2.2.20/kotlin-stdlib-2.2.20.jar stdlib.jar
fetch org/jetbrains/kotlin/kotlin-script-runtime/2.2.20/kotlin-script-runtime-2.2.20.jar script.jar
fetch org/jetbrains/kotlin/kotlin-reflect/1.6.10/kotlin-reflect-1.6.10.jar reflect.jar
fetch org/jetbrains/kotlin/kotlin-daemon-embeddable/2.2.20/kotlin-daemon-embeddable-2.2.20.jar daemon.jar
fetch org/jetbrains/kotlinx/kotlinx-coroutines-core-jvm/1.8.0/kotlinx-coroutines-core-jvm-1.8.0.jar coroutines.jar
fetch org/jetbrains/annotations/13.0/annotations-13.0.jar annotations.jar
fetch org/robolectric/android-all/9-robolectric-4913185-2/android-all-9-robolectric-4913185-2.jar android.jar
fetch org/json/json/20240303/json-20240303.jar json.jar
java -cp "$work/*" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect \
 -classpath "$work/stdlib.jar:$work/android.jar:$work/json.jar" -d "$work/check.jar" \
 "$src/verification/ShadowRecognizer.kt" "$src/ReaderShadowControls.kt" "$src/HistoryShadowBatch.kt" \
 "$src/ShadowModeCheck.kt" "$src/HistoryShadowBatchCheck.kt"
java -cp "$work/check.jar:$work/stdlib.jar:$work/android.jar:$work/json.jar" com.example.pokemonivreader.ShadowModeCheckKt
java -cp "$work/check.jar:$work/stdlib.jar:$work/json.jar" com.example.pokemonivreader.HistoryShadowBatchCheckKt
