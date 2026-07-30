
import json
from datetime import date, timedelta

from core.documents.ocr import extract_text_from_pdf, OCRDependencyError
from core.documents.pipeline import classify_and_summarize_document
from core.documents.analyzer import analyze_documents
from core.documents.validation import (
    validate_document_against_case,
    check_expiry,
)
from core.rules.risk import calculate_risk_from_rules
from core.rules.engine import build_workflow_from_rules
from core.workflow.states import normalize_legacy_state, get_next_state
from core.communication.email import generate_email

from db.database import (
    get_documents,
    save_document_analysis,
    add_task,
    set_task_due_date,
    log_case_event,
)


REMINDER_DAYS_AHEAD = 7


def attach_operator_result(result, doc_id):
    """
    Record an already-processed upload against a checklist row.

    The operator classifies first and asks second: the user is shown what
    the document appears to be, with the matching checklist item
    pre-selected, and confirms. This performs the write for that
    confirmation without re-running OCR and classification, which cost
    real time and would produce a second, possibly different answer.

    Returns True if the status was recorded.

    Lives here rather than in the page because it is the same write the
    operator performs when given a target up front - one definition of
    "this file satisfies that obligation", not two.
    """

    extraction = result.get("extraction") if result else None

    if not doc_id or not extraction:
        return False

    key_facts = (result.get("classification") or {}).get("key_facts") or {}

    save_document_analysis(
        doc_id=doc_id,
        file_path="uploaded_via_ai_operator",
        extracted_text=extraction["text"],
        extracted_fields_json=json.dumps(key_facts),
        ocr_method=extraction["method"],
        ocr_confidence=None,
    )

    result["attached"] = True
    result["attached_doc_id"] = doc_id

    return True


def run_ai_operator(case, file_bytes, target_doc_id=None):
    """
    Extract, classify, validate and score an uploaded document.

    ``target_doc_id`` is the checklist row this file satisfies. Without
    it the document's status is not changed, because the operator does
    not know which obligation the upload discharges and will not guess -
    marking the wrong item received makes a missing document look
    present, and nothing downstream re-checks.

    The caller must therefore pass one. The page asks the user, with the
    best match from the classification pre-selected.

    ``attached`` in the returned dict says whether the status was
    actually recorded. It exists because the absence of it was the bug:
    the page called this without a target, every branch below ran and
    reported success, and the one write that moves a document from
    MISSING to UPLOADED was skipped in silence. "AI operator finished"
    was true and useless.
    """

    result = {
        "extraction": None,
        "classification": {},
        "validation_warnings": [],
        "expiry": ("unknown", None),
        "missing_documents_report": None,
        "risk": None,
        "workflow": None,
        "tasks_created": [],
        "reminder_due_date": None,
        "email_draft": None,
        "next_stage_recommendation": None,
        "attached": False,
        "attached_doc_id": None,
        "error": None,
    }

    case_id = case[0]


    try:
        extraction = extract_text_from_pdf(file_bytes)
    except OCRDependencyError as e:
        result["error"] = str(e)
        return result

    result["extraction"] = extraction


    classification = classify_and_summarize_document(extraction["text"])
    result["classification"] = classification

    key_facts = classification.get("key_facts") or {}


    result["validation_warnings"] = validate_document_against_case(key_facts, case)
    result["expiry"] = check_expiry(key_facts)


    # The only write that moves a document from MISSING to UPLOADED.
    # Everything below reads the resulting status, so it has to happen
    # before the analysis - not after, and not conditionally on anything
    # other than having been told which row this is.
    if target_doc_id:

        save_document_analysis(
            doc_id=target_doc_id,
            file_path="uploaded_via_ai_operator",
            extracted_text=extraction["text"],
            extracted_fields_json=json.dumps(key_facts),
            ocr_method=extraction["method"],
            ocr_confidence=None,
        )

        result["attached"] = True
        result["attached_doc_id"] = target_doc_id


    docs = get_documents(case_id)
    missing_report = analyze_documents(case, docs)
    result["missing_documents_report"] = missing_report


    risk_score, risk_trace = calculate_risk_from_rules(case)
    result["risk"] = (risk_score, risk_trace)


    workflow = build_workflow_from_rules(case)
    result["workflow"] = workflow


    tasks_created = []
    task_ids = []

    for missing_doc in missing_report["missing_documents"]:

        task_title = f"Request missing document: {missing_doc}"

        # add_task() is idempotent: on a re-run over the same still-missing
        # document it returns the existing active task instead of creating
        # a second one. Only genuinely new tasks are reported as created,
        # while every task - new or reused - still gets its reminder
        # refreshed below, exactly as before.
        upsert = add_task(case_id, task_title)
        task_ids.append(upsert.task_id)

        if upsert.created:
            tasks_created.append(task_title)

    result["tasks_created"] = tasks_created


    if task_ids:

        due_date = (date.today() + timedelta(days=REMINDER_DAYS_AHEAD)).isoformat()

        for task_id in task_ids:
            set_task_due_date(task_id, due_date)

        result["reminder_due_date"] = due_date


    if missing_report["missing_documents"]:

        missing_list_str = ", ".join(missing_report["missing_documents"])
        email_step = f"Request the following missing documents: {missing_list_str}"

        result["email_draft"] = generate_email(case, email_step)


    current_state = normalize_legacy_state(case[8])
    next_state = get_next_state(current_state)

    if next_state and not missing_report["missing_documents"]:
        result["next_stage_recommendation"] = (
            f"No missing documents detected — this case looks ready to "
            f"move from {current_state} to {next_state}. A human must "
            f"confirm this in the Workflow Stage section."
        )


    log_case_event(
        case_id,
        "AI_OPERATOR_RUN",
        f"AI Operator processed an uploaded document: "
        f"{len(missing_report['missing_documents'])} missing document(s) found, "
        f"{len(tasks_created)} task(s) auto-created, current risk={risk_score}."
    )

    return result
