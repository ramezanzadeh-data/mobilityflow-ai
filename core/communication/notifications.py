
import hmac
import hashlib
import json
import logging

import requests

from db.database import get_active_webhooks_for_event
from core.security.url_safety import UnsafeUrlError, validate_public_https_url


logger = logging.getLogger(__name__)

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


def dispatch_webhooks(company, event_type, payload):

    webhooks = get_active_webhooks_for_event(company, event_type)

    body = json.dumps(payload).encode("utf-8")

    results = []

    for webhook in webhooks:

        webhook_id, _company, url, _event_type, secret, _is_active, _created_at = webhook

        # Re-validate immediately before every delivery, not just at
        # registration time: DNS can change between the two (a
        # hostname that resolved to a public IP at registration could
        # later resolve to an internal one - "DNS rebinding").
        try:
            validate_public_https_url(url)
        except UnsafeUrlError as e:

            logger.warning(f"Webhook {webhook_id} ({url}) blocked: {e}")

            results.append({
                "webhook_id": webhook_id,
                "url": url,
                "success": False,
                "error": f"Blocked unsafe webhook URL: {e}",
            })
            continue

        signature = sign_payload(body, secret)

        try:
            response = requests.post(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
                # Never follow redirects for an outbound webhook
                # request: a malicious or compromised endpoint could
                # otherwise 3xx-redirect this request to an internal
                # address that would fail the upfront validation
                # above.
                allow_redirects=False,
            )

            results.append({
                "webhook_id": webhook_id,
                "url": url,
                "success": response.status_code < 400,
                "status_code": response.status_code,
            })

        except requests.RequestException as e:

            logger.warning(f"Webhook {webhook_id} ({url}) delivery failed: {e}")

            results.append({
                "webhook_id": webhook_id,
                "url": url,
                "success": False,
                "error": str(e),
            })

    return results
