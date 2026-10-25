#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
image="${SELF_TEST_IMAGE:-self-ci}"

python scripts/check_architecture_docs.py
python scripts/check_docs_claims.py

docker build --tag "$image" .

# Dockerfile supplies PYTHONPATH=/opt:/opt/agent for both suites.
docker run --rm --entrypoint python -e SELF_BASE_MODEL=gpt-oss:120b "$image" \
  --mount "type=bind,source=$repo/docker-compose.yml,target=/opt/eval-compose.yml,readonly" \
  -m unittest discover -s /opt/agent/tests -v

# Hidden eval definitions stay on the host and never enter the self image.
docker run --rm --entrypoint python -e SELF_BASE_MODEL=gpt-oss:120b \
  --mount "type=bind,source=$repo/eval,target=/opt/eval,readonly" \
  --mount "type=bind,source=$repo/docker-compose.yml,target=/opt/eval-compose.yml,readonly" \
  "$image" -m unittest discover -s /opt/eval/tests -v
