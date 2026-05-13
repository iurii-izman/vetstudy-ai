param(
    [switch]$DeepChecks
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
$logDir = Join-Path $repoRoot "artifacts\ops_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "ensure-stack-$timestamp.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format s) $Message"
    $line | Tee-Object -FilePath $logFile -Append
}

function Test-ReadyEndpoint {
    param(
        [int]$MaxAttempts = 8,
        [int]$SleepSeconds = 5
    )
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/ready" -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Write-Log "Ready check passed on attempt $i."
                return $true
            }
            Write-Log "Ready check returned status $($response.StatusCode) on attempt $i."
        } catch {
            Write-Log "Ready check failed on attempt ${i}: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds $SleepSeconds
    }
    return $false
}

function Repair-UnhealthyServices {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $psOutput = docker compose ps 2>&1
    $ErrorActionPreference = $prevEap
    $hasUnhealthy = ($psOutput | Select-String -Pattern "unhealthy") -ne $null
    if ($hasUnhealthy) {
        Write-Log "Detected unhealthy service(s). Restarting bot service."
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        cmd /c "docker compose restart bot" 2>$null | Tee-Object -FilePath $logFile -Append
        $restartExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        if ($restartExit -ne 0) {
            throw "docker compose restart bot failed (exit code: $restartExit)"
        }
        Start-Sleep -Seconds 5
    }
}

Push-Location $repoRoot
try {
    Write-Log "Starting ensure_stack.ps1 in $repoRoot"

    docker info | Out-Null
    Write-Log "Docker engine is reachable."

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    cmd /c "docker compose up -d" 2>$null | Tee-Object -FilePath $logFile -Append
    $composeExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($composeExit -ne 0) {
        throw "docker compose up -d failed (exit code: $composeExit)"
    }
    Write-Log "docker compose up -d completed."
    Repair-UnhealthyServices

    $readyOk = Test-ReadyEndpoint -MaxAttempts 20 -SleepSeconds 6
    if (-not $readyOk) {
        Write-Log "Service readiness failed. Capturing recent compose logs."
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker compose ps 2>&1 | Tee-Object -FilePath $logFile -Append
        docker compose logs --since 20m backend bot media-worker db redis 2>&1 | Tee-Object -FilePath $logFile -Append
        $ErrorActionPreference = $prevEap
        throw "Ready endpoint did not become healthy."
    }

    if ($DeepChecks) {
        Write-Log "Running deep preflight checks: --db --schema"
        python scripts/preflight_check.py --db --schema 2>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -ne 0) {
            throw "Deep preflight checks failed (exit code: $LASTEXITCODE)"
        }
    } else {
        Write-Log "Running quick preflight checks: --db"
        python scripts/preflight_check.py --db 2>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -ne 0) {
            throw "Quick preflight checks failed (exit code: $LASTEXITCODE)"
        }
    }

    Write-Log "ensure_stack.ps1 finished successfully."
    exit 0
} catch {
    Write-Log "ensure_stack.ps1 failed: $($_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
