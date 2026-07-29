"""
Guards the separation between the test database and the live one.

Several tests in this suite write for real: they create cases, tasks,
documents and audit events. Before conftest.py redirected PGDATABASE,
those writes went into the database the application serves. It had
already happened - the live database contained case_events referencing
cases 25, 31, 37, 42, 43 and 49, none of which exist in the cases table,
left behind by earlier test runs.

For a product whose selling points include an audit trail, that is not a
tidiness problem. An audit log stops being evidence the moment anything
other than real activity can appear in it, and "our test suite writes
into it" is not an answer that survives a compliance review.

The redirection is one assignment in conftest.py and would be easy to
undo by accident - by reinstating DATABASE_URL, for instance, which takes
precedence over the PG* variables. These tests fail loudly if that
happens, rather than letting a suite quietly resume writing to live data.
"""

import os

import pytest

from conftest import APPLICATION_DATABASE, TEST_DATABASE


def test_the_suite_is_not_pointed_at_the_application_database():
    """The property this whole file exists for."""

    assert os.environ["PGDATABASE"] == TEST_DATABASE

    assert TEST_DATABASE != APPLICATION_DATABASE, (
        f"The test database and the application database are both "
        f"'{TEST_DATABASE}'. Tests in this suite create cases and audit "
        f"events for real; they must not run against live data."
    )


def test_database_url_does_not_override_the_redirection():
    """
    db.database._build_pool() prefers DATABASE_URL over the PG*
    variables. If something reinstates it mid-session, every subsequent
    connection would go to whatever it names - most likely the
    application database - and the redirection above would be silently
    void.
    """

    assert "DATABASE_URL" not in os.environ, (
        "DATABASE_URL is set during the test session. It takes precedence "
        "over PGDATABASE, so the suite may be connected to the "
        "application database despite the redirection in conftest.py."
    )


def test_the_connection_pool_actually_uses_the_test_database():
    """
    Asserts against the live connection rather than the environment.

    The environment is only an instruction; the pool is built once, on
    first use, and what matters is which database it actually opened. A
    module that connected before conftest set PGDATABASE would pass the
    checks above and still be writing to the wrong place.
    """

    from db.database import get_db_connection

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            connected_to = cursor.fetchone()[0]

    assert connected_to == TEST_DATABASE, (
        f"The connection pool is attached to '{connected_to}', not the "
        f"test database '{TEST_DATABASE}'. Something imported and "
        f"connected before conftest.py redirected PGDATABASE."
    )


def test_writes_are_visible_only_in_the_test_database():
    """
    End-to-end proof, rather than an argument from configuration: write a
    row, confirm it lands in the test database, and confirm the
    application database does not have it.

    Skipped when the application database is unreachable - a developer
    with only a test database should not see a failure here.
    """

    import psycopg2

    from db.database import add_case, delete_case

    marker = "isolation-check-please-delete"

    case_id = add_case(
        employee_name=marker,
        nationality="EU",
        canton="VAUD",
        permit="B",
        business_mode="SME",
        employer=marker,
        company="Isolation Test Company",
        risk_level=0,
        ai_summary="",
        assigned_to="pytest",
    )

    try:
        try:
            application_connection = psycopg2.connect(
                host=os.environ.get("PGHOST", "localhost"),
                port=os.environ.get("PGPORT", "5432"),
                dbname=APPLICATION_DATABASE,
                user=os.environ.get("PGUSER", "mobilityflow"),
                password=os.environ.get("PGPASSWORD", "mobilityflow"),
            )
        except psycopg2.OperationalError:
            pytest.skip(
                f"Application database '{APPLICATION_DATABASE}' is not "
                f"reachable; cannot compare against it."
            )

        try:
            with application_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM cases WHERE employee_name = %s",
                    (marker,),
                )
                leaked = cursor.fetchone()[0]
        finally:
            application_connection.close()

        assert leaked == 0, (
            f"A row written by the test suite appeared in the application "
            f"database '{APPLICATION_DATABASE}'. Test data is reaching "
            f"live data."
        )

    finally:
        delete_case(case_id)
