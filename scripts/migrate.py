"""
Apply the database schema and all checked-in migrations.

Idempotent - safe to re-run against an already-migrated database.

Usage:

    python -m scripts.migrate
"""

# Must run before db.database is imported: that module reads
# DATABASE_URL at import time and the PG* variables when it first builds
# the connection pool. Without it this script silently migrated whichever
# server happened to answer on localhost:5432 rather than the configured
# one, and reported success either way - see bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

from db.database import init_db  # noqa: E402  (deliberate - see above)


def main() -> int:

    init_db()

    print("Database migration completed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
