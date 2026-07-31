
import json
import logging
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
from core.storage.object_storage import ensure_bucket_exists, upload_bytes

from db.database import (
    get_documents,
    save_document_analysis,
    add_task,
    set_task_due_date,
    log_case_event,
)


logger = logging.getLogger(__name__)

REMINDER_DAYS_AHEAD = 7


def _store_uploaded_file(case_id, doc_id, filename, file_bytes):
    """
    Put the uploaded file in object storage and return its key.

    Returns "" when there is nothing to store or storage is unavailable.
    An empty file_path is an honest record of "we analysed this and did
    not keep the original"; a fabricated path would be worse, because
    every later attempt to fetch it would fail with no explanation.
    """

    if not (case_id and doc_id and filename and file_bytes):
        return ""

    key = f"documents/{case_id}/{doc_id}/{filename}"

    try:
        ensure_bucket_exists()
        upload_bytes(key, file_bytes, content_type="application/pdf")

    except Exception:  # noqa: BLE001 - see the caller's docstring
        logger.warning(
            "Could not store the uploaded file for document %s. The "
            "analysis was kept; the original was not.",
            doc_id,
            exc_info=True,
        )
        return ""

    return key


def attach_operator_result(result, doc_id, case_id=None, filename=None,
                           file_bytes=None):
    """
    Record an already-processed upload against a checklist row.

    The operator classifies first and asks second: the user is shown what
    the document appears to be, with the matching checklist item
    pre-selected, and confirms. This performs the write for that
    confirmation without re-running OCR and classification, which cost
    real time and would produce a second, possibly different answer.

    Returns True if the status was recorded.

    The file itself
    ---------------
    ``file_bytes`` is stored in object storage and its key recorded, the
    same way core.documents.document_processing_service does it. Without
    that, this path wrote the literal string "uploaded_via_ai_operator"
    into file_path and dropped the bytes: the extracted text was kept,
    the document was not, and a user who came back the next day had to
    upload it again to see anything. Two upload paths, one of which
    quietly discarded the file.

    Storage failure does not block the status change. The extraction is
    already done and the checklist item genuinely is satisfied; refusing
    to record that because MinIO is unreachable would lose more than it
    protects. The file_path is left empty instead, which the screen can
    read as "analysed, original not retained".
    """

    extraction = result.get("extraction") if result else None

    if not doc_id or not extraction:
        return False

    key_facts = (result.get("classification") or {}).get("key_facts") or {}

    storage_key = _store_uploaded_file(case_id, doc_id, filename, file_bytes)

    written = save_document_analysis(
        doc_id=doc_id,
        file_path=storage_key,
        extracted_text=extraction["text"],
        extracted_fields_json=json.dumps(key_facts),
        ocr_method=extraction["method"],
        ocr_confidence=None,
    )

    # The write can match zero rows without raising - see
    # db.database.save_document_analysis. Reporting success for a status
    # change that did not happen is the defect this whole path already
    # had once; do not reintroduce it one layer up.
    if not written:
        result["attached"] = False
        result["attach_error"] = (
            "The document status could not be updated. The row was not "
            "visible to this session - most often because the case or the "
            "document has no tenant recorded. Nothing was changed."
        )
        return False

    result["attached"] = True
    result["attached_doc_id"] = doc_id
    result["attach_error"] = None

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
        "attach_error": None,
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

        written = save_document_analysis(
            doc_id=target_doc_id,
            file_path="uploaded_via_ai_operator",
            extracted_text=extraction["text"],
            extracted_fields_json=json.dumps(key_facts),
            ocr_method=extraction["method"],
            ocr_confidence=None,
        )

        result["attached"] = bool(written)
        result["attached_doc_id"] = target_doc_id if written else None


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
