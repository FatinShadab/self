#!/usr/bin/env bash
set -euo pipefail

docker compose down --remove-orphans

cat <<'NOTE'
Container stopped and removed. The workspace was preserved.

For a fresh start, stop the stack first and then remove only the project
workspace contents from the host (review them before deleting):

  # PowerShell: Remove-Item -LiteralPath .\workspace\* -Recurse -Force
  # Bash:      find ./workspace -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
NOTE
