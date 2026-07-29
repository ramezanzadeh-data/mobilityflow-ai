"""
Guards the information architecture of the Case Detail screen.

The page previously stacked nine expanders on top of each other, so one
case printed to eight pages and every section had to be scrolled past to
reach any other. It is now five tabs, with the summary and workflow
permanently visible above them.

Layout is not covered by any behavioural test, so nothing else in the
suite would notice the old shape coming back one section at a time. These
tests assert the structure directly, from the source.

They deliberately check *shape*, not appearance: how many top-level
sections there are and how they are grouped. Colours and spacing belong in
components/theme.py and are reviewed by eye.
"""

import ast
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

CASE_DETAIL = REPOSITORY_ROOT / "apps" / "web" / "views" / "case_detail.py"

EXPECTED_TABS = [
    "tasks_tab_label",
    "documents_tab_label",
    "ai_tab_label",
    "communication_tab_label",
    "insights_tab_label",
]

# Above the tabs: identity, risk and workflow position stay on screen
# whichever tab is open. This is the whole point of the restructure.
ALWAYS_VISIBLE_CALLS = ["field_grid", "workflow_stepper"]


def _tree():
    return ast.parse(CASE_DETAIL.read_text(encoding="utf-8"))


def _show_case_detail():
    return next(
        node
        for node in _tree().body
        if isinstance(node, ast.FunctionDef) and node.name == "show_case_detail"
    )


def _string_constants(node):
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_page_is_organised_into_the_expected_tabs():

    function = _show_case_detail()

    tab_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "tabs"
    ]

    top_level = [
        call
        for call in tab_calls
        if set(EXPECTED_TABS) & set(_string_constants(call))
    ]

    assert len(top_level) == 1, (
        "Expected exactly one top-level st.tabs() on the Case Detail page, "
        f"found {len(top_level)}."
    )

    assert _string_constants(top_level[0]) == EXPECTED_TABS, (
        "Case Detail tabs changed. Update EXPECTED_TABS here if the change "
        "is intended - this test exists so a regrouping is a deliberate, "
        "reviewed decision rather than a side effect."
    )


def test_no_top_level_expanders_remain():
    """
    The defect itself: sections stacked directly on the page.

    Expanders nested *inside* a tab are fine - the Insights tab groups
    four unrelated sections and an accordion is the right control there.
    What must not come back is a section hanging off the function body,
    outside any tab.
    """

    function = _show_case_detail()

    offenders = []

    for node in function.body:
        if not isinstance(node, ast.With):
            continue

        for item in node.items:
            expression = item.context_expr

            # `with tasks_tab:` is a plain Name and has no .func at all -
            # only call expressions such as `st.expander(...)` do.
            if not isinstance(expression, ast.Call):
                continue

            if getattr(expression.func, "attr", None) == "expander":
                keys = _string_constants(expression)
                offenders.append(f"  line {node.lineno}: {keys}")

    assert not offenders, (
        "Section added directly to the Case Detail page instead of inside a "
        "tab. Nine of these made the page an eight-page scroll:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("call_name", ALWAYS_VISIBLE_CALLS)
def test_summary_stays_outside_the_tabs(call_name):
    """
    The case summary and workflow position must render before the tabs,
    so they are visible regardless of which tab is open. If either drifts
    inside a tab, the operator loses the case context on four screens out
    of five.
    """

    function = _show_case_detail()

    tabs_line = min(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "tabs"
        and set(EXPECTED_TABS) & set(_string_constants(node))
    )

    call_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == call_name
    ]

    assert call_lines, f"{call_name}() is no longer called on the page"

    assert min(call_lines) < tabs_line, (
        f"{call_name}() now renders inside the tabs (line {min(call_lines)} "
        f"vs tabs at {tabs_line}). It must stay above them so the case "
        f"context is visible on every tab."
    )


@pytest.mark.parametrize("name", ["current_user", "logged_in_user", "case_id"])
def test_shared_context_is_assigned_before_the_tabs(name):
    """
    Values used by more than one tab must be assigned above them.

    This is a real regression, not a hypothetical. ``current_user`` was
    assigned part-way down the page, inside the Communication section,
    and read by the AI section. The two were coupled by nothing but
    source order, so grouping the page into tabs put the read above the
    write and every case page raised UnboundLocalError.

    Python does not catch this: the module imports cleanly and the
    function only fails when executed. Nothing in a behavioural test
    suite covers it either, because no test renders the page. So the
    ordering is asserted from the source.
    """

    function = _show_case_detail()

    first_assignment = min(
        (
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id == name
        ),
        default=None,
    )

    assert first_assignment is not None, f"{name} is no longer assigned"

    tabs_line = min(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "tabs"
        and set(EXPECTED_TABS) & set(_string_constants(node))
    )

    assert first_assignment < tabs_line, (
        f"'{name}' is first assigned at line {first_assignment}, below the "
        f"tab block at line {tabs_line}. A tab that reads it will raise "
        f"UnboundLocalError depending on which tab is rendered first - "
        f"assign it above the tabs."
    )


def test_workflow_stepper_is_used_instead_of_per_stage_markdown():
    """
    The stepper replaced a loop that emitted one st.markdown per stage,
    wrapped in a <div> whose opening and closing tags were separate calls
    and therefore never wrapped anything. Reverting to that pattern would
    look fine in review and render badly.
    """

    tree = _tree()

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "workflow_stepper" in called

    # Checked against string literals rather than the raw file, so the
    # comment explaining why these classes were removed does not itself
    # trip the assertion.
    emitted_strings = " ".join(_string_constants(tree))

    for dead_class in ('class="workflow-card"', 'class="stage-item"'):
        assert dead_class not in emitted_strings, (
            f"{dead_class} is emitted again. That class was never defined "
            f"in any stylesheet, so the markup it decorated rendered "
            f"unstyled."
        )
