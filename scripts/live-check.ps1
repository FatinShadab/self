[CmdletBinding()]
param(
    [string]$Workspace = 'workspace',
    [string]$ConfigDir = '',
    [switch]$DryRun,
    [switch]$FailOnWarn,
    [switch]$FailOnError
)

$ErrorActionPreference = 'Stop'

# Locate workspace directory
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$resolvedWs = Resolve-Path $Workspace -ErrorAction SilentlyContinue
if (-not $resolvedWs) {
    $resolvedWs = Join-Path $repo $Workspace
} else {
    $resolvedWs = $resolvedWs.Path
}

# Locate config directory
if (-not $ConfigDir) {
    if (Test-Path -LiteralPath (Join-Path $resolvedWs 'config')) {
        $resolvedCfg = (Join-Path $resolvedWs 'config')
    } elseif (Test-Path -LiteralPath (Join-Path (Split-Path $resolvedWs -Parent) 'config')) {
        $resolvedCfg = (Join-Path (Split-Path $resolvedWs -Parent) 'config')
    } else {
        $resolvedCfg = Join-Path $repo 'config'
    }
} else {
    $resolvedCfg = (Resolve-Path $ConfigDir -ErrorAction SilentlyContinue).Path
    if (-not $resolvedCfg) { $resolvedCfg = $ConfigDir }
}

$passCount = 0
$warnCount = 0
$failCount = 0

function Report-Item([string]$Status, [string]$CheckName, [string]$Detail) {
    $color = switch ($Status) {
        'PASS' { 'Green' }
        'WARN' { 'Yellow' }
        'FAIL' { 'Red' }
        Default { 'White' }
    }
    Write-Host ("[{0,-4}] {1,-38} : {2}" -f $Status, $CheckName, $Detail) -ForegroundColor $color
    if ($Status -eq 'PASS') { $script:passCount++ }
    elseif ($Status -eq 'WARN') { $script:warnCount++ }
    elseif ($Status -eq 'FAIL') { $script:failCount++ }
}

