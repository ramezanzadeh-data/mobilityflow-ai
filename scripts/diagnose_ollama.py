"""
Manual diagnostic: check that the configured Ollama backend is reachable
and answering.

This is a developer tool, not a test. It calls a live LLM, so it must not
live under tests/ - pytest imports every tests/test_*.py at collection
time, and a module that performs network I/O at import aborts collection
of the entire suite when the backend is down. The automated coverage for
the AI layer stubs the client instead.

The target URL comes from OLLAMA_HOST, falling back to
core.ai.ollama_client.DEFAULT_OLLAMA_HOST (http://localhost:11434).

Usage:

    python -m scripts.diagnose_ollama ["your prompt here"]

Exits 0 if the backend responded, 1 if it is unreachable.
"""

import argparse
import sys

# Must run before any module that reads configuration at import time -
# see bootstrap/environment.py. OLLAMA_HOST in particular comes from .env.
from bootstrap import load_environment

load_environment()

from core.ai.ollama_client import (  # noqa: E402  (deliberate - see above)
    OllamaUnavailableError,
    generate_response,
    resolve_ollama_base_url,
)


DEFAULT_PROMPT = "Say hello in one sentence."


def _parse_args(argv=None):

    parser = argparse.ArgumentParser(
        description="Send one prompt to the configured Ollama backend.",
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        default=DEFAULT_PROMPT,
        help="Prompt to send (default: a short greeting)",
    )

    return parser.parse_args(argv)


def main(argv=None) -> int:

    args = _parse_args(argv)

    print(f"Ollama backend: {resolve_ollama_base_url()}")

    try:
        result = generate_response(args.prompt)
    except OllamaUnavailableError as exc:
        # Reported as a clean message rather than a traceback: an
        # unreachable backend is the expected negative outcome of this
        # diagnostic, not a crash.
        print(f"UNREACHABLE: {exc}", file=sys.stderr)
        return 1

    print("AI Response:")
    print(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
