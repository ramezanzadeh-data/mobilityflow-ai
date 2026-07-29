"""
The product covers the cantons it has knowledge bases for, and no others.

Scope used to be an opinion held in six places. The case form offered
Vaud and defaulted to it, the dashboard filter listed it, the risk engine
added five points for it, the workflow engine added a commune step for
it - and ``core.rules.rules.get_canton_knowledge("VAUD")`` returned
``None``, because ``data/canton_vaud_rules.json`` had never existed.

The result was not "partial support". A Vaud case produced a workflow, a
risk score and a document checklist rendered identically to a Valais
one, assembled from numbers nobody could trace. For a compliance
product, a confident answer with nothing behind it is the most expensive
kind of wrong, because nothing about it invites checking.

So scope is now derived: a canton is covered if and only if it has a
knowledge base file. These tests hold that line, and hold the second
property that makes narrowing safe - that records already in the database
are never rejected because of a decision taken after they were written.
"""

import json
from pathlib import Path

import pytest

from core.cantons import (
    CantonNotSupportedError,
    is_readable,
    is_selectable,
    knowledge_base_filename,
    require_supported,
    supported_cantons,
)
from core.rules.rules import get_canton_knowledge
from core.rules.risk import calculate_risk_from_rules
from core.workflow.engine import build_workflow


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

UNCOVERED_CANTON = "UNCOVERED_CANTON"


# ------------------------------------------------------------- scope ---

def test_the_product_covers_at_least_one_canton():
    """
    A zero-canton build would be a product with nothing to say. It would
    also make every other test here vacuous.
    """

    assert supported_cantons()


def test_every_covered_canton_has_a_knowledge_base_that_loads():
    """
    The invariant the whole design rests on.

    Being covered means the knowledge base exists, so there is no state
    in which a canton is offered and the data behind it is missing. That
    state is exactly what Vaud was in.
    """

    for canton in supported_cantons():

        path = REPOSITORY_ROOT / "data" / knowledge_base_filename(canton)

        assert path.exists(), f"{canton} is covered but {path.name} is missing"

        knowledge = get_canton_knowledge(canton)

        assert knowledge, f"{path.name} exists but loads as empty"
        assert knowledge.get("_meta"), (
            f"{path.name} has no _meta block, so its provenance and "
            f"verification status cannot be shown to a customer"
        )


def test_a_canton_without_a_knowledge_base_is_not_selectable():

    assert not is_selectable(UNCOVERED_CANTON)
    assert not is_selectable("")
    assert not is_selectable(None)


def test_selectability_is_case_insensitive():
    """
    Canton codes reach this from a form, from OCR and from the API. A
    lower-cased code is the same canton, not an unknown one.
    """

    covered = supported_cantons()[0]

    assert is_selectable(covered.lower())
    assert require_supported(covered.lower()) == covered


def test_requiring_an_uncovered_canton_raises_rather_than_returning_empty():
    """
    Silence was the original defect. get_canton_knowledge() returned
    None for Vaud and every caller carried on, so the product produced
    output for a canton it knew nothing about without one line of code
    noticing.
    """

    with pytest.raises(CantonNotSupportedError) as raised:
        require_supported(UNCOVERED_CANTON)

    message = str(raised.value)

    assert UNCOVERED_CANTON in message
    assert supported_cantons()[0] in message, (
        "the error should say what *is* covered - otherwise the reader "
        "knows only that they are wrong, not what to do"
    )


# --------------------------------------------------- existing records ---

def test_a_case_in_an_uncovered_canton_is_still_readable():
    """
    Narrowing scope must never make a customer's existing records
    inaccessible. The record exists; the decision to stop offering that
    canton came afterwards and cannot retroactively invalidate it.
    """

    assert is_readable(UNCOVERED_CANTON)


def test_readable_and_selectable_are_different_questions():
    """
    They were the same question, which is why narrowing scope looked
    like it required deleting data. Keeping them apart is what makes
    "we only cover Valais" a product decision rather than a migration.
    """

    assert is_readable(UNCOVERED_CANTON)
    assert not is_selectable(UNCOVERED_CANTON)


# ------------------------------------------------ derived output ---

def test_no_cantonal_workflow_steps_for_an_uncovered_canton():

    workflow = build_workflow(
        nationality="EU", permit="B", canton=UNCOVERED_CANTON, mode="SME"
    )

    assert workflow, "the federal steps still apply"

    assert not [
        step for step in workflow
        if "commune" in step.lower() or "cantonal" in step.lower()
    ]


def test_no_canton_risk_contribution_for_an_uncovered_canton():

    case = (1, "Test", "EU", UNCOVERED_CANTON, "B", "SME")

    _, trace = calculate_risk_from_rules(case)

    assert not [
        line for line in trace["breakdown"]
        if UNCOVERED_CANTON.lower() in line.lower()
    ]


# ------------------------------------------------------- consistency ---

