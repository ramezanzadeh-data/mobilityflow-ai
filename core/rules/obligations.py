"""
Statutory obligation and deadline engine.

Turns a case plus its known dates into a list of dated obligations - the
things that must happen by a certain day, and what goes wrong if they do
not. A missed immigration deadline is the single most expensive failure
in this domain: it affects a real person's right to live and work, and no
amount of good document handling compensates for it.

This is also where the product's defensible advantage sits. Generic HR
and workflow platforms can be configured to hold a date; none of them
knows that a Valais commune registration follows arrival, or that a
renewal has to be filed before a permit lapses. That knowledge is the
product.

Three design decisions, all of them about honesty
-------------------------------------------------

**Rules are data, not code** (``data/obligations.json``). Deadlines
change, differ per canton, and must be auditable. As data, a specialist
can review a diff, a customer can be shown exactly which rule produced a
date, and a correction does not require a release.

**Every rule carries its own verification status.** The engine never
decides whether a rule is legally correct - it reports what the rule
claims *and* whether anyone has confirmed it. An unverified rule is
still useful as a working reminder; presenting it as legal advice would
not be. The distinction is preserved all the way to the UI.

**A deadline computed from a guessed trigger date is marked as
estimated.** The obligations that matter are anchored to real events -
arrival, contract start, permit expiry. Where the case does not record
that date, the engine says so rather than quietly substituting the date
the case was opened and presenting the result as a legal deadline.
"""

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta


_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

OBLIGATIONS_FILE = "obligations.json"

_CACHE = {}


# --- Verification status -------------------------------------------------

VERIFIED = "verified"
UNVERIFIED = "unverified"
SUPERSEDED = "superseded"


# --- Urgency, reusing the vocabulary the task inbox already speaks -------

OVERDUE = "overdue"
DUE_TODAY = "due_today"
DUE_SOON = "due_soon"
UPCOMING = "upcoming"

DUE_SOON_DAYS = 14


@dataclass(frozen=True)
class Obligation:
    """
    One dated obligation for one case.

    Attributes:
        id: Stable rule identifier.
        title: What must be done.
        description: Plain-language detail.
        due_date: The computed date, or None when it cannot be computed.
        trigger: Which date it was calculated from.
        trigger_date: The value of that date, or None.
        offset_days: Days from the trigger. Negative means "before".
        severity: 'statutory' or 'administrative'.
        consequence: What happens if it is missed.
        legal_basis: The provision, once recorded.
        verification_status: See VERIFIED / UNVERIFIED / SUPERSEDED.
        verification_note: Why it is not verified, or what was checked.
        source_url: Official source, once recorded.
        reviewed_by / reviewed_on: Who confirmed it, and when.
        is_estimated: True when the trigger date was not available and the
            date is therefore indicative only.
        missing_trigger: Name of the date that would make this exact.
    """

    id: str
    title: str
    description: str
    due_date: date
    trigger: str
    trigger_date: date
    offset_days: int
    severity: str
    consequence: str
    legal_basis: str
    verification_status: str
    verification_note: str
    source_url: str
    reviewed_by: str
    reviewed_on: str
    is_estimated: bool
    missing_trigger: str

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VERIFIED

    @property
    def is_actionable(self) -> bool:
        """
        Whether this can be put in front of a user as a real deadline.

        An obligation with no computable date is still worth showing - as
        a prompt to supply the missing date - but it is not a deadline.
        """

        return self.due_date is not None

    def days_remaining(self, today):
        if self.due_date is None:
            return None
        return (self.due_date - today).days

    def urgency(self, today):
        """
        Bucket for display. None when there is no date to judge.
        """

        remaining = self.days_remaining(today)

        if remaining is None:
            return None

        if remaining < 0:
            return OVERDUE

        if remaining == 0:
            return DUE_TODAY

        if remaining <= DUE_SOON_DAYS:
            return DUE_SOON

        return UPCOMING


