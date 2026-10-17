[CmdletBinding()]
param(
    [string]$Workspace = 'workspace',
    [int]$StaleCycles = 5,
    [switch]$FailOnFlag
)

$ErrorActionPreference = 'Stop'

# Locate workspace directory and action log
$resolvedWs = Resolve-Path $Workspace -ErrorAction SilentlyContinue
if (-not $resolvedWs) {
    $repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $resolvedWs = Join-Path $repo $Workspace
} else {
    $resolvedWs = $resolvedWs.Path
}

$logFile = $null
if (Test-Path -LiteralPath (Join-Path $resolvedWs 'logs\actions.jsonl')) {
    $logFile = Join-Path $resolvedWs 'logs\actions.jsonl'
} elseif (Test-Path -LiteralPath (Join-Path $resolvedWs 'actions.jsonl')) {
    $logFile = Join-Path $resolvedWs 'actions.jsonl'
} elseif ($resolvedWs.EndsWith('.jsonl') -and (Test-Path -LiteralPath $resolvedWs)) {
    $logFile = $resolvedWs
    $resolvedWs = Split-Path (Split-Path $logFile -Parent) -Parent
}

if (-not $logFile -or -not (Test-Path -LiteralPath $logFile)) {
    Write-Warning "Could not find actions.jsonl at $resolvedWs"
    return
}

$planFile = Join-Path $resolvedWs 'state\plan.json'

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "SELF Autonomous Plan Audit" -ForegroundColor Cyan
Write-Host "Log file  : $logFile" -ForegroundColor Gray
Write-Host "Plan file : $planFile" -ForegroundColor Gray
Write-Host "Threshold : $StaleCycles cycles without progress marks stale" -ForegroundColor Gray
Write-Host "================================================================`n" -ForegroundColor Cyan

# Parse actions.jsonl line-by-line
$rawLines = Get-Content -LiteralPath $logFile -Encoding UTF8
$eventsByCycle = @{}
$planReviewsByCycle = @{}
$cycleCompletions = @{}
$maxCycle = 0
$historicalPlans = @{}

$countPlanUpdated = 0
$countPlanUnchangedAgent = 0
$countPlanUnchangedHarness = 0

foreach ($line in $rawLines) {
    if (-not $line.Trim()) { continue }
    if ($line -notmatch '"event"\s*:\s*"(plan_updated|plan_unchanged|cycle_completed)"') { continue }
    try {
        $evt = $line | ConvertFrom-Json
    } catch {
        continue
    }

    $c = $evt.cycle
    if ($evt.event -eq 'plan_updated') {
        $countPlanUpdated++
        $cNum = if ($c) { [int]$c } else { 1 }
        if ($cNum -gt $maxCycle) { $maxCycle = $cNum }
        $planReviewsByCycle[$cNum] = $evt
    } elseif ($evt.event -eq 'plan_unchanged') {
        if ($evt.source -eq 'harness_auto') {
            $countPlanUnchangedHarness++
        } else {
            $countPlanUnchangedAgent++
        }
        $cNum = if ($c) { [int]$c } else { 1 }
        if ($cNum -gt $maxCycle) { $maxCycle = $cNum }
        $planReviewsByCycle[$cNum] = $evt
    }

    if ($evt.event -eq 'cycle_completed') {
        $cNum = if ($evt.cycle) { [int]$evt.cycle } else { 1 }
        if ($cNum -gt $maxCycle) { $maxCycle = $cNum }
        $cycleCompletions[$cNum] = $evt
    }
}

if ($maxCycle -eq 0 -and $cycleCompletions.Count -gt 0) {
    $maxCycle = ($cycleCompletions.Keys | Measure-Object -Maximum).Maximum
}

