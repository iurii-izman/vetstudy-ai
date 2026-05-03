Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$watchdogScript = (Resolve-Path (Join-Path $scriptDir "watchdog_loop.ps1")).Path
$startupDir = [Environment]::GetFolderPath("Startup")
$launcherPath = Join-Path $startupDir "VetStudyAI-Watchdog.cmd"

$cmd = "@echo off`r`nstart `"`" /min powershell -NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`"`r`n"
Set-Content -Path $launcherPath -Value $cmd -Encoding ASCII

Write-Host "Startup launcher installed:"
Write-Host $launcherPath
Write-Host "Watchdog script:"
Write-Host $watchdogScript
