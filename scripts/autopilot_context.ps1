param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "VetStudy AI autopilot context" -ForegroundColor Cyan
Write-Host ""

Write-Host "Repository" -ForegroundColor Yellow
git status --short --branch
git log -1 --oneline --decorate
git remote -v
Write-Host ""

Write-Host "Required reading" -ForegroundColor Yellow
@(
    "AGENTS.md",
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/beta/RUNBOOK.md",
    "docs/beta/CLOSED_BETA_DECISIONS.md",
    "docs/ai/AUTOPILOT_HANDOFF.md",
    "docs/ai/AUTOPILOT_NEXT_BLOCKS.md",
    "docs/ai/CURSOR_MCP_SETUP.md",
    "docs/ai/NOTEBOOKLM_WORKFLOW.md",
    "quality/dosage_policy_transnistria.md"
) | ForEach-Object {
    if (Test-Path $_) {
        Write-Host "ok   $_"
    } else {
        Write-Host "miss $_" -ForegroundColor Red
    }
}
Write-Host ""

Write-Host "Cursor project rules" -ForegroundColor Yellow
if (Test-Path ".cursor/rules") {
    Get-ChildItem ".cursor/rules" -Filter "*.mdc" | Sort-Object Name | ForEach-Object {
        Write-Host ("ok   " + $_.FullName.Replace($root + "\", ""))
    }
} else {
    Write-Host "miss .cursor/rules" -ForegroundColor Red
}
Write-Host ""

Write-Host "Current high-ROI next blocks" -ForegroundColor Yellow
Select-String -Path "docs/ai/AUTOPILOT_NEXT_BLOCKS.md" -Pattern "^## Block" | ForEach-Object {
    Write-Host ($_.Line.Trim())
}
Write-Host ""

Write-Host "Safe commands" -ForegroundColor Yellow
Write-Host "python -m ruff check ."
Write-Host "python -m pytest -q"
Write-Host "alembic upgrade head"
Write-Host "cd web; npm test; npm run build; npm audit --omit=dev"
Write-Host "python scripts/preflight_check.py --db --schema"
Write-Host "python scripts/quality_audit.py --limit 10 --delay-s 0"
Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_notebooklm_pack.ps1"

if ($Full) {
    Write-Host ""
    Write-Host "Fast environment check" -ForegroundColor Yellow
    python --version
    node --version
    npm --version
    python -m ruff --version
}
