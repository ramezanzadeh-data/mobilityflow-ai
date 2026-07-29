"""
Root-level pytest conftest.

Three things happen here, in a deliberate order.

1. Load the repository's ``.env`` through bootstrap.load_environment - the
   same call every other entry point makes. Loading it here rather than
   in the test suite specifically is what keeps pytest and
   ``python -m scripts.migrate`` pointed at the same *server*; see
   bootstrap/environment.py for the failure this prevents.

   pytest imports this file before collecting any test module, so the
   load happens before any `import db.database` / `import auth...`
   anywhere in the suite - which matters, because those modules read
   configuration at import time.

2. Redirect the suite to a dedicated database on that server. Several
   tests create cases, tasks and audit events for real; without this they
   write into whatever database the application is using. On this project
   that had already happened - the live database contained case_events
   referencing cases 25, 31, 37, 42, 43 and 49, none of which exist,
   left behind by test runs.

   For a product sold on the strength of its audit trail, a test suite
   that writes into customer data is not defensible: the audit log stops
   being evidence the moment anything other than real activity can appear
   in it.

3. Provide test-only fallbacks for the two secrets that auth/jwt.py and
   auth/encryption.py refuse to import without (a randomly-generated
   per-process fallback silently breaks auth and data decryption across
   restarts and multi-worker deployments). ``setdefault`` means these
   apply only when neither the real environment nor ``.env`` supplied a
   value, preserving the precedence documented in bootstrap/environment.py.

   These are test-only values. Never reuse them outside of tests.
"""

import os

from bootstrap import load_environment

load_environment()


# ---------------------------------------------------------------------
# 2. Test database isolation
# ---------------------------------------------------------------------
#
# Applied by overwriting PGDATABASE *before* db.database is imported: that
# module builds its connection pool from the environment on first use, so
# once it has connected the choice can no longer be changed.
#
# The name is derived from the configured database rather than hardcoded,
# so a developer pointing .env at a different database still gets that
# database's own test twin instead of a shared one.
#
# MOBILITYFLOW_TEST_DATABASE overrides it, for a CI runner that wants an
# explicit name.

APPLICATION_DATABASE = os.environ.get("PGDATABASE", "mobilityflow")

TEST_DATABASE = os.environ.get(
    "MOBILITYFLOW_TEST_DATABASE",
    f"{APPLICATION_DATABASE}_test",
)

os.environ["PGDATABASE"] = TEST_DATABASE

# DATABASE_URL takes precedence over the PG* variables in
# db.database._build_pool(), so leaving it set would silently defeat the
# redirection above and send the suite straight back at the application
# database. Removed rather than rewritten: parsing and re-emitting a DSN
# to swap one component is a source of subtle breakage, and the PG*
# variables are sufficient here.
_DATABASE_URL = os.environ.pop("DATABASE_URL", None)


def pytest_report_header(config):
    """
    State which database the suite is using, on every run.

    Silent redirection is its own hazard: someone debugging a failure
    needs to know immediately that the data they are inspecting in the
    application is not the data the test just used.
    """

    lines = [
        f"database: {TEST_DATABASE} "
        f"(isolated; application database is {APPLICATION_DATABASE!r})"
    ]

    if _DATABASE_URL:
        lines.append(
            "DATABASE_URL was set and has been ignored for this run - "
            "the PG* variables select the test database instead."
        )

    return lines


# ---------------------------------------------------------------------
# 3. Test-only secrets
# ---------------------------------------------------------------------

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-secret-key-do-not-use-in-production-1234567890",
)

os.environ.setdefault(
    "ENCRYPTION_KEY",
    # A valid, fixed Fernet key reserved for tests only.
    "DpzHVAf8GUh5obKUI1pqjRhwv9io37RSsETHVdcrUcc=",
)


# ---------------------------------------------------------------------
# Test database lifecycle
# ---------------------------------------------------------------------

import pytest  # noqa: E402  (must follow the environment setup above)


# Connected to in order to issue CREATE DATABASE, which cannot run from
# inside the database being created.
_MAINTENANCE_DATABASE = "postgres"


