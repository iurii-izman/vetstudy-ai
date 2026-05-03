param(
    [string]$OutputPath = "artifacts/notebooklm/VetStudyAI_NotebookLM_SourcePack.md",
    [switch]$Deep
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$coreSources = @(
    "docs/ai/NOTEBOOKLM_PROJECT_BRIEF.md",
    "docs/ai/NOTEBOOKLM_WORKFLOW.md",
    "README.md",
    "AGENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/beta/CLOSED_BETA_DECISIONS.md",
    "docs/beta/KNOWN_LIMITATIONS.md",
    "docs/beta/RUNBOOK.md",
    "docs/beta/RELEASE_CHECKLIST.md",
    "quality/dosage_policy_transnistria.md",
    "docs/ai/AUTOPILOT_HANDOFF.md",
    "docs/ai/AUTOPILOT_NEXT_BLOCKS.md",
    "docs/ai/CURSOR_MCP_SETUP.md"
)

$deepSources = @(
    "docs/ai/VetStudyAI_FINAL_SPEC.md",
    "docs/ai/VetStudyAI_AUTOPILOT_PROMPTS.md",
    "quality/medical_golden_set_seed.json",
    "quality/evidence_sources/sources.json",
    "app/ai/safety.py",
    "app/ai/prompts.py",
    "scripts/quality_audit.py",
    "app/tests/test_safety_gate.py",
    "app/tests/test_quality_audit_pipeline.py",
    "app/tests/test_prompt_manager.py",
    "app/tests/test_learning_service.py"
)

$sources = New-Object System.Collections.Generic.List[string]
$coreSources | ForEach-Object { [void]$sources.Add($_) }
if ($Deep) {
    $deepSources | ForEach-Object { [void]$sources.Add($_) }
}

$outputFullPath = Join-Path $root $OutputPath
$outputDir = Split-Path -Parent $outputFullPath
New-Item -ItemType Directory -Force $outputDir | Out-Null
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
$mode = if ($Deep) { "deep" } else { "core" }

$header = @"
# VetStudy AI NotebookLM Source Pack

Generated: $generatedAt
Mode: $mode

This generated file is intended for manual upload to NotebookLM.
It should contain only safe project documentation and selected source files.

Do not upload secrets, private Telegram IDs, raw clinical records, raw uploads, backups, local DB data, generated quality-audit artifacts, private Codex logs, or proprietary veterinary source content without confirmed license rights.

"@

[System.IO.File]::WriteAllText($outputFullPath, $header, $utf8NoBom)

foreach ($source in $sources) {
    if (-not (Test-Path -LiteralPath $source)) {
        [System.IO.File]::AppendAllText($outputFullPath, "`r`n`r`n---`r`n`r`n## Missing Source: $source`r`n", $utf8NoBom)
        continue
    }

    $sourceFullPath = Join-Path $root $source
    $content = [System.IO.File]::ReadAllText($sourceFullPath, [System.Text.Encoding]::UTF8)
    $separator = @"


---

## Source: $source

"@
    [System.IO.File]::AppendAllText($outputFullPath, $separator, $utf8NoBom)
    [System.IO.File]::AppendAllText($outputFullPath, $content, $utf8NoBom)
    [System.IO.File]::AppendAllText($outputFullPath, "`r`n", $utf8NoBom)
}

Write-Host "NotebookLM source pack written to $OutputPath" -ForegroundColor Cyan
Write-Host "Mode: $mode"
Write-Host "Sources included: $($sources.Count)"
