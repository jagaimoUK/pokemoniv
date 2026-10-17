param(
    [string]$Project = "$env:USERPROFILE\AndroidStudioProjects\PokemonIVReader",
    [string]$BackupRoot = 'C:\new_folder\code\backups'
)
$ErrorActionPreference = 'Stop'
function Get-CanonicalHash([string]$Path) {
    $value = [IO.File]::ReadAllText($Path).Replace("`r`n", "`n").TrimEnd([char[]]"`r`n") + "`n"
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($value)))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'patch-manifest.json') -Raw | ConvertFrom-Json
if (!(Test-Path -LiteralPath (Join-Path $Project 'gradlew.bat'))) { throw "Project not found: $Project" }
$changes = @()
foreach ($item in $manifest.files) {
    $source = Join-Path $PSScriptRoot $item.source
    $target = Join-Path $Project $item.target
    if ((Get-CanonicalHash $source) -ne $item.sha256) { throw "Patch file checksum mismatch: $source" }
    if (!(Test-Path -LiteralPath $target)) { throw "Expected existing integrated source is missing: $target" }
    $hash = Get-CanonicalHash $target
    if ($hash -eq $item.sha256) { continue }
    if ($item.accepted -notcontains $hash) { throw "Source differs from the verified baseline; nothing was changed. File: $target Hash: $hash" }
    $changes += [PSCustomObject]@{ Source=$source; Target=$target; Relative=$item.target }
}
if ($changes.Count -eq 0) { Write-Host 'This patch is already applied.'; exit 0 }
# Resolve Java before modifying any source. Prefer Android Studio's bundled JBR.
$javaCandidates = @(
    (Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Android Studio\jbr'),
    $env:JAVA_HOME
) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\java.exe')) }
if (!$javaCandidates) { throw 'Java was not found. Open Android Studio and use its bundled JBR, then retry.' }
$env:JAVA_HOME = $javaCandidates[0]
$env:Path = (Join-Path $env:JAVA_HOME 'bin') + ';' + $env:Path
$backup = Join-Path $BackupRoot ('PokemonIVReader_before_CPCompact_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($change in $changes) {
    $saved = Join-Path $backup $change.Relative
    New-Item -ItemType Directory -Path (Split-Path $saved -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $change.Target -Destination $saved
}
Write-Host "Backup: $backup"
try {
    foreach ($change in $changes) { Copy-Item -LiteralPath $change.Source -Destination $change.Target -Force }
    Push-Location $Project
    try {
        & (Join-Path $Project 'gradlew.bat') --stop
        & (Join-Path $Project 'gradlew.bat') :app:assembleDebug --no-daemon
        if ($LASTEXITCODE -ne 0) { throw "Gradle failed: $LASTEXITCODE" }
    } finally { Pop-Location }
} catch {
    foreach ($change in $changes) { Copy-Item -LiteralPath (Join-Path $backup $change.Relative) -Destination $change.Target -Force }
    throw "Build failed; all patched source files were restored. Backup: $backup. $($_.Exception.Message)"
}
Write-Host 'BUILD SUCCESSFUL. Open the ORIGINAL project in Android Studio and use Run to update your phone.'
Write-Host (Join-Path $Project 'app\build\outputs\apk\debug\app-debug.apk')
