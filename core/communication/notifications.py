"""
Webhook payload signing, and the timeout every delivery shares.

Delivery itself lives in core/communication/outbox.py. This module used
to hold a dispatch_webhooks() that resolved subscribers and posted to
each one, called from a Celery task published inside the user's request.
That path is gone: it could lose a notification in the gap between
committing a case event and publishing the task, with nothing recording
that anything had been owed. See db/migrations/0005_webhook_outbox.up.sql.

What remains is the part both designs need - an HMAC over the exact bytes
sent, so a subscriber can prove a payload came from us and was not
altered on the way.
"""

import hmac
import hashlib
import logging


logger = logging.getLogger(__name__)

# Shared with the relay. Five seconds is a deliberate choice about whose
# time it is: a subscriber's slow endpoint must not hold a delivery
# worker, and an endpoint that cannot acknowledge in five seconds should
# be queueing our request rather than processing it inline.
REQUEST_TIMEOUT_SECONDS = 5


def sign_payload(payload_bytes, secret):

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    return f"sha256={signature}"


def verify_webhook_signature(payload_bytes, signature_header, secret):

    expected = sign_payload(payload_bytes, secret)

    return hmac.compare_digest(expected, signature_header or "")
