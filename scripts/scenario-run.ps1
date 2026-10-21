param(
    [string]$Scenario = "file-triage",
    [int]$Seed = 42,
    [switch]$Hidden,
    [switch]$All,
    [switch]$List,
    [string]$Out
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repo
try {
    $cmdArgs = @("-m", "eval.scenario_runner")
    if ($List) {
        $cmdArgs += "--list"
    } elseif ($All) {
        $cmdArgs += "--all"
        $cmdArgs += @("--seed", $Seed)
    } else {
        $cmdArgs += @("--scenario", $Scenario)
        $cmdArgs += @("--seed", $Seed)
        if ($Hidden) {
            $cmdArgs += "--hidden"
        }
        if ($Out) {
            $cmdArgs += @("--out", $Out)
        }
    }

    python @cmdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Scenario run failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
