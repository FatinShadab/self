[CmdletBinding()]
param(
    [switch]$WipeWorkspace
)

$ErrorActionPreference = 'Stop'

$repo = [System.IO.Path]::GetFullPath((Get-Location).Path)
$workspace = [System.IO.Path]::GetFullPath((Join-Path $repo 'workspace'))
$separator = [System.IO.Path]::DirectorySeparatorChar
$workspacePrefix = $workspace.TrimEnd('\', '/') + $separator

if (-not $WipeWorkspace) {
    throw "This verification deliberately clears '$workspace'. Re-run with -WipeWorkspace only after backing up any discoveries you want to keep."
}

Write-Host @"
Phase 8 verification will stop this compose project and permanently remove only
the contents of:
  $workspace

It will then build the image and run an offline verifier. The verifier uses a
fake local model: it does not read keys or call a provider. Type WIPE to continue.
"@ -ForegroundColor Yellow
if ((Read-Host 'Confirmation') -cne 'WIPE') {
    throw 'Workspace wipe was not confirmed.'
}

docker compose down --remove-orphans

if (Test-Path -LiteralPath $workspace) {
    Get-ChildItem -LiteralPath $workspace -Force | ForEach-Object {
        $target = [System.IO.Path]::GetFullPath($_.FullName)
        if (-not $target.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a path outside the workspace: $target"
        }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
} else {
    New-Item -ItemType Directory -LiteralPath $workspace | Out-Null
}

Write-Host 'Building the Phase 8 image...' -ForegroundColor Cyan
docker compose build

Write-Host 'Running the complete offline regression suite...' -ForegroundColor Cyan
docker compose run --rm --no-deps --entrypoint python self -m unittest discover -s /opt/agent/tests -v

Write-Host 'Running the fresh-workspace Phase 8 acceptance check...' -ForegroundColor Cyan
docker compose run --rm --no-deps --entrypoint python self -m agent.phase8_verify --workspace /home/entity

Write-Host "`n--- identity.json ---" -ForegroundColor Cyan
Get-Content -LiteralPath (Join-Path $workspace 'state\identity.json')
Write-Host "`n--- identity log (tail) ---" -ForegroundColor Cyan
Get-Content -LiteralPath (Join-Path $workspace 'state\identity_log.md') -Tail 30
Write-Host "`n--- proposed patches ---" -ForegroundColor Cyan
Get-ChildItem -LiteralPath (Join-Path $workspace 'state\proposed_patches') | Select-Object Name, Length

Write-Host @"

Phase 8 verification passed without external API calls. For a visual TUI check,
run the command below, inspect the header and Self panel, then use /stop:

  docker compose run --rm self --max-iterations 20

The offline verifier named the disposable identity Phase8Verifier. Use
/rename <name> in the TUI if you want a different test name, or wipe the
workspace again before a real first awakening.
"@ -ForegroundColor Green
