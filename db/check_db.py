"""
Quick manual inspection of a table's columns, e.g.:
    python -m db.check_db cases
"""

import sys

from db.database import get_db_connection


def main(table_name="cases"):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
        """, (table_name,))

        columns = c.fetchall()

    if not columns:
        print(f"Table '{table_name}' not found.")
        return

    for name, data_type in columns:
        print(f"{name}: {data_type}")


if __name__ == "__main__":
    table = sys.argv[1] if len(sys.argv) > 1 else "cases"
    main(table)
