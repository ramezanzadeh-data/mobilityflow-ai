from fastapi import APIRouter, Depends, HTTPException

from core.case.repository import get_by_id, get_tenant_id_for_case
from db.database import record_job_enqueued
from apps.api.schemas.jobs import JobEnqueued
from apps.api.schemas.communication import GenerateEmailRequest
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit
from workers.email_tasks import (
    generate_email_for_case,
    generate_checklist_for_case,
    generate_letter_for_case,
)

router = APIRouter(prefix="/cases", tags=["communications"])


def _ensure_case_access(case_id: int, current_user):

    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    user_tenant_id = current_user.get("tenant_id")

    if user_tenant_id and get_tenant_id_for_case(case_id) != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this case")


@router.post(
    "/{case_id}/communications/email",
    response_model=JobEnqueued,
    status_code=202,
    summary="Generate an email for a case as a background job",
)
def request_email(
    case_id: int,
    payload: GenerateEmailRequest,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(case_id, current_user)

    async_result = generate_email_for_case.delay(case_id, payload.step, payload.tone)

    record_job_enqueued(
        async_result.id, "email.generate_email_for_case",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(task_id=async_result.id, status_url=f"/api/v1/jobs/{async_result.id}")


@router.post(
    "/{case_id}/communications/checklist",
    response_model=JobEnqueued,
    status_code=202,
    summary="Generate a workflow checklist for a case as a background job",
)
def request_checklist(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(case_id, current_user)

    async_result = generate_checklist_for_case.delay(case_id)

    record_job_enqueued(
        async_result.id, "email.generate_checklist_for_case",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(task_id=async_result.id, status_url=f"/api/v1/jobs/{async_result.id}")


@router.post(
    "/{case_id}/communications/letter",
    response_model=JobEnqueued,
    status_code=202,
    summary="Generate a formal support letter for a case as a background job",
)
def request_letter(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(case_id, current_user)

    async_result = generate_letter_for_case.delay(case_id)

    record_job_enqueued(
        async_result.id, "email.generate_letter_for_case",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(task_id=async_result.id, status_url=f"/api/v1/jobs/{async_result.id}")
