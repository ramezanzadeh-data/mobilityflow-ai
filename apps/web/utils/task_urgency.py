"""
Groups pending tasks by urgency for display.

Pure functions, no Streamlit and no database: given the rows that
``db.database.get_pending_tasks_for_company()`` already returns, decide
what order to show them in. Nothing here changes a task, a status or a due
date - "overdue" is a statement about today's date, not a state stored
anywhere, and no workflow rule depends on it.

Why this exists: the task inbox printed every pending task as one flat
line in whatever order the query returned. With two cases that was thirty
lines; the operator had no way to see that one task was overdue and
twenty-nine were not. Sorting by urgency is the difference between a list
and a work queue.
"""

from datetime import date, datetime


OVERDUE = "overdue"
DUE_TODAY = "due_today"
DUE_THIS_WEEK = "due_this_week"
LATER = "later"
NO_DUE_DATE = "no_due_date"

# Most urgent first. Undated tasks sit last: they are real work, but
# nothing about them is time-critical, so they must never push a genuinely
# late task down the screen.
URGENCY_ORDER = [OVERDUE, DUE_TODAY, DUE_THIS_WEEK, LATER, NO_DUE_DATE]

# Bucket -> badge level from components/theme.py.
URGENCY_LEVELS = {
    OVERDUE: "danger",
    DUE_TODAY: "warning",
    DUE_THIS_WEEK: "info",
    LATER: "neutral",
    NO_DUE_DATE: "neutral",
}

DUE_THIS_WEEK_DAYS = 7


def parse_due_date(value):
    """
    Return a ``date`` for an ISO-8601 due date, or None.

    Due dates are stored as TEXT, so a malformed or empty value is
    possible and must not raise: a single bad row cannot be allowed to
    take down the whole inbox.
    """

    if not value:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def classify_urgency(due_date, today):
    """
    Bucket a single due date.

    Args:
        due_date: Parsed date, or None.
        today: Reference date, passed in rather than read from the clock
            so the behaviour is testable and so every row in one render
            is classified against the same day - a render that straddles
            midnight must not sort itself inconsistently.
    """

    if due_date is None:
        return NO_DUE_DATE

    if due_date < today:
        return OVERDUE

    if due_date == today:
        return DUE_TODAY

    if (due_date - today).days <= DUE_THIS_WEEK_DAYS:
        return DUE_THIS_WEEK

    return LATER


def group_tasks_by_urgency(tasks, today):
    """
    Group pending-task rows into ordered urgency buckets.

    Args:
        tasks: Rows as returned by get_pending_tasks_for_company():
            ``(task_id, case_id, title, status, due_date, employee_name)``.
        today: Reference date.

    Returns:
        List of ``(bucket, [(due_date, employee_name, title), ...])`` in
        URGENCY_ORDER, omitting empty buckets. Within a bucket, dated
        tasks are ordered soonest first, then by employee, then by title -
        a total order, so the list does not reshuffle between renders.
    """

    buckets = {name: [] for name in URGENCY_ORDER}

    for row in tasks:
        _, _, title, _, raw_due_date, employee_name = row

        due_date = parse_due_date(raw_due_date)

        buckets[classify_urgency(due_date, today)].append(
            (due_date, employee_name, title)
        )

    ordered = []

    for name in URGENCY_ORDER:
        entries = buckets[name]

        if not entries:
            continue

        entries.sort(
            key=lambda item: (
                item[0] or date.max,
                str(item[1] or ""),
                str(item[2] or ""),
            )
        )

        ordered.append((name, entries))

    return ordered
