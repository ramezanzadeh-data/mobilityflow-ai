"""
Prove that init_db() can build a working database from nothing.

    python -m scripts.verify_fresh_install

Why this exists
---------------
Every developer database in this project grew incrementally: tables were
created, then columns were added, then migrations were applied, in the
order the code happened to be written. ``init_db()`` succeeding against
such a database says only that it is idempotent - not that it can produce
that database from an empty one.

Those are different properties, and CI found the difference. Against a
brand-new PostgreSQL 16 the run failed with::

    schema setup failed on 'mobilityflow_test' -
    column "tenant_id" does not exist

The suite then skipped 82 database-backed tests and reported success. The
same defect on a customer's first deployment is not a skipped test; it is
an installation that cannot be completed, and it appears at the worst
possible moment - the first hour of an enterprise onboarding.

What this does
--------------
Creates a throwaway database, runs init_db() against it, and drops it
again. On failure it prints the full traceback, which names the exact
statement PostgreSQL rejected.

Safe by construction: the database is created here and its name carries a
timestamp, so the script can never touch the application database or the
test database. It is dropped on the way out even when init_db() raises.
"""

import os
import sys
import traceback
from datetime import datetime

from bootstrap import load_environment


load_environment()


# Timestamped so a leftover from an interrupted run is obvious and never
# collides with the next one. The prefix makes an orphan easy to find.
SCRATCH_DATABASE = (
    f"mobilityflow_freshcheck_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
)

# CREATE DATABASE cannot run from inside the database being created.
MAINTENANCE_DATABASE = "postgres"


def _connection_settings():
    """
    The PG* settings, resolved the same way db.database resolves them.

    DATABASE_URL is rejected rather than parsed. It takes precedence over
    the PG* variables inside db.database, so honouring only half of that
    precedence here would let this script verify one server while the
    application uses another - the exact class of failure documented in
    bootstrap/environment.py.
    """

    if os.environ.get("DATABASE_URL"):
        sys.exit(
            "DATABASE_URL is set. This script configures the target "
            "database through PGDATABASE, which DATABASE_URL overrides.\n"
            "Unset it for this run, or set the PG* variables instead."
        )

    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
        "user": os.environ.get("PGUSER", "mobilityflow"),
        "password": os.environ.get("PGPASSWORD", ""),
    }


def _maintenance_connection(settings):

    import psycopg2

    connection = psycopg2.connect(
        dbname=MAINTENANCE_DATABASE, **settings
    )

    # CREATE DATABASE and DROP DATABASE cannot run inside a transaction.
    connection.autocommit = True

    return connection


def _create_scratch_database(connection):

    from psycopg2 import sql

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(SCRATCH_DATABASE)
            )
        )


def _drop_scratch_database(connection):

    from psycopg2 import sql

    with connection.cursor() as cursor:
        # WITH (FORCE) closes any session still attached. The connection
        # pool inside db.database holds one open after init_db(), and
        # without this the drop blocks and leaves the database behind.
        cursor.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(SCRATCH_DATABASE)
            )
        )


def main():

    settings = _connection_settings()

    print(f"Server:   {settings['host']}:{settings['port']}")
    print(f"Database: {SCRATCH_DATABASE} (created and dropped by this script)")
    print()

    try:
        connection = _maintenance_connection(settings)
    except Exception as error:  # noqa: BLE001 - reported verbatim
        print(f"Cannot reach PostgreSQL: {error}")
        return 2

    try:
        _create_scratch_database(connection)
        print("Empty database created. Running init_db()...")
        print()

        # Set before importing db.database: that module reads the
        # environment when it first builds its connection pool, and the
        # choice cannot be changed once it has connected.
        os.environ["PGDATABASE"] = SCRATCH_DATABASE

        from db.database import init_db

        try:
            init_db()

        except Exception:  # noqa: BLE001 - the whole point of the script
            print("init_db() FAILED on an empty database.")
            print()
            print("-" * 68)
            traceback.print_exc()
            print("-" * 68)
            print()
            print(
                "This is what a customer's first deployment would hit. The "
                "statement named above is the one PostgreSQL rejected; it "
                "depends on something an existing database already has and "
                "an empty one does not."
            )
            return 1

        print("init_db() completed on an empty database.")
        print()

        problems = _remaining_schema_problems()

        if problems:
            print("But the schema is still incomplete afterwards:")
            for problem in problems:
                print(f"  - {problem}")
            return 1

        print("Schema check passes. A fresh install is viable.")
        return 0

    finally:
        try:
            _close_pool()
            _drop_scratch_database(connection)
            print(f"\nDropped {SCRATCH_DATABASE}.")
        except Exception as error:  # noqa: BLE001
            print(
                f"\nWARNING: could not drop {SCRATCH_DATABASE}: {error}\n"
                f"Remove it manually:  DROP DATABASE {SCRATCH_DATABASE};"
            )
        finally:
            connection.close()


def _remaining_schema_problems():
    """
    Run the application's own startup check against the fresh database.

    init_db() returning without raising is necessary but not sufficient:
    a statement guarded by IF NOT EXISTS can no-op on a table that was
    never created. db.schema_check is what the application uses to decide
    whether the database matches the code, so it is the right judge here.
    """

    from db.schema_check import find_schema_problems

    return [str(problem) for problem in find_schema_problems()]


def _close_pool():
    """
    Release the pooled connections so the scratch database can be dropped.

    Tolerant of the pool never having been built - init_db() may have
    failed before the first connection was opened.
    """

    try:
        from db import database

        # db.database keeps the SimpleConnectionPool in a module global
        # named _POOL, built lazily by _get_pool().
        pool = getattr(database, "_POOL", None)

        if pool is not None:
            pool.closeall()

    except Exception:  # noqa: BLE001 - DROP ... WITH (FORCE) covers this
        pass


if __name__ == "__main__":
    raise SystemExit(main())
