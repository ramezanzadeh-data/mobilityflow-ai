"""
Workflow construction.

The workflow is a checklist a specialist works through, so a step in it
is an assertion that the step is required. Steps derived from
nationality, permit and mode are federal and apply everywhere; steps
derived from the canton are only as good as the canton knowledge base
behind them.

There used to be a Vaud branch adding "Commune registration (Vaud)".
There is no data/canton_vaud_rules.json and never was, so that step was a
guess rendered in the same list, in the same typeface, as steps that came
from somewhere. It has been removed, and the property below replaces it:
an uncovered canton adds no canton-specific steps at all.
"""

from core.workflow.engine import build_workflow


# Not a real canton code, so nobody later "fixes" this by adding a branch
# for it. The point is a canton the product has no knowledge base for.
UNCOVERED_CANTON = "UNCOVERED_CANTON"


def test_base_steps_always_present():

    workflow = build_workflow(
        nationality="EU", permit="C", canton=UNCOVERED_CANTON, mode="SME"
    )

    assert "Initial case review" in workflow
    assert "Collect identity documents" in workflow
    assert "Verify employment contract" in workflow


def test_non_eu_adds_visa_related_steps():

    workflow = build_workflow(
        nationality="NON_EU", permit="C", canton=UNCOVERED_CANTON, mode="SME"
    )

    assert "Validate visa eligibility" in workflow
    assert "Check immigration quota" in workflow


def test_eu_adds_registration_not_visa_steps():

    workflow = build_workflow(
        nationality="EU", permit="C", canton=UNCOVERED_CANTON, mode="SME"
    )

    assert "Process EU registration" in workflow
    assert "Validate visa eligibility" not in workflow


def test_permit_g_adds_cross_border_steps():

    workflow = build_workflow(
        nationality="EU", permit="G", canton=UNCOVERED_CANTON, mode="SME"
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


def test_an_uncovered_canton_adds_no_cantonal_steps():
    """
    What replaced test_vaud_adds_only_commune_registration.

    The federal part of the workflow still applies - nationality and
    permit do not depend on which canton it is - so the case is not
    useless. But the product must not invent the cantonal part, because
    a wrong step in a compliance checklist is followed, not questioned.
    """

    workflow = build_workflow(
        nationality="EU", permit="C", canton=UNCOVERED_CANTON, mode="SME"
    )

    assert "Initial case review" in workflow, (
        "the federal steps still apply and must still be produced"
    )

    cantonal = [
        step for step in workflow
        if "commune" in step.lower() or "cantonal" in step.lower()
    ]

    assert cantonal == [], (
        f"cantonal steps were produced for a canton with no knowledge "
        f"base: {cantonal}"
    )


def test_the_covered_canton_is_what_makes_the_difference():
    """
    Two cases identical but for the canton. The whole difference must be
    the covered canton's own steps - nothing else moves.
    """

    covered = build_workflow(
        nationality="EU", permit="C", canton="VALAIS", mode="SME"
    )
    uncovered = build_workflow(
        nationality="EU", permit="C", canton=UNCOVERED_CANTON, mode="SME"
    )

    assert set(uncovered) < set(covered)

    assert set(covered) - set(uncovered) == {
        "Commune registration (Valais)",
        "Cantonal approval",
    }


def test_workflow_always_ends_with_closing_step():

    workflow = build_workflow(
        nationality="NON_EU", permit="N", canton="VALAIS", mode="RELOCATION"
    )

    assert workflow[-1] == "Close relocation case"


def test_relocation_mode_adds_housing_support():

    workflow = build_workflow(
        nationality="EU", permit="C", canton=UNCOVERED_CANTON, mode="RELOCATION"
    )

    assert "Housing registration" in workflow
    assert "Family relocation support" in workflow
