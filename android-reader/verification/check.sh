#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fetch() { curl -fLsS --retry 2 "https://repo.maven.apache.org/maven2/$1" -o "$work/$2"; }
aar() {
 curl -fLsS --retry 2 "https://dl.google.com/dl/android/maven2/$1/$2/$3/$2-$3.aar" -o "$work/temp.aar"
 unzip -p "$work/temp.aar" classes.jar > "$work/$2.jar"
}
fetch org/jetbrains/kotlin/kotlin-compiler-embeddable/2.2.20/kotlin-compiler-embeddable-2.2.20.jar compiler.jar
fetch org/jetbrains/kotlin/kotlin-stdlib/2.2.20/kotlin-stdlib-2.2.20.jar stdlib.jar
fetch org/jetbrains/kotlin/kotlin-script-runtime/2.2.20/kotlin-script-runtime-2.2.20.jar script.jar
fetch org/jetbrains/kotlin/kotlin-reflect/1.6.10/kotlin-reflect-1.6.10.jar reflect.jar
fetch org/jetbrains/kotlin/kotlin-daemon-embeddable/2.2.20/kotlin-daemon-embeddable-2.2.20.jar daemon.jar
fetch org/jetbrains/kotlinx/kotlinx-coroutines-core-jvm/1.8.0/kotlinx-coroutines-core-jvm-1.8.0.jar coroutines.jar
fetch org/jetbrains/annotations/13.0/annotations-13.0.jar annotations.jar
fetch org/robolectric/android-all/9-robolectric-4913185-2/android-all-9-robolectric-4913185-2.jar android.jar
fetch org/json/json/20240303/json-20240303.jar json.jar
fetch junit/junit/4.13.2/junit-4.13.2.jar junit.jar
fetch org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar hamcrest.jar
aar com/google/android/gms play-services-tasks 18.2.0
aar com/google/android/gms play-services-base 18.5.0
aar com/google/android/gms play-services-basement 18.4.0
aar com/google/android/gms play-services-mlkit-text-recognition-common 19.1.0
aar com/google/android/gms play-services-mlkit-text-recognition-japanese 16.0.1
aar com/google/mlkit vision-common 17.3.0
aar com/google/mlkit vision-interfaces 16.3.0
aar com/google/mlkit common 18.11.0
aar com/google/mlkit text-recognition-japanese 16.0.1
aar com/google/mlkit text-recognition-bundled-common 17.0.0
curl -fLsS --retry 2 https://dl.google.com/dl/android/maven2/androidx/lifecycle/lifecycle-common/2.6.1/lifecycle-common-2.6.1.jar -o "$work/lifecycle.jar"
curl -fLsS --retry 2 https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster/pokemon.json -o "$work/pokemon.json"
curl -fLsS --retry 2 https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv -o "$work/names.csv"
classpath=$(find "$work" -name '*.jar' -printf '%p:' | sed 's/:$//')
java -cp "$work/*" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect \
 -classpath "$classpath" -d "$work/check.jar" \
 "$root"/app/src/main/java/com/example/pokemonivreader/{CatalogData,CatalogUpdates,PokemonCatalog,RankingEligibility,GenderRecognizer,ShadowRecognizer,EvolutionMath,PumpkinForms,PumpkinHeightClassifier,TypeBandEvidence,AutoIvRecords,HistoryShadowBatch,IvSelectionText,ScreenTextRecognizer,OverlayIvProcessor,ReaderShadowControls,IvBarRecognizer,OverlayEligibilityBadge,CaptureGate}.kt \
 "$root/verification/RegionalFormsCheck.kt" "$root/app/src/test/java/com/example/pokemonivreader/IvSelectionTextTest.kt"
java -cp "$work/check.jar:$classpath" com.example.pokemonivreader.RegionalFormsCheckKt "$root" "$work/pokemon.json" "$work/names.csv" - "$work/merged.json"
(cd "$root" && java -cp "$work/check.jar:$classpath" org.junit.runner.JUnitCore com.example.pokemonivreader.IvSelectionTextTest)
python3 "$root/tools/build_catalog.py" --pokemon-file "$work/pokemon.json" --names-file "$work/names.csv" --output "$work/generated.json"
python3 - "$work/merged.json" "$work/generated.json" <<'PY'
import sys,json
left,right=({p['id']:p for p in json.load(open(path))} for path in sys.argv[1:])
assert left==right,'Python and Android catalog merges differ'
print('PASS: Python/Android data parity')
PY
