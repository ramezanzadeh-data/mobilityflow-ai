"""
Handles any operational intent that the Intent Router correctly
recognized and that has already passed the RBAC gate
(core.ai.tool_policy.check_operational_permission), but for which no
tool is implemented yet (REJECT_CASE, DELETE_CASE, CLOSE_CASE,
ARCHIVE_CASE, ASSIGN_TASK, GENERIC_ACTION - see
core.ai.tool_policy._TOOL_FOR_INTENT).
"""

from core.ai.intent import Intent
from core.ai import tool_policy
from core.ai.response_formatter import format_response
from core.ai.schemas import ActionPayload

from core.ai.agent.shared import record_step, finish
from core.ai.agent.audit import audit_ai_action


def run_unimplemented_action(
    intent: Intent,
    user_goal: str,
    case_id: int,
    context: dict,
    steps_log: list,
    on_step,
    current_user: dict,
) -> dict:
    """
    This NEVER calls the LLM: there is nothing for a model to usefully
    contribute when there is no tool to call, and doing so would only
    add a hallucination surface (e.g. the model inventing prose that
    sounds like the case was actually rejected/deleted/closed). The
    user-facing wording comes entirely from
    tool_policy.tool_availability_decision, so the Tool Policy layer
    stays the single source of truth for every ACTION-route outcome.
    """

    decision = tool_policy.tool_availability_decision(intent)

    payload = ActionPayload(
        tool_name=tool_policy.resolve_tool_for_intent(intent) or intent.value,
        arguments={"case_id": case_id},
        result=decision.reason,
        success=False,
    )
    answer = format_response(Intent.ACTION, payload)

    # Distinct from AI_ACTION_DENIED (RBAC): this attempt already
    # passed permission checks - it failed only because no backing
    # tool exists yet. Keeping the two apart lets a compliance review
    # tell "blocked by role" apart from "feature not implemented".
    audit_ai_action(
        current_user,
        case_id,
        "AI_ACTION_NOT_IMPLEMENTED",
        f"AI attempted '{intent.value}' but no tool is implemented: "
        f"{decision.reason}",
        success=False,
    )

    step = {
        "type": "tool_call",
        "tool": intent.value,
        "arguments": {"case_id": case_id},
        "result": decision.reason,
    }
    record_step(steps_log, on_step, step)
    record_step(
        steps_log, on_step, {"type": "final_answer", "content": answer}
    )

    return finish(case_id, user_goal, answer, steps_log, context)
