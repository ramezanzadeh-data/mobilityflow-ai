import tempfile
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from db.database import get_tasks, get_documents, record_job_enqueued
from core.case.repository import get_by_id, list_by_company, get_tenant_id_for_case
from core.reporting.pdf import export_case_pdf
from core.reporting.excel import export_cases_to_excel
from core.reporting.analytics import export_company_summary_pdf
from auth.permissions import can_export_reports
from apps.api.schemas.jobs import JobEnqueued
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit
from workers.pdf_tasks import generate_case_pdf, generate_company_summary_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_export_permission(current_user):
    if not can_export_reports(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only ADMIN users can export company-wide reports.",
        )


def _require_own_tenant_company(company, current_user):

    user_tenant_id = current_user.get("tenant_id")
    user_company = current_user.get("company")

    # user_tenant_id of None means a legacy API key/dev-mode client with
    # cross-tenant (superadmin) access - otherwise a tenant admin can only
    # export their own company's data, never another tenant's.
    if user_tenant_id and company != user_company:
        raise HTTPException(
            status_code=403,
            detail="You can only export reports for your own company.",
        )


@router.get("/cases/{case_id}/pdf", summary="Export a single case as a PDF")
def export_case_report(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    user_tenant_id = current_user.get("tenant_id")

    if user_tenant_id and get_tenant_id_for_case(case_id) != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this case")

    tasks = get_tasks(case_id)
    docs = get_documents(case_id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    export_case_pdf(tmp_path, case_row, tasks, docs)

    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=f"case_{case_id}.pdf",
    )


@router.get("/company/excel", summary="Export all cases for a company as an Excel workbook")
def export_company_excel(
    company: str = Query(...),
    lang: str = Query("en"),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _require_export_permission(current_user)
    _require_own_tenant_company(company, current_user)

    cases = list_by_company(company)

    workbook_bytes = export_cases_to_excel(cases, lang=lang)

    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{company}_cases.xlsx"'
        },
    )


@router.get("/company/summary-pdf", summary="Export a company-wide summary PDF")
def export_company_summary(
    company: str = Query(...),
    lang: str = Query("en"),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _require_export_permission(current_user)
    _require_own_tenant_company(company, current_user)

    cases = list_by_company(company)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    export_company_summary_pdf(tmp_path, company, cases, lang=lang)

    return FileResponse(
        tmp_path,
        media_type="application/pdf",
        filename=f"{company}_summary.pdf",
    )


@router.post(
    "/cases/{case_id}/pdf/async",
    response_model=JobEnqueued,
    status_code=202,
    summary="Generate a case PDF as a background job (recommended for larger reports)",
)
def export_case_report_async(
    case_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    user_tenant_id = current_user.get("tenant_id")

    if user_tenant_id and get_tenant_id_for_case(case_id) != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this case")

    async_result = generate_case_pdf.delay(case_id)

    record_job_enqueued(
        async_result.id, "pdf.generate_case_pdf",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(
        task_id=async_result.id,
        status_url=f"/api/v1/jobs/{async_result.id}",
    )


@router.post(
    "/company/summary-pdf/async",
    response_model=JobEnqueued,
    status_code=202,
    summary="Generate a company-wide summary PDF as a background job",
)
def export_company_summary_async(
    company: str = Query(...),
    lang: str = Query("en"),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _require_export_permission(current_user)
    _require_own_tenant_company(company, current_user)

    async_result = generate_company_summary_pdf.delay(company, lang)

    record_job_enqueued(
        async_result.id, "pdf.generate_company_summary_pdf",
        current_user.get("tenant_id"), current_user["username"]
    )

    return JobEnqueued(
        task_id=async_result.id,
        status_url=f"/api/v1/jobs/{async_result.id}",
    )
