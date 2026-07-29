from pathlib import Path
import importlib


ROOT = Path(__file__).resolve().parents[2]


def test_ai_files_exist():

    files = [
        "core/ai/intent.py",
        "core/ai/tools.py",
        "core/ai/tool_policy.py",
        "core/ai/router.py",
        "core/ai/response_formatter.py",
    ]

    missing = []

    for f in files:
        if not (ROOT / f).exists():
            missing.append(f)

    assert not missing, f"Missing AI files: {missing}"


def test_agent_package():

    path = ROOT / "core/ai/agent"

    assert path.exists(), "core.ai.agent package missing"

    files = [
        "orchestrator.py",
        "tool_execution.py",
        "read_only.py",
        "audit.py",
    ]

    missing=[]

    for f in files:
        if not (path / f).exists():
            missing.append(f)

    assert not missing, f"Missing agent files: {missing}"


def test_import_ai_modules():

    modules = [
        "core.ai.intent",
        "core.ai.tools",
        "core.ai.tool_policy",
        "core.ai.router",
    ]

    errors=[]

    for m in modules:
        try:
            importlib.import_module(m)
        except Exception as e:
            errors.append(
                f"{m}: {e}"
            )

    assert not errors, "\n".join(errors)