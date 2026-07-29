"""
One way in and out of the LLM.

Every call to Ollama must go through ``core.ai.ollama_client``. That
module is not a preference - it is the only place in the project that
applies a request timeout and converts transport failures into a single
exception type.

The failure this prevents
-------------------------
``core/ai/engine.py`` and ``core/communication/templates.py`` imported
the ``ollama`` package directly. That package builds a module-level HTTP
client on import and explicitly disables the timeout::

    Timeout(timeout=None)          # ollama
    Timeout(timeout=5.0)           # httpx's own default

None of the four ``ask_ai`` call sites caught anything, so a backend that
accepted the TCP connection and then went quiet - a model still loading,
a stale port forward, a laptop that slept - blocked the caller
indefinitely. In Streamlit that is a spinner the user can only escape by
restarting; in a Celery worker it is a slot held for the life of the
process.

Constructing the client at import time had a second cost: it put the
whole test suite behind it. In an environment with a SOCKS proxy the
suite failed collection before running a single test, including in
modules that never touch the LLM.

Why a static check rather than a code review note
--------------------------------------------------
``import ollama`` is the obvious thing to write when adding an AI
feature, and the resulting code works perfectly on a developer machine
with Ollama running locally and answering fast. The defect only appears
under conditions a developer does not reproduce. A reviewer will not
catch it reliably; this will.
"""

import ast
import socket
from pathlib import Path

import pytest

from core.ai.engine import ask_ai
from core.ai.ollama_client import OllamaUnavailableError


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# The package name that must not be imported anywhere. Kept as a
# constant so the failure message can name it exactly.
FORBIDDEN_PACKAGE = "ollama"

# The module every LLM caller is expected to go through instead.
SANCTIONED_MODULE = "core.ai.ollama_client"

SKIPPED_DIRECTORIES = {
    "__pycache__", ".git", ".venv", "venv", "env",
    "node_modules", "build", "dist", ".pytest_cache",
}


def _python_files():
    """Every source file in the repository, excluding build artefacts."""

    for path in REPOSITORY_ROOT.rglob("*.py"):

        if any(part in SKIPPED_DIRECTORIES for part in path.parts):
            continue

        yield path


def _imports_forbidden_package(tree):
    """
    Whether this module imports the ``ollama`` package.

    Parsed rather than matched textually. A regex over the source would
    fire on the word in a comment or a docstring - including the ones in
    this file and in core/ai/engine.py, which exist precisely to explain
    why the import is absent.

    ``core.ai.ollama_client`` is a different, sanctioned module: its
    dotted name starts with "core", not "ollama", so it does not match.
    """

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == FORBIDDEN_PACKAGE:
                    return True

        elif isinstance(node, ast.ImportFrom):
            # node.module is None for a relative import ("from . import
            # x"), which cannot reach a third-party package.
            root = (node.module or "").split(".")[0]
            if root == FORBIDDEN_PACKAGE:
                return True

    return False


def test_no_module_imports_the_ollama_package_directly():
    """
    The boundary itself.

    Every LLM call goes through core.ai.ollama_client, which is where the
    timeout and the single exception type live.
    """

    offenders = []

    for path in _python_files():

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # Not this test's business to fail on a file that does not
            # parse - it would report the wrong problem.
            continue

        if _imports_forbidden_package(tree):
            offenders.append(str(path.relative_to(REPOSITORY_ROOT)))

    assert not offenders, (
        f"These modules import the {FORBIDDEN_PACKAGE!r} package directly:\n"
        + "\n".join(f"  - {name}" for name in sorted(offenders))
        + f"\n\nThat package disables the HTTP timeout entirely, so a call "
        f"to a backend that stops responding never returns.\n"
        f"Use {SANCTIONED_MODULE} instead - it applies "
        f"REQUEST_TIMEOUT_SECONDS and raises OllamaUnavailableError."
    )


def test_the_package_is_not_a_declared_dependency():
    """
    Nothing imports it, so nothing should install it.

    A dependency that is present but unused is one `import ollama` away
    from being used again, and the failure it causes is invisible in
    development.
    """

    requirements = (REPOSITORY_ROOT / "requirements.txt").read_text(
        encoding="utf-8"
    )

    declared = [
        line.strip()
        for line in requirements.splitlines()
        # Comments in requirements.txt explain why the package is absent
        # and legitimately contain the word.
        if line.strip() and not line.strip().startswith("#")
    ]

    offenders = [
        line for line in declared
        if line.split("=")[0].split(">")[0].split("<")[0].strip()
        == FORBIDDEN_PACKAGE
    ]

    assert not offenders, (
        f"requirements.txt still declares {offenders}. "
        f"Nothing imports it; the project reaches Ollama over HTTP from "
        f"{SANCTIONED_MODULE}."
    )


def _closed_local_port():
    """
    A port on the loopback interface with nothing listening.

    Bound and released rather than hardcoded: a fixed port number is a
    test that passes until the day something happens to be running on it.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_an_unreachable_backend_raises_one_documented_exception(monkeypatch):
    """
    The contract callers depend on.

    core.ai.agent catches OllamaUnavailableError specifically and degrades
    to a deterministic answer. If a raw transport exception escaped
    instead, that handler would be bypassed and the failure would surface
    as an unhandled crash in the user's face.

    Exercised against a genuinely closed port rather than a mocked
    requests.post: the point is that the real wrapping works, not that a
    mock returns what it was told to.
    """

    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{_closed_local_port()}")

    with pytest.raises(OllamaUnavailableError):
        ask_ai("any prompt")


def test_ask_ai_passes_the_prompt_through_unaltered(monkeypatch):
    """
    Callers assemble their own prompts and several then parse the reply
    as JSON. A system message or any reformatting added here would change
    the model's output and break them at a distance.
    """

    captured = {}

    def fake_generate_response(prompt, model=None):
        captured["prompt"] = prompt
        captured["model"] = model
        return "reply"

    monkeypatch.setattr(
        "core.ai.engine.generate_response", fake_generate_response
    )

    assert ask_ai("exactly this text") == "reply"
    assert captured["prompt"] == "exactly this text"


def test_the_timeout_is_bounded():
    """
    The specific property whose absence caused the original defect. A
    client with no timeout waits forever, which is indistinguishable from
    a hang to the person looking at the screen.
    """

    from core.ai import ollama_client

    assert isinstance(ollama_client.REQUEST_TIMEOUT_SECONDS, (int, float))
    assert 0 < ollama_client.REQUEST_TIMEOUT_SECONDS <= 300
