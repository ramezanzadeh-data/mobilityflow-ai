"""
run_agent - the single public entry point of the AI agent package.

Pipeline for every request:

  1. Build verified case context (core.context.case_context_builder).
  2. Classify intent BEFORE talking to the LLM (core.ai.intent) - this
     alone decides whether the model is ever offered a tool.
  3. RBAC gate (core.ai.tool_policy.check_operational_permission) runs
     before anything operational is acted on.
  4. Dispatch:
       STATUS / CHECK_BLOCKERS -> fully deterministic, no LLM call at
                 all (core.ai.agent.read_only.run_status_or_blockers).
       ANALYZE -> the LLM is consulted only for recommended_next_steps
                 (core.ai.agent.read_only.run_analysis).
       APPROVE_CASE / ADVANCE_WORKFLOW -> handled directly, right here,
                 calling the real workflow function deterministically.
                 Neither needs any free-text parameter extracted from
                 the user's message (only case_id, which the agent
                 already has verified), so neither is ever routed
                 through LLM tool-calling.
       REJECT_CASE / DELETE_CASE / CLOSE_CASE / ARCHIVE_CASE /
       ASSIGN_TASK / GENERIC_ACTION -> recognized and RBAC-gated, but
                 no backing tool is implemented yet
                 (core.ai.agent.unimplemented.run_unimplemented_action).
       CREATE_TASK / DOCUMENT_ACTION -> native tool-calling
                 (core.ai.agent.tool_execution.run_action), because
                 these genuinely need a free-text parameter (a task
                 title, or a document name/status) extracted from the
                 user's message.

The LLM is never trusted to write the final user-facing sentence, is
never the source of an authoritative fact it could instead look up,
and is never trusted to describe an action beyond what a tool actually
confirmed.
"""

import json

from core.context.case_context_builder import build_agent_context
from core.ai.tools import recommend_workflow_advance
from core.ai.intent import Intent, classify_intent
from core.ai import tool_policy
from core.ai.response_formatter import format_response
from core.ai.schemas import ActionPayload
from core.workflow.service import approve_case

from core.ai.agent.shared import record_step, finish
from core.ai.agent.audit import audit_ai_action
from core.ai.agent.tool_execution import run_action, tool_step_succeeded
from core.ai.agent.read_only import run_status_or_blockers, run_analysis
from core.ai.agent.unimplemented import run_unimplemented_action


