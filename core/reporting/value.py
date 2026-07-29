"""
Value realisation reporting.

Turns activity the product already records into figures a customer can put
in front of their own CFO: how much manual work the system absorbed, and
how many compliance problems it caught before they became expensive.

This is the artefact that justifies the subscription. Enterprises do not
buy software; they buy less risk, fewer hours and demonstrable compliance.
A renewal conversation goes very differently when the vendor can say "here
is what we did for you last quarter" with the customer's own numbers.

Design constraints, all deliberate
----------------------------------

**Read-only.** Nothing here writes, and nothing here changes a case, a
task, a workflow state or a risk score. It aggregates rows that other
parts of the system already produced.

**Counts events by type, never by parsing descriptions.** ``event_type``
is a small controlled vocabulary written by application code, so counting
it is stable. ``description`` is free text - today
``DOCUMENT_PROCESSED`` renders as::

    Processed 'passport.pdf' as Passport - rules_passed=False, risk=100

Extracting ``risk=100`` from that with a regex would work until somebody
rewords the sentence, and would then fail *silently* - producing a wrong
number in a document used to justify a price. Any figure that cannot be
derived from an event type or a table row is deliberately not reported.

**Assumptions are the customer's, never ours.** "Saved 9.4 hours" is only
credible if the reader can see how it was calculated. Every derived figure
carries the input it came from, so the report can state: *you told us
manual review takes 12 minutes; we counted 47 documents.* An invented
baseline is worse than no baseline - a procurement team will find it, and
then everything else in the report is suspect too.

**Absolute counts are facts; time savings are estimates.** They are kept
in separate fields so a reader can trust the first group unconditionally
and audit the second.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime


# --------------------------------------------------------------------
# Event vocabulary. These strings are written by application code
# (db.database, core.ai.operator, core.documents.document_processing_service)
# and are the only part of an event this module relies on.
# --------------------------------------------------------------------

EVENT_CASE_CREATED = "CASE_CREATED"
EVENT_DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"
EVENT_DOCUMENT_STATUS_CHANGED = "DOCUMENT_STATUS_CHANGED"
EVENT_AI_OPERATOR_RUN = "AI_OPERATOR_RUN"
EVENT_TASK_STATUS_CHANGED = "TASK_STATUS_CHANGED"
EVENT_WORKFLOW_STATE_CHANGED = "WORKFLOW_STATE_CHANGED"
EVENT_RISK_CHANGED = "RISK_CHANGED"

# Typical fully loaded specialist rates in Switzerland, shown as guidance
# beside the rate field. A range, never a prefilled value: the report's
# credibility rests on the reader recognising the number as their own, and
# a default would be a figure we invented sitting in a field they may
# never look at.
SWISS_RATE_GUIDANCE_LOW = 50
SWISS_RATE_GUIDANCE_HIGH = 150


# Index of the fields this module reads out of a case_events row:
# (id, case_id, event_type, description, created_at[, employee_name])
_EVENT_TYPE_INDEX = 2
_EVENT_CREATED_AT_INDEX = 4


@dataclass(frozen=True)
class ValueAssumptions:
    """
    The customer's own numbers.

    Defaults are placeholders for a demo, not claims. Every one of them
    should be replaced with a figure the customer states, because the
    report's credibility rests entirely on the reader recognising these
    as their own.

    Attributes:
        minutes_per_document_review: How long a specialist spends reading
            and checking one incoming document by hand.
        minutes_per_case_status_update: Time to chase and record one
            status change without the workflow engine.
        minutes_per_document_request: Time to notice a document is
            missing and write to the employee about it.
        currency: Reporting currency label.
        hourly_cost: Fully loaded cost of an HR specialist hour. Used
            only when the customer supplies it; when None, the report
            reports hours and stays silent about money.
        platform_cost_per_month: What this customer pays for the
            product. Supplied by them, never by us - the software does
            not know its own price, and a vendor that computes its own
            return is the least credible number in any procurement pack.
            When None, no comparison against cost is shown at all.
    """

    minutes_per_document_review: float = 12.0
    minutes_per_case_status_update: float = 5.0
    minutes_per_document_request: float = 8.0
    currency: str = "CHF"
    hourly_cost: float = None
    platform_cost_per_month: float = None


@dataclass(frozen=True)
class ValueMetric:
    """
    One line of the report.

    Args:
        key: Stable identifier for the UI to translate.
        count: The observed fact. Always exact.
        hours_saved: Estimate derived from ``count`` and one assumption,
            or None when the metric is a count only.
        basis: Plain-language statement of the arithmetic, shown beside
            the figure so the reader can check it. This is what makes the
            estimate defensible rather than asserted.
    """

    key: str
    count: int
    hours_saved: float = None
    basis: str = None


@dataclass(frozen=True)
class ValueReport:

    company: str
    period_start: str
    period_end: str
    metrics: list = field(default_factory=list)
    assumptions: ValueAssumptions = None

    @property
    def total_hours_saved(self) -> float:
        return round(
            sum(m.hours_saved or 0.0 for m in self.metrics),
            1,
        )

    @property
    def total_cost_saved(self):
        """
        Monetary value, or None when the customer has not supplied an
        hourly cost. Reporting a franc figure from a rate we guessed
        would be the least defensible number in the document.
        """

        if not self.assumptions or self.assumptions.hourly_cost is None:
            return None

        return round(self.total_hours_saved * self.assumptions.hourly_cost, 2)

    @property
    def period_days(self):
        """Length of the reporting window, or None if unbounded."""

        if not self.period_start or not self.period_end:
            return None

        start = datetime.fromisoformat(self.period_start)
        end = datetime.fromisoformat(self.period_end)

        return max(1, (end - start).days + 1)

    @property
    def annualised_hours_saved(self):
        """
        The observed rate extended to a year.

        A projection, not a measurement, and labelled as one wherever it
        is shown. It exists because a three-month window understates a
        recurring saving, not to make a small number look larger: the
        arithmetic is simply observed hours over observed days, times
        365.

        None when the window is unbounded - there is no rate to extend.
        """

        days = self.period_days

        if not days or not self.total_hours_saved:
            return None

        return round(self.total_hours_saved * 365.0 / days, 1)

    @property
    def annualised_cost_saved(self):

        hours = self.annualised_hours_saved

        if hours is None or not self.assumptions:
            return None

        if self.assumptions.hourly_cost is None:
            return None

        return round(hours * self.assumptions.hourly_cost, 2)

    @property
    def platform_cost_for_period(self):
        """
        What the customer paid for the product over this window, from
        the monthly figure they supplied.
        """

        if not self.assumptions or self.assumptions.platform_cost_per_month is None:
            return None

        days = self.period_days

        if not days:
            return None

        return round(
            self.assumptions.platform_cost_per_month * days / 30.44, 2
        )

    @property
    def value_cost_ratio(self):
        """
        Value created divided by what it cost, over the same window.

        Deliberately not called ROI. "Return on investment" implies a
        financial model - discounting, a time horizon, assumptions about
        what the freed hours were worth doing instead. This is one
        division of two numbers the customer supplied, and the name says
        exactly that.

        None unless both figures came from the customer. Neither is ever
        defaulted.
        """

        value = self.total_cost_saved
        cost = self.platform_cost_for_period

        if value is None or cost is None or cost <= 0:
            return None

        return round(value / cost, 2)

    @property
    def net_value(self):
        """Value created minus what it cost, over this window."""

        value = self.total_cost_saved
        cost = self.platform_cost_for_period

        if value is None or cost is None:
            return None

        return round(value - cost, 2)


def parse_event_timestamp(value):
    """
    Parse a ``case_events.created_at`` value.

    Stored as TEXT, so a malformed value is possible and must not raise -
    one unparseable row cannot be allowed to abort a report. Unparseable
    rows are excluded from period filtering by the caller rather than
    silently counted in the wrong period.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(pattern) + 6], pattern)
        except (ValueError, TypeError):
            continue

    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def filter_events_to_period(events, period_start=None, period_end=None):
    """
    Restrict events to a reporting window.

    Args:
        events: case_events rows.
        period_start: Inclusive lower bound, or None for no lower bound.
        period_end: Inclusive upper bound, or None for no upper bound.

    Events whose timestamp cannot be parsed are dropped when a bound is
    given: counting a row whose date is unknown would attribute work to a
    quarter it may not belong to, and a report that quietly misattributes
    is worse than one that reports a slightly smaller number.
    """

    if period_start is None and period_end is None:
        return list(events)

    kept = []

    for event in events:
        timestamp = parse_event_timestamp(event[_EVENT_CREATED_AT_INDEX])

        if timestamp is None:
            continue

        if period_start is not None and timestamp < period_start:
            continue

        if period_end is not None and timestamp > period_end:
            continue

        kept.append(event)

    return kept


