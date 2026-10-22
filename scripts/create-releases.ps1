<#
.SYNOPSIS
    Operator release script for SELF tags and GitHub releases.

.DESCRIPTION
    Pushes verified local tags to remote 'origin' and creates GitHub releases using the 'gh' CLI.
    Guarded by -DryRun to allow safe simulation without network modifications.

.NOTES
    OPERATOR DECISION REQUIRED:
    The operator must decide whether all releases should be public. By default, release candidates
    (core-v0.1.0-rc1, core-v0.1.0-rc2, core-v0.1.0-rc3) are flagged with --prerelease.
    API specification releases (v1.0.0, v1.1.0) represent public plugin interface standards.
#>
[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$OwnerRepo = "FatinShadab/self"
$Tags = @("v1.0.0", "v1.1.0", "core-v0.1.0-rc1", "core-v0.1.0-rc2", "core-v0.1.0-rc3")

Write-Host "======================================================================"
Write-Host "SELF Operator Release Tool"
Write-Host "Repository : $OwnerRepo"
Write-Host "DryRun Mode: $(if ($DryRun) { 'ENABLED (No changes will be pushed)' } else { 'DISABLED (LIVE RELEASE)' })"
Write-Host "======================================================================"

# Step 1: Pre-check remote tags
Write-Host "`nStep 1: Inspecting remote tags on origin..."
$RemoteTagsRaw = git ls-remote --tags origin
$RemoteTags = @()
if ($RemoteTagsRaw) {
    $RemoteTags = ($RemoteTagsRaw | ForEach-Object { ($_ -split '\s+')[1] -replace '^refs/tags/', '' })
}

Write-Host "Found $($RemoteTags.Count) tags on remote origin."
foreach ($tag in $Tags) {
    $onRemote = $RemoteTags -contains $tag
    Write-Host "  - Local tag '$tag': $(if ($onRemote) { 'Already present on origin' } else { 'Missing on origin (needs push)' })"
}

# Step 2: Push tags to origin
Write-Host "`nStep 2: Pushing explicit release tags to origin..."
$TagsToPush = $Tags | Where-Object { $RemoteTags -notcontains $_ }
if ($TagsToPush.Count -gt 0) {
    $PushArgs = @("push", "origin") + $TagsToPush
    if ($DryRun) {
        $PushArgs += "--dry-run"
        Write-Host "[DRY-RUN] Executing: git $($PushArgs -join ' ')"
        & git @PushArgs
    } else {
        Write-Host "[LIVE] Executing: git $($PushArgs -join ' ')"
        & git @PushArgs
    }
} else {
    Write-Host "All release tags already exist on origin; skipping tag push."
}

# Step 3: Create GitHub Releases via gh CLI
Write-Host "`nStep 3: Creating GitHub Releases via 'gh release create'..."

$ReleaseDefinitions = @(
    @{
        Tag = "v1.0.0"
        Title = "SELF Plugin API v1.0.0"
        Prerelease = $false
        Notes = @"
### SELF Plugin API v1.0.0 Specification

Initial public release of the SELF Plugin API specification and developer toolchain:
- **Plugin Manifest Schema**: Declarative `plugin.json` supporting metadata, capabilities, entrypoints, and core API compatibility declarations.
- **Plugin Manager**: Dynamic discovery in `workspace/plugins/` and `/opt/agent/plugins/`, isolated runtime loader, private state directory sandboxing, and execution lifecycle hooks.
- **Plugin CLI**: Developer management tools (`list`, `inspect`, `check`, `validate`, `create`).
- **Demo Plugin**: `hello` demo plugin demonstrating sensor inspection and greeting action.
"@
    },
    @{
        Tag = "v1.1.0"
        Title = "SELF Plugin API v1.1.0"
        Prerelease = $false
        Notes = @"
### SELF Plugin API v1.1.0 Specification

Feature enhancement release for the Plugin API specification:
- **Custom Slash Commands**: Added `commands` field to `PluginManifest`, enabling plugins to register interactive UI commands (e.g. `/pet`).
- **Reserved Command Protection**: `PluginManager` enforces hard protection preventing plugins from overriding core human operator controls (`/pause`, `/resume`, `/stop`, `/goal`, `/models`, `/coverage`).
- **Demo Plugin**: `pet_companion` demonstration plugin with emotional state tracking and habit simulation.
- **Specification Bump**: `VERSION` and `CORE_API_VERSION` set to 1.1.0.
"@
    },
    @{
        Tag = "core-v0.1.0-rc1"
        Title = "SELF Core Engine v0.1.0 Release Candidate 1"
        Prerelease = $true
        Notes = @"
### SELF Core Engine v0.1.0 Release Candidate 1

First release candidate packaging the complete autonomous agent harness:
- **Self-Development Pipeline**: In-container plugin synthesis tools (`propose_plugin`, `write_plugin_file`, `test_plugin`, `list_plugins_dev`, `read_cost_ledger`, `read_plugin_file`).
- **Cost Ledger & Governance**: Append-only telemetry (`state/cost_ledger.jsonl`) tracking token spend, duration, and cycles with stop-loss threshold governance (25%, 50%, 100%).
- **Interactive Proposals**: Slash command `/proposals` for human review and arbitration.
- **Pre-Live Diagnostics**: `scripts/live-check.ps1` and 30-cycle log analysis (`scripts/analyze-run.ps1`).
- **State Migration**: Snapshot backup and byte-for-byte SHA-256 verification (`scripts/migrate_p14_tagged_state.py`).
"@
    },
    @{
        Tag = "core-v0.1.0-rc2"
        Title = "SELF Core Engine v0.1.0 Release Candidate 2"
        Prerelease = $true
        Notes = @"
### SELF Core Engine v0.1.0 Release Candidate 2

Hardening and stability release candidate:
- **Empty Ledger Bootstrap**: Enabled proposal authoring when historical cost ledger has 0 tool creations.
- **Stop-Loss Enforcement**: Draft write operations (`write_plugin_file`) blocked on stop-loss triggers until operator arbitration.
- **Deterministic Hash Pinning**: Ordinal directory file hashing excluding mutable `state/`.
- **Handoff Boundedness**: Hard 6,000-character ceiling with compaction and archival to `state/handoff_overflow.json`.
- **Windows File Lock Recovery**: Handled Windows file lock contention on uninitialized byte ranges in `agent/infra/file_lock.py`.
"@
    },
    @{
        Tag = "core-v0.1.0-rc3"
        Title = "SELF Core Engine v0.1.0 Release Candidate 3"
        Prerelease = $true
        Notes = @"
### SELF Core Engine v0.1.0 Release Candidate 3

Long-running stability and deterministic soak verification:
- **Deterministic Soak Test Suite**: Multi-cycle scenario testing (`scripts/soak.ps1`, Scenarios B1-B10) across 60 to 200 cycles without live provider spend.
- **Reproducible Replay**: Historical execution traces validated against recorded provider payloads (`test_soak_replay.py`).
- **Pre-Live Soak Gate**: Invariant verification gate (`scripts/live_soak_gate.py`) checking token reservations, handoffs, and plan hygiene.
- **Tight-Spin Prevention**: Fixed CPU spin in `AgentLoop._pause_until_daily_reset` when balance is below minimum call size.
- **Handoff Deduplication**: Deduplicated recursive `"Session complete after X cycles"` headers in `WakeCoordinator`.
"@
    }
)

foreach ($rel in $ReleaseDefinitions) {
    $Tag = $rel.Tag
    $Title = $rel.Title
    $Notes = $rel.Notes
    $PrereleaseFlag = if ($rel.Prerelease) { "--prerelease" } else { "" }

    $ghArgs = @("release", "create", $Tag, "--title", $Title, "--notes", $Notes)
    if ($rel.Prerelease) {
        $ghArgs += "--prerelease"
    }

    if ($DryRun) {
        Write-Host "[DRY-RUN] Would create release: $Tag ('$Title')$(if ($rel.Prerelease) { ' [Pre-release]' } else { '' })"
        Write-Host "          Command: gh $($ghArgs -join ' ')"
    } else {
        Write-Host "[LIVE] Creating release: $Tag ('$Title')..."
        & gh @ghArgs
    }
}

Write-Host "`nRelease script execution complete."
