"""
Guards the display numbering of conditionally-rendered steps.

The AI operator panel numbered its results with literals 1..9 while four
of those steps only render when the corresponding result is present. A run
that created no tasks therefore showed the user:

    1, 2, 3, 4, 6, 7, 8

A gap in a numbered report reads as "something is missing", which is an
expensive impression for a compliance product. StepNumbering removes the
possibility by only consuming a number when a step actually renders.

The first three tests cover the helper directly. The last one is the
regression test proper: it asserts the defective pattern has not returned
to the page, since a future edit could reintroduce a literal without any
behavioural test noticing.
"""

import re
from pathlib import Path

from apps.web.utils.ui import StepNumbering


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

CASE_DETAIL_PAGE = REPOSITORY_ROOT / "apps" / "web" / "views" / "case_detail.py"


def test_numbers_are_consecutive():

    step = StepNumbering()

    assert [step.next() for _ in range(4)] == ["1.", "2.", "3.", "4."]


def test_skipped_steps_leave_no_gap():
    """
    The actual defect: rendering only some steps must still produce a
    contiguous sequence, because a number is consumed on render, not on
    definition.
    """

    step = StepNumbering()

    rendered = []

    for should_render in [True, True, False, True, False, True]:
        if should_render:
            rendered.append(step.next())

    assert rendered == ["1.", "2.", "3.", "4."]


def test_peek_used_does_not_advance_the_sequence():

    step = StepNumbering()

    step.next()
    step.next()

    assert step.peek_used() == 2
    assert step.peek_used() == 2, "peek must not consume a number"
    assert step.next() == "3.", "peek must not disturb the sequence"


def test_case_detail_page_has_no_hardcoded_step_numbers():
    """
    Regression guard on the page itself.

    Matches the bold-literal form the defect used (`**5. `) inside an
    f-string. Numbers reached through StepNumbering are written as
    `{step.next()}` and are unaffected.
    """

    source = CASE_DETAIL_PAGE.read_text(encoding="utf-8")

    hardcoded = [
        f"  line {number}: {line.strip()}"
        for number, line in enumerate(source.splitlines(), start=1)
        if re.search(r"\*\*\d+\.", line)
    ]

    assert not hardcoded, (
        "Hardcoded step number(s) in the AI operator panel. Conditionally "
        "rendered steps must use StepNumbering, otherwise skipping one "
        "leaves a visible gap in the sequence:\n" + "\n".join(hardcoded)
    )
