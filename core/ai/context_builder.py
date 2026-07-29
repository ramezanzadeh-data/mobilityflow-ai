from core.ai.tools import (
    get_case_summary,
    get_case_risk,
    get_missing_documents,
    get_case_workflow_steps,
    get_case_timeline,
    recommend_workflow_advance,
)


def build_case_context(case_id: int) -> dict:
    """
    Collect all real case information from internal tools.
    Returns structured data for AI analysis.
    """

    return {
        "case_id": case_id,
        "summary": get_case_summary(case_id),
        "risk": get_case_risk(case_id),
        "missing_documents": get_missing_documents(case_id),
        "workflow": get_case_workflow_steps(case_id),
        "timeline": get_case_timeline(case_id),
        "recommendation": recommend_workflow_advance(case_id),
    }


def context_to_prompt(context: dict) -> str:
    """
    Convert structured case context into AI prompt format.
    """

    return f"""
You are a Swiss Relocation AI Case Manager.

Use ONLY the following verified case data.
Do not invent information.

CASE ID:
{context["case_id"]}

CASE SUMMARY:
{context["summary"]}

RISK ANALYSIS:
{context["risk"]}

MISSING DOCUMENTS:
{context["missing_documents"]}

WORKFLOW:
{context["workflow"]}

TIMELINE:
{context["timeline"]}

RECOMMENDATION:
{context["recommendation"]}

Provide:
1. Case analysis
2. Current status
3. Main risks
4. Required actions
5. Recommended next step
"""