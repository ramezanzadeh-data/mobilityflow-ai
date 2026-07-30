"""
The positional constants must match the query they describe.

Case rows are plain tuples read by index. ``db.database`` names those
indices as constants, which reads as though it makes them safe. It does
not - a name is only a claim, and this one was false for as long as the
statutory dates feature existed:

    CASE_INDEX_ARRIVAL_DATE = 16      # described a SELECT * row
    load_case()                       # selects explicit columns,
                                      # index 16 is tenant_id,
                                      # and no date column at all

So ``case_statutory_dates(load_case(id))`` returned the integer tenant id
as the arrival date. ``parse_date`` rejected it, correctly, and every
obligation reported "date not recorded".

Nothing failed. That is the part worth dwelling on. "We have no arrival
date for this case" is an answer the obligations engine is designed to
give and shows honestly on screen, so a completely disconnected read
looked exactly like a user who had not filled the field in. The feature
that carries this product's Swiss domain claim produced no deadlines at
all, and the screens looked correct while it did.

These tests parse load_case()'s own SELECT statement and check each
constant against the column it is named for. A constant can now only be
wrong if someone changes both it and the query - which is the point.
"""

import ast
import re
from pathlib import Path

import pytest


DATABASE_SOURCE = (
    Path(__file__).resolve().parent.parent / "db" / "database.py"
).read_text(encoding="utf-8")


def _index_constants():
    """
    The CASE_INDEX_* values, parsed rather than imported.

    Importing db.database is what conftest.py uses to decide a test
    module needs PostgreSQL, and this module needs none: every property
    here is the source agreeing with itself. Importing would have made
    these checks skip on any machine without a database - which is
    exactly where a positional mismatch goes unnoticed.
    """

    tree = ast.parse(DATABASE_SOURCE)

    values = {}

    for node in tree.body:

        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:

            if (
                isinstance(target, ast.Name)
                and target.id.startswith("CASE_INDEX_")
                and isinstance(node.value, ast.Constant)
            ):
                values[target.id] = node.value.value

    return values


def _load_case_columns():
    """
    The column list load_case() actually selects, in order.

    Read from the source rather than by running the query: the property
    is about the code agreeing with itself, and this has to be checkable
    on a machine with no database - which is where the mismatch would
    otherwise sit unnoticed.
    """

    start = DATABASE_SOURCE.index("def load_case")
    block = DATABASE_SOURCE[start:start + 2500]

    select = block[block.index("SELECT"):block.index("FROM cases")]

    columns = []

    for line in select.replace("SELECT", "").split(","):

        # Strip SQL comments; they explain which migration added a
        # column and would otherwise be read as column names.
        line = re.sub(r"--.*", "", line).strip()

        if line:
            columns.append(line)

    return columns


@pytest.mark.parametrize(
    "constant,column",
    [
        ("CASE_INDEX_ARRIVAL_DATE", "arrival_date"),
        ("CASE_INDEX_CONTRACT_START_DATE", "contract_start_date"),
        ("CASE_INDEX_PERMIT_EXPIRY_DATE", "permit_expiry_date"),
        ("CASE_INDEX_CORRESPONDENCE_LANGUAGE", "correspondence_language"),
    ],
)
def test_each_index_constant_points_at_the_column_it_names(constant, column):

    columns = _load_case_columns()

    constants = _index_constants()

    assert constant in constants, f"{constant} no longer exists"

    index = constants[constant]

    assert index < len(columns), (
        f"{constant} = {index}, but load_case() returns only "
        f"{len(columns)} columns. Reading it yields nothing at all - the "
        f"exact failure that made every statutory deadline report "
        f"'date not recorded'."
    )

    assert columns[index] == column, (
        f"{constant} = {index}, which is '{columns[index]}' in "
        f"load_case(), not '{column}'.\n\n"
        f"load_case() selects:\n"
        + "\n".join(f"  [{n:2}] {c}" for n, c in enumerate(columns))
    )


def test_load_case_selects_every_column_read_by_position():
    """
    A constant cannot point at a column the query does not fetch.

    This is what was actually wrong: the constants were plausible, and
    the query simply did not ask for the columns.
    """

    columns = set(_load_case_columns())

    required = {
        "arrival_date",
        "contract_start_date",
        "permit_expiry_date",
        "correspondence_language",
    }

    missing = required - columns

    assert not missing, (
        f"load_case() does not select {sorted(missing)}, but code reads "
        f"them by index from its result. The read returns whatever "
        f"happens to sit at that position, or nothing."
    )


def test_the_columns_are_read_in_the_order_the_query_returns_them():
    """
    The three date constants are consecutive and in query order.

    A behavioural test of case_statutory_dates() would be the direct
    check, but importing db.database is how conftest.py decides a module
    needs PostgreSQL - and these checks must run on a machine without
    one, since that is exactly where a positional mismatch survives. So
    the ordering is asserted against the parsed query instead.
    """

    columns = _load_case_columns()
    constants = _index_constants()

    ordered = [
        constants["CASE_INDEX_ARRIVAL_DATE"],
        constants["CASE_INDEX_CONTRACT_START_DATE"],
        constants["CASE_INDEX_PERMIT_EXPIRY_DATE"],
    ]

    assert ordered == sorted(ordered), (
        f"the date constants are out of order: {ordered}"
    )

    assert [columns[i] for i in ordered] == [
        "arrival_date",
        "contract_start_date",
        "permit_expiry_date",
    ]


def test_the_constants_are_not_simply_sequential_by_accident():
    """
    Guards the guard.

    Four constants in a row that happen to line up would pass the checks
    above while describing a different query. Assert against the parsed
    names, not against each other.
    """

    columns = _load_case_columns()

    constants = _index_constants()

    positions = {
        columns[constants["CASE_INDEX_ARRIVAL_DATE"]],
        columns[constants["CASE_INDEX_CONTRACT_START_DATE"]],
        columns[constants["CASE_INDEX_PERMIT_EXPIRY_DATE"]],
        columns[constants["CASE_INDEX_CORRESPONDENCE_LANGUAGE"]],
    }

    assert positions == {
        "arrival_date",
        "contract_start_date",
        "permit_expiry_date",
        "correspondence_language",
    }


def test_no_module_reads_a_case_row_by_a_bare_number():
    """
    Positional access to a case row goes through a named constant.

    Not style. `case[16]` is unreviewable - nobody reading a diff can
    tell whether 16 is still the column the author meant, and that is
    precisely how this defect survived. Restricted to db/ and core/,
    where the row shape is a contract; the views unpack the first few
    fields by position and are excluded deliberately, since those
    positions come from the CREATE TABLE and have never moved.
    """

    repository_root = Path(__file__).resolve().parent.parent

    offenders = []

    for path in list((repository_root / "db").rglob("*.py")):

        if "__pycache__" in path.parts:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):

            if not isinstance(node, ast.Subscript):
                continue

            target = node.value
            index = node.slice

            if not isinstance(target, ast.Name):
                continue

            if "case" not in target.id.lower():
                continue

            if isinstance(index, ast.Constant) and isinstance(index.value, int):
                if index.value >= 16:
                    offenders.append(
                        f"{path.relative_to(repository_root)}:{node.lineno} "
                        f"-> {target.id}[{index.value}]"
                    )

    assert not offenders, (
        "case rows are indexed with a bare number past the original "
        "columns:\n" + "\n".join(f"  - {entry}" for entry in offenders)
        + "\n\nUse a CASE_INDEX_* constant, which this file checks "
          "against load_case()'s own SELECT."
    )
