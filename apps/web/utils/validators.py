"""
Input validation for the case form.

The form had none. An empty employee name saved silently, which is how
the live database ended up holding cases identified only as "zohre" and
"esmaeil" - single lowercase words, no surname, no error at any point.

For a product whose output is a compliance decision about a named person,
the name is not a nice-to-have field. A permit application built on a
half-entered case is worse than no case: it looks complete.

Design notes
------------

**Pure and framework-free.** No Streamlit import, so the rules are
testable in isolation and reusable if the REST API ever needs the same
checks - which it should, since a validation rule that only exists in one
client is a rule the other client does not have.

**Returns messages, never raises.** A form shows every problem at once;
raising on the first one would make the user fix the fields one round
trip at a time.

**Warnings are separate from errors.** An error blocks submission. A
warning is a judgement the operator is allowed to overrule - "this looks
like only a first name" is a strong hint, not a fact, and a product that
refuses to save a legitimate mononym would be wrong.
"""

from dataclasses import dataclass, field


# Long enough to catch an accidental single keystroke, short enough not
# to reject a genuinely short name.
MINIMUM_NAME_LENGTH = 2

# Guards against a paste accident filling the column, not against real
# names; Postgres would take far more.
MAXIMUM_NAME_LENGTH = 120

MAXIMUM_EMPLOYER_LENGTH = 120


@dataclass
class ValidationResult:
    """
    Outcome of validating one form submission.

    Attributes:
        errors: Field name -> message. Any entry blocks submission.
        warnings: Field name -> message. Shown, but the user may proceed.
    """

    errors: dict = field(default_factory=dict)
    warnings: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def error_for(self, field_name):
        return self.errors.get(field_name)

    def warning_for(self, field_name):
        return self.warnings.get(field_name)


def _clean(value):
    return "" if value is None else str(value).strip()


def validate_case_form(
    employee_name,
    employer,
    nationality,
    canton,
    permit,
    business_mode,
    valid_nationalities,
    valid_cantons,
    valid_permits,
    valid_modes,
) -> ValidationResult:
    """
    Validate a case submission.

    The allowed value lists are passed in rather than imported, so this
    module never becomes a second place where the domain's vocabulary is
    defined. The caller supplies the same lists it renders in the form,
    which means a select box and its validation cannot disagree.
    """

    result = ValidationResult()

    name = _clean(employee_name)

    if not name:
        result.errors["employee_name"] = (
            "Employee name is required. A case identifies a specific "
            "person; without a name it cannot be acted on."
        )

    elif len(name) < MINIMUM_NAME_LENGTH:
        result.errors["employee_name"] = (
            f"Employee name looks too short (minimum "
            f"{MINIMUM_NAME_LENGTH} characters)."
        )

    elif len(name) > MAXIMUM_NAME_LENGTH:
        result.errors["employee_name"] = (
            f"Employee name is longer than {MAXIMUM_NAME_LENGTH} "
            f"characters. Check for pasted text."
        )

    elif not any(character.isalpha() for character in name):
        result.errors["employee_name"] = (
            "Employee name must contain letters."
        )

    elif " " not in name:
        # A warning, not an error. Mononyms exist, and a permit file
        # legitimately belongs to whatever the passport says. But a
        # single word is far more often an unfinished entry, and the
        # document-validation step later compares this against the name
        # extracted from uploaded documents - a mismatch there is
        # expensive to unpick.
        result.warnings["employee_name"] = (
            "This looks like a first name only. Documents are checked "
            "against this name, so the full legal name avoids false "
            "mismatches later."
        )

    employer_name = _clean(employer)

    if not employer_name:
        result.errors["employer"] = (
            "Employer is required. Permit eligibility depends on the "
            "employing entity."
        )

    elif len(employer_name) > MAXIMUM_EMPLOYER_LENGTH:
        result.errors["employer"] = (
            f"Employer name is longer than {MAXIMUM_EMPLOYER_LENGTH} "
            f"characters. Check for pasted text."
        )

    # The select boxes make these unreachable through the UI. They are
    # checked anyway because this function is the contract: anything that
    # calls it - a future API endpoint, an import script - must not be
    # able to write a case with a canton the rules engine has never heard
    # of, which would silently score its risk as if the canton added
    # nothing.
    for value, allowed, field_name, label in [
        (nationality, valid_nationalities, "nationality", "Nationality"),
        (canton, valid_cantons, "canton", "Canton"),
        (permit, valid_permits, "permit", "Permit"),
        (business_mode, valid_modes, "business_mode", "Business mode"),
    ]:
        if _clean(value) not in allowed:
            result.errors[field_name] = (
                f"{label} '{value}' is not one of the recognised values: "
                f"{', '.join(allowed)}."
            )

    return result
