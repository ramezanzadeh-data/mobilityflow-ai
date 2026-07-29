"""
STATUS / CHECK_BLOCKERS: fully deterministic, the LLM is never called
for these at all.

ANALYZE: the LLM is consulted only for recommended_next_steps; every
other field is overwritten from verified context regardless of what
the model returned.
"""

from pydantic import ValidationError

from core.ai.ollama_client import chat, OllamaUnavailableError
from core.ai.intent import Intent
from core.ai.json_utils import extract_json_object
from core.ai.response_formatter import format_response
from core.ai.schemas import AnalysisPayload, StatusPayload, BlockersPayload

from core.ai.agent.config import MODEL
from core.ai.agent.prompts import BASE_SYSTEM_PROMPT, ANALYZE_SCHEMA_INSTRUCTION, build_messages
from core.ai.agent.shared import record_step, finish


def context_derived_fields(context: dict) -> dict:
    """
    The single source of every fact that can be read directly off the
    verified case context, used by ALL THREE reasoning intents
    (STATUS, CHECK_BLOCKERS, ANALYZE). None of these values are ever
    taken from LLM output - they are looked up here, not generated.
    """

    case = context.get("case", {})
    workflow = context.get("workflow", {})
    documents = context.get("documents", {})
    recommendation = context.get("recommendation", {})

    blocking_items = (
        ["Case not found."]
        if "error" in context
        else recommendation.get("blocking_items", [])
    )

    reason = recommendation.get("reason")

    return {
        "case_status": case.get("status", "UNKNOWN"),
        "workflow_state": workflow.get("current_state", "UNKNOWN"),
        "blocking_items": blocking_items,
        "missing_documents": documents.get("missing_documents", []),
        "risk_factors": documents.get("risk_factors", []),
        "workflow_issues": [reason] if reason else [],
    }


def run_status_or_blockers(
    intent: Intent,
    user_goal: str,
    case_id: int,
    context: dict,
    steps_log: list,
    on_step,
) -> dict:
    """
    STATUS and CHECK_BLOCKERS never call the LLM: every field they
    report is a direct, deterministic lookup from the verified case
    context (context_derived_fields), so there is no path at all for
    the model to invent, paraphrase, or drift on facts that are
    already fully known. This is the strongest possible hallucination
    guarantee for these two intents - the model is never in the loop
    for their content, not even for phrasing.
    """

    fields = context_derived_fields(context)

    if intent == Intent.STATUS:
        payload = StatusPayload(
            case_status=fields["case_status"],
            workflow_state=fields["workflow_state"],
            blocking_items=fields["blocking_items"],
        )
    else:
        payload = BlockersPayload(
            blockers=fields["blocking_items"],
            missing_documents=fields["missing_documents"],
        )

    answer = format_response(intent, payload)

    record_step(
        steps_log, on_step, {"type": "final_answer", "content": answer}
    )

    return finish(case_id, user_goal, answer, steps_log, context)


# Cap on how many recommended_next_steps are ever shown, regardless of
# how many the model returned - a defensive limit against a runaway or
# rambling model response, never a legitimate long remediation list.
MAX_RECOMMENDED_NEXT_STEPS = 5


def grounded_next_steps(model_steps: list, fields: dict) -> list:
    """
    recommended_next_steps is the one field in the whole reasoning
    pipeline that legitimately requires the model to synthesize
    wording rather than just look up a value - so it is the only field
    ANALYZE still takes from the LLM. Even so, it is never trusted
    unconditionally:

    - If verified context shows nothing to remediate (no blockers, no
      missing documents, no risk factors), there is nothing to
      recommend - forced to an empty list regardless of what the model
      said, closing off the common hallucination pattern of inventing
      a "next step" for an already-clean case.
    - Capped at MAX_RECOMMENDED_NEXT_STEPS.
    """

    has_anything_to_remediate = bool(
        fields["blocking_items"]
        or fields["missing_documents"]
        or fields["risk_factors"]
    )

    if not has_anything_to_remediate:
        return []

    return [str(step) for step in model_steps if step][:MAX_RECOMMENDED_NEXT_STEPS]


def run_analysis(
    user_goal: str,
    case_id: int,
    context: dict,
    context_json: str,
    steps_log: list,
    on_step,
) -> dict:
    """
    ANALYZE: tools=None, no operational action is ever possible here.
    The LLM is consulted ONLY to synthesize recommended_next_steps;
    blockers, missing_documents, risk_factors, and workflow_issues are
    always overwritten from verified context after the call, whether
    or not the model's JSON parsed - so even a fully successful,
    schema-valid model response cannot make this intent report a fact
    that isn't actually in the verified context.
    """

    system_prompt = BASE_SYSTEM_PROMPT + "\n" + ANALYZE_SCHEMA_INSTRUCTION
    messages = build_messages(system_prompt, case_id, context_json, user_goal)

    model_next_steps = []

    try:
        response = chat(messages=messages, tools=None, model=MODEL)
        content = response.get("message", {}).get("content", "")

        parsed_json = extract_json_object(content)

        if parsed_json is None:
            raise ValueError("No JSON object found in model output.")

        # Only recommended_next_steps is ever read from this payload -
        # every other field the model might have included is ignored.
        model_next_steps = parsed_json.get("recommended_next_steps", [])

        if not isinstance(model_next_steps, list):
            raise ValueError("recommended_next_steps must be a list.")

    except (ValueError, ValidationError, AttributeError, OllamaUnavailableError):
        # Whether the model is unreachable, times out, or returns
        # unparsable/malformed output, ANALYZE degrades the same way:
        # recommended_next_steps is empty and every other field still
        # comes from verified context below - never a crash, never a
        # fabricated recommendation.
        model_next_steps = []

    fields = context_derived_fields(context)

    payload = AnalysisPayload(
        blockers=fields["blocking_items"],
        missing_documents=fields["missing_documents"],
        risk_factors=fields["risk_factors"],
        workflow_issues=fields["workflow_issues"],
        recommended_next_steps=grounded_next_steps(model_next_steps, fields),
    )

    answer = format_response(Intent.ANALYZE, payload)

    record_step(
        steps_log, on_step, {"type": "final_answer", "content": answer}
    )

    return finish(case_id, user_goal, answer, steps_log, context)
