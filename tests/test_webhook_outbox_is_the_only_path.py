"""
Every webhook leaves through the outbox. There is no second door.

The outbox is only worth its table if it cannot be bypassed. Publishing a
delivery straight to Celery still works - the broker is right there, and
`dispatch.delay(...)` is one line - and it reintroduces the whole defect
silently:

  * the publish runs inside the user's request, so an unreachable broker
    blocks the page;
  * the publish is outside the transaction that committed the case event,
    so a failure between the two loses a notification with nothing
    recording that it was owed.

Neither shows up in testing. On a developer machine the broker is up and
fast, so the bypass looks identical to the correct path and behaves
identically until the day it does not.

These are static checks over the source, for the same reason
tests/test_ai_client_boundary.py is: a reviewer will not reliably catch a
line that works perfectly in every environment they can see.
"""

import ast
import functools
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# The one task allowed to deliver webhooks.
RELAY_TASK_MODULE = "workers.outbox_tasks"

# Removed when the outbox replaced it. Named here so the failure message
# can say what happened rather than only that something is missing.
REMOVED_MODULE = "workers.notification_tasks"

SKIPPED_DIRECTORIES = {
    "__pycache__", ".git", ".venv", "venv", "env", "build", "dist",
    ".pytest_cache",
}


def _python_files():

    for path in REPOSITORY_ROOT.rglob("*.py"):

        if any(part in SKIPPED_DIRECTORIES for part in path.parts):
            continue

        yield path


@functools.lru_cache(maxsize=1)
def _parsed_sources():
    """
    Every source file in the repository, read and parsed once.

    Cached because several tests here walk the whole tree, and reading
    and parsing two hundred files per test turned this module into the
    slowest part of the suite. A guard that makes the suite tedious to
    run is a guard people start skipping.

    Returns a tuple rather than a generator: lru_cache has to hold the
    result, and a consumed generator would give every test after the
    first an empty tree to check - passing vacuously.
    """

    parsed = []

    for path in _python_files():

        try:
            source = path.read_text(encoding="utf-8")
            parsed.append((path, source, ast.parse(source)))
        except (SyntaxError, UnicodeDecodeError):
            continue

    return tuple(parsed)


def _dotted_name(node):

    parts = []

    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value

    if isinstance(node, ast.Name):
        parts.append(node.id)

    return ".".join(reversed(parts))


def test_the_superseded_notification_task_module_is_gone():
    """
    Deleted rather than left unused. An unused module that does the wrong
    thing correctly is an invitation - the next person adding an
    integration finds it, sees that it works, and uses it.
    """

    assert not (REPOSITORY_ROOT / "workers" / "notification_tasks.py").exists(), (
        f"{REMOVED_MODULE} is back. Webhook delivery goes through the "
        f"outbox: write rows in the transaction that commits the event "
        f"(db.database._enqueue_webhook_deliveries) and let "
        f"{RELAY_TASK_MODULE} deliver them."
    )


def test_nothing_imports_the_removed_module():

    offenders = []

    for path, _source, tree in _parsed_sources():

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):
                if any(a.name.startswith(REMOVED_MODULE) for a in node.names):
                    offenders.append(str(path.relative_to(REPOSITORY_ROOT)))

            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith(REMOVED_MODULE):
                    offenders.append(str(path.relative_to(REPOSITORY_ROOT)))

    assert not offenders, (
        f"These modules import {REMOVED_MODULE}, which was removed with "
        f"the outbox:\n" + "\n".join(f"  - {name}" for name in sorted(offenders))
    )


def test_the_data_layer_never_publishes_to_the_broker():
    """
    No .delay() or .apply_async() anywhere in db/.

    The line this draws is between two things that look alike and are
    not.

    An API route publishing a job - generate_case_pdf.delay() in
    apps/api/routes/reports.py, say - is fine. The caller asked for the
    work, is handed a job id, and sees an error if the publish fails.
    Nothing is lost, because nothing had been promised yet.

    The data layer is different. By the time db/ publishes anything, a
    row has been written and very often committed. A failure there is
    silent and unrecoverable: the change is durable, the side effect it
    was supposed to trigger is gone, and nothing anywhere records that it
    was ever due. That is precisely what log_case_event() did.

    So the rule is scoped to where the damage is asymmetric. If db/ needs
    something to happen afterwards, it writes that intent to a table in
    the same transaction - the outbox - and a scheduled task picks it up.
    """

    publishing_calls = {"delay", "apply_async", "send_task"}

    offenders = []

    for path, _source, tree in _parsed_sources():

        relative = path.relative_to(REPOSITORY_ROOT)

        if relative.parts[0] != "db":
            continue

        for node in ast.walk(tree):

            if not isinstance(node, ast.Call):
                continue

            name = _dotted_name(node.func)

            if name.split(".")[-1] in publishing_calls:
                offenders.append(f"{relative}:{node.lineno} -> {name}(...)")

    assert not offenders, (
        "The data layer publishes to the broker:\n"
        + "\n".join(f"  - {entry}" for entry in sorted(offenders))
        + "\n\nBy this point the change is already written. If the publish "
          "fails, the change stands and the side effect is lost with "
          "nothing recording that it was owed. Write the intent to a "
          "table in the same transaction instead - see "
          "db.database._enqueue_webhook_deliveries and "
          "db/migrations/0005_webhook_outbox.up.sql."
    )


def test_log_case_event_writes_the_outbox_inside_its_transaction():
    """
    The structural property, checked structurally.

    Both writes must be inside one `with get_db_connection()` block. A
    second connection, or a call after the block, and the atomicity the
    whole design rests on is gone - while the code still looks correct
    and passes every functional test on a healthy machine.
    """

    source = (REPOSITORY_ROOT / "db" / "database.py").read_text(encoding="utf-8")

    tree = ast.parse(source)

    function = next(
        (
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "log_case_event"
        ),
        None,
    )

    assert function is not None, "log_case_event has been renamed or removed"

    enqueue_calls_inside_a_with = 0

    for node in ast.walk(function):

        if not isinstance(node, ast.With):
            continue

        for inner in ast.walk(node):

            if (
                isinstance(inner, ast.Call)
                and _dotted_name(inner.func).endswith("_enqueue_webhook_deliveries")
            ):
                enqueue_calls_inside_a_with += 1

    assert enqueue_calls_inside_a_with == 1, (
        "log_case_event does not queue its notifications inside the "
        "transaction that writes the case event. Either the enqueue "
        "moved out of the `with get_db_connection()` block, or it is "
        "opening its own connection - both reopen the window where an "
        "event is committed and its notification is lost."
    )


@pytest.mark.parametrize(
    "name",
    [
        "claim_due_webhook_deliveries",
        "mark_webhook_delivered",
        "mark_webhook_delivery_failed",
        "cancel_webhook_delivery",
    ],
)
def test_every_claimed_row_has_a_way_to_be_resolved(name):
    """
    A claimed row with no terminal path is invisible: not pending, not
    delivered, not failed - retried forever with nothing explaining why.

    Checked by parsing rather than by importing db.database. Everything
    in this module is a static check and none of it needs a connection;
    importing the database module would make conftest.py treat the whole
    file as database-backed and skip these guards on any machine without
    Postgres - which is exactly the class of silent gap they exist to
    close.
    """

    tree = ast.parse(
        (REPOSITORY_ROOT / "db" / "database.py").read_text(encoding="utf-8")
    )

    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    assert name in defined, (
        f"db.database.{name}() is gone. Without it a claimed outbox row "
        f"has no way to reach a terminal state."
    )
