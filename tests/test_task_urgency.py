"""
Tests for task-inbox urgency grouping.

The inbox printed every pending task as one flat line in query order, so
an overdue task looked identical to one due next month and could appear
anywhere in the list. Grouping by urgency is what turns the same rows into
a work queue.

The grouping is pure presentation - it reads today's date and the stored
due date, and changes nothing. These tests pin the two properties that
matter operationally:

* nothing is silently dropped (an inbox that hides work is worse than an
  unsorted one), and
* the ordering is total, so the list does not reshuffle between renders of
  the same data.
"""

from datetime import date

import pytest

from apps.web.utils.task_urgency import (
    DUE_THIS_WEEK,
    DUE_TODAY,
    LATER,
    NO_DUE_DATE,
    OVERDUE,
    URGENCY_LEVELS,
    URGENCY_ORDER,
    classify_urgency,
    group_tasks_by_urgency,
    parse_due_date,
)


TODAY = date(2026, 7, 28)


def task(title, due, employee="zohre"):
    """Row shaped like get_pending_tasks_for_company() returns."""

    return (1, 1, title, "PENDING", due, employee)


# ------------------------------------------------------------ parsing ---

@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-07-28", date(2026, 7, 28)),
        ("2026-07-28 14:30:00", date(2026, 7, 28)),
        ("  2026-07-28  ", date(2026, 7, 28)),
        (date(2026, 7, 28), date(2026, 7, 28)),
        (None, None),
        ("", None),
        ("not-a-date", None),
        ("2026-13-45", None),
    ],
)
def test_parse_due_date(value, expected):
    """
    Due dates are stored as TEXT, so malformed values are possible. One
    bad row must degrade to "no due date", never raise - otherwise a
    single corrupt record takes down the whole inbox.
    """

    assert parse_due_date(value) == expected


# ------------------------------------------------------- classifying ---

@pytest.mark.parametrize(
    "due,expected",
    [
        (date(2026, 7, 27), OVERDUE),
        (date(2020, 1, 1), OVERDUE),
        (date(2026, 7, 28), DUE_TODAY),
        (date(2026, 7, 29), DUE_THIS_WEEK),
        (date(2026, 8, 4), DUE_THIS_WEEK),      # exactly 7 days out
        (date(2026, 8, 5), LATER),              # 8 days out
        (None, NO_DUE_DATE),
    ],
)
def test_classify_urgency(due, expected):
    assert classify_urgency(due, TODAY) == expected


def test_every_bucket_has_a_badge_level():
    """A bucket without a level would render an unstyled badge."""

    assert set(URGENCY_LEVELS) == set(URGENCY_ORDER)


# ---------------------------------------------------------- grouping ---

def test_buckets_are_returned_most_urgent_first():

    groups = group_tasks_by_urgency(
        [
            task("later", "2026-09-01"),
            task("undated", None),
            task("overdue", "2026-07-01"),
            task("today", "2026-07-28"),
            task("this week", "2026-07-30"),
        ],
        TODAY,
    )

    assert [name for name, _ in groups] == [
        OVERDUE,
        DUE_TODAY,
        DUE_THIS_WEEK,
        LATER,
        NO_DUE_DATE,
    ]


def test_empty_buckets_are_omitted():

    groups = group_tasks_by_urgency([task("a", None)], TODAY)

    assert [name for name, _ in groups] == [NO_DUE_DATE]


def test_no_task_is_dropped():
    """
    The property that matters most: an inbox that silently hides work is
    worse than an unsorted one.
    """

    tasks = [
        task("a", "2026-07-01"),
        task("b", None),
        task("c", "2026-07-28"),
        task("d", "not-a-date"),
        task("e", "2026-12-31"),
    ]

    grouped = group_tasks_by_urgency(tasks, TODAY)

    titles = {title for _, entries in grouped for _, _, title in entries}

    assert titles == {"a", "b", "c", "d", "e"}


def test_unparseable_due_date_is_treated_as_undated_not_overdue():
    """
    Failing "safe" matters here: a corrupt date rendered as Overdue would
    send someone chasing a deadline that does not exist.
    """

    groups = dict(group_tasks_by_urgency([task("x", "garbage")], TODAY))

    assert NO_DUE_DATE in groups
    assert OVERDUE not in groups


def test_within_a_bucket_soonest_is_first():

    groups = dict(
        group_tasks_by_urgency(
            [
                task("three days ago", "2026-07-25"),
                task("long overdue", "2026-01-01"),
                task("yesterday", "2026-07-27"),
            ],
            TODAY,
        )
    )

    # Oldest deadline first: the longest-overdue task is the most urgent.
    assert [title for _, _, title in groups[OVERDUE]] == [
        "long overdue",
        "three days ago",
        "yesterday",
    ]


def test_ordering_is_total_so_the_list_does_not_reshuffle():
    """
    Same due date and same employee must still order deterministically,
    otherwise the inbox appears to shuffle itself on every rerun - and
    Streamlit reruns on every interaction.
    """

    rows = [
        task("bbb", "2026-07-30", "anna"),
        task("aaa", "2026-07-30", "anna"),
        task("ccc", "2026-07-30", "anna"),
    ]

    first = group_tasks_by_urgency(rows, TODAY)
    second = group_tasks_by_urgency(list(reversed(rows)), TODAY)

    assert first == second
    assert [title for _, _, title in first[0][1]] == ["aaa", "bbb", "ccc"]


def test_undated_tasks_never_outrank_dated_ones():
    """
    Undated work is real, but nothing about it is time-critical. It must
    not push a genuinely late task down the screen.
    """

    groups = group_tasks_by_urgency(
        [task("undated", None), task("overdue", "2026-01-01")],
        TODAY,
    )

    assert groups[0][0] == OVERDUE
    assert groups[-1][0] == NO_DUE_DATE
