[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scriptPath = Join-Path $PSScriptRoot 'live-check.ps1'

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("self-live-check-fixture-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $stateDir = Join-Path $tempRoot 'state'
    $logsDir = Join-Path $tempRoot 'logs'
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

    # 1. Mock image check
    Set-Content -LiteralPath (Join-Path $stateDir '.mock_image_check.json') -Value '{"detail":"Built after latest commit; contains agent/learning/plan.py."}' -Encoding UTF8

    # 2. plan.json
    $planJson = @'
{
  "schema_version": 1,
  "plan_version": 3,
  "items": [
    {"id": "goal-1", "goal": "Explore environment", "status": "in_progress", "priority": 1}
  ],
  "human_input_decisions": []
}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'plan.json') -Value $planJson -Encoding UTF8

    # 3 & 5. actions.jsonl
    $actionsJsonl = @'
{"event": "plan_updated", "cycle": 1, "diff": "added goal", "reason": "startup"}
{"event": "plan_unchanged", "cycle": 2, "source": "agent", "reason": "valid"}
{"event": "plan_unchanged", "cycle": 3, "source": "harness_auto", "reason": "auto"}
{"event": "human_input_decision", "cycle": 2, "decision": "accepted", "input": "test input"}
{"event": "cycle_completed", "cycle": 1, "actions": [{"name": "read_plan"}, {"name": "update_plan"}]}
'@
    Set-Content -LiteralPath (Join-Path $logsDir 'actions.jsonl') -Value $actionsJsonl -Encoding UTF8

    # 4. models.json
    $modelsJson = @'
{
  "schema_version": 3,
  "base_model": "gpt-oss:120b-cloud",
  "models": [
    {
      "name": "helper-alpha",
      "role": "helper",
      "probe_history": [{"format_version": 2, "success": true}],
      "research": {"status": "verified_mention"},
      "agent_assessment": "Fast helper model"
    }
  ]
}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'models.json') -Value $modelsJson -Encoding UTF8

    # 6. daily_token_budget.json
    $budgetJson = @'
{
  "date": "2026-10-17",
  "used_tokens": 1500,
  "reserved_tokens": 0,
  "cap": 200000
}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'daily_token_budget.json') -Value $budgetJson -Encoding UTF8

    # 7. memory.jsonl (clean)
    $memoryJsonl = @'
{"task": "Mapping", "lesson": "Verified proc filesystem", "outcome": "completed"}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'memory.jsonl') -Value $memoryJsonl -Encoding UTF8

    # 8. handoff.json (clean)
    $handoffJson = @'
{
  "summary": "Session complete after cycle 1.",
  "plan": []
}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'handoff.json') -Value $handoffJson -Encoding UTF8

    # 9. conversation_threads.jsonl (clean)
    $convJsonl = @'
{"role": "assistant", "text": "I will inspect the container and update my plan."}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'conversation_threads.jsonl') -Value $convJsonl -Encoding UTF8

    Write-Host "Running dry-run live-check against clean fixture..." -ForegroundColor Cyan
    $output = & powershell -ExecutionPolicy Bypass -File $scriptPath -Workspace $tempRoot -DryRun
    $outputStr = $output -join "`n"
    Write-Host $outputStr

    if ($outputStr -match '0 FAIL' -and $outputStr -match 'OVERALL: PASS') {
        Write-Host "PASS: Dry-run check passed clean fixture." -ForegroundColor Green
    } else {
        throw "Dry-run check failed on clean fixture: $outputStr"
    }

    # Test failure injection: leftover old framing phrase
    Write-Host "Testing leftover phrase detection..." -ForegroundColor Cyan
    Add-Content -LiteralPath (Join-Path $stateDir 'memory.jsonl') -Value '{"lesson": "protective of the human"}' -Encoding UTF8
    $failOutput = & powershell -ExecutionPolicy Bypass -File $scriptPath -Workspace $tempRoot -DryRun
    $failStr = $failOutput -join "`n"
    if ($failStr -match 'FAIL.*7\. Old-framing phrases audit') {
        Write-Host "PASS: Successfully caught leftover old-framing phrase." -ForegroundColor Green
    } else {
        throw "Failed to detect leftover old-framing phrase: $failStr"
    }

    # Test WARN injection: excessive token cap
    Write-Host "Testing excessive daily token cap warning..." -ForegroundColor Cyan
    Set-Content -LiteralPath (Join-Path $stateDir 'daily_token_budget.json') -Value '{"cap": 5000000000}' -Encoding UTF8
    $warnOutput = & powershell -ExecutionPolicy Bypass -File $scriptPath -Workspace $tempRoot -DryRun
    $warnStr = $warnOutput -join "`n"
    if ($warnStr -match 'WARN.*6\. Daily token ledger cap') {
        Write-Host "PASS: Successfully warned on excessive token cap." -ForegroundColor Green
    } else {
        throw "Failed to warn on excessive token cap: $warnStr"
    }

    # Reset token cap and memory
    Set-Content -LiteralPath (Join-Path $stateDir 'daily_token_budget.json') -Value '{"cap": 200000}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $stateDir 'memory.jsonl') -Value '{"task": "Mapping", "lesson": "Clean", "outcome": "completed"}' -Encoding UTF8

    # Test 11, 12, 13: proposals, cost ledger, and plugin_hash_mismatch warning
    Write-Host "Testing proposals, cost ledger, and plugin_hash_mismatch warning..." -ForegroundColor Cyan
    $proposalsJsonl = @'
{"name": "sensor_x", "status": "proposed", "estimate": {"tokens": {"min": 1000, "max": 2000}}, "need": "Telemetry"}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'plugin_proposals.jsonl') -Value $proposalsJsonl -Encoding UTF8

    $costLedgerJsonl = @'
{"kind": "tool", "target": "tool_a", "tokens": 1500, "llm_calls": 2}
{"kind": "plugin", "target": "sensor_x", "tokens": 4000, "llm_calls": 5}
'@
    Set-Content -LiteralPath (Join-Path $stateDir 'cost_ledger.jsonl') -Value $costLedgerJsonl -Encoding UTF8

    # Inject plugin_hash_mismatch in actions.jsonl
    Add-Content -LiteralPath (Join-Path $logsDir 'actions.jsonl') -Value '{"event": "plugin_hash_mismatch", "plugin": "tampered_p", "expected": "hash1", "actual": "hash2"}' -Encoding UTF8

    $pluginWarnOutput = & powershell -ExecutionPolicy Bypass -File $scriptPath -Workspace $tempRoot -DryRun
    $pluginWarnStr = $pluginWarnOutput -join "`n"

    if ($pluginWarnStr -match 'WARN.*11\. Plugin inventory & hash state.*plugin_hash_mismatch') {
        Write-Host "PASS: Successfully detected plugin_hash_mismatch warning." -ForegroundColor Green
    } else {
        throw "Failed to warn on plugin_hash_mismatch: $pluginWarnStr"
    }

    if ($pluginWarnStr -match '12\. Proposals and project reviews.*Proposals: 1 total') {
        Write-Host "PASS: Successfully reported plugin proposals." -ForegroundColor Green
    } else {
        throw "Failed to report proposals: $pluginWarnStr"
    }

    if ($pluginWarnStr -match '13\. Cost ledger summary.*2 records') {
        Write-Host "PASS: Successfully reported cost ledger summary." -ForegroundColor Green
    } else {
        throw "Failed to report cost ledger summary: $pluginWarnStr"
    }

    Write-Host "`nAll live-check fixture tests PASSED." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
