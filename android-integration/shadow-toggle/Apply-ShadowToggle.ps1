#requires -Version 5.1
param(
 [string]$Project = "$env:USERPROFILE\AndroidStudioProjects\PokemonIVReader",
 [string]$BackupRoot = 'C:\new_folder\code\backups'
)
$ErrorActionPreference='Stop'
$utf8=New-Object System.Text.UTF8Encoding($false)
$base=Join-Path $Project 'app\src\main\java\com\example\pokemonivreader'
$gradle=Join-Path $Project 'gradlew.bat'
if(!(Test-Path -LiteralPath $gradle -PathType Leaf)){throw "Original project missing: $Project"}
$plan=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'replacements.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$staged=@()
# Validate ALL exact anchors before writing anything. Preserve unrelated patches and CRLF.
foreach($property in $plan.PSObject.Properties){
 $path=Join-Path $base $property.Name
 if(!(Test-Path -LiteralPath $path -PathType Leaf)){throw "Missing source; no changes: $path"}
 $original=[IO.File]::ReadAllText($path,$utf8)
 $value=$original.Replace("`r`n","`n")
 foreach($replacement in $property.Value){
  $before=$replacement.before; $after=$replacement.after
  # An already-applied replacement often contains its before text; test the after first.
  if($value.Contains($after)){continue}
  $at=$value.IndexOf($before,[StringComparison]::Ordinal)
  if($at -lt 0 -or $value.IndexOf($before,$at+$before.Length,[StringComparison]::Ordinal) -ge 0){throw "Unsupported source in $($property.Name). No files changed. Please provide the current source."}
  $value=$value.Substring(0,$at)+$after+$value.Substring($at+$before.Length)
 }
 if($original.Contains("`r`n")){$value=$value.Replace("`n","`r`n")}
 $staged+=@{Path=$path;Value=$value;Exists=$true}
}
$helper=Join-Path $base 'ReaderShadowControls.kt'
$helperSource=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'ReaderShadowControls.kt'),$utf8)
if((Test-Path -LiteralPath $helper) -and [IO.File]::ReadAllText($helper,$utf8).Replace("`r`n","`n") -ne $helperSource.Replace("`r`n","`n")){throw 'A different ReaderShadowControls.kt exists; no files changed.'}
$staged+=@{Path=$helper;Value=$helperSource;Exists=(Test-Path -LiteralPath $helper)}
$candidates=@((Join-Path $env:ProgramFiles 'Android\Android Studio\jbr'),(Join-Path $env:LOCALAPPDATA 'Programs\Android Studio\jbr'),$env:JAVA_HOME) | Where-Object {$_ -and (Test-Path -LiteralPath (Join-Path $_ 'bin\java.exe'))}
if(!$candidates){throw 'Android Studio JBR/JDK missing; no files changed.'}
$env:JAVA_HOME=@($candidates)[0]
$env:Path=(Join-Path $env:JAVA_HOME 'bin')+';'+$env:Path
$backup=Join-Path $BackupRoot ('PokemonIVReader_before_ShadowToggle_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($item in $staged){if($item.Exists){Copy-Item -LiteralPath $item.Path -Destination (Join-Path $backup ([IO.Path]::GetFileName($item.Path)))}}
Write-Host "Backup: $backup"
try {
 foreach($item in $staged){[IO.File]::WriteAllText($item.Path,$item.Value,$utf8)}
 Push-Location $Project
 try {& $gradle ':app:assembleDebug' '--no-daemon';if($LASTEXITCODE -ne 0){throw "Gradle exit code $LASTEXITCODE"}}
 finally {Pop-Location}
} catch {
 foreach($item in $staged){
  if($item.Exists){Copy-Item -LiteralPath (Join-Path $backup ([IO.Path]::GetFileName($item.Path))) -Destination $item.Path -Force}
  elseif(Test-Path -LiteralPath $item.Path){Remove-Item -LiteralPath $item.Path -Force}
 }
 throw "Build failed; original source restored. Backup: $backup. $($_.Exception.Message)"
}
Write-Host 'BUILD SUCCESSFUL. Install APK or use Android Studio Run.' -ForegroundColor Green
Write-Host (Join-Path $Project 'app\build\outputs\apk\debug\app-debug.apk')