def run_agent(
    user_goal: str,
    case_id: int = None,
    current_user: dict = None,
    *,
    on_step=None,
) -> dict:
    """
    `current_user` should be the authenticated caller (the same dict
    shape produced by apps/api/dependencies/auth.get_current_user or
    stored in Streamlit's session as st.session_state["user"]) -
    it must contain at least a "role" key. It is required in order to
    execute any operational intent (CREATE_TASK, ADVANCE_WORKFLOW,
    APPROVE_CASE, DOCUMENT_ACTION); read-only intents (ANALYZE,
    STATUS, CHECK_BLOCKERS) do not require it.

    Passing current_user=None will cause any operational request to
    be denied rather than silently allowed - there is no "trusted by
    default" caller for this function.

    `current_user` comes right after `case_id`, and `on_step` is
    keyword-only (note the `*`). Every real call site in this codebase
    already passes `current_user` by keyword; making `on_step`
    keyword-only turns a positional-argument mistake into a loud
    TypeError instead of a silent, hard-to-debug auth failure.
    """

    steps_log = []

    if case_id is None:
        return {
            "answer": "case_id is required.",
            "steps": steps_log
        }

    try:
        context = build_agent_context(case_id)
    except Exception as e:
        # The Context layer (core.context.case_context_builder) already
        # returns a clean {"error": ...} dict for a not-found case; this
        # guards only against an unexpected failure underneath it (e.g.
        # a database/connectivity error), so the whole pipeline degrades
        # to a clear message instead of an unhandled crash.
        answer = f"Case context could not be loaded: {e}"
        steps_log.append({"type": "final_answer", "content": answer})
        if on_step:
            on_step(steps_log[-1])
        return {"answer": answer, "steps": steps_log, "context": {"error": str(e)}}

    context_json = json.dumps(
        context,
        indent=2,
        ensure_ascii=False
    )

    # Intent Router - classified BEFORE any call to the LLM.
    intent = classify_intent(user_goal)

    # RBAC gate - must run before ANY operational intent is acted on.
    # This is independent of, and in addition to, the tool-vs-catalog
    # check inside tool_policy.authorize() used by
    # core.ai.agent.tool_execution.execute_tool: that check only knows
    # whether a tool exists for an intent, never whether the calling
    # user's role is allowed to invoke it.
    permission_decision = tool_policy.check_operational_permission(
        intent, current_user
    )

    if not permission_decision.allowed:
        if permission_decision.code == tool_policy.DECISION_AUTH_REQUIRED:
            # Exact required phrase for the "no authenticated caller"
            # case - kept distinct from an authenticated-but-forbidden
            # denial below, since these are different failure modes
            # (401-equivalent vs 403-equivalent). Not audit-logged:
            # there is no authenticated identity to attribute the
            # attempt to.
            answer = "Authentication required."
        else:
            answer = f"Action denied: {permission_decision.reason}"
            audit_ai_action(
                current_user,
                case_id,
                "AI_ACTION_DENIED",
                f"AI action denied for intent '{intent.value}': "
                f"{permission_decision.reason}",
                success=False,
            )

        record_step(
            steps_log, on_step, {"type": "final_answer", "content": answer}
        )

        return finish(case_id, user_goal, answer, steps_log, context)

    if intent == Intent.APPROVE_CASE:

        result = approve_case(case_id)

        step = {
            "type": "tool_call",
            "tool": "approve_case",
            "arguments": {
                "case_id": case_id
            },
            "result": result,
        }

        record_step(
            steps_log,
            on_step,
            step
        )

        answer = result.get(
            "message",
            str(result)
        )

        audit_ai_action(
            current_user,
            case_id,
            "AI_CASE_APPROVED",
            answer,
            success=bool(result.get("success")),
        )

        record_step(
            steps_log,
            on_step,
            {
                "type": "final_answer",
                "content": answer
            }
        )

        return finish(
            case_id,
            user_goal,
            answer,
            steps_log,
            context
        )

    if intent == Intent.ADVANCE_WORKFLOW:
        # Handled directly and deterministically, exactly like
        # APPROVE_CASE above: recommend_workflow_advance takes only
        # case_id (already verified, never model-supplied) and needs
        # no free-text parameter extracted from the user's message, so
        # there is nothing for the LLM to usefully contribute here -
        # routing it through tool-calling would only add an
        # unnecessary hallucination surface.

        result_text = recommend_workflow_advance(case_id)

        step = {
            "type": "tool_call",
            "tool": "recommend_workflow_advance",
            "arguments": {"case_id": case_id},
            "result": result_text,
        }

        record_step(steps_log, on_step, step)

        payload = ActionPayload(
            tool_name="recommend_workflow_advance",
            arguments={"case_id": case_id},
            result=result_text,
            success=tool_step_succeeded(step),
        )
        answer = format_response(Intent.ACTION, payload)

        # AI_WORKFLOW_REVIEWED, not AI_WORKFLOW_ADVANCED:
        # recommend_workflow_advance only produces a recommendation for
        # a human to confirm - it never calls set_workflow_state itself.
        # AI_WORKFLOW_ADVANCED is reserved for when a real
        # state-mutating tool backs this intent.
        audit_ai_action(
            current_user,
            case_id,
            "AI_WORKFLOW_REVIEWED",
            result_text,
            success=payload.success,
        )

        record_step(
            steps_log, on_step, {"type": "final_answer", "content": answer}
        )

        return finish(case_id, user_goal, answer, steps_log, context)

    if intent in (
        Intent.REJECT_CASE,
        Intent.DELETE_CASE,
        Intent.CLOSE_CASE,
        Intent.ARCHIVE_CASE,
        Intent.ASSIGN_TASK,
        Intent.GENERIC_ACTION,
    ):
        # Recognized, RBAC-gated operational intents with no backing
        # tool implemented yet. Answered entirely by the Action Policy
        # layer - never by the LLM, never by the analytical path.
        return run_unimplemented_action(
            intent, user_goal, case_id, context, steps_log, on_step, current_user
        )

    if intent in (Intent.CREATE_TASK, Intent.DOCUMENT_ACTION):
        # The only two operational intents genuinely mediated by the
        # LLM, because both need a free-text parameter (a task title,
        # or a document name/status) extracted from the user's
        # message that cannot be deterministically looked up.

        return run_action(
            user_goal,
            case_id,
            context,
            context_json,
            steps_log,
            on_step,
            intent,
            current_user,
        )

    if intent in (Intent.STATUS, Intent.CHECK_BLOCKERS):
        return run_status_or_blockers(
            intent, user_goal, case_id, context, steps_log, on_step
        )

    # Intent.ANALYZE: the only remaining case. The LLM is consulted
    # only for recommended_next_steps; every other field is overwritten
    # from verified context.
    return run_analysis(
        user_goal,
        case_id,
        context,
        context_json,
        steps_log,
        on_step,
    )
