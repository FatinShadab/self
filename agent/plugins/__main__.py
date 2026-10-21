"""Entrypoint for python -m agent.plugins."""
import sys
from agent.plugins.cli import main

if __name__ == "__main__":
    sys.exit(main())
