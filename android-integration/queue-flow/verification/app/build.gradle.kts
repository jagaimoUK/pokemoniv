plugins {
    id("com.android.application") version "8.7.3"
    id("org.jetbrains.kotlin.android") version "2.0.21"
}
android {
    namespace = "com.example.pokemonivreader.overlayqueue"
    compileSdk = 35
    defaultConfig { applicationId = "com.example.pokemonivreader.queueverification"; minSdk = 23; targetSdk = 35 }
    sourceSets["main"].java.srcDir("../../../overlayqueue")
    testOptions.unitTests.isIncludeAndroidResources = true
}
dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
}