@pytest.mark.parametrize(
    "view",
    ["apps/web/views/create_case.py", "apps/web/views/dashboard.py"],
)
def test_no_view_hardcodes_a_canton_list(view):
    """
    The screens derive their options; they do not keep their own list.

    Parsed rather than searched as text, so the explanatory comments in
    those files - which name Vaud precisely because it is the thing that
    went wrong - do not trip the check.

    What is prohibited is a list literal of canton-shaped strings. That
    is the exact shape of ["VAUD", "VALAIS"], which outlived the Vaud
    knowledge base by however long it took to notice, because nothing
    connected the two.
    """

    import ast

    tree = ast.parse((REPOSITORY_ROOT / view).read_text(encoding="utf-8"))

    known_codes = set(supported_cantons()) | {
        "VAUD", "GENEVA", "GENEVE", "ZURICH", "ZUERICH", "BERN", "BERNE",
        "TICINO", "FRIBOURG", "NEUCHATEL", "JURA", "LUZERN",
    }

    offenders = []

    for node in ast.walk(tree):

        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            continue

        codes = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant)
            and isinstance(element.value, str)
            and element.value in known_codes
        ]

        if codes:
            offenders.append(f"line {node.lineno}: {codes}")

    assert not offenders, (
        f"{view} contains a hardcoded canton list:\n"
        + "\n".join(f"  - {entry}" for entry in offenders)
        + "\n\nDerive it from core.cantons.supported_cantons() instead. A "
          "list here can outlive the knowledge base it was written for, "
          "which is how the product came to offer a canton it knew "
          "nothing about."
    )


@pytest.mark.parametrize(
    "view",
    ["apps/web/views/create_case.py", "apps/web/views/dashboard.py"],
)
def test_each_view_derives_its_cantons_from_one_place(view):

    source = (REPOSITORY_ROOT / view).read_text(encoding="utf-8")

    assert "supported_cantons" in source, (
        f"{view} no longer reads the covered cantons from core.cantons"
    )


# ------------------------------------------ editing an existing record ---
#
# The case form validates against the same list it offers, so these two
# tests are really about one thing: whether narrowing the scope silently
# turned some of the customer's existing cases into records that can be
# opened but never saved again.

def test_a_new_case_cannot_be_created_in_an_uncovered_canton():

    from apps.web.utils.validators import validate_case_form

    result = validate_case_form(
        employee_name="Anna Müller",
        employer="Lonza AG",
        nationality="EU",
        canton=UNCOVERED_CANTON,
        permit="B",
        business_mode="SME",
        valid_nationalities=["EU", "NON_EU"],
        valid_cantons=list(supported_cantons()),
        valid_permits=["B"],
        valid_modes=["SME"],
    )

    assert not result.is_valid
    assert "canton" in result.errors


def test_an_existing_case_in_an_uncovered_canton_can_still_be_saved():
    """
    The half that is easy to forget.

    Refusing the canton everywhere would leave a customer with records
    they can open, edit and then not save - the worst of the three, since
    they only discover it after retyping something. The form adds the
    case's own canton to the vocabulary when editing, so an existing
    record stays workable while the canton remains unofferable to new
    ones.
    """

    from apps.web.utils.validators import validate_case_form

    # What create_case.py builds when editing a case whose canton is no
    # longer covered.
    vocabulary_when_editing = list(supported_cantons()) + [UNCOVERED_CANTON]

    result = validate_case_form(
        employee_name="Anna Müller",
        employer="Lonza AG",
        nationality="EU",
        canton=UNCOVERED_CANTON,
        permit="B",
        business_mode="SME",
        valid_nationalities=["EU", "NON_EU"],
        valid_cantons=vocabulary_when_editing,
        valid_permits=["B"],
        valid_modes=["SME"],
    )

    assert result.is_valid, (
        "an existing case in an uncovered canton can no longer be saved - "
        "narrowing the scope has made the customer's own data unusable"
    )


def test_the_case_form_widens_its_vocabulary_only_for_the_edited_case():
    """
    The widening is one canton - the one already on the record - not a
    general escape hatch. Read from the source because the property is
    structural: it must come from canton_default, so it cannot admit any
    canton other than the one being edited.
    """

    source = (
        REPOSITORY_ROOT / "apps" / "web" / "views" / "create_case.py"
    ).read_text(encoding="utf-8")

    assert "canton_options + [canton_default]" in source, (
        "the case form no longer re-admits the edited case's own canton, "
        "so an existing record in an uncovered canton cannot be saved"
    )


def test_the_shipped_obligation_rules_only_cover_supported_cantons():
    """
    A rule scoped to a canton nobody covers can never fire, so nobody
    will ever notice that it is wrong. A rule scoped to nothing at all
    fires for every canton, including ones it was never reviewed for.
    Both are silent.
    """

    path = REPOSITORY_ROOT / "data" / "obligations.json"

    data = json.loads(path.read_text(encoding="utf-8"))

    covered = set(supported_cantons())

    for rule in data["obligations"]:

        cantons = rule["applies_to"]["cantons"]

        assert cantons, f"'{rule['id']}' applies to every canton"
        assert set(cantons) <= covered, (
            f"'{rule['id']}' is scoped to a canton with no knowledge base"
        )
