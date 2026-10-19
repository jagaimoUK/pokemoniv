# Read-only APK update compatibility check. Windows PowerShell 5.1+.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstalledApk,
    [Parameter(Mandatory=$true)][string]$CandidateApk
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-SdkTool([string]$toolName) {
    $roots = @()
    if ($env:ANDROID_SDK_ROOT) { $roots += $env:ANDROID_SDK_ROOT }
    if ($env:ANDROID_HOME) { $roots += $env:ANDROID_HOME }
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA 'Android\Sdk') }
    foreach ($root in ($roots | Select-Object -Unique)) {
        $dir = Join-Path $root 'build-tools'
        if (-not (Test-Path -LiteralPath $dir -PathType Container)) { continue }
        foreach ($versionDir in (Get-ChildItem -LiteralPath $dir -Directory | Sort-Object Name -Descending)) {
            $candidate = Join-Path $versionDir.FullName $toolName
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    throw "Android SDK build-tools ($toolName) not found."
}

function Read-Apk([string]$path,[string]$aapt,[string]$signer) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "APK not found: $path" }
    $file = (Resolve-Path -LiteralPath $path).Path
    $output = @(& $aapt dump badging $file 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "aapt failed: $file" }
    $packageLine = $output | Where-Object { $_ -match '^package:\s' } | Select-Object -First 1
    $parsed = [regex]::Match([string]$packageLine, "name='([^']+)'\s+versionCode='([0-9]+)'")
    if (-not $parsed.Success) { throw "Cannot parse applicationId/versionCode: $file" }
    $certInfo = @(& $signer verify --print-certs $file 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "APK signature invalid: $file" }
    $certificates = @()
    foreach ($line in $certInfo) {
        if ($line -match 'Signer #\d+ certificate SHA-256 digest:\s*([0-9A-Fa-f:]+)') {
            $certificates += $Matches[1].Replace(':','').ToLowerInvariant()
        }
    }
    if ($certificates.Count -eq 0) { throw "Cannot read APK signer digest: $file" }
    [PSCustomObject]@{
        ApplicationId = $parsed.Groups[1].Value
        VersionCode = [long]$parsed.Groups[2].Value
        Signatures = @($certificates | Sort-Object -Unique)
    }
}

$aapt = Find-SdkTool 'aapt.exe'
$signer = Find-SdkTool 'apksigner.bat'
$old = Read-Apk $InstalledApk $aapt $signer
$new = Read-Apk $CandidateApk $aapt $signer
Write-Host "Installed: $($old.ApplicationId) versionCode=$($old.VersionCode)"
Write-Host "Candidate: $($new.ApplicationId) versionCode=$($new.VersionCode)"
$idOk = $old.ApplicationId -eq $new.ApplicationId
$signOk = ($old.Signatures -join ',') -eq ($new.Signatures -join ',')
$versionOk = $new.VersionCode -gt $old.VersionCode
Write-Host "ApplicationId match: $idOk"
Write-Host "Signing certificate match: $signOk"
Write-Host "Version increased: $versionOk"
if (-not ($idOk -and $signOk -and $versionOk)) {
    throw 'STOP: APK update incompatible. Never uninstall the existing app to force installation.'
}
Write-Host 'PASS: Basic Android update identity checks passed. Data-migration and OCR tests are still required.'
