param(
    [int]$MaxTotalCalls = 0
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$planPath = Join-Path $repo 'eval/ab/plan.json'
$statePath = Join-Path $repo 'eval/ab/state.json'
$resultsRoot = Join-Path $repo 'eval/ab/results'
$seedRoot = Join-Path $repo 'ab_seed'
$seedWorkspace = Join-Path $seedRoot 'workspace'
$runsRoot = Join-Path $repo 'ab_runs'
$plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json -AsHashtable
$tasks = (Get-Content -LiteralPath (Join-Path $repo 'eval/ab_tasks.json') -Raw | ConvertFrom-Json -AsHashtable).tasks
$seed = Get-Content -LiteralPath (Join-Path $seedRoot 'metadata.json') -Raw | ConvertFrom-Json -AsHashtable
if ($seed.seed_hash -ne $plan.seed_hash) { throw 'Plan and seed hashes differ. Regenerate the plan for this seed.' }
$cap = if ($MaxTotalCalls -gt 0) { [Math]::Min($MaxTotalCalls, [int]$plan.max_total_calls) } else { [int]$plan.max_total_calls }
if ($cap -lt 1) { throw 'Campaign call cap must be positive.' }
New-Item -ItemType Directory -Path $runsRoot, $resultsRoot -Force | Out-Null
$runsRootFull = [IO.Path]::GetFullPath($runsRoot)
$docker = (Get-Command docker).Source

function Save-State($value) {
    $temporary = "$statePath.tmp"
    $value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statePath -Force
}

function Invoke-BoundedDocker([string[]]$arguments, [hashtable]$environment, [int]$timeoutSeconds, [string]$logPath) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $docker
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $arguments) { [void]$info.ArgumentList.Add($argument) }
    foreach ($key in $environment.Keys) { $info.Environment[$key] = [string]$environment[$key] }
    $process = [Diagnostics.Process]::Start($info)
    $out = $process.StandardOutput.ReadToEndAsync()
    $err = $process.StandardError.ReadToEndAsync()
    $timedOut = -not $process.WaitForExit($timeoutSeconds * 1000)
    if ($timedOut) { $process.Kill($true); $process.WaitForExit() }
    ($out.GetAwaiter().GetResult() + $err.GetAwaiter().GetResult()) |
        Set-Content -LiteralPath $logPath -Encoding utf8
    return $(if ($timedOut) { 124 } else { $process.ExitCode })
}

function Invoke-RunVerifier([string]$workspace, [string]$runId, [int]$exitCode,
                            [double]$wallSeconds, [string]$logPath) {
    $verifyArgs = @('run', '--rm', '--network', 'none', '--read-only',
        '--tmpfs', '/tmp:rw,nosuid,nodev',
        '--mount', "type=bind,source=$workspace,target=/home/entity,readonly",
        '--mount', "type=bind,source=$(Join-Path $repo 'eval'),target=/opt/eval",
        '--mount', "type=bind,source=$seedRoot,target=/opt/ab_seed,readonly",
        '--env', 'PYTHONPATH=/opt:/opt/agent', '--entrypoint', 'python',
        'self-eval', '-m', 'eval.ab_verify',
        '--run-id', $runId, '--exit-code', [string]$exitCode,
        '--wall-seconds', [string]$wallSeconds)
    $verifyExit = Invoke-BoundedDocker $verifyArgs @{} 60 $logPath
    if ($verifyExit -ne 0) { throw "Verifier failed for $runId; see $logPath" }
    return Get-Content -LiteralPath (Join-Path $resultsRoot "$runId.json") -Raw | ConvertFrom-Json -AsHashtable
}

$state = if (Test-Path -LiteralPath $statePath) {
    Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json -AsHashtable
} else {
    @{ campaign_id = $plan.campaign_id; plan_seed = $plan.plan_seed;
       seed_hash = $plan.seed_hash; calls_used = 0; completed = @(); in_progress = $null }
}
if ($state.campaign_id -ne $plan.campaign_id) {
    if ($state.in_progress) { throw "Finish interrupted campaign $($state.campaign_id) before changing plans." }
    $archive = Join-Path (Split-Path $statePath) ("state-" + $state.campaign_id + ".json")
    if (Test-Path -LiteralPath $archive) { throw "Campaign archive already exists: $archive" }
    Move-Item -LiteralPath $statePath -Destination $archive
    $state = @{ campaign_id = $plan.campaign_id; plan_seed = $plan.plan_seed;
                seed_hash = $plan.seed_hash; calls_used = 0; completed = @(); in_progress = $null }
}
if ($state.plan_seed -ne $plan.plan_seed -or $state.seed_hash -ne $plan.seed_hash) {
    throw 'Saved campaign state belongs to a different plan.'
}

