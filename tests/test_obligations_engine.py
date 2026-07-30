"""
Tests for the statutory obligation engine.

This engine produces dates that a customer will act on, for obligations
whose failure mode is a person losing the right to work. The properties
worth pinning are therefore mostly about what the engine refuses to do:

* it never invents a deadline from a date that does not mean what the
  rule needs,
* it never presents an unverified rule as if it were confirmed law,
* it never silently drops an obligation that applies.

The rule content itself is deliberately not asserted here. These tests
use their own fixture file, so a specialist correcting a real deadline in
data/obligations.json does not break the suite - which is the point of
holding the rules as data.
"""

import json
from datetime import date

import pytest

from core.rules.obligations import (
    DUE_SOON,
    DUE_TODAY,
    OVERDUE,
    UNVERIFIED,
    UPCOMING,
    VERIFIED,
    build_obligations,
    clear_cache,
    missing_trigger_dates,
    parse_date,
    rule_applies,
    unverified_count,
)


TODAY = date(2026, 8, 1)


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    """A small rule set with known content, in place of the real one."""

    rules = {
        "obligations": [
            {
                "id": "commune_registration",
                "title": "Register at the commune",
                "description": "Register in person.",
                "applies_to": {
                    "cantons": ["VALAIS"],
                    "nationalities": None,
                    "permits": None,
                    "business_modes": None,
                },
                "trigger": "arrival_date",
                "offset_days": 14,
                "severity": "statutory",
                "consequence": "Administrative penalty.",
                "legal_basis": "",
                "verification": {"status": UNVERIFIED, "note": "not checked"},
            },
            {
                "id": "permit_renewal",
                "title": "File the renewal",
                "description": "File before expiry.",
                "applies_to": {
                    "cantons": None,
                    "nationalities": None,
                    "permits": ["B"],
                    "business_modes": None,
                },
                "trigger": "permit_expiry_date",
                "offset_days": -90,
                "severity": "statutory",
                "consequence": "Status lapses.",
                "legal_basis": "Art. X",
                "verification": {
                    "status": VERIFIED,
                    "source_url": "https://example.ch/rule",
                    "reviewed_by": "A Specialist",
                    "reviewed_on": "2026-07-01",
                    "note": "",
                },
            },
        ]
    }

    path = tmp_path / "test_obligations.json"
    path.write_text(json.dumps(rules), encoding="utf-8")

    monkeypatch.setattr("core.rules.obligations._DATA_DIR", str(tmp_path))
    clear_cache()

    yield "test_obligations.json"

    clear_cache()


def build(rules_file, canton="VALAIS", nationality="NON_EU", permit="B",
          mode="SME", **trigger_dates):

    return build_obligations(
        canton=canton,
        nationality=nationality,
        permit=permit,
        business_mode=mode,
        trigger_dates=trigger_dates,
        filename=rules_file,
    )


# ----------------------------------------------------------- dates ---

@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-01", date(2026, 8, 1)),
        ("01.08.2026", date(2026, 8, 1)),
        ("01/08/2026", date(2026, 8, 1)),
        (date(2026, 8, 1), date(2026, 8, 1)),
        (None, None),
        ("", None),
        ("next tuesday", None),
    ],
)
def test_parse_date(value, expected):
    """
    Dates arrive from a TEXT column and from OCR. An unparseable value is
    normal and must degrade to "unknown", never raise.
    """

    assert parse_date(value) == expected


# ------------------------------------------------------ scoping ---

def test_a_rule_scoped_to_another_canton_does_not_apply(rules_file):

    ids = [o.id for o in build(rules_file, canton="VAUD")]

    assert "commune_registration" not in ids


def test_a_null_scope_means_all_not_none():
    """
    The reading that matters. If null meant "matches nothing", every
    broadly-applicable obligation would silently vanish - and nobody
    notices a missing deadline until it is missed.
    """

    rule = {
        "applies_to": {
            "cantons": None,
            "nationalities": None,
            "permits": None,
            "business_modes": None,
        }
    }

    assert rule_applies(rule, "VALAIS", "NON_EU", "B", "SME")
    assert rule_applies(rule, "VAUD", "EU", "C", "RELOCATION")


