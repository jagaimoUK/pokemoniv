#requires -Version 5.1
param(
    [string]$Project = "$env:USERPROFILE\AndroidStudioProjects\PokemonIVReader",
    [string]$BackupRoot = 'C:\new_folder\code\backups',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
$relative = 'app\src\main\java\com\example\pokemonivreader\overlayqueue'
$controller = Join-Path $Project (Join-Path $relative 'OverlayCopyQueueController.kt')
$helper = Join-Path $Project (Join-Path $relative 'OverlayQueueFlow.kt')
$gradle = Join-Path $Project 'gradlew.bat'
foreach($p in @($controller,$gradle)) { if(!(Test-Path -LiteralPath $p -PathType Leaf)){throw "Required file missing: $p. No file changed."} }
function Get-CanonicalText([string]$Path) {
    return [IO.File]::ReadAllText($Path).Replace("`r`n","`n").TrimEnd([char[]]"`r`n") + "`n"
}
function Get-CanonicalHash([string]$Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes((Get-CanonicalText $Path))))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'queue-flow-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$original = [IO.File]::ReadAllText($controller)
$inputHash = Get-CanonicalHash $controller
$matchingProfiles = @($manifest.profiles | Where-Object { $_.accepted -contains $inputHash })
if($matchingProfiles.Count -ne 1) { throw "Unsupported controller SHA256: $inputHash. No file changed. Please provide the current controller for review." }
$profile = $matchingProfiles[0]
$source = Join-Path $PSScriptRoot $profile.source
if((Get-CanonicalHash $source) -ne $profile.sha256) { throw 'Patch controller checksum mismatch. No file changed.' }
foreach($dependency in $manifest.dependencies) {
    $path = Join-Path (Split-Path $controller -Parent) $dependency.name
    if(!(Test-Path -LiteralPath $path) -or (Get-CanonicalHash $path) -ne $dependency.sha256) { throw "Dependency differs: $($dependency.name). No file changed." }
}
$text = Get-CanonicalText $source
$helperSource = Join-Path $PSScriptRoot $manifest.helper.source
if(!(Test-Path -LiteralPath $helperSource)) { $helperSource = Join-Path $PSScriptRoot '..\overlayqueue\OverlayQueueFlow.kt' }
if((Get-CanonicalHash $helperSource) -ne $manifest.helper.sha256) { throw 'Patch helper checksum mismatch. No file changed.' }
$newHelper = [IO.File]::ReadAllText($helperSource)
$helperExisted = Test-Path -LiteralPath $helper
if($helperExisted -and (Get-CanonicalHash $helper) -ne $manifest.helper.sha256) { throw 'Existing helper differs. No file changed.' }
Write-Host "Verified controller profile: $($profile.name)"
if($VerifyOnly) { Write-Host 'VERIFY ONLY PASSED. No project file changed.'; exit 0 }
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
