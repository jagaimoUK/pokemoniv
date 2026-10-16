#requires -Version 5.1
# Recover from the REAL Android Studio project on this Windows PC.
# Does not rebuild from a source-only handoff ZIP and never modifies the original project.
[CmdletBinding()]
param(
    [string]$ProjectDir = '',
    [string]$PatchDir = 'C:\新しいフォルダー\コード\OverlayCopyQueue_patch',
    [string]$OutputBase = 'C:\新しいフォルダー\コード'
)
$ErrorActionPreference = 'Stop'

function Test-CompleteReaderProject([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $false }
    $settingsOK = (Test-Path -LiteralPath (Join-Path $Root 'settings.gradle.kts')) -or (Test-Path -LiteralPath (Join-Path $Root 'settings.gradle'))
    $appOK = (Test-Path -LiteralPath (Join-Path $Root 'app\build.gradle.kts')) -or (Test-Path -LiteralPath (Join-Path $Root 'app\build.gradle'))
    $manifest = Test-Path -LiteralPath (Join-Path $Root 'app\src\main\AndroidManifest.xml')
    if (-not ($settingsOK -and $appOK -and $manifest)) { return $false }
    # We want the actual OCR reader, not the independent overlay demo.
    $sourceRoot = Join-Path $Root 'app\src\main\java'
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { return $false }
    $ocr = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Filter 'ScreenCaptureService.kt' -ErrorAction SilentlyContinue | Select-Object -First 1)
    $main = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Filter 'MainActivity.kt' -ErrorAction SilentlyContinue | Select-Object -First 1)
    return ($ocr.Count -gt 0 -and $main.Count -gt 0)
}

$apply = Join-Path $PatchDir 'Apply-OverlayCopyQueue.ps1'
$build = Join-Path $PatchDir 'Build-OverlayCopyQueue.ps1'
$patchSource = Join-Path $PatchDir 'patch\app\src\main\java\com\example\pokemonivreader\overlayqueue\OverlayPairParser.kt'
foreach ($p in @($apply, $build, $patchSource)) {
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Missing patch file: $p" }
}

if ($ProjectDir) {
    $project = [IO.Path]::GetFullPath($ProjectDir)
    if (-not (Test-CompleteReaderProject $project)) {
        throw "ProjectDir does not contain a complete OCR reader Android project: $project"
    }
} else {
    $roots = @(
        (Join-Path $env:USERPROFILE 'AndroidStudioProjects'),
        (Join-Path $env:USERPROFILE 'Documents\AndroidStudioProjects'),
        (Join-Path $env:USERPROFILE 'Documents'),
        (Join-Path $env:USERPROFILE 'Desktop'),
        $OutputBase
    ) | Select-Object -Unique
    $candidates = New-Object System.Collections.ArrayList
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $dirs = New-Object System.Collections.ArrayList
        [void]$dirs.Add($root)
        foreach ($d in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
            [void]$dirs.Add($d.FullName)
            # Only inspect two directory levels. Avoid scanning build caches and node_modules.
            if ($d.Name -notmatch '^(\.git|\.gradle|build|node_modules|\.idea)$') {
                foreach ($sub in @(Get-ChildItem -LiteralPath $d.FullName -Directory -ErrorAction SilentlyContinue)) {
                    [void]$dirs.Add($sub.FullName)
                }
            }
        }
        foreach ($dir in @($dirs)) {
            if (Test-CompleteReaderProject $dir) {
                if (-not $candidates.Contains($dir)) { [void]$candidates.Add($dir) }
            }
        }
    }
    if ($candidates.Count -eq 0) {
        Write-Host 'No complete PokemonIVReader Android Studio project was found in common PC locations.' -ForegroundColor Yellow
        Write-Host 'The supplied Current_Source ZIP is a source-only reference and cannot be compiled as the full reader.'
        Write-Host 'In Android Studio, locate the project folder that contains settings.gradle(.kts), app/build.gradle(.kts), and ScreenCaptureService.kt.'
        Write-Host 'Then rerun this script with -ProjectDir "FULL_PROJECT_FOLDER".'
        throw 'Original complete Android Studio project not found. No files were modified.'
    }
    $sorted = @($candidates | ForEach-Object { Get-Item -LiteralPath $_ } | Sort-Object LastWriteTime -Descending)
    $project = $sorted[0].FullName
    if ($sorted.Count -gt 1) {
        Write-Host 'Multiple valid projects found; using the most recently modified. Check before installing the APK:' -ForegroundColor Yellow
        foreach ($candidate in $sorted) { Write-Host "  $($candidate.FullName)" }
    }
}
Write-Host "Original project (read-only): $project" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $OutputBase -PathType Container)) {
    New-Item -Path $OutputBase -ItemType Directory -Force | Out-Null
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dest = Join-Path $OutputBase "PokemonIVReader_OverlayCopyQueue_FULL_$stamp"
$stage = Join-Path $env:TEMP "IVReader_stage_$([Guid]::NewGuid().ToString('N'))"
$temporaryZip = Join-Path $env:TEMP "IVReader_full_$([Guid]::NewGuid().ToString('N')).zip"
New-Item -Path $stage -ItemType Directory -Force | Out-Null
try {
    Write-Host 'Copying the real Android project to a temporary staging area...' -ForegroundColor Cyan
    & robocopy.exe $project $stage /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD '.git' '.gradle' '.idea' '.kotlin' '.cxx' 'build' 'node_modules' /XF 'local.properties' '*.apk' '*.aab' '*.jks' '*.keystore' 'google-services.json' | Out-Null
    $roboCode = $LASTEXITCODE
    if ($roboCode -gt 7) { throw "Could not copy source project (robocopy exit $roboCode)." }
    if (-not ((Test-Path -LiteralPath (Join-Path $stage 'settings.gradle.kts')) -or (Test-Path -LiteralPath (Join-Path $stage 'settings.gradle')))) {
        throw 'Copy failed to preserve Gradle settings; stopped before applying changes.'
    }
    Write-Host 'Creating a temporary source ZIP with Gradle files...' -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $temporaryZip -CompressionLevel Optimal -Force
    Write-Host 'Applying overlay feature to a NEW output directory...' -ForegroundColor Cyan
    & $apply -SourceZip $temporaryZip -OutputDir $dest
    if (-not (Test-Path -LiteralPath (Join-Path $dest 'app\src\main\java\com\example\pokemonivreader\overlayqueue\OverlayPairParser.kt'))) {
        throw 'Patch did not create the expected overlay source file.'
    }
    Write-Host "Patched full project: $dest" -ForegroundColor Green
    Write-Host 'Attempting Android debug build...' -ForegroundColor Cyan
    & $build -ProjectDir $dest
    Write-Host 'Build finished. The APK path is printed above.' -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $temporaryZip) { Remove-Item -LiteralPath $temporaryZip -Force -ErrorAction SilentlyContinue }
}