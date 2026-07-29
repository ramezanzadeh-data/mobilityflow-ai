import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_project_structure():

    required = [
        "apps",
        "core",
        "auth",
        "db",
        "workers",
        "tests",
        "requirements.txt",
        "docker-compose.yml",
    ]

    missing = []

    for item in required:
        if not (ROOT / item).exists():
            missing.append(item)

    assert not missing, f"Missing project components: {missing}"


def test_core_modules_exist():

    expected = [
        "core/ai",
        "core/workflow",
        "core/documents",
        "core/rules",
        "core/case",
    ]

    missing = []

    for item in expected:
        if not (ROOT / item).exists():
            missing.append(item)

    assert not missing, f"Missing core modules: {missing}"


def test_python_files_count():

    files = list(ROOT.rglob("*.py"))

    print("\nPython files:", len(files))

    for f in files[:20]:
        print(f)

    assert len(files) > 30