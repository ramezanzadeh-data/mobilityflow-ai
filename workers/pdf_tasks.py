import os
import tempfile
import uuid

from workers.celery_app import celery_app
from db.database import load_case, get_tasks, get_documents, get_cases_by_company, get_case_tenant_id
from core.reporting.pdf import export_case_pdf
from core.reporting.analytics import export_company_summary_pdf
from core.storage.object_storage import upload_bytes, generate_presigned_url, ensure_bucket_exists


@celery_app.task(name="workers.pdf_tasks.generate_case_pdf")
def generate_case_pdf(case_id):

    case = load_case(case_id)

    if not case:
        return {"error": f"Case {case_id} not found"}

    tasks = get_tasks(case_id)
    docs = get_documents(case_id)
    tenant_id = get_case_tenant_id(case_id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        export_case_pdf(tmp_path, case, tasks, docs)

        storage_key = f"reports/{tenant_id}/case_{case_id}_{uuid.uuid4().hex[:8]}.pdf"

        ensure_bucket_exists()
        with open(tmp_path, "rb") as f:
            upload_bytes(storage_key, f.read(), content_type="application/pdf")

    finally:
        os.remove(tmp_path)

    return {
        "case_id": case_id,
        "storage_key": storage_key,
        "download_url": generate_presigned_url(storage_key),
    }


@celery_app.task(name="workers.pdf_tasks.generate_company_summary_pdf")
def generate_company_summary_pdf(company, lang="en"):

    cases = get_cases_by_company(company)
    tenant_id = cases[0][-1] if cases else None

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        export_company_summary_pdf(tmp_path, company, cases, lang=lang)

        storage_key = f"reports/{tenant_id}/summary_{uuid.uuid4().hex[:8]}.pdf"

        ensure_bucket_exists()
        with open(tmp_path, "rb") as f:
            upload_bytes(storage_key, f.read(), content_type="application/pdf")

    finally:
        os.remove(tmp_path)

    return {
        "company": company,
        "storage_key": storage_key,
        "download_url": generate_presigned_url(storage_key),
    }
