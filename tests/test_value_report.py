"""
Tests for the value realisation report.

This report exists to justify the subscription price, which makes its
correctness a commercial matter rather than a cosmetic one: a customer who
finds one figure they can disprove will discount every other figure in the
document, and the renewal conversation is over.

So the properties pinned here are mostly about *honesty* rather than
arithmetic:

* an unparseable timestamp is never counted into a period it may not
  belong to,
* a compliance gap is counted but never priced,
* no monetary figure appears unless the customer supplied the rate,
* every estimate carries the arithmetic that produced it.

The report is a pure function of its inputs - no database, no clock - so
the same archived data always regenerates the same report. That matters
when a figure is questioned months later.
"""

from datetime import datetime

import pytest

from core.reporting.value import (
    EVENT_AI_OPERATOR_RUN,
    EVENT_CASE_CREATED,
    EVENT_DOCUMENT_PROCESSED,
    EVENT_WORKFLOW_STATE_CHANGED,
    ValueAssumptions,
    compute_value_report,
    count_events_by_type,
    filter_events_to_period,
    parse_event_timestamp,
)


def event(event_type, created_at="2026-07-15 10:00:00", case_id=1):
    """Row shaped like case_events: (id, case_id, type, description, created_at)."""

    return (1, case_id, event_type, "description text", created_at)


def metric(report, key):
    return next(m for m in report.metrics if m.key == key)


# ---------------------------------------------------------- timestamps ---

@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-07-15 10:00:00", datetime(2026, 7, 15, 10, 0, 0)),
        ("2026-07-15T10:00:00", datetime(2026, 7, 15, 10, 0, 0)),
        ("2026-07-15", datetime(2026, 7, 15, 0, 0, 0)),
        (datetime(2026, 7, 15, 10), datetime(2026, 7, 15, 10)),
        (None, None),
        ("", None),
        ("not a date", None),
    ],
)
def test_parse_event_timestamp(value, expected):
    """created_at is TEXT, so malformed values must degrade, not raise."""

    assert parse_event_timestamp(value) == expected


def test_unparseable_timestamps_are_excluded_from_a_period():
    """
    The honest choice. Counting a row whose date is unknown would
    attribute work to a quarter it may not belong to; under-reporting is
    recoverable, misattribution is not.
    """

    events = [
        event(EVENT_DOCUMENT_PROCESSED, "2026-07-15 10:00:00"),
        event(EVENT_DOCUMENT_PROCESSED, "corrupted"),
    ]

    kept = filter_events_to_period(
        events,
        datetime(2026, 7, 1),
        datetime(2026, 7, 31),
    )

    assert len(kept) == 1


def test_unbounded_period_keeps_everything_including_bad_timestamps():
    """
    With no window there is nothing to misattribute, so a row with an
    unreadable date is still a real event and still counts.
    """

    events = [
        event(EVENT_DOCUMENT_PROCESSED, "2026-07-15 10:00:00"),
        event(EVENT_DOCUMENT_PROCESSED, "corrupted"),
    ]

    assert len(filter_events_to_period(events)) == 2


def test_period_bounds_are_inclusive():

    events = [
        event(EVENT_CASE_CREATED, "2026-07-01 00:00:00"),
        event(EVENT_CASE_CREATED, "2026-07-31 23:59:59"),
        event(EVENT_CASE_CREATED, "2026-08-01 00:00:01"),
    ]

    kept = filter_events_to_period(
        events,
        datetime(2026, 7, 1, 0, 0, 0),
        datetime(2026, 7, 31, 23, 59, 59),
    )

    assert len(kept) == 2


# -------------------------------------------------------------- counts ---

def test_counts_are_by_event_type_only():
    """
    Descriptions are free text and get reworded; event types are a
    controlled vocabulary. Only the type is ever read.
    """

    events = [
        (1, 1, EVENT_DOCUMENT_PROCESSED, "any wording at all", "2026-07-15"),
        (2, 1, EVENT_DOCUMENT_PROCESSED, "rules_passed=False, risk=100", "2026-07-15"),
        (3, 1, EVENT_CASE_CREATED, "", "2026-07-15"),
    ]

    assert count_events_by_type(events) == {
        EVENT_DOCUMENT_PROCESSED: 2,
        EVENT_CASE_CREATED: 1,
    }


# ---------------------------------------------------------- arithmetic ---

def test_hours_saved_uses_the_supplied_assumption():

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED) for _ in range(47)],
        assumptions=ValueAssumptions(minutes_per_document_review=12.0),
    )

    documents = metric(report, "documents_auto_processed")

    assert documents.count == 47
    assert documents.hours_saved == 9.4          # 47 × 12 / 60
    assert "47 document(s) × 12 min" in documents.basis


def test_every_estimate_states_its_own_arithmetic():
    """
    A figure without a visible basis cannot be defended in a procurement
    review, and one unexplained number discredits the whole report.
    """

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED), event(EVENT_AI_OPERATOR_RUN)],
        assumptions=ValueAssumptions(),
    )

    for entry in report.metrics:
        assert entry.basis, f"{entry.key} has no stated basis"

        if entry.hours_saved is not None:
            assert "×" in entry.basis, (
                f"{entry.key} reports hours without showing the calculation"
            )


