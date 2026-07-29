"""
Process configuration for entry points.

The only public symbol is load_environment (bootstrap.environment), which
loads the repository's .env exactly once. See that module for why the
load must happen in one shared place rather than per entry point.
"""

from bootstrap.environment import ENV_FILE, REPOSITORY_ROOT, load_environment

__all__ = ["ENV_FILE", "REPOSITORY_ROOT", "load_environment"]
