"""
Guards the heading hierarchy across screens.

Before this, Settings used ``st.title()`` while Dashboard, Create Case and
Case Detail used ``st.header()``. Streamlit renders those as h1 and h2
respectively, so the page title was a top-level heading on one screen and
a second-level one on the others.

Two consequences, neither visible while reading any single page:

* A screen reader announces the document outline from the heading levels.
  An inverted hierarchy makes the page structure wrong for exactly the
  users who depend on it most.
* Visually the screens sized their titles differently, which is a large
  part of why the app felt assembled rather than designed.

The fix was one component per role - page_header() and section_header() -
so a screen cannot pick its own convention. This test keeps it that way.
"""

import ast
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

VIEWS_DIR = REPOSITORY_ROOT / "apps" / "web" / "views"

# Streamlit's own heading calls. Each screen must go through the
# components instead, so the level and the size are decided in one place.
LEGACY_HEADINGS = {"title", "header", "subheader"}


def _view_modules():

    return [
        path
        for path in sorted(VIEWS_DIR.glob("*.py"))
        if path.name != "__init__.py"
    ]


def _calls(tree, name, attribute=False):

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        found = (
            getattr(node.func, "attr", None)
            if attribute
            else getattr(node.func, "id", None)
        )
        if found == name:
            yield node


@pytest.mark.parametrize("view", _view_modules(), ids=lambda p: p.stem)
def test_views_use_the_heading_components(view):
    """No screen reaches for Streamlit's headings directly."""

    tree = ast.parse(view.read_text(encoding="utf-8"))

    offenders = [
        f"  line {node.lineno}: st.{node.func.attr}(...)"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) in LEGACY_HEADINGS
    ]

    assert not offenders, (
        f"{view.name} uses Streamlit's heading calls directly. Use "
        f"page_header() for the screen title and section_header() for a "
        f"division within it, so the level and size are decided in one "
        f"place:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("view", _view_modules(), ids=lambda p: p.stem)
def test_each_screen_has_exactly_one_title(view):
    """
    One h1 per screen.

    Two titles is an ambiguous outline; none leaves the screen unnamed in
    the document structure even when a visual heading happens to be
    present.
    """

    tree = ast.parse(view.read_text(encoding="utf-8"))

    titles = list(_calls(tree, "page_header"))

    assert len(titles) == 1, (
        f"{view.name} calls page_header() {len(titles)} times; a screen has "
        f"exactly one title."
    )


def test_the_title_component_emits_h1_and_the_section_component_h2():
    """
    Pins the levels themselves.

    The tests above enforce that the components are used; this one
    enforces that using them produces the right outline. Without it the
    two could be swapped and every screen would still 'pass'.
    """

    source = (
        REPOSITORY_ROOT / "apps" / "web" / "components" / "layout.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    def emitted_tags(function_name):
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        text = " ".join(
            node.value
            for node in ast.walk(function)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        return {tag for tag in ("<h1", "<h2", "<h3") if tag in text}

    assert emitted_tags("page_header") == {"<h1"}
    assert emitted_tags("section_header") == {"<h2"}
