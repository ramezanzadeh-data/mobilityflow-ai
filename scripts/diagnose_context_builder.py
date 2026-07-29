"""
Manual diagnostic: print the AI case context for a single case.

This is a developer tool, not a test. It performs live database I/O, so
it must not live under tests/ - pytest imports every tests/test_*.py at
collection time, and a module that opens a real connection at import
aborts collection of the entire suite when the database is unreachable.
The automated coverage for this code path lives in the AI pipeline tests,
which use stubs instead of live infrastructure.

Requires a reachable PostgreSQL instance (see .env / .env.example).

Usage:

    python -m scripts.diagnose_context_builder [CASE_ID]

CASE_ID defaults to 1.
"""

import argparse
import sys

# Must run before any module that reads configuration at import time -
# see bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

from core.ai.context_builder import (  # noqa: E402  (deliberate - see above)
    build_case_context,
    context_to_prompt,
)


DEFAULT_CASE_ID = 1


def _parse_args(argv=None):

    parser = argparse.ArgumentParser(
        description="Print the structured AI context and rendered prompt "
                    "for one case.",
    )

    parser.add_argument(
        "case_id",
        nargs="?",
        type=int,
        default=DEFAULT_CASE_ID,
        help=f"Case id to inspect (default: {DEFAULT_CASE_ID})",
    )

    return parser.parse_args(argv)


def main(argv=None) -> int:

    args = _parse_args(argv)

    context = build_case_context(args.case_id)

    print("STRUCTURED CONTEXT:")
    print(context)

    print("\nAI PROMPT:")
    print(context_to_prompt(context))

    return 0


if __name__ == "__main__":
    sys.exit(main())
