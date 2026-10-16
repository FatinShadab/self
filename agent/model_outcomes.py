# Compatibility shim: implementation lives in agent.helper_models.model_outcomes.
from agent.helper_models.model_outcomes import *  # noqa: F401,F403
import sys
if __name__ == "__main__":
    print_outcome_summary(sys.argv[1] if len(sys.argv) > 1 else "/home/entity")
