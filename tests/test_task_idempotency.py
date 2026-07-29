"""
Regression tests for the P0 duplicate-task defect.

These run against the real PostgreSQL instance the rest of the suite uses
(see tests/project_audit/test_database_audit.py::test_database_connection).
That is deliberate: the guarantee under test is a database guarantee - a
partial UNIQUE index plus INSERT ... ON CONFLICT - so a mocked database
would prove nothing. Every test cleans up the case it creates.
"""

import threading

import pytest

from db import database
from db.database import (
    add_task,
    get_tasks,
    update_task,
    delete_tasks_for_case,
    get_db_connection,
)


CASE_TITLE = "Request missing document: Commune Registration Form"


@pytest.fixture
def case_id():
    """A throwaway case to hang tasks off, removed afterwards."""

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cases (employee_name, status) VALUES (%s, %s) RETURNING id",
            ("Idempotency Test Subject", "OPEN"),
        )
        new_case_id = c.fetchone()[0]

    yield new_case_id

    delete_tasks_for_case(new_case_id)

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM cases WHERE id=%s", (new_case_id,))


def _active_titles(case_id):
    return [row[2] for row in get_tasks(case_id) if row[3] != "DONE"]


def test_repeated_add_task_creates_exactly_one_task(case_id):
    """The core defect: an operator re-run must not stack up duplicates."""

    first = add_task(case_id, CASE_TITLE)
    second = add_task(case_id, CASE_TITLE)
    third = add_task(case_id, CASE_TITLE)

    assert first.created is True
    assert second.created is False
    assert third.created is False

    assert first.task_id == second.task_id == third.task_id
    assert _active_titles(case_id) == [CASE_TITLE]


def test_title_normalisation_collapses_equivalent_titles(case_id):
    """Casing and whitespace differences are the same business fact."""

    original = add_task(case_id, "Collect Passport Copy")
    variant = add_task(case_id, "  collect   PASSPORT copy ")

    assert variant.created is False
    assert variant.task_id == original.task_id

    # The stored spelling is the one that was inserted first - the index
    # folds the key only, it does not rewrite the row.
    assert _active_titles(case_id) == ["Collect Passport Copy"]


def test_distinct_titles_still_create_distinct_tasks(case_id):
    """Idempotency must not swallow genuinely different work items."""

    first = add_task(case_id, "Collect Passport Copy")
    second = add_task(case_id, "Collect Employment Contract")

    assert second.created is True
    assert second.task_id != first.task_id
    assert len(_active_titles(case_id)) == 2


def test_completed_task_can_be_raised_again(case_id):
    """
    The index is partial on purpose: once a task is DONE the same task may
    legitimately be needed again (document expired, rejected, superseded).
    """

    first = add_task(case_id, CASE_TITLE)
    update_task(first.task_id, "DONE")

    reopened = add_task(case_id, CASE_TITLE)

    assert reopened.created is True
    assert reopened.task_id != first.task_id
    assert _active_titles(case_id) == [CASE_TITLE]


def test_add_task_does_not_mutate_an_existing_task(case_id):
    """Requirement 6: reuse must leave status, due date and title alone."""

    first = add_task(case_id, CASE_TITLE)
    database.set_task_due_date(first.task_id, "2030-01-01")

    before = [row for row in get_tasks(case_id) if row[0] == first.task_id][0]

    add_task(case_id, CASE_TITLE.upper())

    after = [row for row in get_tasks(case_id) if row[0] == first.task_id][0]

    assert before == after


def test_concurrent_add_task_is_race_free(case_id):
    """
    The regression an application-side "check then insert" cannot survive:
    several AI Operator runs hitting the same case at the same moment. Each
    thread uses its own pooled connection and therefore its own transaction.
    """

    thread_count = 8
    barrier = threading.Barrier(thread_count)
    results = []
    errors = []

    def worker():
        try:
            barrier.wait(timeout=10)
            results.append(add_task(case_id, CASE_TITLE))
        except Exception as exc:  # pragma: no cover - failure diagnostics
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert not errors, f"add_task raised under concurrency: {errors}"
    assert len(results) == thread_count

    assert sum(1 for r in results if r.created) == 1
    assert len({r.task_id for r in results}) == 1
    assert _active_titles(case_id) == [CASE_TITLE]


def test_unique_index_exists_and_is_partial():
    """
    Guards the guarantee itself: if the migration is ever dropped or the
    predicate silently changed, this fails rather than duplicates
    reappearing in production.
    """

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename='tasks' AND indexname='uq_tasks_active_case_title'"
        )
        row = c.fetchone()

    assert row is not None, "uq_tasks_active_case_title is missing"

    indexdef = row[0]

    assert "UNIQUE" in indexdef
    assert "case_id" in indexdef
    assert "WHERE" in indexdef and "DONE" in indexdef
