from workers.celery_app import celery_app
from db.database import load_case
from core.rules.risk import calculate_risk_from_rules
from core.rules.engine import build_workflow_from_rules
from core.communication.email import generate_email, generate_checklist, generate_letter


@celery_app.task(name="workers.email_tasks.generate_email_for_case")
def generate_email_for_case(case_id, step, tone="formal"):

    case = load_case(case_id)

    if not case:
        return {"error": f"Case {case_id} not found"}

    return {"case_id": case_id, "email": generate_email(case, step, tone)}


@celery_app.task(name="workers.email_tasks.generate_checklist_for_case")
def generate_checklist_for_case(case_id):

    case = load_case(case_id)

    if not case:
        return {"error": f"Case {case_id} not found"}

    workflow = build_workflow_from_rules(case)

    return {"case_id": case_id, "checklist": generate_checklist(case, workflow)}


@celery_app.task(name="workers.email_tasks.generate_letter_for_case")
def generate_letter_for_case(case_id):

    case = load_case(case_id)

    if not case:
        return {"error": f"Case {case_id} not found"}

    risk, trace = calculate_risk_from_rules(case)
    workflow = build_workflow_from_rules(case)

    return {"case_id": case_id, "letter": generate_letter(case, risk, trace, workflow)}
