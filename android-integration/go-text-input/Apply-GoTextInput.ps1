param(
    [string]$ProjectDir = 'C:\Users\kuros\AndroidStudioProjects\PokemonIVReader',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$integration = Split-Path -Parent $PSScriptRoot
$sourceService = Join-Path $integration 'overlayqueue\GoTextInputAccessibilityService.kt'
$sourceXml = Join-Path $PSScriptRoot 'go_text_input_service.xml'
$dstJava = Join-Path $ProjectDir 'app\src\main\java\com\example\pokemonivreader\overlayqueue'
$dstController = Join-Path $dstJava 'OverlayCopyQueueController.kt'
$dstService = Join-Path $dstJava 'GoTextInputAccessibilityService.kt'
$dstManifest = Join-Path $ProjectDir 'app\src\main\AndroidManifest.xml'
$dstXml = Join-Path $ProjectDir 'app\src\main\res\xml\go_text_input_service.xml'
$gradlew = Join-Path $ProjectDir 'gradlew.bat'
foreach($p in @($sourceService, $sourceXml, $dstController, $dstManifest, $gradlew)) {
    if(-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Required file missing: $p" }
}

function Replace-ExactlyOnce([string]$s, [string]$a, [string]$b) {
    $index = $s.IndexOf($a, [StringComparison]::Ordinal)
    if($index -lt 0 -or $s.IndexOf($a, $index + $a.Length, [StringComparison]::Ordinal) -ge 0) {
        throw "Unsupported controller source: unique anchor not found: $($a.Substring(0, [Math]::Min(65, $a.Length)))"
    }
    return $s.Substring(0, $index) + $b + $s.Substring($index + $a.Length)
}

$current = [IO.File]::ReadAllText($dstController)
$newController = $current -replace '\r\n?', ([string][char]10)
$LF = [string][char]10
if(-not $newController.Contains('private fun requestGoInput(')) {
    $newController = Replace-ExactlyOnce $newController 'import android.content.Context' ('import android.content.Context' + $LF + 'import android.content.Intent')
    $requestMethod = @'
    /**
     * Input is separate from "copied"; saving in GO is never inferred.
     */
    private fun requestGoInput(item: OverlayQueueStore.Item, search: Boolean) {
        if (rows.none { it.id == item.id }) return
        val value = if (search) item.search else item.nickname
        val target = if (search) GoTextInputAccessibilityService.Target.SEARCH
            else GoTextInputAccessibilityService.Target.NICKNAME
        if (!GoTextInputAccessibilityService.request(target, value) { _, message -> toast(message) }) {
            toast("自動入力にはユーザー補助の「厳選テキスト入力」を有効にしてください")
            try {
                app.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                })
            } catch (_: Exception) { }
        }
    }
'@
    $newController = Replace-ExactlyOnce $newController '    private fun copyCleanup(value: String) {' ($requestMethod + $LF + '    private fun copyCleanup(value: String) {')
    $newController = Replace-ExactlyOnce $newController '    private data class Holder(val title: TextView, val search: Button, val nick: Button)' '    private data class Holder(val title: TextView, val search: Button, val nick: Button, val inputSearch: Button, val inputNick: Button)'
    $before = @'
                buttons.addView(b, LinearLayout.LayoutParams(0, dp(40), 1f)); addView(buttons)
                tag = Holder(title, a, b)
'@
    $after = @'
                buttons.addView(b, LinearLayout.LayoutParams(0, dp(40), 1f)); addView(buttons)
                val inputButtons = LinearLayout(app).apply { orientation = LinearLayout.HORIZONTAL }
                val inputSearch = button("検索入力") {}
                val inputNick = button("名前入力") {}
                inputButtons.addView(inputSearch, LinearLayout.LayoutParams(0, dp(36), 1f).apply { marginEnd = dp(3) })
                inputButtons.addView(inputNick, LinearLayout.LayoutParams(0, dp(36), 1f))
                addView(inputButtons)
                tag = Holder(title, a, b, inputSearch, inputNick)
'@
    # Here-strings use CRLF on Windows; the source was normalized to LF above.
    $before = $before -replace '\r\n?', $LF
    $after = $after -replace '\r\n?', $LF
    $newController = Replace-ExactlyOnce $newController $before $after
    $newController = Replace-ExactlyOnce $newController '            h.nick.visibility = if (item.nickname.isBlank()) View.GONE else View.VISIBLE' @'
            h.nick.visibility = if (item.nickname.isBlank()) View.GONE else View.VISIBLE
            h.inputNick.visibility = if (item.nickname.isBlank()) View.GONE else View.VISIBLE
            h.inputSearch.contentDescription = "Pokémon GOの検索欄に検索式を入力。失敗時は手動コピー"
            h.inputNick.contentDescription = "Pokémon GOの名前編集欄にニックネームを入力。保存は手動"
            h.inputSearch.setOnClickListener { requestGoInput(item, true) }
            h.inputNick.setOnClickListener { requestGoInput(item, false) }
'@
}
$manifest = [IO.File]::ReadAllText($dstManifest)
if(-not $manifest.Contains('GoTextInputAccessibilityService')) {
    $serviceTag = @'
        <service android:name="com.example.pokemonivreader.overlayqueue.GoTextInputAccessibilityService"
            android:label="厳選テキスト入力"
            android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data android:name="android.accessibilityservice"
                android:resource="@xml/go_text_input_service" />
        </service>
'@
    $manifest = Replace-ExactlyOnce $manifest '</application>' ($serviceTag + $LF + '    </application>')
}
foreach($pair in @(@($dstService, $sourceService), @($dstXml, $sourceXml))) {
    if((Test-Path -LiteralPath $pair[0]) -and
       ([IO.File]::ReadAllText($pair[0]) -ne [IO.File]::ReadAllText($pair[1]))) {
        throw "Target file exists with different content: $($pair[0])"
    }
}
if($VerifyOnly) {
    Write-Host 'VERIFY OK: supported controller and manifest. No files changed.'
    return
}