Write-Host "Review Accounting:" -ForegroundColor White
Write-Host "  plan_updated (agent)         : $countPlanUpdated" -ForegroundColor Gray
Write-Host "  plan_unchanged (agent)       : $countPlanUnchangedAgent" -ForegroundColor Gray
Write-Host "  plan_unchanged (harness_auto): $countPlanUnchangedHarness" -ForegroundColor Gray
Write-Host ""

$totalFlags = 0
$stopWords = @('the','and','for','with','from','that','this','into','after','before','then','them','they','what','when','where','how','why','not','are','was','were','will','shall','should','would','could','can','may','might','must')

# Track latest plan items as of each cycle
$latestPlanItems = @()
if (Test-Path -LiteralPath $planFile) {
    try {
        $planObj = (Get-Content -LiteralPath $planFile -Raw -Encoding UTF8) | ConvertFrom-Json
        if ($planObj.items) {
            $latestPlanItems = @($planObj.items)
        }
    } catch {
        Write-Warning "Failed to parse state/plan.json: $_"
    }
}

$consecutiveUntouchedCycles = 0
for ($cycle = 1; $cycle -le $maxCycle; $cycle++) {
    $review = $planReviewsByCycle[$cycle]
    $completion = $cycleCompletions[$cycle]

    $cycleFlags = @()

    # Track whether agent touched the plan in this cycle
    $agentTouched = $false
    if ($review) {
        if ($review.event -eq 'plan_updated') {
            $agentTouched = $true
        } elseif ($review.event -eq 'plan_unchanged' -and $review.source -eq 'agent') {
            $agentTouched = $true
        }
    }

    if ($agentTouched) {
        $consecutiveUntouchedCycles = 0
    } else {
        $consecutiveUntouchedCycles++
        if ($consecutiveUntouchedCycles -ge $StaleCycles) {
            $cycleFlags += "[FLAG: PLAN_UNTOUCHED_CONSECUTIVE] Agent did not touch plan for $consecutiveUntouchedCycles consecutive cycles (cycles $($cycle - $consecutiveUntouchedCycles + 1) to $cycle; threshold: $StaleCycles)."
        }
    }

    # 1. Plan review check
    $planVersion = "unknown"
    $diffSummary = "(none)"
    $reason = "(no review recorded)"

    if ($review) {
        $planVersion = $review.plan_version
        $sourceLabel = if ($review.event -eq 'plan_updated') { "agent" } elseif ($review.source) { $review.source } else { "harness_auto" }
        if ($review.event -eq 'plan_updated') {
            $diffSummary = $review.diff
        } else {
            $diffSummary = "(plan unchanged)"
        }
        $reason = "[$sourceLabel] $($review.reason)"
    } else {
        $cycleFlags += "[FLAG: NO_PLAN_REVIEW] Cycle $cycle has no recorded plan review (missing plan_updated or plan_unchanged event)."
    }

    # 2. Tool calls for this cycle
    $actions = @()
    if ($completion -and $completion.actions) {
        $actions = @($completion.actions)
    }

    $firstFiveDisplay = @()
    for ($i = 0; $i -lt [Math]::Min(5, $actions.Count); $i++) {
        $act = $actions[$i]
        $statusStr = if ($act.ok) { "ok" } else { "failed" }
        $firstFiveDisplay += "$($i + 1). $($act.name) ($statusStr)"
    }
    if ($firstFiveDisplay.Count -eq 0) {
        $firstFiveDisplay += "(no tool actions in cycle)"
    }

    # 3. Check if first action matches the plan
    if ($actions.Count -gt 0 -and $latestPlanItems.Count -gt 0) {
        $topGoalItem = $latestPlanItems | Where-Object {
            $st = ("" + $_.status).ToLower()
            $st -ne 'done' -and $st -ne 'complete' -and $st -ne 'dropped'
        } | Select-Object -First 1

        if ($topGoalItem) {
            $firstActionName = ("" + $actions[0].name).ToLower()
            $goalText = ("" + $topGoalItem.goal + " " + $topGoalItem.step + " " + $topGoalItem.next_steps).ToLower()

            $matches = $false
            if ($firstActionName -in @('read_plan', 'update_plan')) {
                $matches = $true
            } else {
                # Check keyword overlap
                $words = $goalText -split '\s+' | Where-Object { $_.Length -ge 3 -and $_ -notin $stopWords }
                foreach ($w in $words) {
                    if ($firstActionName -match [regex]::Escape($w) -or $w -match [regex]::Escape($firstActionName)) {
                        $matches = $true
                        break
                    }
                }
                # Check common tool categories
                if (-not $matches) {
                    if ($firstActionName -eq 'run_shell' -and ($goalText -match 'run|shell|command|bash|exec|terminal|which|cat|ls|pip|python|stat|env')) {
                        $matches = $true
                    } elseif ($firstActionName -match 'model' -and ($goalText -match 'model|probe|eval|ask')) {
                        $matches = $true
                    } elseif ($firstActionName -match 'file' -and ($goalText -match 'file|read|write|inspect|source')) {
                        $matches = $true
                    }
                }
            }

            if (-not $matches) {
                $cycleFlags += "[FLAG: FIRST_ACTION_MISMATCH] Cycle $cycle first action '$firstActionName' does not align with top active plan goal: '$($topGoalItem.goal)'"
            }
        }
    }

    # Print cycle summary
    Write-Host "--- Cycle $cycle ---" -ForegroundColor White
    Write-Host "  Plan Version   : $planVersion" -ForegroundColor Gray
    Write-Host "  Diff Summary   : $diffSummary" -ForegroundColor Gray
    Write-Host "  Review Reason  : $reason" -ForegroundColor Gray
    Write-Host "  First 5 Actions:" -ForegroundColor Gray
    foreach ($a in $firstFiveDisplay) {
        Write-Host "    $a" -ForegroundColor DarkGray
    }

    if ($cycleFlags.Count -gt 0) {
        Write-Host "  Flags:" -ForegroundColor Red
        foreach ($fl in $cycleFlags) {
            Write-Host "    $fl" -ForegroundColor Red
            $totalFlags++
        }
    } else {
        Write-Host "  Flags          : None (plan review verified)" -ForegroundColor Green
    }
    Write-Host ""
}

