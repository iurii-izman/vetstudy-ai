param(
    [switch]$RunElevated
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
$ensureScript = (Resolve-Path (Join-Path $scriptDir "ensure_stack.ps1")).Path

$psArgsBoot = "-NoProfile -ExecutionPolicy Bypass -File `"$ensureScript`" -DeepChecks"
$psArgsHeal = "-NoProfile -ExecutionPolicy Bypass -File `"$ensureScript`""

$bootTaskName = "VetStudyAI-Autostart"
$healTaskName = "VetStudyAI-SelfHeal-10min"
$runLevel = if ($RunElevated) { "HIGHEST" } else { "LIMITED" }

schtasks /Create /TN $bootTaskName /TR "powershell.exe $psArgsBoot" /SC ONLOGON /RL $runLevel /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create task $bootTaskName. Try running PowerShell as Administrator or remove -RunElevated."
}

schtasks /Create /TN $healTaskName /TR "powershell.exe $psArgsHeal" /SC MINUTE /MO 10 /RL $runLevel /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create task $healTaskName. Try running PowerShell as Administrator or remove -RunElevated."
}

Write-Host "Installed tasks:"
Write-Host "- $bootTaskName (on logon, deep checks)"
Write-Host "- $healTaskName (every 10 minutes, quick checks)"
Write-Host "- Run level: $runLevel"
Write-Host "Repo root: $repoRoot"
Write-Host "Ensure script: $ensureScript"