def count_events_by_type(events):
    """Tally events. The only thing read from a row is its type."""

    counts = {}

    for event in events:
        event_type = event[_EVENT_TYPE_INDEX]
        counts[event_type] = counts.get(event_type, 0) + 1

    return counts


def _hours(count, minutes_each):
    return round(count * minutes_each / 60.0, 1)


def compute_value_report(
    company,
    events,
    missing_document_count=0,
    completed_task_count=0,
    assumptions=None,
    period_start=None,
    period_end=None,
) -> ValueReport:
    """
    Build the report from already-fetched data.

    Pure: no database access, no clock. Everything it needs is passed in,
    so the arithmetic can be tested exactly and a report can be
    regenerated identically from archived data - which matters when a
    customer questions a figure six months later.

    Args:
        company: Tenant name, for the report header.
        events: case_events rows for this company.
        missing_document_count: Documents currently recorded as MISSING.
            A compliance gap the system surfaced; counted, never
            converted to hours, because the value of catching it is
            avoided rework and avoided penalties, not minutes.
        completed_task_count: Tasks moved to DONE.
        assumptions: The customer's baseline figures.
        period_start / period_end: Reporting window.
    """

    assumptions = assumptions or ValueAssumptions()

    in_period = filter_events_to_period(events, period_start, period_end)
    counts = count_events_by_type(in_period)

    documents_processed = counts.get(EVENT_DOCUMENT_PROCESSED, 0)
    operator_runs = counts.get(EVENT_AI_OPERATOR_RUN, 0)
    workflow_transitions = counts.get(EVENT_WORKFLOW_STATE_CHANGED, 0)
    cases_created = counts.get(EVENT_CASE_CREATED, 0)

    metrics = [
        ValueMetric(
            key="documents_auto_processed",
            count=documents_processed,
            hours_saved=_hours(
                documents_processed,
                assumptions.minutes_per_document_review,
            ),
            basis=(
                f"{documents_processed} document(s) × "
                f"{assumptions.minutes_per_document_review:g} min manual "
                f"review"
            ),
        ),
        ValueMetric(
            key="ai_operator_runs",
            count=operator_runs,
            hours_saved=_hours(
                operator_runs,
                assumptions.minutes_per_document_request,
            ),
            basis=(
                f"{operator_runs} run(s) × "
                f"{assumptions.minutes_per_document_request:g} min to "
                f"identify and request missing documents"
            ),
        ),
        ValueMetric(
            key="workflow_transitions_recorded",
            count=workflow_transitions,
            hours_saved=_hours(
                workflow_transitions,
                assumptions.minutes_per_case_status_update,
            ),
            basis=(
                f"{workflow_transitions} status change(s) × "
                f"{assumptions.minutes_per_case_status_update:g} min to "
                f"chase and record manually"
            ),
        ),
        # Counted, never priced. What a caught compliance gap is worth
        # depends on the penalty avoided, which we cannot know - and
        # inventing a figure here would undermine the numbers above.
        ValueMetric(
            key="compliance_gaps_detected",
            count=missing_document_count,
            basis="Documents flagged as missing before submission",
        ),
        ValueMetric(
            key="tasks_completed",
            count=completed_task_count,
            basis="Follow-up tasks tracked to completion",
        ),
        ValueMetric(
            key="cases_managed",
            count=cases_created,
            basis="Cases opened in this period",
        ),
    ]

    return ValueReport(
        company=company,
        period_start=period_start.isoformat() if period_start else None,
        period_end=period_end.isoformat() if period_end else None,
        metrics=metrics,
        assumptions=assumptions,
    )


# Status values the report counts. Kept as constants so the query and the
# report cannot drift apart.
DOCUMENT_STATUS_MISSING = "MISSING"
TASK_STATUS_DONE = "DONE"


def build_value_report(
    company,
    assumptions=None,
    period_start=None,
    period_end=None,
) -> ValueReport:
    """
    Fetch what the report needs, then compute it.

    The only function here that touches the database. compute_value_report
    stays pure so the arithmetic is testable and so an archived dataset
    regenerates an identical report - this wrapper exists purely to keep
    that separation.

    All reads are scoped to ``company``, and every underlying query joins
    through ``cases`` where the tenant RLS policy applies, so a report
    cannot span tenants even if called with the wrong argument.
    """

    from db.database import (
        count_documents_by_status_for_company,
        count_tasks_by_status_for_company,
        get_events_for_company,
    )

    return compute_value_report(
        company=company,
        events=get_events_for_company(company),
        missing_document_count=count_documents_by_status_for_company(
            company, DOCUMENT_STATUS_MISSING
        ),
        completed_task_count=count_tasks_by_status_for_company(
            company, TASK_STATUS_DONE
        ),
        assumptions=assumptions,
        period_start=period_start,
        period_end=period_end,
    )
