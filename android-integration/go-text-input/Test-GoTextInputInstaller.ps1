$ErrorActionPreference = 'Stop'
$root = Join-Path $env:RUNNER_TEMP 'GoTextInputVerification'
$project = Join-Path $root 'Success'
$source = Join-Path $project 'app\src\main\java\com\example\pokemonivreader\overlayqueue'
New-Item -ItemType Directory -Force $source | Out-Null
$baseline = & git show 'origin/main:android-integration/overlayqueue/OverlayCopyQueueController.kt'
if($LASTEXITCODE -ne 0) { throw 'Cannot load baseline controller from main' }
[IO.File]::WriteAllText((Join-Path $source 'OverlayCopyQueueController.kt'), ($baseline -join [Environment]::NewLine))
New-Item -ItemType Directory -Force (Join-Path $project 'app\src\main') | Out-Null
$manifest = '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:label="test"></application></manifest>'
[IO.File]::WriteAllText((Join-Path $project 'app\src\main\AndroidManifest.xml'),$manifest)
[IO.File]::WriteAllText((Join-Path $project 'gradlew.bat'), ('@echo off' + [Environment]::NewLine + 'exit /b 0'))
$installer = Join-Path $PSScriptRoot 'Apply-GoTextInput.ps1'
$controller = Join-Path $source 'OverlayCopyQueueController.kt'
$original = [IO.File]::ReadAllText($controller)
& $installer -ProjectDir $project -VerifyOnly
if([IO.File]::ReadAllText($controller) -cne $original) { throw 'VerifyOnly modified controller' }
& $installer -ProjectDir $project
$modified = [IO.File]::ReadAllText($controller)
if(-not $modified.Contains('private fun requestGoInput(')) { throw 'Controller patch absent' }
if(-not $modified.Contains('h.inputNick.setOnClickListener')) { throw 'Name button absent' }
if(-not (Test-Path (Join-Path $source 'GoTextInputAccessibilityService.kt'))) { throw 'Service missing' }
if(-not (Test-Path (Join-Path $project 'app\src\main\res\xml\go_text_input_service.xml'))) { throw 'XML missing' }
if(-not [IO.File]::ReadAllText((Join-Path $project 'app\src\main\AndroidManifest.xml')).Contains('android.permission.BIND_ACCESSIBILITY_SERVICE')) { throw 'Manifest permission missing' }
& $installer -ProjectDir $project -VerifyOnly

$failed = Join-Path $root 'FailedBuild'
$failedJava = Join-Path $failed 'app\src\main\java\com\example\pokemonivreader\overlayqueue'
New-Item -ItemType Directory -Force $failedJava | Out-Null
[IO.File]::WriteAllText((Join-Path $failedJava 'OverlayCopyQueueController.kt'),$original)
New-Item -ItemType Directory -Force (Join-Path $failed 'app\src\main') | Out-Null
[IO.File]::WriteAllText((Join-Path $failed 'app\src\main\AndroidManifest.xml'),$manifest)
[IO.File]::WriteAllText((Join-Path $failed 'gradlew.bat'),('@echo off' + [Environment]::NewLine + 'exit /b 1'))
try {
    & $installer -ProjectDir $failed
    throw 'Expected build failure was not raised'
} catch {
    if($_.ToString() -like '*Expected build failure was not raised*') { throw }
}
if([IO.File]::ReadAllText((Join-Path $failedJava 'OverlayCopyQueueController.kt')) -cne $original) { throw 'Rollback did not restore original' }
if(Test-Path (Join-Path $failedJava 'GoTextInputAccessibilityService.kt')) { throw 'Rollback did not delete new service' }
if([IO.File]::ReadAllText((Join-Path $failed 'app\src\main\AndroidManifest.xml')) -cne $manifest) { throw 'Rollback did not restore manifest' }
Write-Host 'Installer preflight, patch, idempotency, and rollback succeeded.'

# The intentionally failed mock gradlew left LASTEXITCODE=1; the rollback test passed.
$global:LASTEXITCODE = 0
