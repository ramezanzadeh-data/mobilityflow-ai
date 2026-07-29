"""
Tests for case form validation.

The form had no validation at all: an empty employee name saved silently.
That is how the live database came to hold cases identified only as
"zohre" and "esmaeil" - single lowercase words, no surname, no error at
any point.

This matters beyond tidiness. The document pipeline compares the name on
an uploaded passport against the name on the case
(core/documents/validation.validate_document_against_case). A case
created with a partial name produces a mismatch warning on a document
that is actually correct, and an operator who sees enough false warnings
stops reading them.

The distinction these tests pin down is between blocking and advising:

* An **error** stops the write. Reserved for input that cannot be acted
  on - no name, no employer, a canton the rules engine does not know.
* A **warning** is shown and the operator proceeds. Reserved for input
  that is probably wrong but might not be. Mononyms exist; a product that
  refuses to save one would be wrong about the world.
"""

import pytest

from apps.web.utils.validators import (
    MAXIMUM_NAME_LENGTH,
    validate_case_form,
)


NATIONALITIES = ["EU", "NON_EU"]
CANTONS = ["VAUD", "VALAIS"]
PERMITS = ["NO_PERMIT", "N", "F", "S", "L", "B", "C", "G"]
MODES = ["SME", "RELOCATION", "RECRUITMENT"]


def check(employee_name="Anna Müller", employer="Lonza AG", **overrides):
    """Validate a submission that is valid unless overridden."""

    payload = {
        "employee_name": employee_name,
        "employer": employer,
        "nationality": "EU",
        "canton": "VAUD",
        "permit": "B",
        "business_mode": "SME",
        "valid_nationalities": NATIONALITIES,
        "valid_cantons": CANTONS,
        "valid_permits": PERMITS,
        "valid_modes": MODES,
    }
    payload.update(overrides)

    return validate_case_form(**payload)


def test_a_complete_submission_is_valid():

    result = check()

    assert result.is_valid
    assert not result.errors
    assert not result.warnings


# ------------------------------------------------------ blocking ---

@pytest.mark.parametrize("name", ["", "   ", None])
def test_an_empty_employee_name_is_rejected(name):
    """The regression this file exists for."""

    result = check(employee_name=name)

    assert not result.is_valid
    assert result.error_for("employee_name")


@pytest.mark.parametrize("employer", ["", "   ", None])
def test_an_empty_employer_is_rejected(employer):
    """Permit eligibility depends on the employing entity."""

    result = check(employer=employer)

    assert not result.is_valid
    assert result.error_for("employer")


def test_a_single_character_name_is_rejected():

    assert not check(employee_name="A").is_valid


def test_a_name_without_letters_is_rejected():

    assert not check(employee_name="12345").is_valid


def test_an_overlong_name_is_rejected():
    """Catches a paste accident rather than a long real name."""

    assert not check(employee_name="x" * (MAXIMUM_NAME_LENGTH + 1)).is_valid


@pytest.mark.parametrize(
    "field,value",
    [
        ("nationality", "SWISS"),
        ("canton", "ZURICH"),
        ("permit", "Z"),
        ("business_mode", "FREELANCE"),
    ],
)
def test_values_outside_the_domain_vocabulary_are_rejected(field, value):
    """
    Unreachable through the select boxes, checked anyway.

    This function is the contract for anything that writes a case. A
    canton the rules engine has never heard of would score its risk as if
    the canton contributed nothing - a silently wrong compliance figure,
    which is the worst kind for this product.
    """

    result = check(**{field: value})

    assert not result.is_valid
    assert result.error_for(field)


def test_every_problem_is_reported_at_once():
    """
    A form that reveals one error at a time makes the user submit
    repeatedly to discover them all.
    """

    result = check(employee_name="", employer="", canton="ZURICH")

    assert set(result.errors) == {"employee_name", "employer", "canton"}


# ------------------------------------------------------ advisory ---

def test_a_single_word_name_warns_but_does_not_block():
    """
    Mononyms are real. The product may say "this is probably incomplete";
    it may not say "this person cannot exist".
    """

    result = check(employee_name="zohre")

    assert result.is_valid, "a single-word name must not block the save"
    assert result.warning_for("employee_name")


def test_a_full_name_produces_no_warning():

    assert not check(employee_name="Roghaieh Ramezanzadeh").warnings


def test_warnings_never_appear_in_errors():
    """
    The two channels drive different behaviour - one returns early, the
    other does not - so they must not overlap.
    """

    result = check(employee_name="zohre")

    assert not set(result.errors) & set(result.warnings)


# ------------------------------------------------------ whitespace ---

def test_surrounding_whitespace_does_not_make_a_name_valid():

    assert not check(employee_name="   ").is_valid


def test_a_padded_name_is_accepted_and_the_caller_trims_it():
    """
    Validation accepts it; the view stores the trimmed value. Recorded
    here because " Anna Müller " and "Anna Müller" must not become two
    different people in the document-matching step.
    """

    assert check(employee_name="  Anna Müller  ").is_valid
