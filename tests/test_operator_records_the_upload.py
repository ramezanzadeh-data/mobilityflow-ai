"""
Uploading a document must actually change its status.

The whole point of the AI operator, from the user's side, is that
uploading a file moves a checklist item from MISSING to UPLOADED. That
one write - ``save_document_analysis`` - was guarded by
``if target_doc_id:`` and the page never passed a target. Everything else
in the run worked, "AI operator finished" appeared, and the checklist
stayed exactly where it was.

Silent, and worse than a crash. A missing document that looks present is
read as present by the risk engine, the workflow gate and the submission
readiness check; none of them re-open the file. The user's own correction
- setting the dropdown by hand - is the only thing that made the record
true.

These tests hold two properties:

  * given a target, the operator records the upload;
  * without one it records nothing *and says so*, rather than reporting
    success for a status change that did not happen.

No database and no LLM: the collaborators are replaced, because the
question is whether the call is made, not what it writes.
"""

import pytest


@pytest.fixture
def operator(monkeypatch):
    """
    core.ai.operator with its slow and stateful collaborators replaced.

    OCR and classification are stubbed to fixed values; every database
    write is recorded rather than performed. The module is imported
    inside the fixture so the patches are in place first.
    """

    from core.ai import operator as module

    recorded = {"analysis_saved": []}

    monkeypatch.setattr(
        module, "extract_text_from_pdf",
        lambda file_bytes: {"text": "extracted text", "method": "native"},
    )
    monkeypatch.setattr(
        module, "classify_and_summarize_document",
        lambda text: {
            "document_type": "Passport",
            "key_facts": {"surname": "Müller"},
            "summary": "A passport.",
        },
    )
    def fake_save(**kwargs):
        recorded["analysis_saved"].append(kwargs)
        # Mirrors the real signature: True when a row was written.
        return recorded.get("write_succeeds", True)

    monkeypatch.setattr(module, "save_document_analysis", fake_save)

    monkeypatch.setattr(module, "validate_document_against_case", lambda f, c: [])
    monkeypatch.setattr(module, "check_expiry", lambda facts: ("unknown", None))
    monkeypatch.setattr(module, "get_documents", lambda case_id: [])
    monkeypatch.setattr(
        module, "analyze_documents",
        lambda case, docs: {"missing_documents": [], "risk_factors": [],
                            "compliance_score": 100},
    )
    monkeypatch.setattr(
        module, "calculate_risk_from_rules",
        lambda case: (20, {"total": 20, "breakdown": []}),
    )
    monkeypatch.setattr(
        module, "build_workflow_from_rules", lambda case: ([], [], [])
    )
    monkeypatch.setattr(module, "normalize_legacy_state", lambda state: "DRAFT")
    monkeypatch.setattr(module, "get_next_state", lambda state: None)
    monkeypatch.setattr(module, "generate_email", lambda *a, **k: "draft")
    monkeypatch.setattr(module, "add_task", lambda *a, **k: None)
    monkeypatch.setattr(module, "set_task_due_date", lambda *a, **k: None)
    monkeypatch.setattr(module, "log_case_event", lambda *a, **k: None)

    module._recorded = recorded

    return module


# Shaped like db.database.load_case(): the operator reads case[8]
# (workflow_state) as well as the leading fields, so a short tuple raises
# IndexError long before reaching the behaviour under test.
CASE = (
    1,                      # id
    "Anna Müller",          # employee_name
    "EU",                   # nationality
    "VALAIS",               # canton
    "B",                    # permit
    "SME",                  # business_mode
    "Lonza AG",             # employer
    "OPEN",                 # status
    "DRAFT",                # workflow_state
    20,                     # risk_level
    "",                     # ai_summary
    "Acme AG",              # company
    "pytest",               # assigned_to
    "2026-07-01",           # created_at
    "",                     # case_history
    "",                     # audit_log
    1,                      # tenant_id
    None,                   # arrival_date
    None,                   # contract_start_date
    None,                   # permit_expiry_date
    None,                   # correspondence_language
)


def test_a_target_document_is_recorded_as_uploaded(operator):
    """
    The defect, directly. This assertion failing is the bug.
    """

    result = operator.run_ai_operator(CASE, b"pdf bytes", target_doc_id=7)

    saved = operator._recorded["analysis_saved"]

    assert len(saved) == 1, (
        "the upload was processed but never recorded against a document, "
        "so the checklist item stays MISSING while the run reports success"
    )
    assert saved[0]["doc_id"] == 7
    assert result["attached"] is True
    assert result["attached_doc_id"] == 7


