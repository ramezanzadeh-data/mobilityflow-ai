"""
Single entry point for the whole document intake chain.

Before this existed, Upload / OCR / Classification / Rule Engine / Risk /
Workflow / Timeline / Notification were wired together ad hoc inside the
Streamlit page (and, separately, duplicated in the OCR background task).
That made the AI document pipeline feel like a side feature bolted onto
the case, rather than the thing that actually drives the case forward.

process_uploaded_document() is now the ONLY place this chain is
implemented. Both the Streamlit UI and the Celery OCR task call this
same function - neither one re-implements any of these steps itself.
"""

import json

from core.documents.ocr import extract_text_from_pdf, OCRDependencyError
from core.documents.pipeline import classify_and_summarize_document
from core.documents.validation import validate_document_against_case
from core.documents.analyzer import analyze_documents
from core.documents.matching import find_matching_document
from core.rules.risk import calculate_risk_from_rules
from core.workflow.states import get_next_state, normalize_legacy_state
from core.storage.object_storage import upload_bytes, ensure_bucket_exists

from db.database import (
    load_case,
    get_documents,
    add_document,
    save_document_analysis,
    update_case,
    set_workflow_state,
    log_case_event,
    get_case_tenant_id,
    record_job_enqueued,
)


def _find_or_create_document(case_id, document_name):
    """
    The checklist row this upload belongs to, creating it if it is new.

    Matching goes through core.documents.matching rather than ``==``.
    The comparison here used to be exact string equality, and the two
    vocabularies never agree: the checklist writes "Passport Copy" and
    the classifier returns "Passport". Every passport upload therefore
    created a second row and left the original at MISSING - the upload
    succeeded, the checklist did not move, and the user corrected it by
    hand.
    """

    existing = find_matching_document(get_documents(case_id), document_name)

    if existing:
        return existing[0]

    add_document(case_id, document_name)

    created = find_matching_document(get_documents(case_id), document_name)

    return created[0] if created else None


def _rules_passed(validation_warnings, doc_analysis):
    return not validation_warnings and not doc_analysis["missing_documents"]


def process_uploaded_document(case_id, document_name, filename, file_bytes, doc_id=None):
    """
    The full chain, in order:

      1.  Save file                -> object storage (S3/MinIO)
      2.  Save to database         -> create/attach the document row
      3.  OCR                      -> extract_text_from_pdf
      4.  AI classification        -> classify_and_summarize_document
      5.  Extract information      -> classification["key_facts"]
      6.  Update document status   -> save_document_analysis
      7.  Run rule engine          -> validate_document_against_case + analyze_documents
      8.  Update risk               -> calculate_risk_from_rules + update_case
      9.  Update workflow           -> set_workflow_state (only if rules passed)
      10. Timeline + notification  -> log_case_event (webhooks fire from there)

    Plus: if the document is complete AND the rule engine passed, this
    automatically queues a review email as part of the workflow - the
    email generator is no longer a disconnected, manually-triggered
    side feature.

    Returns a dict summarizing the outcome; never raises for expected
    failure modes (missing case, OCR unavailable) - it returns
    {"error": ...} instead, since this runs from both a web request and
    a background worker.
    """

    case = load_case(case_id)

    if not case:
        return {"error": f"Case {case_id} not found"}

    # 2. Save to database (create the document row first if this is a
    # brand-new upload, so tenant_id/doc_id exist before anything else).
    if doc_id is None:
        doc_id = _find_or_create_document(case_id, document_name)

    tenant_id = get_case_tenant_id(case_id)

    # 1. Save file to object storage
    storage_key = f"documents/{case_id}/{doc_id}/{filename}"
    ensure_bucket_exists()
    upload_bytes(storage_key, file_bytes, content_type="application/pdf")

    # 3. OCR
    try:
        extraction = extract_text_from_pdf(file_bytes)
    except OCRDependencyError as e:
        return {"error": str(e), "doc_id": doc_id}

    # 4 + 5. AI classification + key fact extraction
    classification = classify_and_summarize_document(extraction["text"])
    key_facts = classification.get("key_facts", {})

    # 6. Update document status / persist the analysis
    save_document_analysis(
        doc_id=doc_id,
        file_path=storage_key,
        extracted_text=extraction["text"],
        extracted_fields_json=json.dumps(key_facts),
        ocr_method=extraction["method"],
        ocr_confidence=None,
    )

    # 7. Run the rule engine: this specific document against the case,
    # plus the case's overall document completeness/compliance.
    validation_warnings = validate_document_against_case(key_facts, case)
    docs = get_documents(case_id)
    doc_analysis = analyze_documents(case, docs)
    rules_passed = _rules_passed(validation_warnings, doc_analysis)

    # 8. Recompute and persist risk (update_case() logs a RISK_CHANGED
    # timeline event itself if the score actually changed).
    risk, risk_trace = calculate_risk_from_rules(case)
    update_case(case_id, risk_level=risk)

    # 9. Advance the workflow - only when the rule engine actually passed.
    # A document that's missing required fields or fails validation
    # should never silently push the case forward.
    workflow_advanced = False

    if rules_passed:
        next_state = get_next_state(normalize_legacy_state(case[8]))

        if next_state:
            set_workflow_state(
                case_id, next_state,
                note=f"Auto-advanced after '{filename}' passed document validation"
            )
            workflow_advanced = True

    # 10. Timeline (webhook notification fires from inside log_case_event)
    log_case_event(
        case_id,
        "DOCUMENT_PROCESSED",
        f"Processed '{filename}' as {classification.get('document_type', 'Unknown')} - "
        f"rules_passed={rules_passed}, risk={risk}"
    )

    # Workflow-driven email: "Document Completed" + "Rule Passed" ->
    # generate a review email automatically, instead of requiring the
    # case manager to separately go and build one.
    email_job_id = None

    if rules_passed:
        from workers.email_tasks import generate_email_for_case

        async_result = generate_email_for_case.delay(
            case_id,
            step="Document review completed - please review and proceed",
            tone="formal",
        )

        record_job_enqueued(
            async_result.id, "email.generate_email_for_case",
            tenant_id, created_by="system:document_processing_service"
        )

        email_job_id = async_result.id

    return {
        "doc_id": doc_id,
        "storage_key": storage_key,
        "extraction": {
            "method": extraction["method"],
            "pages": extraction["pages"],
            "warning": extraction["warning"],
        },
        "classification": classification,
        "validation_warnings": validation_warnings,
        "doc_analysis": doc_analysis,
        "risk": risk,
        "risk_trace": risk_trace,
        "rules_passed": rules_passed,
        "workflow_advanced": workflow_advanced,
        "email_job_id": email_job_id,
    }