def test_permit_scoped_rule_only_applies_to_that_permit(rules_file):

    assert "permit_renewal" in [o.id for o in build(rules_file, permit="B")]
    assert "permit_renewal" not in [o.id for o in build(rules_file, permit="C")]


# --------------------------------------------------- computation ---

def test_a_positive_offset_is_after_the_trigger(rules_file):

    obligation = next(
        o for o in build(rules_file, arrival_date="2026-08-01")
        if o.id == "commune_registration"
    )

    assert obligation.due_date == date(2026, 8, 15)
    assert not obligation.is_estimated


def test_a_negative_offset_is_before_the_trigger(rules_file):
    """A renewal is due *before* the permit expires, not after."""

    obligation = next(
        o for o in build(rules_file, permit_expiry_date="2026-12-31")
        if o.id == "permit_renewal"
    )

    assert obligation.due_date == date(2026, 10, 2)


def test_a_missing_trigger_date_produces_no_deadline(rules_file):
    """
    The refusal that matters most. With no arrival date, the engine must
    not substitute something unrelated - the case creation date, say -
    and present the result as a legal deadline.
    """

    obligation = next(
        o for o in build(rules_file)     # no trigger dates supplied
        if o.id == "commune_registration"
    )

    assert obligation.due_date is None
    assert obligation.is_estimated
    assert obligation.missing_trigger == "arrival_date"
    assert not obligation.is_actionable


def test_an_unparseable_trigger_date_is_treated_as_missing(rules_file):

    obligation = next(
        o for o in build(rules_file, arrival_date="whenever")
        if o.id == "commune_registration"
    )

    assert obligation.due_date is None
    assert obligation.missing_trigger == "arrival_date"


def test_missing_trigger_dates_are_reported_for_prompting(rules_file):
    """
    So the UI can ask for exactly what it needs rather than showing a
    page of blanks.
    """

    obligations = build(rules_file, permit_expiry_date="2026-12-31")

    assert missing_trigger_dates(obligations) == {"arrival_date"}


# ------------------------------------------------------ ordering ---

def test_undated_obligations_sort_last_but_are_not_dropped(rules_file):
    """
    Undated is not unimportant - it means a fact is missing, which is
    itself actionable. It must never be silently discarded.
    """

    obligations = build(rules_file, permit_expiry_date="2026-12-31")

    assert len(obligations) == 2
    assert obligations[0].id == "permit_renewal"
    assert obligations[-1].due_date is None


# ------------------------------------------------------- urgency ---

@pytest.mark.parametrize(
    "arrival,expected",
    [
        ("2026-07-01", OVERDUE),      # due 2026-07-15
        ("2026-07-18", DUE_TODAY),    # due 2026-08-01
        ("2026-07-25", DUE_SOON),     # due 2026-08-08
        ("2026-09-01", UPCOMING),     # due 2026-09-15
    ],
)
def test_urgency_buckets(rules_file, arrival, expected):

    obligation = next(
        o for o in build(rules_file, arrival_date=arrival)
        if o.id == "commune_registration"
    )

    assert obligation.urgency(TODAY) == expected


def test_an_undated_obligation_has_no_urgency(rules_file):
    """None, not "upcoming": there is nothing to judge."""

    obligation = next(
        o for o in build(rules_file) if o.id == "commune_registration"
    )

    assert obligation.urgency(TODAY) is None
    assert obligation.days_remaining(TODAY) is None


# -------------------------------------------------- verification ---