def test_without_a_target_nothing_is_recorded_and_the_result_says_so(operator):
    """
    Not attaching is a legitimate state - the operator does not know
    which obligation the file discharges and will not guess. What it must
    not do is leave the caller unable to tell.

    ``attached`` exists because its absence was the bug: the page had no
    way to distinguish "processed and recorded" from "processed", so it
    showed the same success message for both.
    """

    result = operator.run_ai_operator(CASE, b"pdf bytes")

    assert operator._recorded["analysis_saved"] == []
    assert result["attached"] is False
    assert result["attached_doc_id"] is None


def test_confirming_afterwards_records_it_without_reprocessing(operator):
    """
    The page classifies first and asks second, so the confirmation has to
    write from the result already computed. Re-running OCR and the model
    would cost the user the wait twice and could return a different
    classification the second time.
    """

    result = operator.run_ai_operator(CASE, b"pdf bytes")

    assert result["attached"] is False

    assert operator.attach_operator_result(result, 9) is True

    saved = operator._recorded["analysis_saved"]

    assert len(saved) == 1
    assert saved[0]["doc_id"] == 9
    assert saved[0]["extracted_text"] == "extracted text"
    assert result["attached"] is True


def test_confirming_without_a_document_records_nothing(operator):

    result = operator.run_ai_operator(CASE, b"pdf bytes")

    assert operator.attach_operator_result(result, None) is False
    assert operator._recorded["analysis_saved"] == []


def test_confirming_a_failed_run_records_nothing(operator):
    """
    A run that never extracted anything has nothing to attach. Writing a
    row from it would mark a document received on the strength of an
    empty file.
    """

    assert operator.attach_operator_result({"extraction": None}, 9) is False
    assert operator.attach_operator_result(None, 9) is False
    assert operator._recorded["analysis_saved"] == []


def test_the_page_passes_a_target_or_asks_for_one():
    """
    A static check on the call site, because that is where the defect
    was - the operator's own guard was correct and the page simply never
    satisfied it.

    Either the call supplies target_doc_id, or the page renders the
    attachment step. Both are acceptable; neither is not.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    passes_target = False

    for node in ast.walk(tree):

        if not isinstance(node, ast.Call):
            continue

        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)

        if name == "run_ai_operator":
            passes_target = passes_target or any(
                keyword.arg == "target_doc_id" for keyword in node.keywords
            ) or len(node.args) >= 3

    asks_for_one = "_render_operator_attachment" in source

    assert passes_target or asks_for_one, (
        "case_detail.py runs the AI operator without a target document "
        "and without asking for one afterwards, so the upload is "
        "processed and never recorded - the checklist item stays MISSING "
        "while the page reports success."
    )


def test_a_write_that_changes_nothing_is_not_reported_as_success(operator):
    """
    The failure a user hit: Attach reported success and the checklist
    stayed at 0/5.

    save_document_analysis() can match zero rows and raise nothing.
    `documents` is under FORCE ROW LEVEL SECURITY, and a row whose
    tenant_id is NULL is invisible to a session that has a tenant set -
    NULL = 3 is neither true nor false. The UPDATE then touches nothing
    and returns normally.

    Reporting that as success is worse than the missing write itself: the
    user believes the record is correct and stops checking.
    """

    operator._recorded["write_succeeds"] = False

    result = operator.run_ai_operator(CASE, b"pdf bytes")

    assert operator.attach_operator_result(result, 9) is False

    assert result["attached"] is False
    assert result["attach_error"], (
        "the failure has to say something the user can act on - a silent "
        "False leaves the page with nothing to show"
    )


def test_a_failed_write_from_the_operator_itself_is_not_claimed(operator):
    """Same property on the path that attaches during the run."""

    operator._recorded["write_succeeds"] = False

    result = operator.run_ai_operator(CASE, b"pdf bytes", target_doc_id=7)

    assert result["attached"] is False
    assert result["attached_doc_id"] is None


def test_the_page_reports_a_failed_attachment(operator):
    """
    A static check on the call site. Success and failure must render
    differently - the whole defect was one message for both.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    assert "attach_error" in source, (
        "case_detail.py does not surface attach_error, so a write that "
        "changed nothing still shows as attached"
    )
