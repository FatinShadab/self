#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
image="${SELF_TEST_IMAGE:-self-ci}"

docker build --tag "$image" .

# Dockerfile supplies PYTHONPATH=/opt:/opt/agent for both suites.
docker run --rm --entrypoint python "$image" \
  -m unittest discover -s /opt/agent/tests -v

# Hidden eval definitions stay on the host and never enter the self image.
docker run --rm --entrypoint python \
  --mount "type=bind,source=$repo/eval,target=/opt/eval,readonly" \
  --mount "type=bind,source=$repo/docker-compose.yml,target=/opt/eval-compose.yml,readonly" \
  "$image" -m unittest discover -s /opt/eval/tests -v
