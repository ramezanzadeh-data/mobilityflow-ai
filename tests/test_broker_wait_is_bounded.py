"""
A user request must never wait long on the message broker.

``db.database.log_case_event()`` publishes a webhook task on every case
event - creating a case, advancing the workflow, uploading a document -
and it does so inside the user's own request. That makes Celery's
connection settings part of the interaction design, not just deployment
configuration.

Celery's defaults are written for a worker, which is right to wait::

    Backend.retry_policy = {'max_retries': 20, 'interval_step': 1}

Twenty attempts a second apart. With Redis unavailable that froze the
page for twenty seconds per click and then failed silently, because the
caller wraps the publish in a try/except. It cost twenty seconds of CI
time per run too, which is how it was noticed at all - nothing failed,
so nothing reported it.

The property pinned here is that the wait is bounded, not that any
particular number is correct. The numbers can be tuned; an unbounded
wait in a user's request path cannot be reintroduced.

Worker settings are deliberately not constrained. ``broker_connection_max_retries``
is shared between publisher and consumer, and a worker that gives up
after two attempts dies on a broker restart instead of reconnecting.
"""

import socket
import time

import pytest


# Generous. This is a ceiling that separates "bounded" from "the user
# gave up and refreshed", not an assertion about the tuned value - a
# tighter bound would fail on a slow CI runner and teach everyone to
# ignore the test.
MAXIMUM_ACCEPTABLE_WAIT_SECONDS = 10.0

# Above the tuned settings but far below Celery's twenty-second default,
# so a silent revert to the defaults is caught.
MAXIMUM_CONFIGURED_RETRIES = 5


@pytest.fixture
def celery_configuration():

    from workers.celery_app import celery_app

    return celery_app.conf


def test_the_result_backend_does_not_retry_twenty_times(celery_configuration):
    """
    The exact default that caused the twenty-second block.

    celery.backends.base.Backend.retry_policy is
    {'max_retries': 20, 'interval_start': 0, 'interval_step': 1,
     'interval_max': 1}, and RedisBackend reads overrides from
    result_backend_transport_options['retry_policy'].
    """

    options = celery_configuration.result_backend_transport_options or {}
    policy = options.get("retry_policy") or {}

    assert "max_retries" in policy, (
        "result_backend_transport_options does not override retry_policy, "
        "so Celery's default of 20 retries one second apart applies - and "
        "that runs inside the user's request."
    )

    assert policy["max_retries"] <= MAXIMUM_CONFIGURED_RETRIES


def test_publishing_a_task_does_not_retry_twenty_times(celery_configuration):

    policy = celery_configuration.task_publish_retry_policy or {}

    assert policy.get("max_retries", 99) <= MAXIMUM_CONFIGURED_RETRIES


def test_connecting_to_the_broker_has_a_short_timeout(celery_configuration):
    """
    Reaching an address that accepts the connection and then says nothing
    is the case a retry count does not cover - without a socket timeout
    the publish waits on the read, not on the retry loop.
    """

    assert celery_configuration.broker_connection_timeout <= 5.0

    transport = celery_configuration.broker_transport_options or {}

    assert transport.get("socket_connect_timeout", 999) <= 5.0


def test_the_worker_can_still_reconnect_indefinitely(celery_configuration):
    """
    The bound belongs to the publisher, not the consumer.

    broker_connection_max_retries governs the worker re-establishing its
    own connection. Lowering it to match the publisher would make a
    worker exit on any broker restart, trading a slow page for a
    background queue that silently stops - a much worse failure, and one
    nobody would notice for hours.
    """

    maximum = celery_configuration.broker_connection_max_retries

    assert maximum is None or maximum >= 10, (
        "broker_connection_max_retries has been lowered. That setting is "
        "shared with the worker's own reconnect loop; bound the publisher "
        "with task_publish_retry_policy instead."
    )


def _closed_local_port():
    """A loopback port with nothing listening, bound and released."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_dead_broker_fails_fast_rather_than_hanging(monkeypatch):
    """
    The behaviour itself, not the configuration that should produce it.

    A settings assertion can pass while the value fails to reach the
    connection - this measures the wall clock against a broker that is
    definitely not there.
    """

    port = _closed_local_port()

    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{port}/0")

    from workers.celery_app import celery_app

    # The app was configured at import from the previous URL; point this
    # instance at the dead port for the duration of the test.
    monkeypatch.setattr(
        celery_app.conf, "broker_url", f"redis://127.0.0.1:{port}/0"
    )

    started = time.monotonic()

    try:
        celery_app.send_task("workers.outbox_tasks.deliver_webhook_outbox")
    except Exception:  # noqa: BLE001 - failing is fine; hanging is not
        pass

    elapsed = time.monotonic() - started

    assert elapsed < MAXIMUM_ACCEPTABLE_WAIT_SECONDS, (
        f"Publishing to an unreachable broker took {elapsed:.1f}s. This "
        f"runs inside the user's request in db.database.log_case_event(), "
        f"so that is how long the page is frozen for."
    )