def _connect_to_maintenance_database():

    import psycopg2

    connection = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=_MAINTENANCE_DATABASE,
        user=os.environ.get("PGUSER", "mobilityflow"),
        password=os.environ.get("PGPASSWORD", "mobilityflow"),
    )

    # CREATE DATABASE cannot run inside a transaction block.
    connection.autocommit = True

    return connection


# Set once, by the session fixture below. Most of this suite is pure
# logic - validators, i18n, risk rules, urgency grouping - and must stay
# runnable on a laptop with no database running. Only the tests that
# genuinely touch Postgres are skipped when it is unavailable.
_DATABASE_ERROR = None

# A test module is treated as needing the database if its source mentions
# one of these. Cruder than a marker on every test, but it cannot fall out
# of date: a module that starts using the database starts being skipped
# correctly without anyone remembering to annotate it.
#
# The cost of that crudeness is over-matching, and it has already bitten
# once. "core.reporting.value import" was listed here and matched
# tests/test_value_report.py on its import line - but core/reporting/value.py
# holds no database reference at all; it is a pure function of its inputs
# by design. The result was 25 tests silently not running on any machine
# without Postgres, and those 25 are the ones pinning the honesty of the
# figures in a document the customer shows their CFO.
#
# So a marker belongs here only if the module it names actually opens a
# connection. Before adding one, check:
#
#     python -m pytest <the test file> --noconftest
#
# If it passes with no database, it does not belong in this list.
#
# "core.case.service" was also listed and matched nothing at all.
_DATABASE_MARKERS = (
    "db.database",
    "get_db_connection",
)


def _prepare_test_database():
    """
    Create the test database if missing and bring its schema up to date.

    Returns None on success, or a human-readable reason on failure.
    Returning rather than raising is deliberate: an unavailable database
    must not stop the pure tests from running.
    """

    import psycopg2

    try:
        connection = _connect_to_maintenance_database()
    except psycopg2.OperationalError as error:
        return (
            f"cannot reach PostgreSQL at "
            f"{os.environ.get('PGHOST', 'localhost')}:"
            f"{os.environ.get('PGPORT', '5432')} - {str(error).strip()}"
        )

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (TEST_DATABASE,),
            )

            if not cursor.fetchone():
                # An identifier cannot be parameterised. TEST_DATABASE
                # comes from configuration, not user input, and
                # sql.Identifier quotes it correctly regardless.
                from psycopg2 import sql

                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(TEST_DATABASE)
                    )
                )

    except psycopg2.Error as error:
        return f"could not create '{TEST_DATABASE}' - {str(error).strip()}"

    finally:
        connection.close()

    try:
        # Imported here, not at module scope, so PGDATABASE already points
        # at the test database when the connection pool is built.
        from db.database import init_db

        init_db()

    except Exception as error:  # noqa: BLE001 - reported, not swallowed
        return f"schema setup failed on '{TEST_DATABASE}' - {str(error).strip()}"

    return None


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """
    Prepare the test database once per session.

    Deliberately not dropped afterwards: a failed run is far easier to
    diagnose when the rows it produced are still there, and the database
    is recreated from scratch on any machine that does not have it.
    """

    global _DATABASE_ERROR

    _DATABASE_ERROR = _prepare_test_database()

    yield TEST_DATABASE


def pytest_runtest_setup(item):
    """
    Skip database-backed tests when Postgres is unavailable.

    An earlier version aborted the whole session instead. That made the
    validator, i18n and risk-rule tests - none of which open a connection -
    unrunnable without Docker, which is the opposite of what a fast local
    suite should do.
    """

    if _DATABASE_ERROR is None:
        return

    source_file = getattr(item.module, "__file__", None)

    if not source_file:
        return

    try:
        source = open(source_file, encoding="utf-8").read()
    except OSError:
        return

    if any(marker in source for marker in _DATABASE_MARKERS):
        pytest.skip(f"database unavailable: {_DATABASE_ERROR}")
