
import pytest

from core.workflow.transitions import (
    apply_scenario,
    SCENARIO_JOB_CHANGE,
    SCENARIO_PERMIT_RENEWAL,
    SCENARIO_FAMILY_TRANSFER,
    SCENARIO_CANTON_CHANGE,
    SCENARIO_CONTRACT_TERMINATION,
)


def _make_case(nationality="EU", canton="VAUD", permit="B"):
    return (1, "Test Employee", nationality, canton, permit, "SME", "Employer")


def test_unknown_scenario_raises():

    with pytest.raises(ValueError):
        apply_scenario("NOT_A_REAL_SCENARIO", _make_case())


def test_job_change_adds_permit_reapproval_for_non_eu():

    case = _make_case(nationality="NON_EU")
    result = apply_scenario(SCENARIO_JOB_CHANGE, case)

    assert any("re-approval" in step.lower() for step in result["steps"])


def test_job_change_skips_reapproval_for_eu():

    case = _make_case(nationality="EU")
    result = apply_scenario(SCENARIO_JOB_CHANGE, case)

    assert not any("re-approval" in step.lower() for step in result["steps"])


def test_permit_renewal_adds_contract_check_for_l_permit():

    case = _make_case(permit="L")
    result = apply_scenario(SCENARIO_PERMIT_RENEWAL, case)

    assert any("fixed-term contract" in step.lower() for step in result["steps"])


def test_family_transfer_returns_expected_documents():

    case = _make_case()
    result = apply_scenario(SCENARIO_FAMILY_TRANSFER, case)

    assert "Family Member Passports" in result["documents"]


def test_canton_change_includes_deregistration_step():

    case = _make_case()
    result = apply_scenario(SCENARIO_CANTON_CHANGE, case)

    assert any("de-register" in step.lower() for step in result["steps"])


def test_contract_termination_adds_grace_period_review_for_non_eu():

    case = _make_case(nationality="NON_EU")
    result = apply_scenario(SCENARIO_CONTRACT_TERMINATION, case)

    assert any("grace period" in step.lower() for step in result["steps"])


def test_canton_note_present_for_valais():

    case = _make_case(canton="VALAIS")
    result = apply_scenario(SCENARIO_PERMIT_RENEWAL, case)

    assert result["canton_note"] is not None


def test_canton_note_none_for_uncovered_canton():

    case = _make_case(canton="ZURICH")
    result = apply_scenario(SCENARIO_PERMIT_RENEWAL, case)

    assert result["canton_note"] is None
