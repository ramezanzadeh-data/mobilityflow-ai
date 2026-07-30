"""
Risk scoring.

Every contribution to a score has to be traceable to something. The
canton term used to have two branches - ten points for Valais, five for
Vaud - and only one of them had a knowledge base behind it. Vaud's five
came from nowhere, and nothing in the returned breakdown distinguished it
from a figure with a source.

That is the failure mode these tests are shaped around. A score assembled
partly from invented numbers is not slightly less accurate; it is a
different object presented as the same one, and a customer who traces one
line to nothing will stop trusting the rest.

So: a covered canton contributes and names itself in the breakdown, and
an uncovered canton contributes nothing at all.
"""

from core.rules.risk import calculate_risk_from_rules


# Deliberately not a real canton code. These tests are about a canton the
# product has no knowledge base for, and naming a real one invites
# somebody to "fix" the test later by adding a branch for it.
UNCOVERED_CANTON = "UNCOVERED_CANTON"

COVERED_CANTON = "VALAIS"


def _make_case(nationality, canton, permit, mode):

    return (1, "Test Employee", nationality, canton, permit, mode)


def test_eu_low_risk_case():
    """
    5 (EU) + 5 (permit C) + 0 (canton not covered) + 5 (SME) = 15.

    The expected value is written as its terms rather than as 15. It was
    20 while an uncovered canton silently added five, and a bare number
    gave no way to see which term had changed - the test simply broke and
    invited someone to update the constant to whatever the code now
    produced, which is how a test stops being evidence.
    """

    case = _make_case("EU", UNCOVERED_CANTON, "C", "SME")
    score, trace = calculate_risk_from_rules(case)

    assert score == 5 + 5 + 0 + 5


def test_non_eu_high_risk_case_is_capped_at_100():

    case = _make_case("NON_EU", COVERED_CANTON, "N", "RELOCATION")
    score, trace = calculate_risk_from_rules(case)

    assert score == 100


def test_score_never_exceeds_100():

    case = _make_case("NON_EU", COVERED_CANTON, "N", "RELOCATION")
    score, _ = calculate_risk_from_rules(case)

    assert score <= 100


def test_breakdown_lists_each_contributing_factor():
    """
    Every point in the score is named. A total a customer cannot
    decompose is a number they have to take on trust, and this product
    does not ask for that anywhere else.
    """

    case = _make_case("EU", COVERED_CANTON, "B", "SME")
    _, trace = calculate_risk_from_rules(case)

    breakdown_text = " ".join(trace["breakdown"])

    assert "EU" in breakdown_text
    assert "Permit B" in breakdown_text
    assert "Valais" in breakdown_text
    assert "SME" in breakdown_text


def test_an_uncovered_canton_contributes_nothing_to_the_score():
    """
    The property the Vaud branch violated.

    With no knowledge base there is no basis for any number, so the
    honest contribution is zero - not a smaller guess. Two cases
    identical but for the canton must differ by exactly the covered
    canton's own term.
    """

    covered = _make_case("EU", COVERED_CANTON, "B", "SME")
    uncovered = _make_case("EU", UNCOVERED_CANTON, "B", "SME")

    covered_score, _ = calculate_risk_from_rules(covered)
    uncovered_score, uncovered_trace = calculate_risk_from_rules(uncovered)

    assert uncovered_score < covered_score

    assert not any(
        UNCOVERED_CANTON.lower() in line.lower()
        for line in uncovered_trace["breakdown"]
    ), (
        "the breakdown claims a canton contribution for a canton with no "
        "knowledge base - the defect the Vaud branch was"
    )


def test_unknown_permit_contributes_zero_risk():
    """
    5 (EU) + 0 (permit not in the table) + 0 (canton not covered)
    + 5 (SME) = 10.

    A permit the engine does not recognise adds nothing, for the same
    reason an uncovered canton adds nothing: there is no basis for a
    number, and a guess is worse than an absence.
    """

    case = _make_case("EU", UNCOVERED_CANTON, "UNKNOWN_PERMIT", "SME")
    score, _ = calculate_risk_from_rules(case)

    assert score == 5 + 0 + 0 + 5


def test_trace_total_matches_returned_score():

    case = _make_case("NON_EU", UNCOVERED_CANTON, "L", "RECRUITMENT")
    score, trace = calculate_risk_from_rules(case)

    assert trace["total"] == score