def _load_rules(filename=OBLIGATIONS_FILE):

    if filename in _CACHE:
        return _CACHE[filename]

    path = os.path.join(_DATA_DIR, filename)

    if not os.path.exists(path):
        return {"obligations": []}

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    _CACHE[filename] = data

    return data


def clear_cache():
    """Drop the parsed rules. Used by tests that load a different file."""

    _CACHE.clear()


def parse_date(value):
    """
    Accept a date, datetime or ISO-8601 string; return a date or None.

    Dates arrive from a TEXT column and from OCR output, so an
    unparseable value is normal and must not raise. It becomes "unknown",
    which the engine reports honestly rather than guessing around.
    """

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except (ValueError, TypeError):
            continue

    return None


def _matches(rule_values, case_value):
    """
    A null list in a rule means "applies to all", not "applies to none".

    Written out because the opposite reading would silently drop
    obligations - the failure mode nobody notices until a deadline is
    missed.
    """

    if rule_values is None:
        return True

    return case_value in rule_values


def rule_applies(rule, canton, nationality, permit, business_mode):

    scope = rule.get("applies_to", {})

    return (
        _matches(scope.get("cantons"), canton)
        and _matches(scope.get("nationalities"), nationality)
        and _matches(scope.get("permits"), permit)
        and _matches(scope.get("business_modes"), business_mode)
    )


def build_obligations(
    canton,
    nationality,
    permit,
    business_mode,
    trigger_dates=None,
    filename=OBLIGATIONS_FILE,
):
    """
    Produce every obligation that applies to a case.

    Args:
        canton / nationality / permit / business_mode: Case attributes.
        trigger_dates: Mapping of trigger name to date, e.g.
            ``{"arrival_date": date(2026, 8, 1)}``. Anything absent
            yields an obligation with no date and ``missing_trigger``
            set, rather than a date derived from something unrelated.
        filename: Rule file, overridable for tests.

    Returns:
        Obligations sorted by due date, undated ones last. Undated is not
        the same as unimportant - it means the system is missing a fact
        it needs, which is itself something to act on.
    """

    trigger_dates = {
        name: parse_date(value)
        for name, value in (trigger_dates or {}).items()
    }

    results = []

    for rule in _load_rules(filename).get("obligations", []):

        if not rule_applies(rule, canton, nationality, permit, business_mode):
            continue

        trigger_name = rule.get("trigger")
        trigger_date = trigger_dates.get(trigger_name)
        offset_days = int(rule.get("offset_days", 0))

        due_date = (
            trigger_date + timedelta(days=offset_days)
            if trigger_date is not None
            else None
        )

        verification = rule.get("verification", {})

        results.append(
            Obligation(
                id=rule.get("id", ""),
                title=rule.get("title", ""),
                description=rule.get("description", ""),
                due_date=due_date,
                trigger=trigger_name,
                trigger_date=trigger_date,
                offset_days=offset_days,
                severity=rule.get("severity", "administrative"),
                consequence=rule.get("consequence", ""),
                legal_basis=rule.get("legal_basis", ""),
                verification_status=verification.get("status", UNVERIFIED),
                verification_note=verification.get("note", ""),
                source_url=verification.get("source_url"),
                reviewed_by=verification.get("reviewed_by"),
                reviewed_on=verification.get("reviewed_on"),
                is_estimated=trigger_date is None,
                missing_trigger=None if trigger_date else trigger_name,
            )
        )

    # date.max keeps undated obligations at the end without dropping them.
    return sorted(
        results,
        key=lambda item: (item.due_date or date.max, item.id),
    )


def unverified_count(obligations):
    """
    How many of these have not been confirmed against an official source.

    Surfaced in the UI so nobody mistakes a working reminder for legal
    advice, and so the gap is visible to whoever can close it.
    """

    return sum(1 for item in obligations if not item.is_verified)


def missing_trigger_dates(obligations):
    """
    Which dates would turn estimates into real deadlines.

    Returned as a set so the UI can ask for exactly what it needs -
    "add the arrival date to get 2 more deadlines" is a far better prompt
    than a page of blanks.
    """

    return {
        item.missing_trigger
        for item in obligations
        if item.missing_trigger
    }
