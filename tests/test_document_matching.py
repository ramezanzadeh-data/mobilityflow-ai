"""
An uploaded document has to reach the checklist item it satisfies.

The reported symptom: upload a document, watch the AI operator report
success, and find the checklist row still at MISSING. Two independent
causes, both silent.

1. The page called ``run_ai_operator(case, bytes)`` with no
   ``target_doc_id``. Inside, the only write that sets status='UPLOADED'
   was guarded by ``if target_doc_id:``. Every other branch ran - OCR,
   classification, risk, tasks - so the run genuinely succeeded at
   everything except the one thing the user was watching for.

2. ``_find_or_create_document`` matched names with ``==``, and the two
   vocabularies never agree: the checklist writes "Passport Copy", the
   classifier returns "Passport". So a passport upload created a *second*
   row and left the first at MISSING.

Both are worse than a crash. A missing document that looks present is
read as present by the risk engine, the workflow gate and the submission
readiness check, none of which re-open the file.
"""

import pytest

from core.documents.matching import (
    KNOWN_EQUIVALENCES,
    UNCLASSIFIED,
    find_matching_document,
    normalise,
    suggest_document_for_classification,
)


def document(doc_id, name, status="MISSING"):
    """A row shaped like db.database.get_documents(): (id, case_id, name, status, ...)."""

    return (doc_id, 1, name, status)


CHECKLIST = [
    document(1, "Passport Copy"),
    document(2, "Employment Contract"),
    document(3, "CV"),
]


# ------------------------------------------------------- normalisation ---

@pytest.mark.parametrize(
    "left,right",
    [
        ("Passport Copy", "passport copy"),
        ("Passport  Copy", "Passport Copy"),
        ("  Passport Copy  ", "Passport Copy"),
        ("Permit Application", "permit  application"),
        ("Commune Registration", "Commune registration"),
    ],
)
def test_names_differing_only_in_case_or_spacing_are_the_same_document(
    left, right
):
    assert normalise(left) == normalise(right)


@pytest.mark.parametrize(
    "left,right",
    [
        ("Passport Copy", "Passport Photo"),
        ("Employment Contract", "Employment Confirmation"),
        ("Entry Visa", "Exit Visa"),
    ],
)
def test_names_differing_by_a_word_are_different_documents(left, right):
    """
    The boundary of the tolerance.

    Anything looser is guessing, and a guess here marks a compliance
    obligation discharged on evidence nobody checked.
    """

    assert normalise(left) != normalise(right)


# ------------------------------------------------------------ matching ---

def test_an_exact_name_matches():
    assert find_matching_document(CHECKLIST, "Employment Contract")[0] == 2


def test_the_classifier_vocabulary_reaches_the_checklist_vocabulary():
    """
    The second defect, directly.

    "Passport" is what the classifier returns; "Passport Copy" is what
    the checklist calls it. With ``==`` these never met, and every
    passport upload created a duplicate row.
    """

    matched = find_matching_document(CHECKLIST, "Passport")

    assert matched is not None, (
        "a classified 'Passport' still does not reach the 'Passport Copy' "
        "checklist row - this is the mismatch that created duplicate "
        "documents and left the original MISSING"
    )
    assert matched[0] == 1


def test_an_unknown_name_matches_nothing_rather_than_the_closest_thing():
    """
    None is the correct answer, not the nearest row.

    Returning a best guess here is what makes a wrong attachment silent.
    None sends the decision to a person, which is what the page now asks
    for.
    """

    assert find_matching_document(CHECKLIST, "Bank Statement") is None


def test_an_unclassifiable_document_matches_nothing():
    """
    The classifier returns "Other" when it cannot tell. "Other" satisfies
    no obligation, and attaching it to whatever sorts first would be the
    worst possible reading of an explicit "I do not know".
    """

    assert find_matching_document(CHECKLIST, UNCLASSIFIED) is None
    assert find_matching_document(CHECKLIST, "Other") is None


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_empty_name_matches_nothing(empty):
    assert find_matching_document(CHECKLIST, empty) is None


def test_an_empty_checklist_matches_nothing():
    assert find_matching_document([], "Passport") is None


def test_an_outstanding_row_is_preferred_over_one_already_received():
    """
    Two rows for the same document, one already provided. A second upload
    should satisfy the outstanding one rather than overwrite the record of
    the first.
    """

    documents = [
        document(1, "Passport Copy", status="UPLOADED"),
        document(2, "Passport Copy", status="MISSING"),
    ]

    assert find_matching_document(documents, "Passport Copy")[0] == 2


# -------------------------------------------------------- suggestions ---

def test_a_suggestion_is_offered_for_a_classified_document():

    suggestion = suggest_document_for_classification(CHECKLIST, "Passport")

    assert suggestion is not None and suggestion[0] == 1


def test_no_suggestion_is_invented_when_nothing_matches():
    """
    The dropdown then opens on the first row with nothing claiming it is
    the right one, rather than on a plausible wrong answer the user
    confirms without reading.
    """

    assert suggest_document_for_classification(CHECKLIST, "Bank Statement") is None
    assert suggest_document_for_classification(CHECKLIST, "Other") is None


# ------------------------------------------------------ the table itself ---

def test_every_equivalence_names_a_type_the_classifier_can_return():
    """
    A left-hand side the classifier never produces is a line that can
    never fire - dead configuration that reads as coverage.
    """

    from core.ai.prompts import build_document_classification_prompt

    prompt = build_document_classification_prompt("text").lower()

    for classified_type in KNOWN_EQUIVALENCES:
        assert f'"{classified_type}"' in prompt, (
            f"{classified_type!r} is mapped here but is not in the "
            f"classifier's vocabulary, so this line can never match"
        )


def test_the_equivalence_table_is_normalised_on_the_left():
    """
    Lookups are done on normalised text. A capitalised key would simply
    never be found, and the failure is a document that quietly does not
    match rather than an error.
    """

    for classified_type in KNOWN_EQUIVALENCES:
        assert normalise(classified_type) == classified_type