function Get-PluginDirHash([string]$Dir) {
    if (-not (Test-Path -LiteralPath $Dir)) { return "" }
    $resolvedDir = (Resolve-Path $Dir).Path
    $rawFiles = Get-ChildItem -LiteralPath $resolvedDir -Recurse -File | Where-Object {
        $rel = $_.FullName.Substring($resolvedDir.Length).TrimStart('\', '/')
        $parts = $rel -split '[\\/]'
        if ($parts.Count -gt 0 -and $parts[0] -in @('state', '_archive', '_template')) { return $false }
        if ('_archive' -in $parts -or '_template' -in $parts) { return $false }
        if ('__pycache__' -in $parts -or $_.Extension -in @('.pyc', '.pyo', '.pyd')) { return $false }
        if ($parts | Where-Object { $_.StartsWith('.') }) { return $false }
        return $true
    }

    $relMap = @{}
    foreach ($f in $rawFiles) {
        $rel = $f.FullName.Substring($resolvedDir.Length).TrimStart('\', '/').Replace('\', '/')
        $relMap[$rel] = $f
    }
    $sortedRels = [string[]]($relMap.Keys)
    [System.Array]::Sort($sortedRels, [System.StringComparer]::Ordinal)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = New-Object System.IO.MemoryStream
    foreach ($relPosix in $sortedRels) {
        $f = $relMap[$relPosix]
        $nameBytes = [System.Text.Encoding]::UTF8.GetBytes($relPosix + [char]0)
        $stream.Write($nameBytes, 0, $nameBytes.Length)
        $contentBytes = [System.IO.File]::ReadAllBytes($f.FullName)
        $stream.Write($contentBytes, 0, $contentBytes.Length)
    }
    $stream.Position = 0
    $hashBytes = $sha.ComputeHash($stream)
    $stream.Dispose()
    $sha.Dispose()
    return (-join ($hashBytes | ForEach-Object { $_.ToString('x2') }))
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "SELF Live Check Diagnostic Report" -ForegroundColor Cyan
Write-Host "Workspace : $resolvedWs" -ForegroundColor Gray
Write-Host "Mode      : $(if ($DryRun) { 'DryRun (Mock / Fixture)' } else { 'Live' })" -ForegroundColor Gray
Write-Host "================================================================================" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1. Image Check
# -----------------------------------------------------------------------------
if ($DryRun) {
    # In DryRun mode, check fixture or assume valid for dry-run
    $mockImageFile = Join-Path $resolvedWs 'state\.mock_image_check.json'
    if (Test-Path -LiteralPath $mockImageFile) {
        try {
            $mockInfo = (Get-Content -LiteralPath $mockImageFile -Raw -Encoding UTF8) | ConvertFrom-Json
            if ($mockInfo.fail) {
                Report-Item 'FAIL' '1. Docker image & plan.py' $mockInfo.detail
            } elseif ($mockInfo.warn) {
                Report-Item 'WARN' '1. Docker image & plan.py' $mockInfo.detail
            } else {
                Report-Item 'PASS' '1. Docker image & plan.py' $mockInfo.detail
            }
        } catch {
            Report-Item 'PASS' '1. Docker image & plan.py' 'Dry-run fixture verified (mock).'
        }
    } else {
        Report-Item 'PASS' '1. Docker image & plan.py' 'Dry-run mode: skipped live docker inspection.'
    }
} else {
    try {
        $imageName = 'self-self:latest'
        # Check latest git commit time
        $commitTimeStr = (git log -1 --format="%cI" 2>$null)
        if (-not $commitTimeStr) {
            Report-Item 'WARN' '1. Docker image & plan.py' 'Git repository commit timestamp unavailable.'
        } else {
            $commitDate = [DateTime]::Parse($commitTimeStr.Trim()).ToUniversalTime()
            $imgCreatedStr = (docker inspect $imageName --format "{{.Created}}" 2>$null)
            if (-not $imgCreatedStr) {
                Report-Item 'FAIL' '1. Docker image & plan.py' "Image '$imageName' not found in local Docker daemon."
            } else {
                $imgDate = [DateTime]::Parse($imgCreatedStr.Trim()).ToUniversalTime()
                if ($imgDate -lt $commitDate) {
                    Report-Item 'WARN' '1. Docker image & plan.py' "Image $imageName ($($imgDate.ToString('o'))) was built before latest commit ($($commitDate.ToString('o')))."
                } else {
                    # Verify agent/learning/plan.py exists inside container
                    $fileCheck = (docker run --rm --entrypoint python $imageName -c "import agent.learning.plan; print('OK')" 2>$null)
                    if ($fileCheck -match 'OK') {
                        Report-Item 'PASS' '1. Docker image & plan.py' "Built after latest commit; contains agent/learning/plan.py."
                    } else {
                        Report-Item 'FAIL' '1. Docker image & plan.py' "Image $imageName does not import agent/learning/plan.py."
                    }
                }
            }
        }
    } catch {
        Report-Item 'FAIL' '1. Docker image & plan.py' "Error checking Docker image: $_"
    }
}

# -----------------------------------------------------------------------------
# 2. plan.json Existence & Version
# -----------------------------------------------------------------------------
$planFile = Join-Path $resolvedWs 'state\plan.json'
if (Test-Path -LiteralPath $planFile) {
    try {
        $planData = (Get-Content -LiteralPath $planFile -Raw -Encoding UTF8) | ConvertFrom-Json
        $planVersion = $planData.plan_version
        $itemCount = if ($planData.items) { @($planData.items).Count } else { 0 }
        Report-Item 'PASS' '2. plan.json presence & version' "plan.json exists (version $planVersion, $itemCount goal items)."
    } catch {
        Report-Item 'FAIL' '2. plan.json presence & version' "plan.json exists but failed to parse: $_"
    }
} else {
    Report-Item 'FAIL' '2. plan.json presence & version' "state/plan.json does not exist."
}

# -----------------------------------------------------------------------------
# 3. Counts of Events & Tool Calls
# -----------------------------------------------------------------------------
$logFile = $null
if (Test-Path -LiteralPath (Join-Path $resolvedWs 'logs\actions.jsonl')) {
    $logFile = Join-Path $resolvedWs 'logs\actions.jsonl'
} elseif (Test-Path -LiteralPath (Join-Path $resolvedWs 'actions.jsonl')) {
    $logFile = Join-Path $resolvedWs 'actions.jsonl'
}

$countPlanUpdated = 0
$countPlanUnchangedAgent = 0
$countPlanUnchangedHarness = 0
$countHumanInputDecision = 0
$countUpdatePlanCalls = 0
$countReadPlanCalls = 0

if ($logFile -and (Test-Path -LiteralPath $logFile)) {
    $logLines = Get-Content -LiteralPath $logFile -Encoding UTF8
    foreach ($line in $logLines) {
        if (-not $line.Trim()) { continue }
        try {
            $e = $line | ConvertFrom-Json
        } catch { continue }

        if ($e.event -eq 'plan_updated') {
            $countPlanUpdated++
        } elseif ($e.event -eq 'plan_unchanged') {
            if ($e.source -eq 'harness_auto') {
                $countPlanUnchangedHarness++
            } else {
                $countPlanUnchangedAgent++
            }
        } elseif ($e.event -eq 'human_input_decision') {
            $countHumanInputDecision++
        }

        # Tool calls from cycle_completed actions or tool_result/tool_executed
        if ($e.event -eq 'cycle_completed' -and $e.actions) {
            foreach ($act in $e.actions) {
                if ($act.name -eq 'update_plan') { $countUpdatePlanCalls++ }
                if ($act.name -eq 'read_plan') { $countReadPlanCalls++ }
            }
        }
        if ($e.event -in @('tool_result', 'tool_executed')) {
            if ($e.tool -eq 'update_plan') { $countUpdatePlanCalls++ }
            if ($e.tool -eq 'read_plan') { $countReadPlanCalls++ }
        }
    }
    $detail = "plan_updated: $countPlanUpdated, plan_unchanged: [agent: $countPlanUnchangedAgent, harness_auto: $countPlanUnchangedHarness], human_input_decisions: $countHumanInputDecision, calls: [update_plan: $countUpdatePlanCalls, read_plan: $countReadPlanCalls]"
    Report-Item 'PASS' '3. Plan events & tool call counts' $detail
} else {
    Report-Item 'WARN' '3. Plan events & tool call counts' "actions.jsonl not found in workspace."
}

# -----------------------------------------------------------------------------
# 4. Helper Models Table
# -----------------------------------------------------------------------------
$modelsFile = Join-Path $resolvedWs 'state\models.json'
if (Test-Path -LiteralPath $modelsFile) {
    try {
        $modelsData = (Get-Content -LiteralPath $modelsFile -Raw -Encoding UTF8) | ConvertFrom-Json
        $modelsList = if ($modelsData.models) { @($modelsData.models) } else { @() }
        $helpers = $modelsList | Where-Object { $_.role -ne 'base' -and $_.status -ne 'disabled' }
        if ($helpers.Count -gt 0) {
            Report-Item 'PASS' '4. Helper models evaluation table' "$($helpers.Count) helper model(s) registered:"
            Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
            Write-Host ("       {0,-28} | {1,-7} | {2,-16} | {3,-10}" -f "Model Name", "Probes", "Research Status", "Assessment") -ForegroundColor DarkCyan
            Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
            foreach ($h in $helpers) {
                $pCount = if ($h.probe_history) { @($h.probe_history).Count } else { 0 }
                $rStatus = if ($h.research -and $h.research.status) { $h.research.status } else { 'not_checked' }
                $hasAssess = if ($h.agent_assessment -and ("" + $h.agent_assessment).Trim()) { 'Present' } else { 'None' }
                Write-Host ("       {0,-28} | {1,-7} | {2,-16} | {3,-10}" -f $h.name, $pCount, $rStatus, $hasAssess) -ForegroundColor Gray
            }
            Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
        } else {
            Report-Item 'PASS' '4. Helper models evaluation table' "No active helper models registered in models.json."
        }
    } catch {
        Report-Item 'FAIL' '4. Helper models evaluation table' "Failed to read/parse models.json: $_"
    }
} else {
    Report-Item 'WARN' '4. Helper models evaluation table' "state/models.json not found."
}

# -----------------------------------------------------------------------------
# 5. Last 20 llm_call_failed Events Grouped by Error Type (Look for 400 and 429)
# -----------------------------------------------------------------------------
$failedEvents = @()
if ($logFile -and (Test-Path -LiteralPath $logFile)) {
    $logLines = Get-Content -LiteralPath $logFile -Encoding UTF8
    foreach ($line in $logLines) {
        if ($line -match '"event"\s*:\s*"llm_call_failed"') {
            try {
                $failedEvents += ($line | ConvertFrom-Json)
            } catch { }
        }
    }
}

$last20Failed = if ($failedEvents.Count -gt 20) { $failedEvents[-20..-1] } else { $failedEvents }
if ($last20Failed.Count -eq 0) {
    Report-Item 'PASS' '5. llm_call_failed events (last 20)' 'No llm_call_failed events recorded (0 errors).'
} else {
    $groups = $last20Failed | Group-Object -Property error_type
    $summaryParts = @()
    $has400or429 = $false
    foreach ($g in $groups) {
        $summaryParts += "$($g.Name): $($g.Count)"
        if ($g.Name -match '400|429') { $has400or429 = $true }
    }
    foreach ($evt in $last20Failed) {
        if (("" + $evt.error) -match '400|429') { $has400or429 = $true }
    }
    $statusStr = if ($has400or429) { 'WARN' } else { 'PASS' }
    $notice = if ($has400or429) { " [HTTP 400/429 errors detected]" } else { "" }
    Report-Item $statusStr '5. llm_call_failed events (last 20)' "$($last20Failed.Count) failure(s) grouped: $($summaryParts -join ', ')$notice"
}

# -----------------------------------------------------------------------------
# 6. Effective Daily Token Cap (WARN if > 1,000,000,000)
# -----------------------------------------------------------------------------
$tokenBudgetFile = Join-Path $resolvedWs 'state\daily_token_budget.json'
$effectiveCap = 0
$capSource = ""
if (Test-Path -LiteralPath $tokenBudgetFile) {
    try {
        $tbData = (Get-Content -LiteralPath $tokenBudgetFile -Raw -Encoding UTF8) | ConvertFrom-Json
        if ($tbData.cap) {
            $effectiveCap = [long]$tbData.cap
            $capSource = "state/daily_token_budget.json"
        }
    } catch { }
}

if ($effectiveCap -eq 0) {
    $envFile = Join-Path $repo '.env'
    if (Test-Path -LiteralPath $envFile) {
        $match = (Get-Content -LiteralPath $envFile -Encoding UTF8) | Where-Object { $_ -match '^\s*SELF_MAX_TOKENS_PER_DAY\s*=\s*(\d+)' } | Select-Object -First 1
        if ($match -and $match -match '=\s*(\d+)') {
            $effectiveCap = [long]$Matches[1]
            $capSource = ".env"
        }
    }
}

if ($effectiveCap -eq 0 -and $env:SELF_MAX_TOKENS_PER_DAY) {
    $effectiveCap = [long]$env:SELF_MAX_TOKENS_PER_DAY
    $capSource = "env:SELF_MAX_TOKENS_PER_DAY"
}

if ($effectiveCap -eq 0) {
    $effectiveCap = 200000
    $capSource = "default fallback (200,000)"
}

if ($effectiveCap -gt 1000000000) {
    Report-Item 'WARN' '6. Daily token ledger cap' "Effective cap is $effectiveCap (source: $capSource) - above 1,000,000,000: effectively unlimited."
} else {
    Report-Item 'PASS' '6. Daily token ledger cap' "Effective cap is $effectiveCap (source: $capSource)."
}

# -----------------------------------------------------------------------------
# 7. Leftover Old-Framing Phrases in memory.jsonl & Handoff Files
# -----------------------------------------------------------------------------
$forbiddenPhrases = @(
    "protective of the human",
    "human's goals",
    "loyal companion",
    "Ensures we",
    "High-priority human"
)

$targetFramingFiles = @(
    (Join-Path $resolvedWs 'state\memory.jsonl'),
    (Join-Path $resolvedWs 'state\handoff.json'),
    (Join-Path $resolvedWs 'state\handoff_last_good.json'),
    (Join-Path $resolvedWs 'state\handoff_overflow.json')
)

$foundFramingViolations = @()
foreach ($tf in $targetFramingFiles) {
    if (Test-Path -LiteralPath $tf) {
        $content = Get-Content -LiteralPath $tf -Raw -Encoding UTF8
        foreach ($phrase in $forbiddenPhrases) {
            if ($content -match [regex]::Escape($phrase)) {
                $foundFramingViolations += "'$phrase' in $(Split-Path $tf -Leaf)"
            }
        }
    }
}

if ($foundFramingViolations.Count -gt 0) {
    Report-Item 'FAIL' '7. Old-framing phrases audit' "Leftover phrases found: $($foundFramingViolations -join '; ')"
} else {
    Report-Item 'PASS' '7. Old-framing phrases audit' "No obsolete framing phrases in memory.jsonl or handoff files."
}

# -----------------------------------------------------------------------------
# 8. handoff.json Size & Repeats of "Session complete after"
# -----------------------------------------------------------------------------
$handoffFile = Join-Path $resolvedWs 'state\handoff.json'
if (Test-Path -LiteralPath $handoffFile) {
    $handoffRaw = Get-Content -LiteralPath $handoffFile -Raw -Encoding UTF8
    $handoffChars = $handoffRaw.Length
    $repeats = [regex]::Matches($handoffRaw, "Session complete after").Count
    if ($handoffChars -gt 6000 -or $repeats -gt 1) {
        Report-Item 'WARN' '8. handoff.json size & repeats' "Size: $handoffChars chars (threshold: 6,000), 'Session complete after' repeats: $repeats."
    } else {
        Report-Item 'PASS' '8. handoff.json size & repeats' "Size: $handoffChars chars <= 6,000; 'Session complete after' repeats: $repeats."
    }
} else {
    Report-Item 'PASS' '8. handoff.json size & repeats' "state/handoff.json not yet created (clean first boot state)."
}

# -----------------------------------------------------------------------------
# 9. "we/our/us" Words in Last 20 Chat Replies
# -----------------------------------------------------------------------------
$convFile = Join-Path $resolvedWs 'state\conversation_threads.jsonl'
$weOurUsCount = 0
$assistantRepliesCount = 0

if (Test-Path -LiteralPath $convFile) {
    $convLines = Get-Content -LiteralPath $convFile -Encoding UTF8
    $assistantReplies = @()
    foreach ($line in $convLines) {
        if (-not $line.Trim()) { continue }
        try {
            $msg = $line | ConvertFrom-Json
            if ($msg.role -eq 'assistant' -and $msg.text) {
                $assistantReplies += [string]$msg.text
            }
        } catch { }
    }
    $last20 = if ($assistantReplies.Count -gt 20) { $assistantReplies[-20..-1] } else { $assistantReplies }
    $assistantRepliesCount = $last20.Count
    foreach ($rep in $last20) {
        $matches = [regex]::Matches($rep, '\b(we|our|us)\b', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        $weOurUsCount += $matches.Count
    }
    if ($weOurUsCount -gt 0) {
        Report-Item 'WARN' '9. Autonomous voice (we/our/us)' "Found $weOurUsCount 'we/our/us' word(s) across last $assistantRepliesCount assistant replies."
    } else {
        Report-Item 'PASS' '9. Autonomous voice (we/our/us)' "0 'we/our/us' words found across last $assistantRepliesCount assistant replies."
    }
} else {
    Report-Item 'PASS' '9. Autonomous voice (we/our/us)' "conversation_threads.jsonl not present (no chat replies to scan)."
}

# -----------------------------------------------------------------------------
# 10. Required Environment Variables (Names Only, Never Secrets)
# -----------------------------------------------------------------------------
$candidateKeys = @("OLLAMA_API_KEY", "OLLAMA_API_KEYS", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS")
$candidateModels = @("OLLAMA_MODEL", "ANTHROPIC_MODEL")

$envMap = @{}
$envFilePath = Join-Path $repo '.env'
if (Test-Path -LiteralPath $envFilePath) {
    Get-Content -LiteralPath $envFilePath -Encoding UTF8 | ForEach-Object {
        $l = $_.Trim()
        if ($l -and -not $l.StartsWith('#') -and $l -match '^([A-Za-z0-9_]+)\s*=\s*(.*)$') {
            $name = $Matches[1]
            $val = $Matches[2].Trim()
            if ($val) { $envMap[$name] = $true }
        }
    }
}

# Also check active process environment without reading values
foreach ($k in ($candidateKeys + $candidateModels)) {
    if ([System.Environment]::GetEnvironmentVariable($k)) {
        $envMap[$k] = $true
    }
}

$presentNames = @()
$missingNames = @()
foreach ($k in ($candidateKeys + $candidateModels)) {
    if ($envMap.ContainsKey($k)) {
        $presentNames += $k
    } else {
        $missingNames += $k
    }
}

$hasProviderKey = ($envMap.ContainsKey("OLLAMA_API_KEY") -or $envMap.ContainsKey("OLLAMA_API_KEYS") -or $envMap.ContainsKey("ANTHROPIC_API_KEY") -or $envMap.ContainsKey("ANTHROPIC_API_KEYS"))
$hasModel = ($envMap.ContainsKey("OLLAMA_MODEL") -or $envMap.ContainsKey("ANTHROPIC_MODEL"))

if ($hasProviderKey -and $hasModel) {
    Report-Item 'PASS' '10. Required env vars presence' "Present: $($presentNames -join ', ') | Missing/Unset: $($missingNames -join ', ') [names only]"
} else {
    Report-Item 'FAIL' '10. Required env vars presence' "Missing required LLM credentials or model. Present: $($presentNames -join ', ') | Missing/Unset: $($missingNames -join ', ') [names only]"
}

# -----------------------------------------------------------------------------
# 11. Plugin Inventory & Hash State (with plugin_hash_mismatch warnings)
# -----------------------------------------------------------------------------
$cfgPluginsFile = Join-Path $resolvedCfg 'plugins.json'
$pluginsConfig = @{}
if (Test-Path -LiteralPath $cfgPluginsFile) {
    try {
        $cfgJson = (Get-Content -LiteralPath $cfgPluginsFile -Raw -Encoding UTF8) | ConvertFrom-Json
        if ($cfgJson.plugins) {
            foreach ($prop in $cfgJson.plugins.PSObject.Properties) {
                $pluginsConfig[$prop.Name] = $prop.Value
            }
        }
    } catch { }
}

# Scan for plugin directories
$scannedPlugins = @{}
$pluginSearchPaths = @(
    (Join-Path $repo 'agent\plugins'),
    (Join-Path $repo 'agent\plugins\examples'),
    (Join-Path $repo 'plugins'),
    (Join-Path $resolvedWs 'plugins'),
    '/opt/agent/plugins',
    '/opt/agent/plugins/examples'
)

foreach ($sp in $pluginSearchPaths) {
    if (Test-Path -LiteralPath $sp) {
        Get-ChildItem -LiteralPath $sp -Directory | ForEach-Object {
            $pName = $_.Name
            if ($pName -notin @('__pycache__', '_template', '_archive') -and (Test-Path -LiteralPath (Join-Path $_.FullName 'plugin.json'))) {
                $scannedPlugins[$pName] = $_.FullName
            }
        }
    }
}

# Also include any plugins listed in config even if not found in search paths
foreach ($pName in $pluginsConfig.Keys) {
    if (-not $scannedPlugins.ContainsKey($pName)) {
        $scannedPlugins[$pName] = $null
    }
}

# Scan logs/actions.jsonl for any plugin_hash_mismatch events
$mismatchLogEvents = @()
if ($logFile -and (Test-Path -LiteralPath $logFile)) {
    $logLines = Get-Content -LiteralPath $logFile -Encoding UTF8
    foreach ($line in $logLines) {
        if ($line -match '"event"\s*:\s*"plugin_hash_mismatch"') {
            try {
                $mismatchLogEvents += ($line | ConvertFrom-Json)
            } catch { }
        }
    }
}

$pluginRows = @()
$hasActiveMismatch = $false

foreach ($pName in ($scannedPlugins.Keys | Sort-Object)) {
    $pDir = $scannedPlugins[$pName]
    $cfgEntry = $pluginsConfig[$pName]
    $isEnabled = $false
    $pinnedHash = $null

    if ($cfgEntry) {
        $isEnabled = [bool]$cfgEntry.enabled
        $pinnedHash = $cfgEntry.hash
    }

    $computedHash = $null
    $hashState = "UNPINNED"
    $coreApi = "unknown"

    if ($pDir -and (Test-Path -LiteralPath (Join-Path $pDir 'plugin.json'))) {
        try {
            $pManifest = (Get-Content -LiteralPath (Join-Path $pDir 'plugin.json') -Raw -Encoding UTF8) | ConvertFrom-Json
            if ($pManifest.core_api) { $coreApi = $pManifest.core_api }
        } catch { }

        if (-not $DryRun) {
            $computedHash = Get-PluginDirHash $pDir
        } else {
            # In DryRun mode, check if a mock mismatch was requested
            $mockMismatch = $false
            if ($logMismatchCount -gt 0 -or (Test-Path -LiteralPath (Join-Path $resolvedWs 'state\.mock_hash_mismatch'))) {
                $mockMismatch = $true
            }
            $computedHash = if ($mockMismatch) { "tampered_hash_value" } elseif ($pinnedHash) { $pinnedHash } else { "mock_computed_hash" }
        }

        if ($pinnedHash) {
            if ($computedHash -eq $pinnedHash) {
                $hashState = "MATCH"
            } else {
                $hashState = "MISMATCH"
                if ($isEnabled) { $hasActiveMismatch = $true }
            }
        }
    } else {
        $hashState = "DIR_NOT_FOUND"
        if ($isEnabled) { $hasActiveMismatch = $true }
    }

    $pluginRows += [PSCustomObject]@{
        Name = $pName
        Status = if ($isEnabled) { "Enabled" } else { "Disabled" }
        HashState = $hashState
        CoreAPI = $coreApi
    }
}

$mismatchCount = ($pluginRows | Where-Object { $_.HashState -eq 'MISMATCH' }).Count
$logMismatchCount = $mismatchLogEvents.Count

$item11Status = 'PASS'
$item11Detail = "$($pluginRows.Count) plugin(s) discovered ($(@($pluginRows | Where-Object { $_.Status -eq 'Enabled' }).Count) enabled, $(@($pluginRows | Where-Object { $_.Status -eq 'Disabled' }).Count) disabled)."

if ($hasActiveMismatch -or $mismatchCount -gt 0 -or $logMismatchCount -gt 0) {
    $item11Status = 'WARN'
    $item11Detail += " WARNING: plugin_hash_mismatch detected (active mismatches: $mismatchCount, logged events: $logMismatchCount)!"
}

Report-Item $item11Status '11. Plugin inventory & hash state' $item11Detail

if ($pluginRows.Count -gt 0) {
    Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
    Write-Host ("       {0,-24} | {1,-10} | {2,-16} | {3,-16}" -f "Plugin Name", "Status", "Hash State", "Core API") -ForegroundColor DarkCyan
    Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
    foreach ($row in $pluginRows) {
        $rowColor = if ($row.HashState -eq 'MISMATCH') { 'Yellow' } elseif ($row.Status -eq 'Enabled') { 'Green' } else { 'Gray' }
        Write-Host ("       {0,-24} | {1,-10} | {2,-16} | {3,-16}" -f $row.Name, $row.Status, $row.HashState, $row.CoreAPI) -ForegroundColor $rowColor
    }
    Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# 12. Proposals and Project Reviews
# -----------------------------------------------------------------------------
$proposalsFile = Join-Path $resolvedWs 'state\plugin_proposals.jsonl'
$proposals = @()
if (Test-Path -LiteralPath $proposalsFile) {
    $pLines = Get-Content -LiteralPath $proposalsFile -Encoding UTF8
    foreach ($pl in $pLines) {
        if (-not $pl.Trim()) { continue }
        try { $proposals += ($pl | ConvertFrom-Json) } catch { }
    }
}

$planProjectDecisions = @()
if (Test-Path -LiteralPath $planFile) {
    try {
        $pObj = (Get-Content -LiteralPath $planFile -Raw -Encoding UTF8) | ConvertFrom-Json
        if ($pObj.plugin_project_decisions) {
            $planProjectDecisions = @($pObj.plugin_project_decisions)
        }
    } catch { }
}

$reviewPackets = @()
$pluginDevDir = Join-Path $resolvedWs 'plugin_dev'
if (Test-Path -LiteralPath $pluginDevDir) {
    Get-ChildItem -LiteralPath $pluginDevDir -Directory | ForEach-Object {
        $rf = Join-Path $_.FullName 'review_packet.json'
        if (Test-Path -LiteralPath $rf) {
            try { $reviewPackets += (Get-Content -LiteralPath $rf -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
        }
    }
}

$activeProposals = $proposals | Where-Object { $_.status -in @('proposed', 'in_progress') }
$decSummary = if ($planProjectDecisions.Count -gt 0) {
    $groupedDecs = $planProjectDecisions | Group-Object -Property decision
    ($groupedDecs | ForEach-Object { "$($_.Name): $($_.Count)" }) -join ', '
} else { "none" }

Report-Item 'PASS' '12. Proposals and project reviews' "Proposals: $($proposals.Count) total ($($activeProposals.Count) active), stop-loss reviews: $($planProjectDecisions.Count) ($decSummary), review packets: $($reviewPackets.Count)."

if ($activeProposals.Count -gt 0) {
    Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
    Write-Host ("       {0,-20} | {1,-12} | {2,-16} | {3,-20}" -f "Proposal Name", "Status", "Estimated Spend", "Need") -ForegroundColor DarkCyan
    Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
    foreach ($ap in $activeProposals) {
        $tokEst = if ($ap.estimate -and $ap.estimate.tokens) { "$($ap.estimate.tokens.min)-$($ap.estimate.tokens.max) tok" } else { "n/a" }
        $needSnippet = if ($ap.need) { ($ap.need.ToString().Trim().Substring(0, [Math]::Min(20, $ap.need.Length))) } else { "n/a" }
        Write-Host ("       {0,-20} | {1,-12} | {2,-16} | {3,-20}" -f $ap.name, $ap.status, $tokEst, $needSnippet) -ForegroundColor Gray
    }
    Write-Host "       ----------------------------------------------------------------------------" -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# 13. Cost Ledger Summary
# -----------------------------------------------------------------------------
$costLedgerFile = Join-Path $resolvedWs 'state\cost_ledger.jsonl'
$ledgerEntries = @()
if (Test-Path -LiteralPath $costLedgerFile) {
    $clLines = Get-Content -LiteralPath $costLedgerFile -Encoding UTF8
    foreach ($cl in $clLines) {
        if (-not $cl.Trim()) { continue }
        try { $ledgerEntries += ($cl | ConvertFrom-Json) } catch { }
    }
}

if ($ledgerEntries.Count -gt 0) {
    $toolEntries = $ledgerEntries | Where-Object { $_.kind -eq 'tool' }
    $pluginEntries = $ledgerEntries | Where-Object { $_.kind -eq 'plugin' }

    $totalToolTokens = if ($toolEntries) { ($toolEntries | Measure-Object -Property tokens -Sum).Sum } else { 0 }
    $totalPluginTokens = if ($pluginEntries) { ($pluginEntries | Measure-Object -Property tokens -Sum).Sum } else { 0 }
    $totalLedgerTokens = ($ledgerEntries | Measure-Object -Property tokens -Sum).Sum

    Report-Item 'PASS' '13. Cost ledger summary' "$($ledgerEntries.Count) records ($($toolEntries.Count) tools: $($totalToolTokens) tok, $($pluginEntries.Count) plugins: $($totalPluginTokens) tok, total: $($totalLedgerTokens) tok)."
} else {
    Report-Item 'PASS' '13. Cost ledger summary' "No cost ledger entries recorded yet (state/cost_ledger.jsonl empty or uninitialized)."
}

Write-Host "================================================================================" -ForegroundColor Cyan
$overallStatus = if ($failCount -gt 0) { 'FAIL' } elseif ($warnCount -gt 0) { 'WARN' } else { 'PASS' }
$overallColor = switch ($overallStatus) {
    'PASS' { 'Green' }
    'WARN' { 'Yellow' }
    'FAIL' { 'Red' }
}
Write-Host ("Live Check Complete: {0} PASS, {1} WARN, {2} FAIL => OVERALL: {3}" -f $passCount, $warnCount, $failCount, $overallStatus) -ForegroundColor $overallColor
Write-Host "================================================================================" -ForegroundColor Cyan

if ($FailOnError -and $failCount -gt 0) {
    throw "Live check failed with $failCount error(s)."
}
if ($FailOnWarn -and ($failCount -gt 0 -or $warnCount -gt 0)) {
    throw "Live check failed with $failCount error(s) and $warnCount warning(s)."
}
