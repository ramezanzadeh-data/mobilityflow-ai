import json

from db.database import (
    load_case,
    get_documents,
    get_case_events,
    get_tasks,
)

from core.rules.risk import calculate_risk_from_rules
from core.rules.engine import build_workflow_from_rules
from core.documents.analyzer import analyze_documents
from core.workflow.states import (
    normalize_legacy_state,
    get_next_state,
)


def _safe_case_value(case, index, default=None):
    """
    Safely read tuple based database records.
    """
    try:
        return case[index]
    except (IndexError, TypeError):
        return default


def build_case_context(case_id: int) -> dict:
    """
    Build structured AI context from verified database data.

    This is the single source of truth passed to AI agents.
    AI should never query database directly.
    """

    case = load_case(case_id)

    if not case:
        return {
            "case_id": case_id,
            "error": "Case not found"
        }


    # -----------------------------
    # Basic Case Information
    # -----------------------------

    current_state = normalize_legacy_state(
        _safe_case_value(case, 8, "DRAFT")
    )

    next_state = get_next_state(current_state)


    case_information = {

        "id": _safe_case_value(case, 0),

        "employee": {
            "name": _safe_case_value(case, 1),
            "nationality": _safe_case_value(case, 2),
        },

        "location": {
            "canton": _safe_case_value(case, 3),
        },

        "permit": {
            "type": _safe_case_value(case, 4),
        },

        "business": {
            "mode": _safe_case_value(case, 5),
            "employer": _safe_case_value(case, 6),
        },

        "status": _safe_case_value(case, 7),

        "company": _safe_case_value(case, 11),

        "workflow": {
            "current_state": current_state,            
        }
    }


    # -----------------------------
    # Risk Analysis
    # -----------------------------

    risk_score, risk_trace = calculate_risk_from_rules(case)


    risk_information = {

        "score": risk_score,

        "breakdown": (
            risk_trace.get("breakdown", [])
            if isinstance(risk_trace, dict)
            else []
        )
    }


    # -----------------------------
    # Document Intelligence
    # -----------------------------

    documents = get_documents(case_id)

    document_report = analyze_documents(
        case,
        documents
    )


    document_information = {

        "missing_documents":
            document_report.get(
                "missing_documents",
                []
            ),

        "risk_factors":
            document_report.get(
                "risk_factors",
                []
            ),

        "compliance_score":
            document_report.get(
                "compliance_score"
            ),

        "total_documents":
            len(documents)
    }


    # -----------------------------
    # Workflow Engine
    # -----------------------------

    workflow_steps = build_workflow_from_rules(case)

    tasks = get_tasks(case_id)


    task_status_map = {

        task[2]: task[3]

        for task in tasks
    }


    workflow_information = {

        "current_state": current_state,

        "next_state": next_state,

        "steps": [

            {
                "order": index + 1,

                "name": step,

                "status": task_status_map.get(
                    step,
                    "PENDING"
                )
            }

            for index, step
            in enumerate(workflow_steps)
        ]
    }


    # -----------------------------
    # Activity Summary
    # -----------------------------

    events = get_case_events(case_id)


    last_event = events[-1] if events else None


    activity = {

        "total_events": len(events),

        "last_activity":
            (
                last_event[3]
                if last_event
                else None
            ),

        "last_activity_time":
            (
                last_event[4]
                if last_event
                else None
            )
    }

    # -----------------------------
    # AI Recommendation Context
    # -----------------------------

    missing_docs = document_information["missing_documents"]

    workflow_warning = None

    if missing_docs:

        workflow_warning = (
            "Workflow contains completed steps but "
            "case cannot advance because required documents "
            "are still missing."
        )


    recommendation = {

        "can_advance": len(missing_docs) == 0,

        "blocking_items": missing_docs,

        "workflow_warning": workflow_warning,

        "reason":
            (
                "Resolve blocking documents before advancing workflow."
                if missing_docs
                else
                "No blocking issues detected. Human approval required."
            )
    }


    return {

        "case": case_information,

        "risk": risk_information,

        "documents": document_information,

        "workflow": workflow_information,

        "activity": activity,

        "recommendation": recommendation
    }



def build_case_context_json(case_id: int) -> str:
    """
    JSON string version for LLM prompts.
    """

    context = build_case_context(case_id)

    return json.dumps(
        context,
        indent=2,
        ensure_ascii=False
    )

def build_agent_context(case_id: int) -> dict:
    """
    Reduced context for AI Agent.
    Only includes decision-relevant information.
    """

    context = build_case_context(case_id)

    if "error" in context:
        return context

    return {
        "case": {
            "id": context["case"]["id"],

            "employee": context["case"]["employee"],

            "location": context["case"]["location"],

            "permit": context["case"]["permit"],

            "business": context["case"]["business"],

            "status": context["case"]["status"],

            "company": context["case"]["company"],

        },

        "risk": {
            "score": context["risk"]["score"],
            "breakdown": context["risk"]["breakdown"],
        },

        "documents": {
            "missing_documents":
                context["documents"]["missing_documents"],

            "risk_factors":
                context["documents"]["risk_factors"],

            "compliance_score":
                context["documents"]["compliance_score"],

        },

        "workflow": {
            "current_state": context["workflow"]["current_state"],
            "next_state": context["workflow"]["next_state"],
        },

        "recommendation": {

            "can_advance":
                context["recommendation"]["can_advance"],

            "blocking_items":
                context["recommendation"]["blocking_items"],

            "reason":
                context["recommendation"]["reason"],
        }
    }    