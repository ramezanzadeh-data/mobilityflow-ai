"""
Guards the sidebar against Streamlit's automatic page discovery.

Streamlit registers every module inside a ``pages/`` directory located
beside the main script as a navigable page. ``apps/web/app.py`` had
``apps/web/pages/`` next to it, so the sidebar showed two navigations at
once: the deliberate four-entry "Go to" radio, and a generated list of all
eight modules in that directory.

Three problems with the generated list, in increasing order of severity:

1. Two navigations for one job - the user has to guess which is real.
2. It exposed ``documents``, ``reports`` and ``tasks``, which are helper
   modules rendered inside the case page, not standalone screens.
3. A generated page renders *instead of* ``app.py``, so it never reaches
   ``require_login()``. Today those modules define only functions, so the
   result is a blank screen rather than a data leak - but the authenticated
   entry point is bypassed, and that stops being harmless the moment
   somebody adds a top-level ``st.write(load_cases())`` to one of them.

Renaming the directory to ``views/`` removes the auto-detection at source.
This test keeps it removed: re-creating ``apps/web/pages/`` would silently
restore all three problems, and no behavioural test would notice.
"""

import ast
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

STREAMLIT_ENTRY_POINT = REPOSITORY_ROOT / "apps" / "web" / "app.py"

VIEWS_DIR = REPOSITORY_ROOT / "apps" / "web" / "views"

# Streamlit only auto-discovers a directory with this exact name, and only
# directly beside the main script.
AUTO_DISCOVERED_DIR = STREAMLIT_ENTRY_POINT.parent / "pages"


def test_no_auto_discovered_pages_directory():

    assert not AUTO_DISCOVERED_DIR.exists(), (
        f"{AUTO_DISCOVERED_DIR.relative_to(REPOSITORY_ROOT)} exists again. "
        "Streamlit turns every module in it into a page that renders "
        "outside app.py and therefore skips require_login(), and adds a "
        "second sidebar navigation. Keep view modules in "
        f"{VIEWS_DIR.relative_to(REPOSITORY_ROOT)}."
    )


def test_view_modules_are_importable_helpers_not_scripts():
    """
    The reason the bypass was harmless in practice, made explicit.

    A view module must only *define* things. If one starts executing at
    import time it would run its statements unauthenticated should the
    directory ever be auto-discovered again, and would also fire on a
    plain ``import`` from a test or a script.
    """

    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Assign,          # module-level constants
        ast.AnnAssign,
        ast.Expr,            # docstrings only - calls are rejected below
    )

    offenders = []

    for path in sorted(VIEWS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in tree.body:
            if isinstance(node, ast.Expr):
                # A bare string is a docstring; anything else is a call.
                if isinstance(node.value, ast.Constant):
                    continue
                offenders.append(
                    f"  {path.relative_to(REPOSITORY_ROOT)}:{node.lineno}"
                )
                continue

            if not isinstance(node, allowed):
                offenders.append(
                    f"  {path.relative_to(REPOSITORY_ROOT)}:{node.lineno}"
                )

    assert not offenders, (
        "View module executes code at import time. Move it inside the "
        "show_*() function so it cannot run outside the authenticated "
        "entry point:\n" + "\n".join(offenders)
    )


def test_entry_point_imports_views_not_pages():

    source = STREAMLIT_ENTRY_POINT.read_text(encoding="utf-8")

    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    stale = sorted(m for m in imported if m.startswith("apps.web.pages"))

    assert not stale, (
        f"{STREAMLIT_ENTRY_POINT.name} still imports from apps.web.pages: "
        f"{stale}"
    )


@pytest.mark.parametrize(
    "expected_view",
    ["dashboard", "create_case", "case_detail", "settings"],
)
def test_navigable_views_still_exist(expected_view):
    """
    The rename must not have dropped a screen the sidebar links to.
    """

    assert (VIEWS_DIR / f"{expected_view}.py").is_file()
