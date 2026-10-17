plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("org.robolectric:robolectric:4.14.1")
}

android {
    namespace = "com.example.pokemonivreader"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.example.pokemonivreader.overlayqueuedemo"
        minSdk = 26
        targetSdk = 32 // Only for the isolated test harness. Integrate into real app targetSdk unchanged.
        versionCode = 1
        versionName = "0.1"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    testOptions { unitTests.isIncludeAndroidResources = true }
}
