"""
The relay: what it does with each outcome an endpoint can produce.

Separate from tests/test_webhook_outbox.py, which pins the database
guarantees. This file is about the decisions - deliver, retry, cancel -
and the one property that matters more than any of them: the relay never
leaves a claimed row undecided.

A row claimed and then abandoned is invisible. It is not pending, not
failed, and not delivered; it simply waits out its lease and is tried
again, forever, with nobody able to see why. So every path through
_deliver_one() ends in a recorded state, and the tests below walk each
one.

No HTTP happens here. requests.post is replaced, because the question is
what the relay does with a 500, not whether requests can produce one.
"""

import pytest
import requests

from core.communication import outbox as relay
from db.database import (
    claim_due_webhook_deliveries,
    get_db_connection,
    log_case_event,
)


COMPANY = "Relay Test Company"


class FakeResponse:

    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture
def queued_delivery():
    """
    One case, one subscriber, one pending outbox row.

    Yields (outbox_id, webhook_id) and removes everything afterwards.
    """

    with get_db_connection() as conn:
        c = conn.cursor()

        c.execute(
            "INSERT INTO cases (employee_name, status, company) "
            "VALUES (%s, %s, %s) RETURNING id",
            ("Relay Test Subject", "OPEN", COMPANY),
        )
        case_id = c.fetchone()[0]

        c.execute(
            "INSERT INTO webhooks (company, url, event_type, secret, is_active) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (COMPANY, "https://example.com/hook", "ALL", "test-secret", 1),
        )
        webhook_id = c.fetchone()[0]

    log_case_event(case_id, "CASE_CREATED", "queued by the relay test")

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM webhook_outbox WHERE company = %s", (COMPANY,)
        )
        outbox_id = c.fetchone()[0]

    yield outbox_id, webhook_id

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM webhook_outbox WHERE company = %s", (COMPANY,))
        c.execute("DELETE FROM webhooks WHERE company = %s", (COMPANY,))
        c.execute("DELETE FROM case_events WHERE case_id = %s", (case_id,))
        c.execute("DELETE FROM cases WHERE id = %s", (case_id,))


def _status(outbox_id):

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT status, attempts, last_error, last_status_code "
            "FROM webhook_outbox WHERE id = %s",
            (outbox_id,),
        )
        return c.fetchone()


def _allow_the_test_url(monkeypatch):
    """
    example.com is a public HTTPS host, but resolution differs between a
    laptop, a CI runner and a corporate network. Stubbing the check keeps
    these tests about the relay's decisions; the check itself is covered
    by tests/test_url_safety.py.
    """

    monkeypatch.setattr(relay, "validate_public_https_url", lambda url: None)


# ---------------------------------------------------------- outcomes ---

@pytest.mark.parametrize("status_code", [200, 201, 202, 204, 302])
def test_a_successful_response_is_recorded_once_and_never_retried(
    queued_delivery, monkeypatch, status_code
):
    """Anything below 400 is acceptance. Terminal."""

    outbox_id, _ = queued_delivery

    _allow_the_test_url(monkeypatch)
    monkeypatch.setattr(
        relay.requests, "post", lambda *a, **k: FakeResponse(status_code)
    )

    summary = relay.deliver_due_webhooks()

    assert summary["delivered"] == 1
    assert _status(outbox_id)[0] == "DELIVERED"

    # A second sweep must not find it again.
    assert relay.deliver_due_webhooks()["delivered"] == 0


@pytest.mark.parametrize("status_code", [400, 401, 404, 429, 500, 503])
def test_an_error_response_is_retried_rather_than_dropped(
    queued_delivery, monkeypatch, status_code
):
    """
    4xx is retried as well as 5xx. It is usually permanent and sometimes
    not - 401 after a rotated credential, 404 mid-deploy, 429 by
    definition - and the schedule gives up on its own. Treating 4xx as
    fatal would drop notifications during exactly the blip the outbox
    exists to survive.
    """

    outbox_id, _ = queued_delivery

    _allow_the_test_url(monkeypatch)
    monkeypatch.setattr(
        relay.requests, "post", lambda *a, **k: FakeResponse(status_code)
    )

    summary = relay.deliver_due_webhooks()

    assert summary["retrying"] == 1

    status, attempts, error, recorded_code = _status(outbox_id)

    assert status == "PENDING"
    assert attempts == 1
    assert str(status_code) in error
    assert recorded_code == status_code


