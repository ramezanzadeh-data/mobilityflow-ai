"""
Process configuration for entry points.

load_environment (bootstrap.environment) loads the repository's .env
exactly once. See that module for why the load must happen in one shared
place rather than per entry point.

find_config_problems / describe_problems (bootstrap.config_check) then
answer whether what was loaded is understood. Deliberately separate and
deliberately not called by load_environment: what to do about a
misconfiguration differs by entry point - the API refuses to start, the
Streamlit app shows the operator a message - and a loader that decided
that for its callers would take the choice away from both.
"""

from bootstrap.config_check import (
    ConfigProblem,
    KNOWN_SETTINGS,
    describe_problems,
    find_config_problems,
)
from bootstrap.environment import ENV_FILE, REPOSITORY_ROOT, load_environment

__all__ = [
    "ENV_FILE",
    "REPOSITORY_ROOT",
    "load_environment",
    "ConfigProblem",
    "KNOWN_SETTINGS",
    "find_config_problems",
    "describe_problems",
]
