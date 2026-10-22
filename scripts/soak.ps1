param(
    [int]$Seed = 42,
    [switch]$Long = $false
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repo
try {
    Write-Host "========================================================================" -ForegroundColor Cyan
    Write-Host "SELF Soak Test Suite (Scripted Provider Simulation)" -ForegroundColor Cyan
    Write-Host "Random Seed: $Seed" -ForegroundColor Yellow
    Write-Host "SOAK_LONG  : $(if ($Long) { '1 (200 cycles)' } else { '0 (60 cycles)' })" -ForegroundColor Yellow
    Write-Host "========================================================================" -ForegroundColor Cyan

    if ($Long) {
        $env:SOAK_LONG = "1"
    } else {
        $env:SOAK_LONG = "0"
    }

    $startTime = [System.Diagnostics.Stopwatch]::StartNew()

    # Run soak runner python driver to capture scenario results and growth metrics
    $pythonCmd = @"
import os, sys, time
from agent.tests.soak.harness import linear_slope, SoakRunner, ScriptedProvider
from agent.tests.soak.test_soak_scenarios import SoakScenariosTests
from agent.tests.soak.test_soak_replay import SoakReplayTests
import unittest

suite = unittest.TestSuite()
loader = unittest.TestLoader()
suite.addTests(loader.loadTestsFromTestCase(SoakScenariosTests))
suite.addTests(loader.loadTestsFromTestCase(SoakReplayTests))

runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

print('\n' + '='*72)
print('SOAK SUITE SCENARIO EXECUTION SUMMARY')
print('='*72)
print(f'Total Scenarios Run: {result.testsRun}')
print(f'Failures: {len(result.failures)}')
print(f'Errors: {len(result.errors)}')
print(f'Status: {\"PASSED\" if result.wasSuccessful() else \"FAILED\"}')

# Generate and print growth table from Scenario B6 metrics
print('\n' + '='*72)
print('SCENARIO B6 (GROWTH BOUNDS) TRAJECTORY TABLE (Sampled Cycles)')
print('='*72)
print(f'{\"Cycle\":<8} | {\"Handoff Chars\":<14} | {\"Plan Items\":<11} | {\"Memory Entries\":<15} | {\"Log Bytes\":<10}')
print('-'*72)

b6_metrics = getattr(SoakScenariosTests, 'last_b6_metrics', [])
for m in b6_metrics:
    if m.cycle in (1, 5, 10, 20, 30, 40, 50, 60):
        print(f'{m.cycle:<8} | {m.handoff_chars:<14} | {m.plan_items:<11} | {m.memory_entries:<15} | {m.log_bytes:<10}')
print('-'*72)
if b6_metrics:
    h_slope = linear_slope([m.handoff_chars for m in b6_metrics])
    p_slope = linear_slope([m.plan_items for m in b6_metrics])
    m_slope = linear_slope([m.memory_entries for m in b6_metrics])
    l_slope = linear_slope([m.log_bytes for m in b6_metrics])
    print(f'Linear Slopes: Handoff={h_slope:.2f} chars/cyc, Plan={p_slope:.2f}/cyc, Memory={m_slope:.2f}/cyc, Log={l_slope:.1f} bytes/cyc')

if not result.wasSuccessful():
    sys.exit(1)
"@

    python -c $pythonCmd
    if ($LASTEXITCODE -ne 0) {
        throw "Soak suite failed with exit code $LASTEXITCODE."
    }

    $startTime.Stop()
    Write-Host "`nTotal Soak Suite Execution Time: $([math]::Round($startTime.Elapsed.TotalSeconds, 2)) seconds" -ForegroundColor Green
}
finally {
    Pop-Location
}