def test_an_unreachable_endpoint_is_retried(queued_delivery, monkeypatch):

    outbox_id, _ = queued_delivery

    _allow_the_test_url(monkeypatch)

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr(relay.requests, "post", refuse)

    assert relay.deliver_due_webhooks()["retrying"] == 1

    status, _, error, _ = _status(outbox_id)

    assert status == "PENDING"
    assert "refused" in error.lower()


def test_a_deactivated_subscriber_is_cancelled_not_retried(
    queued_delivery, monkeypatch
):
    """
    Switched off between queueing and delivery. They withdrew the
    request, so this is not something an operator should be asked to fix.
    """

    outbox_id, webhook_id = queued_delivery

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE webhooks SET is_active = 0 WHERE id = %s", (webhook_id,)
        )

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("delivered to a subscriber that was switched off")

    monkeypatch.setattr(relay.requests, "post", must_not_be_called)

    assert relay.deliver_due_webhooks()["cancelled"] == 1
    assert _status(outbox_id)[0] == "CANCELLED"


def test_an_unsafe_destination_is_never_called(queued_delivery, monkeypatch):
    """
    Re-validated on every attempt, not only at registration.

    DNS can change in between: a hostname that resolved to a public
    address when the customer registered it can later resolve to an
    internal one. Without this check the relay - which sits inside the
    network, holding credentials - becomes the attacker's request forger.
    """

    outbox_id, _ = queued_delivery

    from core.security.url_safety import UnsafeUrlError

    def reject(url):
        raise UnsafeUrlError("resolves to a private address")

    monkeypatch.setattr(relay, "validate_public_https_url", reject)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("a blocked URL was requested anyway")

    monkeypatch.setattr(relay.requests, "post", must_not_be_called)

    assert relay.deliver_due_webhooks()["cancelled"] == 1

    status, _, error, _ = _status(outbox_id)

    assert status == "CANCELLED"
    assert "private address" in error


# ------------------------------------------------------------ request ---

def test_the_request_carries_a_signature_and_a_delivery_id(
    queued_delivery, monkeypatch
):
    """
    The signature is what lets a subscriber trust the payload; the
    delivery id is what lets them deduplicate it. Delivery is
    at-least-once, so without the id the contract is unusable.
    """

    outbox_id, _ = queued_delivery

    _allow_the_test_url(monkeypatch)

    captured = {}

    def capture(url, **kwargs):
        captured.update(kwargs)
        captured["url"] = url
        return FakeResponse(200)

    monkeypatch.setattr(relay.requests, "post", capture)

    relay.deliver_due_webhooks()

    headers = captured["headers"]

    assert headers["X-Webhook-Signature"].startswith("sha256=")
    assert headers["X-Webhook-Delivery-Id"] == str(outbox_id)
    assert headers["X-Webhook-Event"] == "CASE_CREATED"

    assert captured["allow_redirects"] is False, (
        "a compromised endpoint could redirect this request at an "
        "internal address that the URL check deliberately rejected"
    )
    assert captured["timeout"] > 0


def test_no_claimed_row_is_ever_left_undecided(queued_delivery, monkeypatch):
    """
    The property behind all of the above.

    A claimed row that records nothing is invisible: not pending, not
    failed, not delivered - it waits out its lease and is retried
    forever with no explanation anywhere. Whatever the endpoint does,
    the row must end in a state someone can read.
    """

    outbox_id, _ = queued_delivery

    _allow_the_test_url(monkeypatch)

    def behave_badly(*args, **kwargs):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(relay.requests, "post", behave_badly)

    summary = relay.deliver_due_webhooks()

    assert sum(summary.values()) == 1, "the claimed row was not accounted for"

    status, attempts, error, _ = _status(outbox_id)

    assert status in {"PENDING", "FAILED", "CANCELLED"}
    assert attempts == 1
    assert error, "an attempt was made and nothing says what happened"


def test_an_empty_outbox_is_not_an_error():
    """The normal state. A sweep every ten seconds mostly finds nothing."""

    assert relay.deliver_due_webhooks() == {
        "delivered": 0, "retrying": 0, "failed": 0, "cancelled": 0,
    }
