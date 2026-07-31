"""
A case with missing documents must not be waved through.

Seen on a printed case page: four of five required documents MISSING,
and a blue primary "Advance to Review" button that worked. The product
recorded the problem in one panel and ignored it in the control directly
above.

That is the defect this whole product exists to prevent. Work may not
begin before an authorisation exists (Art. 11 AIG), and a firm buying a
relocation compliance system is buying the thing that stops a file moving
before it is ready. A checklist that says "missing" and a button that
advances anyway are two features that disagree, and the user believes the
button - it is the one that did something.

Structural tests, not behavioural: the case page is a Streamlit script
that cannot be executed headlessly here, so what is asserted is that the
button's disabled state is derived from the document rows, and that the
override path survives. If this file ever needs relaxing, the question to
ask first is what a customer would say about the case that advanced.
"""

import ast
from pathlib import Path

import pytest


SOURCE = (
    Path(__file__).resolve().parent.parent
    / "apps" / "web" / "views" / "case_detail.py"
).read_text(encoding="utf-8")


def _advance_button():
    """The st.button call that advances the workflow stage."""

    tree = ast.parse(SOURCE)

    for node in ast.walk(tree):

        if not isinstance(node, ast.Call):
            continue

        for keyword in node.keywords:

            if (
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "advance_stage_btn"
            ):
                return node

    pytest.fail("the advance button no longer exists")


def test_the_advance_button_is_disabled_by_something():
    """
    The defect, directly. It had no disabled argument at all, so no
    state of the case could stop it.
    """

    keywords = {keyword.arg for keyword in _advance_button().keywords}

    assert "disabled" in keywords, (
        "the advance button has no disabled condition, so a case with "
        "every document missing advances on one click"
    )


def test_what_disables_it_is_the_documents_and_not_a_constant():
    """
    Guards against disabled=False, which satisfies the check above and
    changes nothing.
    """

    disabled = next(
        keyword.value for keyword in _advance_button().keywords
        if keyword.arg == "disabled"
    )

    assert not isinstance(disabled, ast.Constant), (
        "the disabled state is a literal, so it never reflects the case"
    )

    assert "blocking_documents" in ast.unparse(disabled)


def test_the_blocking_list_is_built_from_upload_status():
    """
    A document row exists whether or not anything was uploaded - the
    checklist creates it. Only the status distinguishes a requirement
    that has been met from one that has not, and counting rows instead
    would report every case as complete.
    """

    assert 'document[3] != "UPLOADED"' in SOURCE, (
        "blocking_documents does not test upload status, so a checklist "
        "row counts as evidence"
    )


def test_the_user_is_told_which_document_is_missing():
    """
    A disabled button with no explanation is indistinguishable from a
    broken page, and the user's next action is to reload rather than to
    upload.
    """

    assert "advance_blocked_note" in SOURCE

    button = _advance_button()

    note_position = SOURCE.index("advance_blocked_note")

    assert note_position < button.lineno * 0 + SOURCE.index("advance_stage_btn"), (
        "the explanation renders after the button it explains"
    )


def test_the_override_path_still_exists():
    """
    Blocking must not become a wall.

    A consultant sometimes knows something the checklist does not - a
    document accepted by the authority in another form, an exemption.
    Manual stage override records a reason, so the decision is
    attributable rather than absent. Removing it would push users to
    falsify document statuses instead, which is worse: the record would
    then be wrong rather than merely overridden.
    """

    assert "apply_override_btn" in SOURCE
    assert "override_reason" in SOURCE


def test_the_override_is_not_disabled_by_the_same_condition():
    """
    The override is the escape hatch. Gating it on the thing it exists
    to escape would make it decorative.
    """

    tree = ast.parse(SOURCE)

    for node in ast.walk(tree):

        if not isinstance(node, ast.Call):
            continue

        for keyword in node.keywords:

            if (
                keyword.arg == "key"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "apply_override_btn"
            ):
                disabled = [
                    other for other in node.keywords if other.arg == "disabled"
                ]

                assert not disabled or "blocking_documents" not in ast.unparse(
                    disabled[0].value
                ), "the override is blocked by the condition it exists to override"


def test_the_document_status_control_has_room_to_show_its_value():
    """
    The status column was 1/6 of the row - about 90px - so the selectbox
    rendered "MISSIN" and "UPLOA". The one word on the row that carries
    the information was the one that did not fit.
    """

    assert "name_col, status_col = st.columns([3, 2])" in SOURCE, (
        "the status column is back to a width that truncates its own values"
    )


def test_the_uploaded_count_is_not_the_largest_thing_on_the_panel():
    """
    st.metric renders at display size. "1/5" was larger than the document
    names it summarised - a caption set as a headline.
    """

    documents_section = SOURCE[SOURCE.index("with documents_tab:"):]
    documents_section = documents_section[:documents_section.index("uploaded_metric") + 200]

    assert "st.progress(" in documents_section
    assert "st.metric(\n                        t(\"uploaded_metric\")" not in SOURCE
