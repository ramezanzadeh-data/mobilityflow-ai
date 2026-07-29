
from core.workflow.engine import build_workflow


def test_base_steps_always_present():

    workflow = build_workflow(
        nationality="EU", permit="C", canton="VAUD", mode="SME"
    )

    assert "Initial case review" in workflow
    assert "Collect identity documents" in workflow
    assert "Verify employment contract" in workflow


def test_non_eu_adds_visa_related_steps():

    workflow = build_workflow(
        nationality="NON_EU", permit="C", canton="VAUD", mode="SME"
    )

    assert "Validate visa eligibility" in workflow
    assert "Check immigration quota" in workflow


def test_eu_adds_registration_not_visa_steps():

    workflow = build_workflow(
        nationality="EU", permit="C", canton="VAUD", mode="SME"
    )

    assert "Process EU registration" in workflow
    assert "Validate visa eligibility" not in workflow


def test_permit_g_adds_cross_border_steps():

    workflow = build_workflow(
        nationality="EU", permit="G", canton="VAUD", mode="SME"
    )

    assert "Cross-border worker verification" in workflow
    assert "Tax registration" in workflow
    assert "Social insurance registration" in workflow


def test_valais_adds_commune_and_cantonal_approval():

    workflow = build_workflow(
        nationality="EU", permit="C", canton="VALAIS", mode="SME"
    )

    assert "Commune registration (Valais)" in workflow
    assert "Cantonal approval" in workflow


def test_vaud_adds_only_commune_registration():

    workflow = build_workflow(
        nationality="EU", permit="C", canton="VAUD", mode="SME"
    )

    assert "Commune registration (Vaud)" in workflow
    assert "Cantonal approval" not in workflow


def test_workflow_always_ends_with_closing_step():

    workflow = build_workflow(
        nationality="NON_EU", permit="N", canton="VALAIS", mode="RELOCATION"
    )

    assert workflow[-1] == "Close relocation case"


def test_relocation_mode_adds_housing_support():

    workflow = build_workflow(
        nationality="EU", permit="C", canton="VAUD", mode="RELOCATION"
    )

    assert "Housing registration" in workflow
    assert "Family relocation support" in workflow
