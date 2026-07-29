from workers.celery_app import celery_app
from db.database import load_case, get_documents, get_document_extracted_text
from core.rules.risk import calculate_risk_from_rules
from core.rules.engine import build_workflow_from_rules
from core.documents.analyzer import analyze_documents
from core.documents.pipeline import classify_and_summarize_document, generate_recommendation
from core.documents.validation import detect_defects_with_ai
from core.ai.agent import run_agent


@celery_app.task(name="workers.ai_tasks.generate_recommendation_for_case")
def generate_recommendation_for_case(case_id):

    case = load_case(case_id)

    if not case:
        return {"error": f"Case {case_id} not found"}

    risk, trace = calculate_risk_from_rules(case)
    workflow = build_workflow_from_rules(case)
    docs = get_documents(case_id)
    doc_analysis = analyze_documents(case, docs)

    recommendation = generate_recommendation(case, risk, trace, workflow, doc_analysis)

    return {"case_id": case_id, "recommendation": recommendation}


@celery_app.task(name="workers.ai_tasks.classify_document")
def classify_document(doc_id):

    raw_text = get_document_extracted_text(doc_id) or ""

    return classify_and_summarize_document(raw_text)


@celery_app.task(name="workers.ai_tasks.detect_document_defects")
def detect_document_defects(doc_id, document_type):

    raw_text = get_document_extracted_text(doc_id) or ""

    return {"defects": detect_defects_with_ai(raw_text, document_type)}


@celery_app.task(name="workers.ai_tasks.run_agent_task")
def run_agent_task(user_goal, case_id=None, current_user=None):

    return run_agent(user_goal, case_id=case_id, current_user=current_user)
