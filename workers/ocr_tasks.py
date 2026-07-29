import base64

from workers.celery_app import celery_app
from core.documents.document_processing_service import process_uploaded_document
from db.database import get_document_case_id, get_documents


@celery_app.task(name="workers.ocr_tasks.process_uploaded_document", bind=True)
def process_uploaded_document_task(self, filename, file_bytes_b64, doc_id=None):
    """
    Thin Celery wrapper: the ENTIRE Upload -> Save -> OCR -> AI
    Classification -> Update Document -> Rule Engine -> Risk -> Workflow
    -> Timeline -> Notification chain lives in
    core.documents.document_processing_service.process_uploaded_document.
    This task never re-implements any of it - it just decodes the bytes
    Celery can carry over the wire and calls straight into that service.
    """

    file_bytes = base64.b64decode(file_bytes_b64)

    case_id = get_document_case_id(doc_id) if doc_id is not None else None

    if case_id is None:
        return {"error": "No case_id could be resolved for this document"}

    document_name = filename
    if doc_id is not None:
        existing = next((d for d in get_documents(case_id) if d[0] == doc_id), None)
        if existing:
            document_name = existing[2]

    return process_uploaded_document(
        case_id=case_id,
        document_name=document_name,
        filename=filename,
        file_bytes=file_bytes,
        doc_id=doc_id,
    )
