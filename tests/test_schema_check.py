"""
Tests for the startup schema check.

Migration 0003 added three columns; the code that writes them was
deployed without the migration being run. Nothing detected it until a
user completed the case form and pressed Create, at which point the
browser showed::

    psycopg2.errors.UndefinedColumn: column "arrival_date" of relation
    "cases" does not exist

Worst moment, worst message: the work was lost, the cause was invisible
to the person affected, and the error disclosed internal table names and
file paths.

The gap was knowable when the process started. These tests cover the two
properties that make the check worth having:

* it reports every missing piece at once, with the migration that
  supplies it and the command to run;
* it never raises, because a check that can crash the application it
  protects is worse than no check at all.
"""

from unittest.mock import patch

import pytest

from db.schema_check import (
    REQUIRED_COLUMNS,
    REQUIRED_TABLES,
    SchemaProblem,
    describe_problems,
    find_schema_problems,
)


# ------------------------------------------------------- the report ---

def test_no_problems_produces_no_message():
    """Silence when the database is current; nothing to act on."""

    assert describe_problems([]) == ""


def test_the_message_names_every_missing_piece():

    problems = [
        SchemaProblem("column", "cases.arrival_date", "0003_case_statutory_dates"),
        SchemaProblem("table", "tenant_value_assumptions", "0002_tenant_value_assumptions"),
    ]

    message = describe_problems(problems)

    assert "cases.arrival_date" in message
    assert "tenant_value_assumptions" in message


def test_the_message_names_the_migration_that_supplies_it():
    """
    Without this, an operator knows something is missing but not which
    change introduces it - which matters when several are outstanding.
    """

    message = describe_problems([
        SchemaProblem("column", "cases.arrival_date", "0003_case_statutory_dates")
    ])

    assert "0003_case_statutory_dates" in message


def test_the_message_includes_the_command_to_run():
    """
    Whoever sees this needs to act immediately. Looking the command up
    elsewhere is friction at exactly the wrong moment.
    """

    message = describe_problems([
        SchemaProblem("column", "cases.arrival_date", "0003_case_statutory_dates")
    ])

    assert "scripts.migrate" in message


def test_the_message_tells_them_to_back_up_first():
    """
    A migration is the moment before which a backup is cheap and after
    which it is not.
    """

    message = describe_problems([
        SchemaProblem("column", "cases.arrival_date", "0003_case_statutory_dates")
    ])

    assert "pg_dump" in message


def test_each_migration_is_listed_once_however_many_columns_it_adds():
    """
    Migration 0003 adds three columns. An operator needs to run one
    command, so the summary says one migration.
    """

    problems = [
        SchemaProblem("column", f"cases.{name}", "0003_case_statutory_dates")
        for name in ("arrival_date", "contract_start_date", "permit_expiry_date")
    ]

    summary_line = next(
        line for line in describe_problems(problems).splitlines()
        if line.startswith("Pending migration")
    )

    assert summary_line.count("0003_case_statutory_dates") == 1


# ------------------------------------------------------ robustness ---

def test_an_unreachable_database_reports_nothing_rather_than_raising():
    """
    The property that keeps this safe to run at startup.

    If the database is unreachable that is a different failure, and the
    ordinary connection error describes it better than anything this
    could invent. What must not happen is the check itself taking down
    the application it exists to protect.
    """

    with patch(
        "db.database.get_db_connection",
        side_effect=RuntimeError("connection refused"),
    ):
        assert find_schema_problems() == []


# --------------------------------------------------- the manifest ---

def test_every_required_column_names_a_real_migration_file():
    """
    The manifest is hand-maintained. A typo in a migration name would
    send an operator looking for a file that does not exist, at the exact
    moment they are under pressure.
    """

    from pathlib import Path

    migrations_dir = (
        Path(__file__).resolve().parents[1] / "db" / "migrations"
    )

    referenced = {
        migration
        for columns in REQUIRED_COLUMNS.values()
        for migration in columns.values()
    } | set(REQUIRED_TABLES.values())

    for migration in sorted(referenced):
        assert (migrations_dir / f"{migration}.up.sql").is_file(), (
            f"REQUIRED_* refers to migration '{migration}', but "
            f"db/migrations/{migration}.up.sql does not exist."
        )


def test_the_columns_the_code_writes_are_all_declared():
    """
    Keeps the manifest honest about the case table specifically.

    db.database.case_statutory_dates() reads these three by position; if
    one were dropped from the manifest, a deployment missing it would
    once again fail at form-submission time instead of at startup.
    """

    assert set(REQUIRED_COLUMNS["cases"]) == {
        "arrival_date",
        "contract_start_date",
        "permit_expiry_date",
    }
