from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException

from workers.celery_app import celery_app
from db.database import get_job, list_jobs_for_tenant
from apps.api.schemas.jobs import JobStatus
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _ensure_job_access(task_id, current_user):

    job_row = get_job(task_id)

    if not job_row:
        raise HTTPException(status_code=404, detail="Job not found")

    user_tenant_id = current_user.get("tenant_id")

    if user_tenant_id and job_row.get("tenant_id") != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this job")

    return job_row


@router.get(
    "",
    summary="List background jobs for the caller's tenant",
)
def list_jobs(
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    tenant_id = current_user.get("tenant_id")

    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="This token/key has no associated tenant - use a JWT obtained via /api/v1/auth/login."
        )

    return list_jobs_for_tenant(tenant_id)


@router.get(
    "/{task_id}",
    response_model=JobStatus,
    summary="Check the status/result of a background job (OCR, AI, PDF, email, notification)",
)
def get_job_status(
    task_id: str,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    # The job row (with its tenant_id) is our own record of who this job
    # belongs to - checked BEFORE ever touching the Celery/Redis result,
    # so one tenant can never even probe for another tenant's task_id.
    _ensure_job_access(task_id, current_user)

    result = AsyncResult(task_id, app=celery_app)

    payload = None

    if result.ready():
        if result.failed():
            payload = {"error": str(result.result)}
        else:
            payload = result.result

    return JobStatus(
        task_id=task_id,
        state=result.state,
        result=payload,
    )
