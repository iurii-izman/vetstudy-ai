Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ensureScript = (Resolve-Path (Join-Path $scriptDir "ensure_stack.ps1")).Path

Write-Host "VetStudyAI watchdog started. Ensure script: $ensureScript"

# First run with deeper checks after login/reboot.
powershell -NoProfile -ExecutionPolicy Bypass -File $ensureScript -DeepChecks

while ($true) {
    Start-Sleep -Seconds 600
    powershell -NoProfile -ExecutionPolicy Bypass -File $ensureScript
}
