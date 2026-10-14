$ErrorActionPreference = 'Stop'

function Show-StateFile([string]$Path) {
    Write-Host "`n--- $Path ---" -ForegroundColor Cyan
    if (Test-Path -LiteralPath $Path) { Get-Content -LiteralPath $Path } else { Write-Host '(not created)' }
}

Write-Host 'Building Phase 7...' -ForegroundColor Cyan
docker compose build

Write-Host @'
1) Interactive clean-stop test
SELF is about to start in the terminal UI. Let it reach several cycles (up to
10), then type /stop in the Chat input. It should finish the safe action,
write a handoff and journal entry, then exit.
'@ -ForegroundColor Yellow
Read-Host 'Press Enter to launch the interactive session'
docker compose run --rm self --max-iterations 10

Show-StateFile '.\workspace\state\handoff.json'
Show-StateFile '.\workspace\state\journal.md'
Show-StateFile '.\workspace\state\sessions.jsonl'

# /stop leaves STOP in the mounted workspace. Remove it only after review.
if (Test-Path -LiteralPath '.\workspace\STOP') {
    Remove-Item -LiteralPath '.\workspace\STOP'
    Write-Host 'Removed workspace\STOP for the restart test.' -ForegroundColor Green
}

Write-Host @'
2) Continuity test
The next greeting should accurately reference the prior handoff summary and
plan. Inspect the greeting, then use /stop again.
'@ -ForegroundColor Yellow
Read-Host 'Press Enter to start the continuity session'
docker compose run --rm self --max-iterations 1

if (Test-Path -LiteralPath '.\workspace\STOP') {
    Remove-Item -LiteralPath '.\workspace\STOP'
}

Write-Host @'
3) Crash-recovery test
The script starts the named service, waits for a checkpoint, then kills it
without a graceful shutdown. The next greeting should report recovery from
active_session.json and the last handoff checkpoint. Attach, inspect, and type
/stop.
'@ -ForegroundColor Yellow
Read-Host 'Press Enter to run the controlled crash test'
docker compose up -d --force-recreate
Start-Sleep -Seconds 8
$containerId = (docker compose ps -q self).Trim()
if (-not $containerId) { throw 'SELF service container was not created.' }
docker kill $containerId
docker compose up -d
Start-Sleep -Seconds 3
$newContainerId = (docker compose ps -q self).Trim()
Write-Host 'Attach now; look for the crash-recovery greeting, then type /stop:' -ForegroundColor Green
Write-Host "  docker attach $newContainerId" -ForegroundColor White
Read-Host 'Press Enter after you detached or the session exited'

Show-StateFile '.\workspace\state\handoff.json'
Show-StateFile '.\workspace\state\journal.md'
Show-StateFile '.\workspace\state\sessions.jsonl'
Write-Host 'Phase 7 manual verification complete.' -ForegroundColor Green