def test_total_hours_is_the_sum_of_the_lines():

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED) for _ in range(10)]
        + [event(EVENT_WORKFLOW_STATE_CHANGED) for _ in range(6)],
        assumptions=ValueAssumptions(
            minutes_per_document_review=12.0,
            minutes_per_case_status_update=5.0,
        ),
    )

    assert report.total_hours_saved == pytest.approx(2.0 + 0.5)


# ------------------------------------------------------------- honesty ---

def test_compliance_gaps_are_counted_but_never_priced():
    """
    What a caught compliance gap is worth depends on the penalty avoided,
    which we cannot know. Attaching an invented figure to it would
    undermine the credibility of the metrics that *are* calculable.
    """

    report = compute_value_report(
        "Acme AG",
        [],
        missing_document_count=23,
        assumptions=ValueAssumptions(),
    )

    gaps = metric(report, "compliance_gaps_detected")

    assert gaps.count == 23
    assert gaps.hours_saved is None


def test_no_money_is_reported_without_a_customer_supplied_rate():
    """
    A franc figure derived from a rate we guessed would be the least
    defensible number in the document.
    """

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED)],
        assumptions=ValueAssumptions(hourly_cost=None),
    )

    assert report.total_hours_saved > 0
    assert report.total_cost_saved is None


def test_money_is_reported_once_the_customer_supplies_a_rate():

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED) for _ in range(10)],
        assumptions=ValueAssumptions(
            minutes_per_document_review=12.0,
            hourly_cost=95.0,
        ),
    )

    assert report.total_hours_saved == 2.0
    assert report.total_cost_saved == pytest.approx(190.0)


def test_empty_period_reports_zeroes_not_an_error():
    """
    A new customer's first report must render. Zero is a truthful answer
    and reads as "nothing happened yet"; a crash reads as "broken".
    """

    report = compute_value_report("Acme AG", [], assumptions=ValueAssumptions())

    assert report.total_hours_saved == 0
    assert all(m.count == 0 for m in report.metrics)
    assert len(report.metrics) == 6


def test_report_is_reproducible_from_the_same_inputs():
    """
    No clock, no database: archived data must regenerate an identical
    report when a figure is questioned months later.
    """

    events = [event(EVENT_DOCUMENT_PROCESSED) for _ in range(5)]
    assumptions = ValueAssumptions(minutes_per_document_review=12.0)

    first = compute_value_report("Acme AG", events, assumptions=assumptions)
    second = compute_value_report("Acme AG", events, assumptions=assumptions)

    assert first == second


# ------------------------------------------- projection and ratio ---

def test_annualised_figures_scale_the_observed_rate():
    """
    A projection, not a measurement. It exists because a one-month window
    understates a recurring saving - not to make a small number look
    larger, which is why it is labelled as a projection wherever shown.
    """

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED, "2026-07-15 10:00:00") for _ in range(10)],
        assumptions=ValueAssumptions(minutes_per_document_review=12.0),
        period_start=datetime(2026, 7, 1),
        period_end=datetime(2026, 7, 31, 23, 59, 59),
    )

    assert report.period_days == 31
    assert report.total_hours_saved == 2.0
    assert report.annualised_hours_saved == pytest.approx(2.0 * 365 / 31, abs=0.1)


def test_no_projection_without_a_bounded_period():
    """With no window there is no rate to extend."""

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED)],
        assumptions=ValueAssumptions(),
    )

    assert report.period_days is None
    assert report.annualised_hours_saved is None


def test_no_ratio_unless_the_customer_supplied_the_platform_cost():
    """
    The product does not know its own price and must never assume one. A
    vendor computing its own return is the least credible number in a
    procurement pack.
    """

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED) for _ in range(10)],
        assumptions=ValueAssumptions(hourly_cost=95.0),
        period_start=datetime(2026, 7, 1),
        period_end=datetime(2026, 7, 31, 23, 59, 59),
    )

    assert report.total_cost_saved is not None
    assert report.platform_cost_for_period is None
    assert report.value_cost_ratio is None
    assert report.net_value is None


def test_the_ratio_is_value_over_cost_from_the_customers_own_figures():

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED, "2026-07-15 10:00:00") for _ in range(100)],
        assumptions=ValueAssumptions(
            minutes_per_document_review=12.0,
            hourly_cost=100.0,
            platform_cost_per_month=500.0,
        ),
        period_start=datetime(2026, 7, 1),
        period_end=datetime(2026, 7, 31, 23, 59, 59),
    )

    assert report.total_cost_saved == 2000.0
    assert report.platform_cost_for_period == pytest.approx(509.2, abs=1.0)
    assert report.value_cost_ratio == pytest.approx(2000.0 / 509.2, abs=0.05)
    assert report.net_value == pytest.approx(2000.0 - 509.2, abs=1.0)


def test_no_ratio_without_an_hourly_rate_either():
    """Both inputs are the customer's; one missing means no comparison."""

    report = compute_value_report(
        "Acme AG",
        [event(EVENT_DOCUMENT_PROCESSED) for _ in range(10)],
        assumptions=ValueAssumptions(platform_cost_per_month=500.0),
        period_start=datetime(2026, 7, 1),
        period_end=datetime(2026, 7, 31, 23, 59, 59),
    )

    assert report.value_cost_ratio is None


def test_nothing_is_defaulted_in_the_assumptions_that_involve_money():
    """
    Guard on the dataclass itself. A default on either of these would put
    a number we invented into a document the customer shows their CFO.
    """

    fresh = ValueAssumptions()

    assert fresh.hourly_cost is None
    assert fresh.platform_cost_per_month is None
