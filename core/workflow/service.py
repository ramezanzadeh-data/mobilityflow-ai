from db.database import (
    load_case,
    update_case,
    set_workflow_state,
)
from core.context.case_context_builder import build_agent_context


def _case_to_dict(row):
    """
    Convert database tuple into dictionary.
    """

    if not row:
        return None

    return {
        "id": row[0],
        "employee_name": row[1],
        "nationality": row[2],
        "canton": row[3],
        "permit": row[4],
        "business_mode": row[5],
        "employer": row[6],
        "status": row[7],
        "workflow_state": row[8],
        "risk_level": row[9],
        "ai_summary": row[10],
        "company": row[11],
        "assigned_to": row[12],
    }


def _get_blockers(case_id):
    """
    Get current blocking items from verified context.
    """

    context = build_agent_context(case_id)

    recommendation = context.get(
        "recommendation",
        {}
    )

    return recommendation.get(
        "blocking_items",
        []
    )


def advance_case(case_id):

    case_row = load_case(case_id)

    case = _case_to_dict(case_row)


    if not case:
        return {
            "success": False,
            "message": "Case not found."
        }


    blockers = _get_blockers(case_id)


    if blockers:
        return {
            "success": False,
            "message": "Case cannot advance. Blocking documents exist.",
            "blockers": blockers
        }


    set_workflow_state(
        case_id,
        "SUBMITTED",
        "Workflow advanced by AI Agent"
    )


    update_case(
        case_id,
        status="SUBMITTED"
    )


    return {
        "success": True,
        "message": "Case advanced successfully.",
        "new_state": "SUBMITTED"
    }



def approve_case(case_id):

    case_row = load_case(case_id)

    case = _case_to_dict(case_row)


    if not case:
        return {
            "success": False,
            "message": "Case not found."
        }


    blockers = _get_blockers(case_id)


    if blockers:
        return {
            "success": False,
            "message": "Case cannot be approved. Blocking documents exist.",
            "blockers": blockers
        }


    set_workflow_state(
        case_id,
        "APPROVED",
        "Case approved by authorized action"
    )


    update_case(
        case_id,
        status="APPROVED"
    )


    return {
        "success": True,
        "message": "Case approved successfully.",
        "new_state": "APPROVED"
    }