"""
Housekeeping for the browser-session handoff table.

Deliberately thin, like workers/outbox_tasks.py: the decision about what
is safe to delete lives in db.database.purge_expired_session_handoffs(),
so it can be reasoned about and tested without a broker or a scheduler.
This file is the schedule and nothing else.

Why it needs a schedule at all
------------------------------
A handoff row is spent seconds after it is created, but it is not deleted
then: session_id links it to the browser session it minted, and logging
out follows that link to revoke a session the tab cannot otherwise name -
see db/migrations/0008_session_handoff.up.sql. So rows outlive their
usefulness as credentials by a session lifetime, and one accumulates per
login. Small, and unbounded, which is the shape of table that is fine for
a year and then is not.

A missed run is harmless. Nothing depends on this having happened; the
next run simply finds more to remove.
"""

from workers.celery_app import celery_app


@celery_app.task(
    name="workers.session_tasks.purge_session_handoffs",
    # Nothing to retry. A failed delete is re-attempted by the next
    # scheduled run, which is a day away and costs nothing.
    max_retries=0,
    acks_late=False,
)
def purge_session_handoffs():
    """Remove handoff rows too old to name a live session. Returns the count."""

    from db.database import purge_expired_session_handoffs

    removed = purge_expired_session_handoffs()

    return {"removed": removed}
