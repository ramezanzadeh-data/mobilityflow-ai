"""
The transactional outbox.

Runs against real PostgreSQL, because every property here is a database
property. Atomicity, FOR UPDATE SKIP LOCKED and the partial index are the
mechanism; a mocked connection would test the mock.

What this is protecting
-----------------------
Before the outbox, db.database.log_case_event() committed the case event
and then published a Celery task on the next line. Between those two
statements a notification could vanish - broker down, worker unreachable,
process killed - and nothing anywhere recorded that it had been owed. The
customer's downstream system was simply missing events, and neither side
could say which.

That is a data-integrity defect wearing the costume of a performance
problem. The tests below are about the integrity half: an event and its
notifications commit together, a claimed row cannot be claimed twice, and
a delivery that fails is still on the books afterwards.

Delivery is at-least-once and deliberately so. A relay killed after the
endpoint accepted a request but before recording it will send again when
the lease expires. Exactly-once over HTTP does not exist; the
X-Webhook-Delivery-Id header is what lets a subscriber deduplicate.
"""

import json
import threading

import pytest

from db import database
from db.database import (
    WEBHOOK_MAX_ATTEMPTS,
    WEBHOOK_RETRY_SCHEDULE_SECONDS,
    cancel_webhook_delivery,
    claim_due_webhook_deliveries,
    get_db_connection,
    log_case_event,
    mark_webhook_delivered,
    mark_webhook_delivery_failed,
)


COMPANY = "Outbox Test Company"


def _clean(case_id=None, webhook_ids=(), company=COMPANY):

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM webhook_outbox WHERE company = %s", (company,))
        for webhook_id in webhook_ids:
            c.execute("DELETE FROM webhooks WHERE id = %s", (webhook_id,))
        if case_id is not None:
            c.execute("DELETE FROM case_events WHERE case_id = %s", (case_id,))
            c.execute("DELETE FROM cases WHERE id = %s", (case_id,))


@pytest.fixture
def case_id():
    """A throwaway case belonging to COMPANY."""

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO cases (employee_name, status, company) "
            "VALUES (%s, %s, %s) RETURNING id",
            ("Outbox Test Subject", "OPEN", COMPANY),
        )
        new_case_id = c.fetchone()[0]

    yield new_case_id

    _clean(case_id=new_case_id)


def _subscriber(event_type="ALL", is_active=1, url="https://example.com/hook"):

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO webhooks (company, url, event_type, secret, is_active) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (COMPANY, url, event_type, "test-secret", is_active),
        )
        return c.fetchone()[0]


def _rows(company=COMPANY):

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, webhook_id, event_type, status, attempts, payload
        FROM webhook_outbox WHERE company = %s ORDER BY id
        """, (company,))
        return c.fetchall()


def _make_due(outbox_id):
    """Bring a row's next_attempt_at back to now, bypassing the wait."""

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE webhook_outbox SET next_attempt_at = now() WHERE id = %s",
            (outbox_id,),
        )


# ------------------------------------------------------------ writing ---

def test_an_event_and_its_notifications_are_written_together(case_id):
    """
    The property the whole design exists for.

    One statement, one transaction: a committed case event always has its
    outbox rows. There is no window in which the event is durable and the
    notification is not.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        rows = _rows()

        assert len(rows) == 1
        assert rows[0][1] == webhook_id
        assert rows[0][3] == "PENDING"
        assert rows[0][5]["case_id"] == case_id

    finally:
        _clean(webhook_ids=[webhook_id])


def test_one_row_per_subscriber_not_one_per_event(case_id):
    """
    Each endpoint retries on its own.

    With a single row per event, one broken subscriber would drag the
    whole event back through the retry schedule and re-deliver it to the
    subscribers that had already accepted it.
    """

    first = _subscriber()
    second = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        assert {row[1] for row in _rows()} == {first, second}

    finally:
        _clean(webhook_ids=[first, second])


def test_only_subscribers_to_this_event_are_queued(case_id):

    matching = _subscriber(event_type="CASE_CREATED")
    other = _subscriber(event_type="DOCUMENT_UPLOADED")
    catch_all = _subscriber(event_type="ALL")

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        assert {row[1] for row in _rows()} == {matching, catch_all}

    finally:
        _clean(webhook_ids=[matching, other, catch_all])


def test_an_inactive_subscriber_is_not_queued(case_id):
    """
    Switching a webhook off must stop it being queued, not merely stop it
    being delivered. Queuing rows for a subscriber who has opted out and
    cancelling them later would fill their operations view with noise.
    """

    inactive = _subscriber(is_active=0)

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        assert _rows() == []

    finally:
        _clean(webhook_ids=[inactive])


def test_a_case_with_no_subscribers_still_records_its_event(case_id):
    """The event is the record. Notifications are a consequence of it."""

    log_case_event(case_id, "CASE_CREATED", "created by the test")

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT count(*) FROM case_events WHERE case_id = %s", (case_id,)
        )
        assert c.fetchone()[0] == 1

    assert _rows() == []


def test_the_payload_is_stored_as_json_not_text(case_id):
    """
    JSONB, so "which events did you send us?" is a query rather than a
    scan through strings. psycopg2 returns it already decoded.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "STATUS_CHANGED", "moved to REVIEW")

        payload = _rows()[0][5]

        assert isinstance(payload, dict)
        assert payload["event_type"] == "STATUS_CHANGED"

    finally:
        _clean(webhook_ids=[webhook_id])