def test_verification_status_is_carried_through(rules_file):
    """
    The engine reports what a rule claims *and* whether anyone confirmed
    it. It never decides legal correctness itself.
    """

    obligations = {o.id: o for o in build(rules_file,
                                          arrival_date="2026-08-01",
                                          permit_expiry_date="2026-12-31")}

    assert not obligations["commune_registration"].is_verified
    assert obligations["commune_registration"].verification_note

    verified = obligations["permit_renewal"]
    assert verified.is_verified
    assert verified.source_url
    assert verified.reviewed_by
    assert verified.reviewed_on


def test_unverified_rules_are_countable(rules_file):
    """So the UI can warn, and the gap stays visible to whoever can close it."""

    assert unverified_count(build(rules_file, arrival_date="2026-08-01")) == 1


def test_the_shipped_rules_are_all_marked_unverified():
    """
    A guard on the real data file, not the fixture.

    Nothing in data/obligations.json has been checked against an official
    source. If someone marks a rule verified, this test fails and forces
    the reviewer's name, date and source to be recorded with it - which
    is the whole point of the provenance fields.
    """

    clear_cache()

    obligations = build_obligations(
        canton="VALAIS",
        nationality="NON_EU",
        permit="B",
        business_mode="SME",
        trigger_dates={"arrival_date": "2026-08-01"},
    )

    for obligation in obligations:
        if obligation.is_verified:
            assert obligation.reviewed_by, (
                f"'{obligation.id}' is marked verified but records no "
                f"reviewer. A verified immigration deadline must name who "
                f"confirmed it."
            )
            assert obligation.reviewed_on, f"'{obligation.id}': no review date"
            assert obligation.source_url, f"'{obligation.id}': no source"
        else:
            assert obligation.verification_note, (
                f"'{obligation.id}' is unverified and does not say why. "
                f"An unexplained gap cannot be closed by anyone."
            )


def test_every_shipped_rule_names_the_canton_it_was_written_for():
    """
    A guard on the real data file.

    The engine reads ``"cantons": null`` as "applies everywhere", and all
    three shipped rules carried it - written while the product presented
    itself as canton-agnostic. Left alone, the first canton to get a
    knowledge base would silently inherit three Valais deadlines, worded
    exactly as confidently, with no review behind them for that canton.

    A deadline reviewed for one canton is evidence about that canton and
    nothing else. Every rule must therefore say which one, and it must be
    a canton the product actually covers - a rule scoped to a canton with
    no knowledge base can never be reached, which is a rule nobody will
    notice is wrong.
    """

    import json
    from pathlib import Path

    from core.cantons import supported_cantons

    path = Path(__file__).resolve().parent.parent / "data" / "obligations.json"

    data = json.loads(path.read_text(encoding="utf-8"))

    covered = set(supported_cantons())

    for rule in data["obligations"]:

        cantons = rule["applies_to"]["cantons"]

        assert cantons, (
            f"'{rule['id']}' has no canton scope, so the engine applies it "
            f"to every canton - including ones nobody reviewed it for. "
            f"Name the canton it was written for."
        )

        unknown = set(cantons) - covered

        assert not unknown, (
            f"'{rule['id']}' is scoped to {sorted(unknown)}, which the "
            f"product does not cover. Either add the knowledge base "
            f"(data/canton_<code>_rules.json) or remove the scope - as it "
            f"stands the rule can never fire, so nobody will ever notice "
            f"if it is wrong."
        )


# --------------------------------------------- sourced, but not verified ---

def _obligation_with_status(status):
    """
    A bare Obligation carrying only a verification status.

    Built by name rather than positionally so adding a field to the
    dataclass does not silently shift what these tests are asserting
    about - the defect this project has already had once, with case row
    indices.
    """

    from core.rules.obligations import Obligation

    return Obligation(
        id=status,
        title="",
        description="",
        due_date=None,
        trigger="",
        trigger_date=None,
        offset_days=0,
        severity="",
        consequence="",
        legal_basis="",
        verification_status=status,
        verification_note="",
        source_url=None,
        reviewed_by=None,
        reviewed_on=None,
        is_estimated=False,
        missing_trigger=None,
    )