# 4. Check for plan items older than N cycles with no progress
Write-Host "--- Plan Hygiene & Stale Items Check ---" -ForegroundColor White
$staleItemFlags = @()
if ($latestPlanItems.Count -gt 0) {
    foreach ($item in $latestPlanItems) {
        $st = ("" + $item.status).ToLower()
        if ($st -in @('done', 'complete', 'dropped', 'achieved', 'cancelled')) {
            continue
        }
        $updated = if ($item.updated_cycle) { [int]$item.updated_cycle } elseif ($item.created_cycle) { [int]$item.created_cycle } else { 1 }
        $age = $maxCycle - $updated
        if ($age -ge $StaleCycles) {
            $msg = "[FLAG: STALE_PLAN_ITEM] Plan item '$($item.id)' ('$($item.goal)') has had no progress for $age cycles (last updated: cycle $updated, current: cycle $maxCycle, threshold: $StaleCycles)."
            $staleItemFlags += $msg
            $totalFlags++
        }
    }
}

if ($staleItemFlags.Count -gt 0) {
    foreach ($stf in $staleItemFlags) {
        Write-Host "  $stf" -ForegroundColor Red
    }
} else {
    Write-Host "  No stale plan items detected. All active items updated within $StaleCycles cycles." -ForegroundColor Green
}

Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "Audit Complete: $maxCycle cycle(s) audited, $totalFlags flag(s) reported." -ForegroundColor $(if ($totalFlags -gt 0) { 'Yellow' } else { 'Green' })
Write-Host "================================================================" -ForegroundColor Cyan

if ($FailOnFlag -and $totalFlags -gt 0) {
    throw "Plan audit failed with $totalFlags flag(s)."
}
