"""
Delivery of queued webhook notifications.

``db.database.log_case_event()`` writes one ``webhook_outbox`` row per
subscriber inside the same transaction as the case event. This module is
the other half: it takes the rows that are due and tries to deliver them.

Kept out of ``workers/`` on purpose. The relay is a domain operation -
"deliver what we owe, record what happened" - and the Celery task in
``workers/outbox_tasks.py`` is only the schedule that calls it. Split
that way, the whole behaviour is testable without a broker, a worker, or
a running scheduler; every property in tests/test_webhook_outbox.py is
checked by calling ``deliver_due_webhooks()`` directly.

Failure handling
----------------
Nothing here raises. A relay that dies partway through leaves the rest of
the batch claimed but undelivered, and those rows only come back when
their lease expires - so one broken endpoint would delay every other
customer's notifications. Each delivery is therefore isolated: it either
records success, records a retry, or records a permanent failure.
"""

import json
import logging

import requests

from core.security.url_safety import UnsafeUrlError, validate_public_https_url
from core.communication.notifications import (
    REQUEST_TIMEOUT_SECONDS,
    sign_payload,
)
from db.database import (
    cancel_webhook_delivery,
    claim_due_webhook_deliveries,
    get_webhook_by_id,
    mark_webhook_delivered,
    mark_webhook_delivery_failed,
)


logger = logging.getLogger(__name__)


# One batch per run. Large enough that a backlog drains in a few cycles,
# small enough that a single run cannot hold a claim on the whole table -
# which would stall every other relay behind a lease it may never
# release.
DEFAULT_BATCH_SIZE = 50


# Indices into the webhooks row, which is a plain tuple:
# (id, company, url, event_type, secret, is_active, created_at)
_WEBHOOK_URL = 2
_WEBHOOK_SECRET = 4
_WEBHOOK_IS_ACTIVE = 5


def deliver_due_webhooks(batch_size=DEFAULT_BATCH_SIZE):
    """
    Claim and attempt every delivery that is due.

    Returns a summary dict: delivered, retrying, failed, cancelled. The
    counts are the return value rather than a log line so a caller - a
    test, an operations endpoint, the Celery task - can assert on them.
    """

    summary = {"delivered": 0, "retrying": 0, "failed": 0, "cancelled": 0}

    for row in claim_due_webhook_deliveries(limit=batch_size):

        outbox_id, webhook_id, _company, event_type, payload, attempts = row

        outcome = _deliver_one(
            outbox_id=outbox_id,
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
            attempts=attempts,
        )

        summary[outcome] += 1

    return summary


def _deliver_one(outbox_id, webhook_id, event_type, payload, attempts):
    """
    One delivery attempt. Returns the key it should be counted under.

    Every exit path records a terminal or scheduled state, so a row can
    never be left claimed with nothing decided about it.
    """

    webhook = get_webhook_by_id(webhook_id)

    # The subscriber was deleted, or switched off, after this row was
    # queued. Cancelled rather than failed: they withdrew the request, so
    # this is not something an operator needs to fix.
    if webhook is None or not webhook[_WEBHOOK_IS_ACTIVE]:
        cancel_webhook_delivery(
            outbox_id, "Subscriber was removed or deactivated before delivery."
        )
        return "cancelled"

    url = webhook[_WEBHOOK_URL]

    # Re-validated on every attempt, not only at registration. DNS can
    # change in between: a hostname that resolved to a public address when
    # the webhook was registered could later resolve to an internal one,
    # which would turn our own relay into a request forger against the
    # customer's private network.
    try:
        validate_public_https_url(url)
    except UnsafeUrlError as error:
        logger.warning(
            "Outbox %s: refusing to deliver to %s - %s", outbox_id, url, error
        )
        cancel_webhook_delivery(outbox_id, f"Unsafe destination URL: {error}")
        return "cancelled"

    body = json.dumps(payload).encode("utf-8")

    try:
        response = requests.post(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": sign_payload(body, webhook[_WEBHOOK_SECRET]),
                # Lets a subscriber recognise a redelivery of something
                # they already processed. Delivery is at-least-once, so
                # this is the mechanism that makes that survivable rather
                # than a caveat in the documentation.
                "X-Webhook-Delivery-Id": str(outbox_id),
                "X-Webhook-Event": event_type,
                "X-Webhook-Attempt": str(attempts),
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            # Never follow a redirect on an outbound webhook: a
            # compromised endpoint could 3xx this request at an internal
            # address that the validation above deliberately rejected.
            allow_redirects=False,
        )

    except requests.RequestException as error:
        # Unreachable, refused, timed out. Transient until proven
        # otherwise, so this retries.
        mark_webhook_delivery_failed(outbox_id, str(error))
        return "retrying"

    if response.status_code < 400:
        mark_webhook_delivered(outbox_id, response.status_code)
        return "delivered"

    # 4xx and 5xx are both retried. A 4xx is usually permanent, but not
    # always - 401 after a rotated credential, 404 during a deploy, 429 by
    # definition - and the schedule gives up after five attempts anyway.
    # Treating 4xx as permanent would silently drop notifications during
    # exactly the kind of blip the outbox exists to survive.
    still_retrying = mark_webhook_delivery_failed(
        outbox_id,
        f"Endpoint returned HTTP {response.status_code}",
        response.status_code,
    )

    return "retrying" if still_retrying else "failed"
