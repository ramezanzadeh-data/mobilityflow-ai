import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.ai.intent import Intent, classify_intent, OPERATIONAL_INTENTS


_READ_ONLY_INTENTS = {Intent.ANALYZE, Intent.STATUS, Intent.CHECK_BLOCKERS}


# Every phrasing below names one of the operational verbs the product
# requirement lists explicitly (Assign, Delete, Approve, Reject, Close,
# Archive, Update, Edit, Submit, Advance) plus direct synonyms already
# present in the codebase's own keyword tables. Every single one MUST
# resolve to an operational intent - never ANALYZE/STATUS/CHECK_BLOCKERS.
_OPERATIONAL_PHRASES = [
    ("Approve this case.", Intent.APPROVE_CASE),
    ("Please approve the relocation case.", Intent.APPROVE_CASE),
    ("Reject this case.", Intent.REJECT_CASE),
    ("Please deny the case.", Intent.REJECT_CASE),
    ("Decline this case.", Intent.REJECT_CASE),
    ("Delete case 12.", Intent.DELETE_CASE),
    ("Please erase this case.", Intent.DELETE_CASE),
    ("Remove this case.", Intent.DELETE_CASE),
    ("Close this case.", Intent.CLOSE_CASE),
    ("Mark case as closed.", Intent.CLOSE_CASE),
    ("Archive this case.", Intent.ARCHIVE_CASE),
    ("Please archive the case.", Intent.ARCHIVE_CASE),
    ("Submit this case for review.", Intent.ADVANCE_WORKFLOW),
    ("Advance the workflow.", Intent.ADVANCE_WORKFLOW),
    ("Move this case to the next stage.", Intent.ADVANCE_WORKFLOW),
    ("Assign this case to Maria.", Intent.ASSIGN_TASK),
    ("Please reassign this task.", Intent.ASSIGN_TASK),
    ("Please hand off this case to the compliance team.", Intent.ASSIGN_TASK),
    ("Create a task to collect the missing form.", Intent.CREATE_TASK),
    ("Add a follow-up reminder.", Intent.CREATE_TASK),
    ("Upload the missing document.", Intent.DOCUMENT_ACTION),
    ("Update the document status to received.", Intent.DOCUMENT_ACTION),
    ("Edit the uploaded document.", Intent.DOCUMENT_ACTION),
    ("Update the case details.", Intent.GENERIC_ACTION),
    ("Edit the employee information.", Intent.GENERIC_ACTION),
    ("Please modify the case.", Intent.GENERIC_ACTION),
    # Verbs with no specific keyword table at all - must still be
    # caught by the trailing safety net, never fall to ANALYZE.
    ("Terminate this case.", Intent.GENERIC_ACTION),
    ("Please confirm the change.", Intent.GENERIC_ACTION),
    ("Cancel this request.", Intent.GENERIC_ACTION),
    ("Revoke the approval.", Intent.APPROVE_CASE),
]


def test_every_operational_phrase_resolves_to_the_expected_intent():
    for phrase, expected_intent in _OPERATIONAL_PHRASES:
        assert classify_intent(phrase) == expected_intent, phrase


def test_no_operational_phrase_ever_falls_through_to_a_read_only_intent():
    for phrase, _expected_intent in _OPERATIONAL_PHRASES:
        classified = classify_intent(phrase)
        assert classified not in _READ_ONLY_INTENTS, (
            f"{phrase!r} was misclassified as read-only intent "
            f"{classified.value!r}"
        )
        assert classified in OPERATIONAL_INTENTS, (
            f"{phrase!r} classified as {classified.value!r}, which is "
            "not registered as operational."
        )


def test_document_update_is_more_specific_than_generic_update():
    # "update document ..." must win over the generic update/edit
    # catch-all, since DOCUMENT_ACTION already has a real tool.
    assert classify_intent("Update document status.") == Intent.DOCUMENT_ACTION


def test_analytical_phrasing_with_a_generic_noun_is_not_swept_into_action():
    # "give me an update" does not start with the verb "update", so the
    # anchored safety net must not fire - this stays a genuine ANALYZE
    # request, not an operational one.
    assert classify_intent("Can you give me an update on this case?") in (
        Intent.ANALYZE,
        Intent.STATUS,
    )


def test_read_only_requests_still_classify_as_read_only():
    assert classify_intent("What is the status of this case?") == Intent.STATUS
    assert classify_intent("What is blocking this case?") == Intent.CHECK_BLOCKERS
    assert classify_intent("Analyze the risk on this case.") == Intent.ANALYZE
    assert classify_intent("") == Intent.ANALYZE
