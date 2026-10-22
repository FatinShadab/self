#!/bin/bash
# Container entrypoint: run optional startup tasks, then start the agent.
set -e

# Ensure opencode is installed (idempotent, never fails).
python /opt/scripts/opencode/install_opencode.py --ensure 2>&1 \
    || echo "[entrypoint] opencode --ensure returned non-zero (should not happen); continuing."

# Start the agent with all passed arguments.
exec python -m agent.wake "$@"
