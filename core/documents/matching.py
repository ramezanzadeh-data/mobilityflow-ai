"""
Deciding which checklist item an uploaded document satisfies.

The case checklist and the AI classifier use different vocabularies and
always have:

    checklist row      "Passport Copy"
    classified type    "Passport"

``core.documents.document_processing_service._find_or_create_document``
compared them with ``==``. It never matched, so uploading a passport
created a *second* document row named "Passport" with status UPLOADED and
left "Passport Copy" sitting at MISSING. The user saw the upload succeed
and the checklist unchanged, and fixed it by hand.

What this module will and will not do
-------------------------------------
It normalises - case, whitespace, punctuation - and it consults an
explicit table of known equivalences. It does not do fuzzy or semantic
matching.

That restraint is the point. This is a compliance checklist: marking an
item received means the case is one document closer to being submittable.
A fuzzy match that pairs an employment contract with "Employment
Confirmation" makes a missing document look present, and nothing
downstream would question it - the risk engine, the workflow gate and the
submission readiness check all read the status, not the file.

So the rule is: match only what is certain, and return None otherwise.
Returning None is not a failure; it means a human chooses, which is what
the automatic tab now asks them to do with the best guess pre-selected.
"""

import re


# Classified type -> the checklist name that type satisfies.
#
# One-directional and explicit. Written out rather than derived because
# each line is a claim that one document discharges one obligation, and
# that is a claim somebody should have to write down.
#
# The classifier's vocabulary is fixed in
# core/ai/prompts.build_document_classification_prompt; the checklist
# names come from apps/web/views/create_case.py and the workflow engine.
# test_document_matching.py checks that both sides of this table are
# still real values on both sides.
KNOWN_EQUIVALENCES = {
    "passport": "Passport Copy",
    "employment contract": "Employment Contract",
    "cv": "CV",
    "visa": "Entry Visa",
    "entry visa": "Entry Visa",
    "permit application": "Permit Application",
    "commune registration": "Commune Registration",
}

# Returned by the classifier when it cannot tell. Never matched to
# anything: "Other" satisfies no obligation.
UNCLASSIFIED = "other"


def normalise(name):
    """
    A comparable form of a document name.

    Lower-cased, punctuation dropped, runs of whitespace collapsed. This
    is what makes "Passport  copy" and "Passport Copy" the same row, and
    it is deliberately the whole of the tolerance: two names that differ
    by a word are two different documents.
    """

    if not name:
        return ""

    without_punctuation = re.sub(r"[^\w\s]", " ", str(name))

    return re.sub(r"\s+", " ", without_punctuation).strip().lower()


def find_matching_document(documents, name):
    """
    The checklist row ``name`` refers to, or None.

    Args:
        documents: Rows from db.database.get_documents(case_id); the
            document name is at index 2 and its status at index 3.
        name: A checklist name or a classified document type.

    Returns:
        The matching row, or None if nothing matches with certainty.

    Prefers a row that is still MISSING when two rows normalise the same
    way. Uploading a second passport should satisfy the outstanding item
    rather than overwrite the one already provided.
    """

    if not name or not documents:
        return None

    target = normalise(name)

    if not target or target == UNCLASSIFIED:
        return None

    candidates = [
        document for document in documents
        if normalise(document[2]) == target
    ]

    if not candidates:
        equivalent = KNOWN_EQUIVALENCES.get(target)

        if equivalent:
            candidates = [
                document for document in documents
                if normalise(document[2]) == normalise(equivalent)
            ]

    if not candidates:
        return None

    outstanding = [
        document for document in candidates if document[3] == "MISSING"
    ]

    return (outstanding or candidates)[0]


def suggest_document_for_classification(documents, classified_type):
    """
    The checklist row an AI-classified document most likely satisfies.

    Used to pre-select the attachment dropdown, never to attach on its
    own. The distinction matters: a pre-selection a human confirms is a
    suggestion, and the same value applied silently is the product
    asserting that a compliance obligation is discharged on the strength
    of a classification nobody checked.

    Returns None when there is no certain match, which leaves the
    dropdown on "choose one" rather than on a plausible wrong answer.
    """

    return find_matching_document(documents, classified_type)