# ----------------------------------------------------------- claiming ---

def test_claiming_returns_due_rows_and_counts_the_attempt(case_id):

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        claimed = claim_due_webhook_deliveries(limit=10)

        assert len(claimed) == 1
        assert claimed[0][5] == 1, "attempts should be incremented on claim"

    finally:
        _clean(webhook_ids=[webhook_id])


def test_a_claimed_row_is_not_handed_out_again_immediately(case_id):
    """
    The lease. Claiming pushes next_attempt_at forward so a second relay
    run - or a second worker - does not deliver the same row while the
    first attempt is still in flight.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        assert len(claim_due_webhook_deliveries(limit=10)) == 1
        assert claim_due_webhook_deliveries(limit=10) == []

    finally:
        _clean(webhook_ids=[webhook_id])


def test_concurrent_relays_never_claim_the_same_row(case_id):
    """
    FOR UPDATE SKIP LOCKED, under real threads against real PostgreSQL.

    Two relay processes is the normal deployment, not an edge case: the
    Compose file runs a worker pool. Without SKIP LOCKED they would either
    deliver each row twice or serialise on the same lock.
    """

    webhook_id = _subscriber()

    try:
        for index in range(20):
            log_case_event(case_id, "CASE_CREATED", f"event {index}")

        claimed_ids = []
        lock = threading.Lock()

        def claim():
            rows = claim_due_webhook_deliveries(limit=20)
            with lock:
                claimed_ids.extend(row[0] for row in rows)

        threads = [threading.Thread(target=claim) for _ in range(4)]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(claimed_ids) == len(set(claimed_ids)), (
            "the same delivery was claimed by more than one relay"
        )
        assert len(claimed_ids) == 20

    finally:
        _clean(webhook_ids=[webhook_id])


# ------------------------------------------------------------ outcomes ---

def test_a_delivered_row_is_terminal(case_id):
    """
    Never sent again, and carrying the time it was accepted - which is
    what answers "when did you notify us?" months later.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        outbox_id = claim_due_webhook_deliveries(limit=1)[0][0]

        assert mark_webhook_delivered(outbox_id, 200) is True

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT status, delivered_at, last_status_code "
                "FROM webhook_outbox WHERE id = %s",
                (outbox_id,),
            )
            status, delivered_at, code = c.fetchone()

        assert status == "DELIVERED"
        assert delivered_at is not None
        assert code == 200

        _make_due(outbox_id)

        assert claim_due_webhook_deliveries(limit=10) == [], (
            "a delivered row was queued for delivery again"
        )

    finally:
        _clean(webhook_ids=[webhook_id])


