[CmdletBinding()]
param(
    [string]$Workspace = 'workspace',
    [switch]$FailOnWarn,
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

$pyScript = Join-Path $PSScriptRoot 'live_soak_gate.py'

$argsList = @($pyScript, "--workspace", $resolvedWs)
if ($FailOnWarn) {
    $argsList += "--fail-on-warn"
}
if ($Json) {
    $argsList += "--json"
}

python @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
