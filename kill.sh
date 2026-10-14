#!/usr/bin/env bash
set -euo pipefail

# `docker compose run --rm self ...` creates a one-off container.  `down`
# does not reliably stop those containers, so remove the Compose-scoped
# service containers first; --stop makes this the force-stop path as well.
docker compose rm --stop --force self
docker compose down --remove-orphans

cat <<'NOTE'
Container stopped and removed. The workspace was preserved.

For a fresh start, stop the stack first and then remove only the project
workspace contents from the host (review them before deleting):

  # PowerShell: Remove-Item -LiteralPath .\workspace\* -Recurse -Force
  # Bash:      find ./workspace -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
NOTE