foreach ($run in $plan.runs) {
    $runId = [string]$run.run_id
    if ($state.completed -contains $runId) { continue }
    $existingResult = Join-Path $resultsRoot "$runId.json"
    if ($state.in_progress -eq $runId -and (Test-Path -LiteralPath $existingResult)) {
        $saved = Get-Content -LiteralPath $existingResult -Raw | ConvertFrom-Json -AsHashtable
        $state.calls_used = [int]$state.calls_used + [int]$saved.provider_calls
        $state.completed = @($state.completed) + $runId
        $state.in_progress = $null
        Save-State $state
        continue
    }
    if ($state.in_progress -and $state.in_progress -ne $runId) {
        throw "Incomplete run $($state.in_progress) needs inspection before continuing."
    }
    $remaining = $cap - [int]$state.calls_used
    if ($remaining -lt 1) { Write-Host "Call cap reached before $runId; resume with a larger cap."; break }
    $runCap = [Math]::Min([int]$run.provider_call_cap, $remaining)
    $runRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $runId))
    if (-not $runRoot.StartsWith($runsRootFull + [IO.Path]::DirectorySeparatorChar,
                                [StringComparison]::OrdinalIgnoreCase)) {
        throw "Run path escapes ab_runs: $runRoot"
    }
    $workspace = Join-Path $runRoot 'workspace'
    if (Test-Path -LiteralPath $workspace) {
        if ($state.in_progress -ne $runId) {
            throw "Workspace for unfinished run already exists: $workspace. Inspect it before retrying."
        }
        $interrupted = Invoke-RunVerifier $workspace $runId 124 0 (Join-Path $runRoot 'verify.log')
        $state.calls_used = [int]$state.calls_used + [int]$interrupted.provider_calls
        $state.completed = @($state.completed) + $runId
        $state.in_progress = $null
        Save-State $state
        Write-Host "Interrupted run $runId recorded as infrastructure error; resume the campaign after inspection."
        break
    }
    New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
    Copy-Item -LiteralPath $seedWorkspace -Destination $workspace -Recurse
    $task = $tasks | Where-Object { $_.id -eq $run.task_id } | Select-Object -First 1
    if (-not $task) { throw "Unknown task $($run.task_id)" }
    $inputRoot = Join-Path $workspace ("ab_inputs/" + $task.id)
    New-Item -ItemType Directory -Path $inputRoot -Force | Out-Null
    foreach ($relative in $task.input_files.Keys) {
        $target = [IO.Path]::GetFullPath((Join-Path $inputRoot $relative))
        if (-not $target.StartsWith([IO.Path]::GetFullPath($inputRoot) + [IO.Path]::DirectorySeparatorChar,
                                    [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unsafe task input path: $relative"
        }
        New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
        [IO.File]::WriteAllText($target, [string]$task.input_files[$relative])
    }
    $hash = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($runId))
    $project = 'selfab' + [Convert]::ToHexString($hash).Substring(0, 12).ToLowerInvariant()
    $mode = if ($run.arm -eq 'on') { 'on' } else { 'off' }
    $critic = if ($run.arm.StartsWith('forced_critic:')) { $run.arm.Split(':', 2)[1] } else { '' }
    $state.in_progress = $runId
    Save-State $state
    $agentArgs = @('compose', '-p', $project, 'run', '--rm', '--no-deps', '-T',
        '-e', "SELF_HELPER_MODELS=$mode", '-e', "SELF_CRITIC_MODEL=$critic",
        '-e', "SELF_MAX_PROVIDER_CALLS=$runCap", '--entrypoint', 'python', 'self',
        '/opt/agent/loop.py', '--task', [string]$task.prompt,
        '--max-iterations', [string]$run.limits.max_iterations,
        '--token-budget', [string]$run.limits.token_budget,
        '--max-wall-clock-seconds', [string]$run.limits.wall_clock_seconds)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $exitCode = Invoke-BoundedDocker $agentArgs @{ SELF_WORKSPACE_DIR = $workspace } `
        ([int]$run.limits.wall_clock_seconds + 60) (Join-Path $runRoot 'agent.log')
    $clock.Stop()
    $result = Invoke-RunVerifier $workspace $runId $exitCode $clock.Elapsed.TotalSeconds `
        (Join-Path $runRoot 'verify.log')
    $state.calls_used = [int]$state.calls_used + [int]$result.provider_calls
    $state.completed = @($state.completed) + $runId
    $state.in_progress = $null
    Save-State $state
    Write-Host "$runId passed=$($result.passed) score=$($result.score) calls=$($result.provider_calls) total_calls=$($state.calls_used)"
    if ($result.infra_error) {
        Write-Host "Infrastructure or provider stop at $runId. Inspect the result before resuming."
        break
    }
}
