"""
Guards against user-facing text that never goes through t().

A hardcoded English string is invisible in an English build. It only
appears when somebody switches to German and finds one sentence still in
English, with no key to fix and no entry in any translation file - and by
then the product has already been demoed in German.

Four were found this way once the pseudo-locale existed:
``"Generating email..."``, ``"Generating checklist..."``,
``"Generating letter..."`` and a ``"↩ Load"`` button. None of them would
have been caught by reading the English UI, because in English they look
exactly like every other label.

What this test is *not*: a rule that every string must be translated.
Plenty of literals here are markup, punctuation or icons, and demanding a
translation key for ``"—"`` would produce a catalogue nobody maintains.
The check targets sentences and words - text a reader reads.
"""

import ast
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

UI_ROOT = REPOSITORY_ROOT / "apps" / "web"

# Streamlit calls whose first positional argument is text a user reads.
USER_FACING_CALLS = {
    "title", "header", "subheader", "caption",
    "button", "download_button", "form_submit_button",
    "checkbox", "radio", "selectbox", "multiselect",
    "text_input", "text_area", "number_input", "date_input",
    "file_uploader", "expander", "metric",
    "info", "warning", "error", "success", "spinner", "toast",
}

# Components build markup; the words inside come from callers that did
# translate. Excluded wholesale rather than case by case, because every
# literal in them is structural.
EXEMPT_DIRECTORIES = {"components"}

# Literals that are not copy: icons, separators, punctuation. A string
# qualifies as copy only if it contains at least two consecutive letters,
# which "🗑", "—" and "·" do not.
MINIMUM_WORD_LENGTH = 2


def _python_sources():

    for path in sorted(UI_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if EXEMPT_DIRECTORIES & set(path.parts):
            continue
        yield path


def _looks_like_copy(text):
    """True if a human would read this as words rather than decoration."""

    stripped = text.strip()

    if len(stripped) < MINIMUM_WORD_LENGTH:
        return False

    letters = 0
    for character in stripped:
        if character.isalpha():
            letters += 1
            if letters >= MINIMUM_WORD_LENGTH:
                return True
        else:
            letters = 0

    return False


def _hardcoded_strings():

    findings = []

    for path in _python_sources():

        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):

            if not isinstance(node, ast.Call):
                continue

            if getattr(node.func, "attr", None) not in USER_FACING_CALLS:
                continue

            if not node.args:
                continue

            first = node.args[0]

            if not (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
            ):
                continue

            if not _looks_like_copy(first.value):
                continue

            findings.append(
                f"  {path.relative_to(REPOSITORY_ROOT)}:{node.lineno}  "
                f"st.{node.func.attr}({first.value!r})"
            )

    return findings


def test_no_hardcoded_user_facing_text():

    findings = _hardcoded_strings()

    assert not findings, (
        f"{len(findings)} user-facing string(s) bypass t(). They will stay "
        f"English in every language, and there is no key for a translator "
        f"to fill:\n" + "\n".join(findings)
    )


@pytest.mark.parametrize(
    "text,is_copy",
    [
        ("Generating email...", True),
        ("↩ Load", True),
        ("Save", True),
        ("🗑", False),
        ("—", False),
        ("·", False),
        ("", False),
        ("  ", False),
        ("{}", False),
    ],
)
def test_copy_detection(text, is_copy):
    """
    Pins where the line sits, so the rule stays reviewable rather than
    becoming folklore about what the checker happens to accept.
    """

    assert _looks_like_copy(text) is is_copy
