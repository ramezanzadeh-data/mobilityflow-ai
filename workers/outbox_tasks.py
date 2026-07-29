"""
Scheduled delivery of the webhook outbox.

Deliberately thin. Everything that decides anything lives in
core.communication.outbox, so the behaviour can be tested without a
broker or a scheduler; this file is the schedule and nothing else.

Runs on Celery beat rather than being published when an event happens.
The point of the outbox is that the request path never touches the
broker: if a publish were needed to trigger delivery, a broker outage
would once again mean a queued notification nobody comes back for. A
periodic sweep depends on nothing but the database.

A missed run is harmless. Rows stay due until delivered, so a beat
process that was down for an hour simply finds more work when it starts.
"""

from workers.celery_app import celery_app


@celery_app.task(
    name="workers.outbox_tasks.deliver_webhook_outbox",
    # No retry. The task's own unit of work is a batch, and every row in
    # it has already recorded its own outcome and its own next attempt.
    # Retrying the task would re-run rows that succeeded.
    max_retries=0,
    # A run holds no state worth resuming. If it is killed, the claimed
    # rows return when their lease expires.
    acks_late=False,
)
def deliver_webhook_outbox():
    """
    Deliver everything that is due, once.

    Returns the per-outcome counts so a run's result is inspectable in
    Flower or the background_jobs table rather than only in the log.
    """

    from core.communication.outbox import deliver_due_webhooks

    return deliver_due_webhooks()
