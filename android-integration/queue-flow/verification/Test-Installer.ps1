# Run on Windows PowerShell 5.1. Uses temporary source fixtures and a fake Gradle batch file.
$ErrorActionPreference = 'Stop'
$package = Split-Path $PSScriptRoot -Parent
$installer = Join-Path $package 'Apply-QueueFlow.ps1'
$manifest = Get-Content -LiteralPath (Join-Path $package 'queue-flow-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskRoot = Join-Path ([IO.Path]::GetTempPath()) ('QueueFlowInstaller_' + [guid]::NewGuid().ToString('N'))
$relative = 'app\src\main\java\com\example\pokemonivreader\overlayqueue'
New-Item -ItemType Directory -Path $taskRoot | Out-Null
function Assert([bool]$Condition,[string]$Message) { if(!$Condition){throw $Message} }
function CanonicalHash([string]$Path) {
    $text=[IO.File]::ReadAllText($Path).Replace("`r`n","`n").TrimEnd([char[]]"`r`n")+"`n"
    $sha=[Security.Cryptography.SHA256]::Create()
    try {([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
}
function New-Fixture([string]$Name,[string]$ProfileName) {
    $project=Join-Path $taskRoot $Name
    $source=Join-Path $project $relative
    New-Item -ItemType Directory -Path $source -Force | Out-Null
    $text=[IO.File]::ReadAllText((Join-Path $PSScriptRoot "fixtures\$ProfileName.before.kt.txt")).Replace("`r`n","`n").Replace("`n","`r`n")
    [IO.File]::WriteAllText((Join-Path $source 'OverlayCopyQueueController.kt'),$text,(New-Object Text.UTF8Encoding($true)))
    foreach($dep in $manifest.dependencies){Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('fixtures\'+$dep.name)) -Destination (Join-Path $source $dep.name)}
    [IO.File]::WriteAllText((Join-Path $project 'gradlew.bat'),"@echo off`r`nexit /b 0`r`n",[Text.Encoding]::ASCII)
    return $project
}
function Invoke-Installer([string]$Project,[bool]$Success,[switch]$VerifyOnly) {
    $log=Join-Path $taskRoot ([guid]::NewGuid().ToString('N'))
    $installerArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$installer+'"'),'-Project',('"'+$Project+'"'),'-BackupRoot',('"'+(Join-Path $Project 'backups')+'"'))
    if($VerifyOnly){$installerArgs+='-VerifyOnly'}
    $result=Start-Process -FilePath 'powershell.exe' -ArgumentList $installerArgs -Wait -PassThru -RedirectStandardOutput ($log+'.out') -RedirectStandardError ($log+'.err')
    Write-Host ([IO.File]::ReadAllText($log+'.out'))
    if($Success -ne ($result.ExitCode -eq 0)){
        Write-Host ([IO.File]::ReadAllText($log+'.err'))
        throw "Unexpected installer exit code: $($result.ExitCode)"
    }
}
foreach($entryProfile in $manifest.profiles){
    $project=New-Fixture $entryProfile.name $entryProfile.name
    $controller=Join-Path $project (Join-Path $relative 'OverlayCopyQueueController.kt')
    $helper=Join-Path $project (Join-Path $relative 'OverlayQueueFlow.kt')
    $original=(Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash
    Invoke-Installer $project $true -VerifyOnly
    Assert ((Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash -eq $original) 'Verify-only mutated source'
    Assert (!(Test-Path -LiteralPath $helper)) 'Verify-only created helper'
    Assert (!(Test-Path -LiteralPath (Join-Path $project 'backups'))) 'Verify-only created backup'
    Invoke-Installer $project $true
    Assert ((CanonicalHash $controller) -eq $entryProfile.sha256) 'Wrong patched controller'
    Assert ((CanonicalHash $helper) -eq $manifest.helper.sha256) 'Wrong helper'
    $backupCount=@(Get-ChildItem -LiteralPath (Join-Path $project 'backups') -Directory).Count
    Invoke-Installer $project $true
    Assert (@(Get-ChildItem -LiteralPath (Join-Path $project 'backups') -Directory).Count -eq $backupCount) 'Repeat apply created extra backup'
    Write-Host "PASS: $($entryProfile.name) verify-only, apply and repeat"
}
$project=New-Fixture 'rollback' 'uploaded-current'
$controller=Join-Path $project (Join-Path $relative 'OverlayCopyQueueController.kt')
$helper=Join-Path $project (Join-Path $relative 'OverlayQueueFlow.kt')
$original=(Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash
[IO.File]::WriteAllText((Join-Path $project 'gradlew.bat'),"@echo off`r`nexit /b 1`r`n",[Text.Encoding]::ASCII)
Invoke-Installer $project $false
Assert ((Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash -eq $original) 'Rollback did not restore exact bytes'
Assert (!(Test-Path -LiteralPath $helper)) 'Rollback left a new helper behind'
Write-Host 'PASS: build failure restores original bytes and removes new helper'
$project=New-Fixture 'unknown' 'uploaded-current'
$controller=Join-Path $project (Join-Path $relative 'OverlayCopyQueueController.kt')
[IO.File]::AppendAllText($controller,"`r`n// local edit`r`n")
$original=(Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash
Invoke-Installer $project $false
Assert ((Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash -eq $original) 'Unknown source mutated'
Assert (!(Test-Path -LiteralPath (Join-Path $project 'backups'))) 'Unknown source reached backup stage'
Write-Host 'PASS: unknown source rejected before modification'
$project=New-Fixture 'helper-conflict' 'uploaded-current'
$controller=Join-Path $project (Join-Path $relative 'OverlayCopyQueueController.kt')
$helper=Join-Path $project (Join-Path $relative 'OverlayQueueFlow.kt')
[IO.File]::WriteAllText($helper,'// unknown helper')
$original=(Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash
Invoke-Installer $project $false
Assert ((Get-FileHash -LiteralPath $controller -Algorithm SHA256).Hash -eq $original) 'Helper conflict mutated controller'
Assert ([IO.File]::ReadAllText($helper) -eq '// unknown helper') 'Helper conflict overwrote helper'
Write-Host 'PASS: conflicting helper rejected before modification'
Write-Host 'ALL WINDOWS INSTALLER TESTS PASSED'