def test_a_failed_attempt_is_retried_and_the_error_is_kept(case_id):
    """
    A FAILED row with no error is a support ticket nobody can answer.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        outbox_id = claim_due_webhook_deliveries(limit=1)[0][0]

        assert mark_webhook_delivery_failed(
            outbox_id, "Connection refused", None
        ) is True

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT status, last_error FROM webhook_outbox WHERE id = %s",
                (outbox_id,),
            )
            status, error = c.fetchone()

        assert status == "PENDING"
        assert error == "Connection refused"

    finally:
        _clean(webhook_ids=[webhook_id])


def test_the_wait_grows_with_each_failure(case_id):
    """
    A restart clears in seconds; a broken endpoint must not be hammered
    every minute for days. Fixed intervals cannot serve both.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        waits = []

        for _ in range(3):

            outbox_id = claim_due_webhook_deliveries(limit=1)[0][0]

            _make_due(outbox_id)
            mark_webhook_delivery_failed(outbox_id, "still down")

            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT EXTRACT(EPOCH FROM (next_attempt_at - now())) "
                    "FROM webhook_outbox WHERE id = %s",
                    (outbox_id,),
                )
                waits.append(float(c.fetchone()[0]))

            _make_due(outbox_id)

        assert waits == sorted(waits), f"backoff did not grow: {waits}"
        assert waits[0] < waits[-1]

    finally:
        _clean(webhook_ids=[webhook_id])


def test_it_gives_up_eventually_and_says_so(case_id):
    """
    FAILED rather than deleted. A notification the customer never got is
    a fact worth keeping - it is what an operator lists when asked what
    is broken, and what settles "you never told us".
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        outbox_id = None
        still_retrying = True

        for _ in range(WEBHOOK_MAX_ATTEMPTS + 2):

            claimed = claim_due_webhook_deliveries(limit=1)

            if not claimed:
                break

            outbox_id = claimed[0][0]
            still_retrying = mark_webhook_delivery_failed(outbox_id, "gone")
            _make_due(outbox_id)

        assert still_retrying is False

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT status, attempts, last_error "
                "FROM webhook_outbox WHERE id = %s",
                (outbox_id,),
            )
            status, attempts, error = c.fetchone()

        assert status == "FAILED"
        assert attempts >= WEBHOOK_MAX_ATTEMPTS
        assert error

        _make_due(outbox_id)

        assert claim_due_webhook_deliveries(limit=10) == [], (
            "a permanently failed row is still being retried"
        )

    finally:
        _clean(webhook_ids=[webhook_id])


def test_a_withdrawn_subscriber_is_cancelled_not_failed(case_id):
    """
    Two different facts. FAILED means we owe something we could not
    deliver; CANCELLED means they asked us to stop. Merging them would
    make the operator's list of broken integrations mostly noise.
    """

    webhook_id = _subscriber()

    try:
        log_case_event(case_id, "CASE_CREATED", "created by the test")

        outbox_id = claim_due_webhook_deliveries(limit=1)[0][0]

        assert cancel_webhook_delivery(outbox_id, "subscriber removed") is True

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT status FROM webhook_outbox WHERE id = %s", (outbox_id,)
            )
            assert c.fetchone()[0] == "CANCELLED"

    finally:
        _clean(webhook_ids=[webhook_id])


def test_deleting_a_subscriber_removes_its_pending_deliveries(case_id):
    """
    ON DELETE CASCADE. Deleting a webhook is a withdrawal of consent to be
    called; a queue that outlives it and keeps calling is not defensible.
    """

    webhook_id = _subscriber()

    log_case_event(case_id, "CASE_CREATED", "created by the test")

    assert len(_rows()) == 1

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM webhooks WHERE id = %s", (webhook_id,))

    assert _rows() == []


# ------------------------------------------------------------- config ---

def test_the_retry_schedule_is_bounded_and_increasing():
    """
    A guard on the constants themselves. An unbounded schedule would
    retry a dead endpoint forever; a flat one would fail a deploy blip as
    hard as a dead host.
    """

    schedule = WEBHOOK_RETRY_SCHEDULE_SECONDS

    # Gaps between attempts, so one fewer than the number of attempts.
    assert len(schedule) == WEBHOOK_MAX_ATTEMPTS - 1
    assert list(schedule) == sorted(schedule)
    assert schedule[0] >= 30, "retrying sooner than this is hammering"
    assert schedule[-1] <= 24 * 3600, "a whole day between attempts is abandonment"


def test_the_outbox_is_tenant_isolated():
    """
    Rows carry the case payload sent to a customer's endpoint. Everything
    true of `cases` is true here, so the table must be under the same
    row-level security policy rather than relying on application filters.
    """

    assert "webhook_outbox" in database._RLS_TABLES
