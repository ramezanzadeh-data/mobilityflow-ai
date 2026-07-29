"""
Single-prompt access to the local LLM.

``ask_ai`` is the plain "one prompt in, one string out" call used by
document validation, the intake pipeline, email drafting and the case
detail view. The agent layer (``core.ai.agent``) needs tool calling and
multi-turn messages and talks to ``ollama_client.chat`` directly; this is
the simple path, not a second implementation of the same thing.

Why this does not import the ``ollama`` package
-----------------------------------------------
It used to. The package builds a module-level HTTP client at import time
with the timeout explicitly disabled::

    >>> ollama._client._client.timeout
    Timeout(timeout=None)

httpx defaults to five seconds; the package turns that off. So a call
that reached a host which accepted the connection but never answered -
Ollama loading a model, a stale port forward, a machine that went to
sleep - blocked forever. None of the four call sites wrapped ``ask_ai``
in a try/except, so in Streamlit that was a spinner the user could only
escape by restarting the app, and in a Celery worker it was a worker slot
held permanently.

Building the client at import time also made the whole test suite
dependent on that construction succeeding. It failed collection outright
in an environment with a SOCKS proxy configured - before a single test
ran, and in modules that never touch the LLM.

``core.ai.ollama_client`` already speaks the same documented HTTP API
over ``requests``, with an explicit timeout and one exception type. This
module delegates to it. That removes the import-time client, gives this
path a bounded wait, and leaves exactly one place in the project that
knows how to reach Ollama.
"""

from core.ai.ollama_client import (
    DEFAULT_MODEL,
    OllamaUnavailableError,
    generate_response,
)


# Retained because callers and tests referred to core.ai.engine.MODEL.
# Bound to the client's own default rather than restating "llama3.1", so
# the model is configured in one place.
MODEL = DEFAULT_MODEL


def ask_ai(prompt: str, model: str = MODEL) -> str:
    """
    Send one prompt to the local LLM and return its reply.

    Args:
        prompt: The complete prompt. Callers assemble their own; this
            function adds no system message and no formatting, so what
            is sent is exactly what was passed.
        model: Ollama model tag. Defaults to the project's model.

    Returns:
        The assistant's message content, unparsed. Callers that expect
        JSON do their own parsing and are responsible for tolerating a
        malformed reply - an LLM is not a schema-conforming API.

    Raises:
        OllamaUnavailableError: The backend was unreachable, timed out
            after ollama_client.REQUEST_TIMEOUT_SECONDS, returned a
            non-2xx status, or sent a body that could not be parsed.

            One exception type, deliberately. ``core.ai.agent`` already
            catches exactly this and degrades to a deterministic answer;
            raising raw transport errors from here would mean every
            caller had to know which HTTP library was in use.
    """

    return generate_response(prompt, model=model)


# Re-exported so a caller can handle the failure without also importing
# ollama_client, and so the exception a caller catches is the one this
# module documents.
__all__ = ["MODEL", "OllamaUnavailableError", "ask_ai"]
