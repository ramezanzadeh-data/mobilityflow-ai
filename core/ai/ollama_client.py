import os
import requests
from typing import Optional


# Base URL of the Ollama runtime. Inside Docker this is injected by
# docker-compose.yml (OLLAMA_HOST=http://host.docker.internal:11434)
# so the containers reach Ollama on the host; when the app runs
# directly on a developer machine the default below is used.
#
# This module is now the only Ollama caller in the project: core/ai/engine.py
# delegates here and core/ai/agent/ calls chat() directly. The `ollama`
# client package is deliberately not used - it disables the HTTP timeout,
# so a backend that stopped responding blocked the caller indefinitely.
# See tests/test_ai_client_boundary.py, which fails if it returns.
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"
REQUEST_TIMEOUT_SECONDS = 120


def resolve_ollama_base_url() -> str:
    """
    Return the normalised Ollama base URL from the OLLAMA_HOST
    environment variable.

    Accepts every form the official Ollama clients accept
    ("http://host:11434", "host:11434", "host") and always returns a
    scheme-qualified URL without a trailing slash. Resolved on each
    call so the value stays correct if the environment is changed at
    runtime (tests, Celery pre-fork workers).
    """

    host = os.getenv("OLLAMA_HOST", "").strip() or DEFAULT_OLLAMA_HOST

    if "://" not in host:
        host = f"http://{host}"

    return host.rstrip("/")


def resolve_ollama_chat_url() -> str:
    """
    Return the full Ollama /api/chat endpoint URL.
    """

    return f"{resolve_ollama_base_url()}/api/chat"


# Kept for backwards compatibility with existing imports. Prefer
# resolve_ollama_chat_url() - this constant is bound at import time.
OLLAMA_URL = resolve_ollama_chat_url()


class OllamaUnavailableError(Exception):
    """
    Raised whenever the Ollama backend cannot be reached or returns a
    malformed/non-2xx response. Callers (core.ai.agent) catch this
    specific type - never a bare Exception - so an LLM infrastructure
    failure degrades into a clear, deterministic, non-analytical
    answer instead of an unhandled crash or a silently wrong result.
    """

    pass


def chat(
    messages: list,
    tools: Optional[list] = None,
    model: str = DEFAULT_MODEL
) -> dict:
    """
    Send chat request to Ollama with optional tools.

    Raises OllamaUnavailableError (never a raw requests/JSON exception)
    on any network failure, timeout, non-2xx response, or unparsable
    body, so every caller can handle exactly one failure type.
    """

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    if tools:
        payload["tools"] = tools

    url = resolve_ollama_chat_url()

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise OllamaUnavailableError(
            f"Could not reach the Ollama backend at {url}: {e}"
        ) from e
    except ValueError as e:
        # response.json() raises ValueError (json.JSONDecodeError) on
        # a malformed/non-JSON body.
        raise OllamaUnavailableError(
            f"Ollama returned a malformed response: {e}"
        ) from e


def generate_response(
    prompt: str,
    model: str = DEFAULT_MODEL
) -> str:
    """
    Simple text generation.
    """

    result = chat(
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        model=model
    )

    return result["message"]["content"]