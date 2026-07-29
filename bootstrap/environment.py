"""
The single point at which the repository's ``.env`` file is loaded.

Why this module exists
----------------------
Under Docker Compose every process receives its configuration through the
container environment, so nothing needs to read ``.env`` at runtime. A
process started directly on a developer machine gets no such injection -
it inherits only the shell environment, which normally has none of the
PG*/S3_*/OLLAMA_HOST variables.

When only some entry points compensated for that, the entry points
disagreed about which database they were talking to: pytest loaded
``.env`` and reached the containerised Postgres, while
``python -m scripts.migrate`` loaded nothing, fell back to
``db.database._build_pool()``'s localhost defaults, and migrated a
different server entirely - reporting success the whole time. Loading the
file in exactly one place, called by every entry point, is what makes
that class of failure impossible rather than merely unlikely.

Precedence
----------
Real environment > ``.env`` > per-module defaults.

``override=False`` is what guarantees the first step. A variable exported
by CI, by Compose, or by a developer for a one-off run always wins over
the file, so this module can be called unconditionally - inside
containers it is a no-op, because ``.env`` is not shipped in the image
(see ``.dockerignore``) and the real environment takes precedence anyway.

Why the package is called ``bootstrap`` and not ``config``
----------------------------------------------------------
``apps/web/config/`` already exists. Streamlit puts the running script's
own directory (``apps/web/``) at the front of ``sys.path``, so inside the
Streamlit process a top-level package named ``config`` is shadowed by
``apps.web.config`` and ``from config import load_environment`` fails
with ``ImportError``. pytest does not reproduce this, because there the
repository root comes first - so the collision passes the whole test
suite and only appears at runtime.

``bootstrap`` cannot collide with anything in the tree. Do not rename
this package to ``config``.

Usage
-----
Call once, as early as possible, at the entry point - before importing
any module that reads configuration at import time (``db.database``,
``auth.jwt`` and ``auth.encryption`` all do)::

    from bootstrap import load_environment

    load_environment()

Library and domain modules must NOT call this. Loading configuration is a
composition-root concern; a module that quietly mutates the process
environment on import is untestable and order-dependent.
"""

from pathlib import Path

from dotenv import load_dotenv


# bootstrap/environment.py -> bootstrap/ -> repository root
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

ENV_FILE = REPOSITORY_ROOT / ".env"

_loaded = False


def load_environment(force: bool = False) -> bool:
    """
    Load the repository's ``.env`` into ``os.environ``, without ever
    overwriting a variable that is already set.

    Pinned to the repository root rather than resolved from the current
    working directory, so ``pytest tests/...`` from a subdirectory and
    ``python -m scripts.migrate`` from anywhere read the same file.

    Idempotent: repeated calls are a no-op, which makes it safe for an
    entry point to call it even when something upstream already did.

    Args:
        force: Re-read the file even if it was already loaded. Intended
            for tests that rewrite ``.env`` and need the change picked
            up; ``override=False`` still applies, so already-set
            variables are still left alone.

    Returns:
        True if the file was found and read on this call, False if it
        was already loaded or does not exist. A missing ``.env`` is not
        an error - that is the normal situation inside a container and
        in CI, where the environment is supplied directly.
    """

    global _loaded

    if _loaded and not force:
        return False

    if not ENV_FILE.is_file():
        _loaded = True
        return False

    load_dotenv(ENV_FILE, override=False)

    _loaded = True

    return True
