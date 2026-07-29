
from db.database import (
    load_case,
    get_documents,
    get_case_events,
    add_task,
    update_document,
)
from core.rules.risk import calculate_risk_from_rules
from core.rules.engine import build_workflow_from_rules
from core.documents.analyzer import analyze_documents
from core.workflow.states import normalize_legacy_state, get_next_state
from core.workflow.service import approve_case

def get_case_summary(case_id: int) -> str:

    case = load_case(case_id)

    if not case:
        return f"No case found with id {case_id}."

    return (
        f"Employee: {case[1]}, Nationality: {case[2]}, Canton: {case[3]}, "
        f"Permit: {case[4]}, Business Mode: {case[5]}, Status: {case[7]}"
    )


def get_case_risk(case_id: int) -> str:

    case = load_case(case_id)

    if not case:
        return f"No case found with id {case_id}."

    score, trace = calculate_risk_from_rules(case)

    return f"Risk score: {score}/100. Breakdown: {'; '.join(trace['breakdown'])}"


def get_missing_documents(case_id: int) -> str:

    case = load_case(case_id)

    if not case:
        return f"No case found with id {case_id}."

    docs = get_documents(case_id)
    report = analyze_documents(case, docs)

    missing = ", ".join(report["missing_documents"]) or "None"
    risks = "; ".join(report["risk_factors"]) or "None"

    return (
        f"Missing documents: {missing}. Risk factors: {risks}. "
        f"Compliance score: {report['compliance_score']}/100"
    )


def get_case_workflow_steps(case_id: int) -> str:

    case = load_case(case_id)

    if not case:
        return f"No case found with id {case_id}."

    workflow = build_workflow_from_rules(case)

    return "; ".join(f"{i + 1}. {step}" for i, step in enumerate(workflow))


def get_case_timeline(case_id: int) -> str:

    events = get_case_events(case_id)

    if not events:
        return "No events recorded yet for this case."

    recent = events[-10:]

    return "; ".join(f"[{e[4]}] {e[3]}" for e in recent)


def recommend_workflow_advance(case_id: int) -> str:

    case = load_case(case_id)

    if not case:
        return f"No case found with id {case_id}."

    current_state = normalize_legacy_state(case[8])
    next_state = get_next_state(current_state)

    if not next_state:
        return f"Case is already at the final stage ({current_state}). No further advance possible."

    docs = get_documents(case_id)
    report = analyze_documents(case, docs)

    if report["missing_documents"]:
        return (
            f"NOT recommended to advance from {current_state} to {next_state} yet: "
            f"missing documents remain ({', '.join(report['missing_documents'])}). "
            f"A human should resolve these first, then advance manually."
        )

    return (
        f"This case appears ready to move from {current_state} to {next_state} "
        f"(no missing documents detected). A human should confirm and click "
        f"'Advance' in the Workflow Stage section to make it official."
    )


def create_task_for_case(case_id: int, title: str) -> str:

    # Idempotent at the database level: if the agent calls this twice for
    # the same case and title, the second call reuses the existing task
    # rather than creating a duplicate. Reporting the reuse truthfully
    # matters - telling the model a task was "created" when it was not
    # invites it to retry, which is one of the ways duplicates were
    # generated in the first place.
    upsert = add_task(case_id, title)

    if not upsert.created:
        return (
            f"Task already exists for case {case_id}: '{title}' "
            f"(task #{upsert.task_id}). No duplicate was created."
        )

    return f"Task created for case {case_id}: '{title}'"


_ALLOWED_DOCUMENT_STATUSES = {
    "RECEIVED",
    "MISSING",
    "REJECTED",
    "PENDING_REVIEW",
}


def update_document_status(
    case_id: int, document_name: str, status: str
) -> str:

    case = load_case(case_id)

    if not case:
        return f"No case found with id {case_id}."

    normalized_status = status.strip().upper()

    if normalized_status not in _ALLOWED_DOCUMENT_STATUSES:
        return (
            f"Invalid status '{status}'. Allowed values: "
            f"{', '.join(sorted(_ALLOWED_DOCUMENT_STATUSES))}."
        )

    documents = get_documents(case_id)

    match = next(
        (
            doc for doc in documents
            if str(doc[2]).strip().lower() == document_name.strip().lower()
        ),
        None,
    )

    if match is None:
        return (
            f"No document named '{document_name}' found for case "
            f"{case_id}."
        )

    update_document(match[0], normalized_status)

    return (
        f"Document '{document_name}' for case {case_id} marked as "
        f"{normalized_status}."
    )


AVAILABLE_TOOLS = {
    "get_case_summary": get_case_summary,
    "get_case_risk": get_case_risk,
    "get_missing_documents": get_missing_documents,
    "get_case_workflow_steps": get_case_workflow_steps,
    "get_case_timeline": get_case_timeline,
    "recommend_workflow_advance": recommend_workflow_advance,
    "create_task_for_case": create_task_for_case,
    "update_document_status": update_document_status,
    "approve_case": approve_case,
}

TOOLS_LIST = [
    {
        "type": "function",
        "function": {
            "name": "create_task_for_case",
            "description": "Create a new task for a relocation case.",
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {
                        "type": "integer"
                    },
                    "title": {
                        "type": "string"
                    }
                },
                "required": [
                    "case_id",
                    "title"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_document_status",
            "description": (
                "Update the status of an existing document on a "
                "relocation case. Allowed status values: RECEIVED, "
                "MISSING, REJECTED, PENDING_REVIEW."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "case_id": {
                        "type": "integer"
                    },
                    "document_name": {
                        "type": "string"
                    },
                    "status": {
                        "type": "string"
                    }
                },
                "required": [
                    "case_id",
                    "document_name",
                    "status"
                ]
            }
        }
    }
]