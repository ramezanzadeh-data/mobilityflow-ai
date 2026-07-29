import base64

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File

from db.database import (
    get_documents,
    add_document,
    update_document,
    get_document_extracted_text,
    get_document_case_id,
    record_job_enqueued,
)
from core.case.repository import get_by_id, get_tenant_id_for_case
from apps.api.schemas.document import (
    DocumentItem,
    DocumentCreate,
    DocumentStatusUpdate,
    DocumentExtractedText,
)
from apps.api.schemas.jobs import JobEnqueued
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit
from workers.ocr_tasks import process_uploaded_document_task
from core.storage.object_storage import generate_presigned_url, object_exists

router = APIRouter(prefix="/documents", tags=["documents"])


def _document_row_to_item(row) -> DocumentItem:
    return DocumentItem(
        id=row[0],
        case_id=row[1],
        name=row[2],
        status=row[3],
        ocr_method=row[7] if len(row) > 7 else None,
        ocr_confidence=row[8] if len(row) > 8 else None,
        uploaded_at=row[9] if len(row) > 9 else None,
    )


def _ensure_case_access(case_id: int, current_user):

    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    user_tenant_id = current_user.get("tenant_id")

    if user_tenant_id and get_tenant_id_for_case(case_id) != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this case")

    return case_row


@router.get("", response_model=list[DocumentItem], summary="List documents for a case")
def list_documents(
    case_id: int = Query(...),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(case_id, current_user)

    return [_document_row_to_item(row) for row in get_documents(case_id)]


@router.post("", response_model=DocumentItem, status_code=201, summary="Register a required document for a case")
def create_document(
    payload: DocumentCreate,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(payload.case_id, current_user)

    add_document(payload.case_id, payload.name)

    matching = [
        row for row in get_documents(payload.case_id) if row[2] == payload.name
    ]

    created = matching[-1] if matching else None

    if not created:
        raise HTTPException(status_code=500, detail="Document was created but could not be retrieved")

    return _document_row_to_item(created)


@router.patch("/{document_id}/status", response_model=dict, summary="Update a document's status")
def update_document_status(
    document_id: int,
    payload: DocumentStatusUpdate,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    update_document(document_id, payload.status)

    return {"id": document_id, "status": payload.status}


@router.get(
    "/{document_id}/extracted-text",
    response_model=DocumentExtractedText,
    summary="Get the OCR/extracted text for a document",
)
def get_extracted_text(
    document_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    text = get_document_extracted_text(document_id)

    if text is None:
        raise HTTPException(status_code=404, detail="No extracted text found for this document")

    return DocumentExtractedText(id=document_id, extracted_text=text)


@router.post(
    "/{document_id}/process",
    response_model=JobEnqueued,
    status_code=202,
    summary="Run OCR + AI classification on an uploaded PDF as a background job",
)
async def process_document(
    document_id: int,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    case_id = get_document_case_id(document_id)

    if case_id is None:
        raise HTTPException(status_code=404, detail="Document not found")

    _ensure_case_access(case_id, current_user)

    file_bytes = await file.read()
    file_bytes_b64 = base64.b64encode(file_bytes).decode("ascii")

    async_result = process_uploaded_document_task.delay(
        filename=file.filename,
        file_bytes_b64=file_bytes_b64,
        doc_id=document_id,
    )

    record_job_enqueued(
        async_result.id, "ocr.process_uploaded_document",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(
        task_id=async_result.id,
        status_url=f"/api/v1/jobs/{async_result.id}",
    )


@router.get(
    "/{document_id}/download",
    summary="Get a presigned download URL for the original uploaded file (stored in S3/MinIO)",
)
def get_download_url(
    document_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    case_id = get_document_case_id(document_id)

    if case_id is None:
        raise HTTPException(status_code=404, detail="Document not found")

    _ensure_case_access(case_id, current_user)

    doc_row = next((d for d in get_documents(case_id) if d[0] == document_id), None)
    storage_key = doc_row[4] if doc_row else None

    if not storage_key or not object_exists(storage_key):
        raise HTTPException(status_code=404, detail="No file stored for this document yet")

    return {"download_url": generate_presigned_url(storage_key)}
