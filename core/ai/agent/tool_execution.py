"""
ACTION route for the two LLM-mediated operational intents: CREATE_TASK
and DOCUMENT_ACTION. These are the only operational intents genuinely
mediated by the LLM, because both need a free-text parameter (a task
title, or a document name/status) extracted from the user's message
that cannot be deterministically looked up.

APPROVE_CASE and ADVANCE_WORKFLOW are handled directly in
core.ai.agent.orchestrator, never through tool-calling here - neither
needs any free-text parameter, only the caller's already-verified
case_id.
"""

from core.ai.ollama_client import chat, OllamaUnavailableError
from core.ai.tools import AVAILABLE_TOOLS, TOOLS_LIST
from core.ai.intent import Intent
from core.ai import tool_policy
from core.ai.response_formatter import format_response
from core.ai.schemas import ActionPayload

from core.ai.agent.config import MODEL
from core.ai.agent.prompts import ACTION_SYSTEM_PROMPT, build_messages
from core.ai.agent.shared import record_step, finish
from core.ai.agent.audit import audit_ai_action


def execute_tool(
    intent: Intent, function_name: str, arguments: dict, case_id: int
) -> dict:
    """
    Execute a single tool call and return a normalized step record. This
    is the ONLY place tool results are produced, so the final answer can
    never drift from what actually ran. Every call is authorized by the
    Tool Policy layer immediately before execution - independent of
    whatever was exposed to the LLM earlier.

    `case_id` is the caller's verified case_id (the one run_agent was
    invoked with), and is ALWAYS substituted into `arguments["case_id"]`
    before the tool runs, overwriting whatever the model put there. The
    model's own case_id argument is never trusted: without this, a
    hallucinated or malformed case_id in the tool call could execute a
    real, permanent write (creating a task, changing a document status)
    against a completely different case than the one the user was
    looking at and was authorized for.
    """

    decision = tool_policy.authorize(intent, function_name, TOOLS_LIST)

    if not decision.allowed:
        return {
            "type": "tool_call",
            "tool": function_name,
            "arguments": arguments,
            "result": f"Blocked by tool policy: {decision.reason}",
        }

    # Never trust the model's case_id - always the verified caller value.
    safe_arguments = dict(arguments)
    safe_arguments["case_id"] = case_id

    tool_function = AVAILABLE_TOOLS.get(function_name)

    if tool_function is None:
        result = f"Unknown tool: {function_name}"
    else:
        try:
            result = tool_function(**safe_arguments)
        except Exception as e:
            result = f"Tool execution error: {str(e)}"

    return {
        "type": "tool_call",
        "tool": function_name,
        "arguments": safe_arguments,
        "result": result,
    }


# Result-text prefixes that mean the tool itself reported a real
# failure (bad input, case/document not found) even though it returned
# normally with no exception. Without this, a message like "No document
# named 'X' found for case 5." was marked success=True purely because
# it didn't start with one of the three infrastructure-level failure
# prefixes below - showing the user a misleading "✅" on an action that
# never actually happened.
TOOL_LEVEL_FAILURE_PREFIXES = (
    "No case found with id",
    "No document named",
    "Invalid status",
)

INFRASTRUCTURE_FAILURE_PREFIXES = (
    "Unknown tool:",
    "Tool execution error:",
    "Blocked by tool policy:",
)

# Audit event name for each LLM-mediated operational intent handled by
# run_action. AI_TASK_CREATED is one of the required event names;
# AI_DOCUMENT_UPDATED is an addition for completeness (DOCUMENT_ACTION
# is a real, executed AI action and therefore needs the same audit
# coverage, even though it wasn't in the original required list).
AUDIT_EVENT_FOR_ACTION_INTENT = {
    Intent.CREATE_TASK: "AI_TASK_CREATED",
    Intent.DOCUMENT_ACTION: "AI_DOCUMENT_UPDATED",
}


def tool_step_succeeded(step: dict) -> bool:
    result_text = str(step["result"])

    return not (
        result_text.startswith(INFRASTRUCTURE_FAILURE_PREFIXES)
        or result_text.startswith(TOOL_LEVEL_FAILURE_PREFIXES)
    )


def run_action(
    user_goal: str,
    case_id: int,
    context: dict,
    context_json: str,
    steps_log: list,
    on_step,
    action_intent: Intent,
    current_user: dict,
) -> dict:
    """
    `action_intent` must be the real classified intent (e.g.
    Intent.CREATE_TASK), not the generic Intent.ACTION - tool_policy's
    authorization and tool-catalog-exposure checks are keyed off the
    real operational intent so they can enforce the correct
    permission for it.
    """

    messages = build_messages(
        ACTION_SYSTEM_PROMPT, case_id, context_json, user_goal
    )

    tools = tool_policy.tools_for_intent(action_intent, TOOLS_LIST)

    def _action_failure_answer(reason: str) -> str:
        # Every ACTION-route outcome - success, tool-level failure, or
        # infrastructure failure - is produced through ActionPayload +
        # format_response(Intent.ACTION, ...), never as an ad-hoc
        # string. This guarantees the answer never drifts into
        # analytical language even when nothing could be executed.
        payload = ActionPayload(
            tool_name=tool_policy.resolve_tool_for_intent(action_intent) or "unknown",
            arguments={"case_id": case_id},
            result=reason,
            success=False,
        )
        return format_response(Intent.ACTION, payload)

    try:
        response = chat(messages=messages, tools=tools, model=MODEL)
    except OllamaUnavailableError as e:
        answer = _action_failure_answer(
            f"The AI service is unavailable, so no action was executed: {e}"
        )
        audit_ai_action(
            current_user,
            case_id,
            AUDIT_EVENT_FOR_ACTION_INTENT[action_intent],
            answer,
            success=False,
        )
        record_step(
            steps_log, on_step, {"type": "final_answer", "content": answer}
        )
        return finish(case_id, user_goal, answer, steps_log, context)

    tool_calls = response.get("message", {}).get("tool_calls") or []

    if not tool_calls:
        answer = _action_failure_answer(
            "No action was executed for this request."
        )
        audit_ai_action(
            current_user,
            case_id,
            AUDIT_EVENT_FOR_ACTION_INTENT[action_intent],
            answer,
            success=False,
        )
        record_step(
            steps_log, on_step, {"type": "final_answer", "content": answer}
        )
        return finish(case_id, user_goal, answer, steps_log, context)

    # Exactly one tool execution per request, even if the model
    # returned more than one call.
    call = tool_calls[0]
    function = call.get("function", {})

    step = execute_tool(
        action_intent,
        function.get("name"),
        function.get("arguments", {}),
        case_id,
    )
    record_step(steps_log, on_step, step)

    payload = ActionPayload(
        tool_name=step["tool"],
        arguments=step["arguments"],
        result=str(step["result"]),
        success=tool_step_succeeded(step),
    )
    answer = format_response(Intent.ACTION, payload)

    audit_ai_action(
        current_user,
        case_id,
        AUDIT_EVENT_FOR_ACTION_INTENT[action_intent],
        str(step["result"]),
        success=payload.success,
    )

    record_step(
        steps_log, on_step, {"type": "final_answer", "content": answer}
    )

    return finish(case_id, user_goal, answer, steps_log, context)