def test_sourced_is_a_third_state_not_a_synonym_for_verified():
    """
    The distinction the whole three-state design rests on.

    Finding the provision and confirming it applies are different jobs.
    A citation establishes what the federal text says; communal practice
    differs from that floor, and the edge cases - which date starts the
    clock when a contract begins remotely and the employee arrives weeks
    later - are written down nowhere.

    If is_verified were true for a sourced rule, every warning in the
    product would fall silent the moment somebody pasted in a URL, and
    the specialist review it exists to demand would look already done.
    """

    from core.rules.obligations import SOURCED, UNVERIFIED, VERIFIED

    assert SOURCED not in (VERIFIED, UNVERIFIED)


@pytest.mark.parametrize(
    "status,verified,sourced",
    [
        ("verified", True, True),
        ("sourced", False, True),
        ("unverified", False, False),
        ("superseded", False, False),
    ],
)
def test_each_status_answers_both_questions_separately(status, verified, sourced):
    """
    "Has someone taken responsibility for this?" and "can we show where
    it came from?" are different questions with different answers.
    """

    from core.rules.obligations import Obligation

    obligation = _obligation_with_status(status)

    assert obligation.is_verified is verified
    assert obligation.is_sourced is sourced


def test_a_sourced_rule_is_still_counted_as_needing_review():
    """
    unverified_count() drives the warning banner. A sourced rule has not
    been reviewed by anyone, so it belongs in that count - otherwise
    citing an article silently removes the warning that says a specialist
    has not looked at this.
    """

    from core.rules.obligations import Obligation, unverified_count

    assert unverified_count([_obligation_with_status("sourced")]) == 1
    assert unverified_count([_obligation_with_status("verified")]) == 0


def test_the_data_file_documents_every_status_the_engine_knows():
    """
    A status the engine accepts but the file does not explain is one
    nobody can use correctly - and this file is what a specialist reads
    before reviewing.
    """

    import json
    from pathlib import Path

    from core.rules.obligations import SOURCED, SUPERSEDED, UNVERIFIED, VERIFIED

    path = Path(__file__).resolve().parent.parent / "data" / "obligations.json"

    documented = json.loads(path.read_text(encoding="utf-8"))["verification_statuses"]

    assert set(documented) == {VERIFIED, SOURCED, UNVERIFIED, SUPERSEDED}

    for status, description in documented.items():
        assert len(description) > 40, (
            f"{status!r} is documented in one line; the difference between "
            f"these states is the whole point and has to be readable"
        )


def test_the_shipped_rules_record_where_they_came_from():
    """
    A guard on the research, not on the law.

    Every rule must say what it is: sourced rules carry a URL, the date
    the source was read, and which body published it; unverified rules
    explain what is still open. A status with nothing behind it is the
    state this whole exercise existed to leave.
    """

    import json
    from pathlib import Path

    from core.rules.obligations import SOURCED, UNVERIFIED

    path = Path(__file__).resolve().parent.parent / "data" / "obligations.json"

    for rule in json.loads(path.read_text(encoding="utf-8"))["obligations"]:

        verification = rule["verification"]
        status = verification["status"]

        assert verification.get("note"), (
            f"{rule['id']}: no note. A status nobody explained cannot be "
            f"acted on by the specialist who reviews it."
        )

        if status == SOURCED:
            assert verification.get("source_url"), f"{rule['id']}: no source URL"
            assert verification.get("sourced_on"), f"{rule['id']}: no date read"
            assert verification.get("sourced_from"), f"{rule['id']}: no publisher"
            assert rule.get("legal_basis"), (
                f"{rule['id']} is sourced but names no provision - which is "
                f"the one thing 'sourced' is supposed to mean"
            )

        if status == UNVERIFIED:
            assert len(verification["note"]) > 80, (
                f"{rule['id']} is unverified and the note is too short to "
                f"tell a specialist what to resolve"
            )
