[CmdletBinding()]
param(
    [string]$Workspace = 'workspace',
    [int]$MaxCycles = 30,
    [string]$LogFile = '',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$resolvedWs = Resolve-Path $Workspace -ErrorAction SilentlyContinue
if (-not $resolvedWs) {
    $resolvedWs = Join-Path $repo $Workspace
} else {
    $resolvedWs = $resolvedWs.Path
}

$pyScript = Join-Path $PSScriptRoot 'analyze_run.py'

$argsList = @($pyScript, "--workspace", $resolvedWs, "--max-cycles", $MaxCycles)
if ($LogFile) {
    $argsList += @("--log-file", $LogFile)
}
if ($Json) {
    $argsList += "--json"
}

python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Run analysis failed with exit code $LASTEXITCODE."
}