if(-not $env:JAVA_HOME) {
    foreach($jbr in @(
        (Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Android Studio\jbr')
    )) {
        if(Test-Path (Join-Path $jbr 'bin\java.exe')) { $env:JAVA_HOME = $jbr; break }
    }
}
$backupDir = Join-Path 'C:\new_folder\code\backups' ('GoTextInput_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$targets = @($dstController, $dstManifest, $dstService, $dstXml)
$existing = @{}
foreach($path in $targets) {
    $existing[$path] = Test-Path -LiteralPath $path
    if($existing[$path]) {
        Copy-Item -LiteralPath $path -Destination (Join-Path $backupDir ([IO.Path]::GetFileName($path))) -Force
    }
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
try {
    New-Item -ItemType Directory -Force -Path $dstJava, (Split-Path -Parent $dstXml) | Out-Null
    [IO.File]::WriteAllText($dstController, $newController, $utf8)
    [IO.File]::WriteAllText($dstManifest, $manifest, $utf8)
    Copy-Item -LiteralPath $sourceService -Destination $dstService -Force
    Copy-Item -LiteralPath $sourceXml -Destination $dstXml -Force
    Push-Location $ProjectDir
    try {
        & $gradlew ':app:assembleDebug' '--no-daemon'
        if($LASTEXITCODE -ne 0) { throw "Gradle build failed: exit $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
    Write-Host "BUILD SUCCESSFUL. Backup: $backupDir"
    Write-Host "APK: $ProjectDir\app\build\outputs\apk\debug\app-debug.apk"
} catch {
    $failure = $_
    foreach($path in $targets) {
        if($existing[$path]) {
            Copy-Item -LiteralPath (Join-Path $backupDir ([IO.Path]::GetFileName($path))) -Destination $path -Force
        } elseif(Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    throw "Build/update failed; source changes rolled back. Backup: $backupDir. Error: $failure"
}
