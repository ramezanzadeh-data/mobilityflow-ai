
from core.rules.risk import calculate_risk_from_rules


def _make_case(nationality, canton, permit, mode):

    return (1, "Test Employee", nationality, canton, permit, mode)


def test_eu_low_risk_case():

    case = _make_case("EU", "VAUD", "C", "SME")
    score, trace = calculate_risk_from_rules(case)


    assert score == 20


def test_non_eu_high_risk_case_is_capped_at_100():

    case = _make_case("NON_EU", "VALAIS", "N", "RELOCATION")
    score, trace = calculate_risk_from_rules(case)


    assert score == 100


def test_score_never_exceeds_100():

    case = _make_case("NON_EU", "VALAIS", "N", "RELOCATION")
    score, _ = calculate_risk_from_rules(case)

    assert score <= 100


def test_breakdown_lists_each_contributing_factor():

    case = _make_case("EU", "VAUD", "B", "SME")
    _, trace = calculate_risk_from_rules(case)

    breakdown_text = " ".join(trace["breakdown"])

    assert "EU" in breakdown_text
    assert "Permit B" in breakdown_text
    assert "Vaud" in breakdown_text
    assert "SME" in breakdown_text


def test_unknown_permit_contributes_zero_risk():

    case = _make_case("EU", "VAUD", "UNKNOWN_PERMIT", "SME")
    score, _ = calculate_risk_from_rules(case)


    assert score == 15


def test_trace_total_matches_returned_score():

    case = _make_case("NON_EU", "VAUD", "L", "RECRUITMENT")
    score, trace = calculate_risk_from_rules(case)

    assert trace["total"] == score
