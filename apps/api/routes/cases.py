from fastapi import APIRouter, Depends, HTTPException, Query

from db.database import get_case_events, log_security_event, record_job_enqueued
from core.case.repository import (
    get_by_id,
    list_by_company_paginated,
    count_by_company,
    get_tenant_id_for_case,
)
from core.rules.risk import calculate_risk_from_rules
from core.workflow.states import normalize_legacy_state
from apps.api.schemas.case import CaseSummary, CaseDetail, PaginatedCases, TimelineEvent
from apps.api.schemas.jobs import JobEnqueued
from apps.api.dependencies.auth import get_current_user, require_tenant_id
from apps.api.dependencies.rate_limit import enforce_rate_limit
from workers.ai_tasks import generate_recommendation_for_case

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_row_to_summary(case_row) -> CaseSummary:

    risk_score, _ = calculate_risk_from_rules(case_row)

    return CaseSummary(
        id=case_row[0],
        employee_name=case_row[1],
        nationality=case_row[2],
        canton=case_row[3],
        permit=case_row[4],
        business_mode=case_row[5],
        status=case_row[7],
        workflow_state=normalize_legacy_state(case_row[8]),
        risk_score=risk_score,
    )


def _ensure_case_tenant_access(case_row, current_user):

    user_tenant_id = current_user.get("tenant_id")

    # A tenant_id of None means a legacy API key/dev-mode client with
    # cross-tenant (admin) access. Any authenticated tenant user must
    # match the case's tenant_id exactly.
    if user_tenant_id and get_tenant_id_for_case(case_row[0]) != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this case")


@router.get("", response_model=PaginatedCases, summary="List cases for the caller's tenant (paginated)")
def list_cases(
    page: int = Query(1, ge=1, description="Page number, starting at 1"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):

    require_tenant_id(current_user)
    company = current_user["company"]

    total = count_by_company(company)
    offset = (page - 1) * page_size

    cases = list_by_company_paginated(company, page_size, offset)

    total_pages = (total + page_size - 1) // page_size if total else 0

    return PaginatedCases(
        items=[_case_row_to_summary(c) for c in cases],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{case_id}", response_model=CaseDetail, summary="Get full details of one case")
def get_case(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):

    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    _ensure_case_tenant_access(case_row, current_user)

    log_security_event(
        current_user["username"], "API_ACCESS", f"Viewed case {case_id}", success=True
    )

    risk_score, _ = calculate_risk_from_rules(case_row)

    return CaseDetail(
        id=case_row[0],
        employee_name=case_row[1],
        nationality=case_row[2],
        canton=case_row[3],
        permit=case_row[4],
        business_mode=case_row[5],
        employer=case_row[6],
        status=case_row[7],
        workflow_state=normalize_legacy_state(case_row[8]),
        risk_score=risk_score,
        company=case_row[11],
        assigned_to=case_row[12],
        created_at=case_row[13],
        ai_summary=case_row[10],
    )


@router.get("/{case_id}/timeline", response_model=list[TimelineEvent], summary="Get the event timeline of a case")
def get_case_timeline(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):

    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    _ensure_case_tenant_access(case_row, current_user)

    events = get_case_events(case_id)

    return [
        TimelineEvent(id=e[0], event_type=e[2], description=e[3], created_at=e[4])
        for e in events
    ]


@router.post(
    "/{case_id}/ai/recommendation",
    response_model=JobEnqueued,
    status_code=202,
    summary="Generate an AI recommendation for a case as a background job",
)
def request_ai_recommendation(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    _ensure_case_tenant_access(case_row, current_user)

    async_result = generate_recommendation_for_case.delay(case_id)

    record_job_enqueued(
        async_result.id, "ai.generate_recommendation_for_case",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(
        task_id=async_result.id,
        status_url=f"/api/v1/jobs/{async_result.id}",
    )
