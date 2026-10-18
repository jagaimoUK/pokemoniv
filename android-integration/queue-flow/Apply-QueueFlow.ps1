#requires -Version 5.1
param(
    [string]$Project = "$env:USERPROFILE\AndroidStudioProjects\PokemonIVReader",
    [string]$BackupRoot = 'C:\new_folder\code\backups'
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
$relative = 'app\src\main\java\com\example\pokemonivreader\overlayqueue'
$controller = Join-Path $Project (Join-Path $relative 'OverlayCopyQueueController.kt')
$helper = Join-Path $Project (Join-Path $relative 'OverlayQueueFlow.kt')
$gradle = Join-Path $Project 'gradlew.bat'
foreach($p in @($controller,$gradle)) { if(!(Test-Path -LiteralPath $p -PathType Leaf)){throw "Required file missing: $p. No file changed."} }
$original = [IO.File]::ReadAllText($controller)
$text = $original.Replace("`r`n","`n")
$replacements = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'controller-replacements.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($patch in $replacements) {
    $before = [string]$patch.before
    $after = [string]$patch.after
    $done = $text.IndexOf($after,[StringComparison]::Ordinal)
    if($done -ge 0) {
        if($text.IndexOf($after,$done+$after.Length,[StringComparison]::Ordinal) -ge 0){throw 'Ambiguous patched source. No file changed.'}
        continue
    }
    $at = $text.IndexOf($before,[StringComparison]::Ordinal)
    if($at -ge 0) {
        if($text.IndexOf($before,$at+$before.Length,[StringComparison]::Ordinal) -ge 0){throw 'Ambiguous source. No file changed.'}
        $text = $text.Substring(0,$at)+$after+$text.Substring($at+$before.Length)
    } else {
        $at = $text.IndexOf($after,[StringComparison]::Ordinal)
        if($at -lt 0 -or $text.IndexOf($after,$at+$after.Length,[StringComparison]::Ordinal) -ge 0){throw 'Unsupported controller source. No file changed. Keep the output and current source for review.'}
    }
}
$helperSource = Join-Path $PSScriptRoot 'OverlayQueueFlow.kt'
if(!(Test-Path -LiteralPath $helperSource)) { $helperSource = Join-Path $PSScriptRoot '..\overlayqueue\OverlayQueueFlow.kt' }
$newHelper = [IO.File]::ReadAllText($helperSource)
$helperExisted = Test-Path -LiteralPath $helper
if($helperExisted -and [IO.File]::ReadAllText($helper).Replace("`r`n","`n").TrimEnd() -ne $newHelper.Replace("`r`n","`n").TrimEnd()) {throw 'Existing helper differs. No file changed.'}
if($original.Contains("`r`n")) { $text = $text.Replace("`n","`r`n") }
if($text -eq $original -and $helperExisted) {Write-Host 'Already applied. Use Run in the ORIGINAL Android Studio project.'; exit 0}
$candidates = @(@(
    (Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Android Studio\jbr'),
    $env:JAVA_HOME
) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\java.exe')) })
if($candidates.Count -eq 0){throw 'Java not found. No file changed. Use the JBR bundled with Android Studio.'}
$env:JAVA_HOME=$candidates[0]
$env:Path=(Join-Path $env:JAVA_HOME 'bin')+';'+$env:Path
$backup = Join-Path $BackupRoot ('PokemonIVReader_before_QueueFlow_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item -LiteralPath $controller -Destination (Join-Path $backup 'OverlayCopyQueueController.kt')
if($helperExisted){Copy-Item -LiteralPath $helper -Destination (Join-Path $backup 'OverlayQueueFlow.kt')}
Write-Host "Backup: $backup"
try {
    [IO.File]::WriteAllText($controller,$text,$utf8)
    [IO.File]::WriteAllText($helper,$newHelper,$utf8)
    Push-Location $Project
    try {
        & $gradle --stop
        & $gradle :app:assembleDebug --no-daemon
        if($LASTEXITCODE -ne 0){throw "Gradle failed: $LASTEXITCODE"}
    } finally {Pop-Location}
} catch {
    Copy-Item -LiteralPath (Join-Path $backup 'OverlayCopyQueueController.kt') -Destination $controller -Force
    if($helperExisted){Copy-Item -LiteralPath (Join-Path $backup 'OverlayQueueFlow.kt') -Destination $helper -Force}
    elseif(Test-Path -LiteralPath $helper){Remove-Item -LiteralPath $helper -Force}
    throw "Update failed; sources restored. Backup: $backup. $($_.Exception.Message)"
}
Write-Host 'BUILD SUCCESSFUL. Open the ORIGINAL Android Studio project and use Run to update the phone.'
Write-Host (Join-Path $Project 'app\build\outputs\apk\debug\app-debug.apk')
