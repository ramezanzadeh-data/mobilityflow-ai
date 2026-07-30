"""
Startup check that the database matches the code.

Migration 0003 added three columns to ``cases``. The code that writes
them shipped in a Docker rebuild; the migration was never run against
the application database. Nothing noticed until a user filled in the case
form and pressed Create, at which point they were shown::

    psycopg2.errors.UndefinedColumn: column "arrival_date" of relation
    "cases" does not exist

That is the worst possible moment and the worst possible message. The
work is lost, the cause is invisible to the person affected, and the
error names internal tables and file paths.

The mismatch was knowable the instant the process started. This module
checks it there, once, and reports it in a sentence that names the fix.

Deliberately a check, not a migration
-------------------------------------
It would be less code to call ``init_db()`` on startup and have the app
migrate itself. That is the wrong trade for this product:

* Schema changes would run automatically on deploy, including the
  destructive ones, with no opportunity to take a backup first.
* Several application processes start at once under Compose - Streamlit,
  the API, the Celery worker. Each would race the others to apply the
  same DDL.
* An operator would lose the ability to say when the database changes,
  which is exactly the control an enterprise customer expects to have.

So the application reports the gap and refuses to pretend; a human runs
``python -m scripts.migrate``.
"""

from dataclasses import dataclass


# Columns the current code depends on, with the migration that adds each.
# Extended whenever a migration adds something the code then requires -
# the point is that this list and the code move together.
REQUIRED_COLUMNS = {
    "cases": {
        "arrival_date": "0003_case_statutory_dates",
        "contract_start_date": "0003_case_statutory_dates",
        "permit_expiry_date": "0003_case_statutory_dates",
        "correspondence_language": "0006_case_correspondence_language",
        "commune": "0007_case_commune",
    },
    "tasks": {
        "due_date": "0001_tasks_unique_active_title",
    },
    "tenant_value_assumptions": {
        "platform_cost_per_month": "0004_platform_cost",
    },
    "webhook_outbox": {
        "next_attempt_at": "0005_webhook_outbox",
        "last_status_code": "0005_webhook_outbox",
    },
}

REQUIRED_TABLES = {
    "tenant_value_assumptions": "0002_tenant_value_assumptions",
    # Without this table log_case_event() cannot record the notifications
    # a committed event owes, and the failure would appear on the user's
    # first case creation rather than at startup.
    "webhook_outbox": "0005_webhook_outbox",
}


@dataclass(frozen=True)
class SchemaProblem:

    kind: str          # "table" or "column"
    name: str          # "cases.arrival_date" or "tenant_value_assumptions"
    migration: str     # which migration provides it

    def __str__(self):
        return f"{self.kind} {self.name} (added by {self.migration})"


def find_schema_problems():
    """
    Compare the live schema against what the code needs.

    Returns a list of SchemaProblem; empty means the database is current.

    Never raises. A check that can take down the application it is meant
    to protect is worse than no check - if the database is unreachable
    that is a different failure, and the normal connection error is a
    clearer report of it than anything this could invent.
    """

    from db.database import get_db_connection

    problems = []

    try:
        with get_db_connection() as connection:

            with connection.cursor() as cursor:

                cursor.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """)
                existing_tables = {row[0] for row in cursor.fetchall()}

                for table, migration in REQUIRED_TABLES.items():
                    if table not in existing_tables:
                        problems.append(
                            SchemaProblem("table", table, migration)
                        )

                cursor.execute("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """)
                existing_columns = {
                    (row[0], row[1]) for row in cursor.fetchall()
                }

                for table, columns in REQUIRED_COLUMNS.items():

                    if table not in existing_tables:
                        # Reported by the table check above, or the table
                        # is genuinely absent; either way, listing every
                        # one of its columns adds noise, not information.
                        continue

                    for column, migration in columns.items():
                        if (table, column) not in existing_columns:
                            problems.append(
                                SchemaProblem(
                                    "column", f"{table}.{column}", migration
                                )
                            )

    except Exception:  # noqa: BLE001 - see the docstring
        return []

    return problems


def describe_problems(problems):
    """
    A message for an operator: what is missing and what to run.

    Written for someone who has just deployed and has thirty seconds to
    understand why the app is refusing to start.
    """

    if not problems:
        return ""

    migrations = sorted({problem.migration for problem in problems})

    lines = [
        "The database is behind the application code.",
        "",
        "Missing:",
    ]

    lines += [f"  - {problem}" for problem in problems]

    lines += [
        "",
        f"Pending migration(s): {', '.join(migrations)}",
        "",
        "Take a backup, then apply them:",
        "",
        "  docker compose exec -T postgres pg_dump -U mobilityflow "
        "-d mobilityflow > backup.sql",
        "  python -m scripts.migrate",
    ]

    return "\n".join(lines)
