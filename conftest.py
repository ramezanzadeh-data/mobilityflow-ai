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

import ast
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


# Distinct from None, which is the answer "the database is fine". Without
# a separate sentinel the two are indistinguishable and the check would
# be repeated on every single test.
_NOT_YET_CHECKED = object()

# Set on first use by _database_error(). Most of this suite is pure
# logic - validators, i18n, risk rules, urgency grouping - and must stay
# runnable on a laptop with no database running. Only the tests that
# genuinely touch Postgres are skipped when it is unavailable.
_DATABASE_ERROR = _NOT_YET_CHECKED

# Which test modules need PostgreSQL, decided by reading their code.
#
# This was a substring search over the file's text, which is the obvious
# implementation and quietly wrong twice over:
#
#   * "core.reporting.value import" matched tests/test_value_report.py on
#     its import line, but core/reporting/value.py touches no database at
#     all. 25 pure tests stopped running on every machine without
#     Postgres - the 25 pinning the honesty of the figures in a document
#     the customer shows their CFO.
#
#   * "db.database" matched tests/project_audit/test_runtime_audit.py on
#     a *comment*, and every module that merely names the module in a
#     docstring. Prose disabled tests.
#
# A substring search cannot tell code from commentary, so this parses
# instead. Three things count as needing a real database, all of them
# executable code rather than text:
#
#   1. importing db.database, at module or function level;
#   2. a patch("db.database...") target - patching one function does not
#      stop the rest of the module opening a connection;
#   3. calling get_db_connection().
#
# Docstrings are excluded deliberately: they are string constants in the
# tree, and a module explaining the database is not a module using it.
#
# Erring towards under-matching is the right direction. A module wrongly
# treated as pure fails loudly with a connection error; one wrongly
# treated as database-backed disappears silently, which is how 25 tests
# went missing. CI is the backstop either way - it provides a database
# and fails on any skip at all.

_DATABASE_MODULE = "db.database"

_DATABASE_FUNCTION = "get_db_connection"

_PATCHING_CALLS = {"patch", "patch.object", "mock.patch"}


def _callable_name(node):
    """Dotted name of a call target: `patch`, `mock.patch`, `x.y.z`."""

    parts = []

    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value

    if isinstance(node, ast.Name):
        parts.append(node.id)

    return ".".join(reversed(parts))


def _docstring_nodes(tree):
    """
    Every string constant that is a docstring.

    Collected so they can be ignored: a docstring is documentation that
    happens to be a string literal, and treating it as code is what let
    prose switch tests off.
    """

    found = set()

    for node in ast.walk(tree):

        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue

        body = getattr(node, "body", None)

        if not body:
            continue

        first = body[0]

        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))

    return found


def _module_needs_the_database(source):
    """Whether this test module's *code* reaches PostgreSQL."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Not this hook's job to fail on a module that does not parse -
        # pytest will report that far more clearly during collection.
        return False

    docstrings = _docstring_nodes(tree)

    for node in ast.walk(tree):

        # 1. import db.database / from db.database import ...
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _DATABASE_MODULE:
                    return True

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""

            if module == _DATABASE_MODULE or module.startswith(
                _DATABASE_MODULE + "."
            ):
                return True

            # `from db import database`
            if module == "db" and any(
                alias.name == "database" for alias in node.names
            ):
                return True

        elif isinstance(node, ast.Call):

            name = _callable_name(node.func)

            # 3. get_db_connection(...) or database.get_db_connection(...)
            if name.split(".")[-1] == _DATABASE_FUNCTION:
                return True

            # 2. patch("db.database.something")
            if name in _PATCHING_CALLS:
                for argument in node.args:
                    if (
                        isinstance(argument, ast.Constant)
                        and isinstance(argument.value, str)
                        and id(argument) not in docstrings
                        and argument.value.startswith(_DATABASE_MODULE)
                    ):
                        return True

    return False


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


def _database_error():
    """
    The reason the test database is unusable, or None if it is fine.

    Prepared on first request and cached, rather than in the session
    fixture. pytest calls pytest_runtest_setup *before* setting up that
    test's fixtures, so with the work in the fixture the module global
    was still at its initial value when the first test of the session was
    examined - and that test alone was never skipped, whatever it needed.

    It showed up as "1 passed, 4 skipped" in a module whose five tests
    are identical in their requirements. Ordering-dependent skipping is
    the kind of defect that reads as a flaky test rather than a bug in
    the harness, so the ordering dependency is removed rather than
    documented.
    """

    global _DATABASE_ERROR

    if _DATABASE_ERROR is _NOT_YET_CHECKED:
        _DATABASE_ERROR = _prepare_test_database()

    return _DATABASE_ERROR


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """
    Prepare the test database once per session.

    Deliberately not dropped afterwards: a failed run is far easier to
    diagnose when the rows it produced are still there, and the database
    is recreated from scratch on any machine that does not have it.
    """

    _database_error()

    yield TEST_DATABASE


def pytest_runtest_setup(item):
    """
    Skip database-backed tests when Postgres is unavailable.

    An earlier version aborted the whole session instead. That made the
    validator, i18n and risk-rule tests - none of which open a connection -
    unrunnable without Docker, which is the opposite of what a fast local
    suite should do.

    In CI this branch should never be taken: the workflow provides a
    PostgreSQL service and then fails the build on any skipped test, so a
    database that cannot be prepared is a red build rather than a quiet
    one.
    """

    reason = _database_error()

    if reason is None:
        return

    source_file = getattr(item.module, "__file__", None)

    if not source_file:
        return

    try:
        source = open(source_file, encoding="utf-8").read()
    except OSError:
        return

    if _module_needs_the_database(source):
        pytest.skip(f"database unavailable: {reason}")
