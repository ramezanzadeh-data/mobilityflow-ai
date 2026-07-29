"""
Response Formatter.

This is the ONLY place in the codebase that produces the final,
user-facing text of an AI agent reply. The LLM (via core/ai/agent.py)
only ever returns structured data (core/ai/schemas.py) for ANALYZE and
STATUS, or a raw tool result for ACTION; this module turns that data
into sentences, and enforces exactly the fields each intent is allowed
to surface:

  - STATUS   -> case status, workflow state, confirmed blockers. Never
               risk, recommendations, or compliance commentary.
  - ANALYZE  -> blockers, missing documents, risk factors, workflow
               issues, recommended next steps. Never a future workflow
               state, and never a suggestion to advance/transition the
               workflow itself.
  - CHECK_BLOCKERS -> blocking items and missing documents only.
  - ACTION   -> a summary of the confirmed tool result only. Never
               analysis, blockers, recommendations, or workflow
               discussion.

Because prompt instructions alone are not reliable, ANALYZE and STATUS
also run every free-text field through a defensive filter that drops
any sentence containing forbidden "advance the workflow" language
before it ever reaches the user.
"""

import re

from core.ai.intent import Intent
from core.ai.schemas import ActionPayload, AnalysisPayload, StatusPayload, BlockersPayload


# Phrases that must never appear in ANALYZE or STATUS output, regardless
# of what the LLM produced, because they imply workflow progression is
# being decided or suggested by the AI.
_FORBIDDEN_PROGRESSION_PHRASES = (
    "advance",
    "advancing",
    "progress to",
    "progression",
    "move forward",
    "moving forward",
    "next stage",
    "next workflow state",
    "transition to",
    "should now proceed",
    "ready to move",
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _drop_forbidden_sentences(text: str) -> str:
    """Remove any sentence containing forbidden progression language."""

    if not text:
        return text

    sentences = _SENTENCE_SPLIT_RE.split(text.strip())

    kept = [
        sentence
        for sentence in sentences
        if not any(
            phrase in sentence.lower()
            for phrase in _FORBIDDEN_PROGRESSION_PHRASES
        )
    ]

    return " ".join(kept).strip()


def _clean_list(items):
    cleaned = [_drop_forbidden_sentences(item) for item in items]
    return [item.rstrip(".").strip() for item in cleaned if item]


def _join(label: str, items: list) -> str:
    return f"{label}: " + "; ".join(items) + "."


def _format_status(payload: StatusPayload) -> str:
    """STATUS: case status, workflow state, confirmed blockers - nothing else."""

    lines = [
        f"Case status: {payload.case_status}.",
        f"Workflow state: {payload.workflow_state}.",
    ]

    blocking_items = _clean_list(payload.blocking_items)

    if blocking_items:
        lines.append(_join("Confirmed blockers", blocking_items))
    else:
        lines.append("No confirmed blockers.")

    return " ".join(lines)


def _format_analysis(payload: AnalysisPayload) -> str:
    """
    ANALYZE: blockers, missing documents, risk factors, workflow issues,
    recommended next steps - and never a workflow-progression
    suggestion, enforced both by the schema (no such field exists) and
    by stripping forbidden sentences from every list below.
    """

    sections = []

    blockers = _clean_list(payload.blockers)
    if blockers:
        sections.append(_join("Blockers", blockers))

    missing_documents = _clean_list(payload.missing_documents)
    if missing_documents:
        sections.append(_join("Missing documents", missing_documents))

    risk_factors = _clean_list(payload.risk_factors)
    if risk_factors:
        sections.append(_join("Risk factors", risk_factors))

    workflow_issues = _clean_list(payload.workflow_issues)
    if workflow_issues:
        sections.append(_join("Workflow issues", workflow_issues))

    recommended_next_steps = _clean_list(payload.recommended_next_steps)
    if recommended_next_steps:
        sections.append(
            _join("Recommended next steps", recommended_next_steps)
        )

    if not sections:
        return "No blockers, risk factors, or workflow issues were found."

    return " ".join(sections)


def _format_blockers(payload: BlockersPayload) -> str:
    """CHECK_BLOCKERS: blocking items and missing documents - nothing else."""

    sections = []

    blockers = _clean_list(payload.blockers)
    if blockers:
        sections.append(_join("Blockers", blockers))

    missing_documents = _clean_list(payload.missing_documents)
    if missing_documents:
        sections.append(_join("Missing documents", missing_documents))

    if not sections:
        return "No blockers or missing documents were found."

    return " ".join(sections)


def _format_action(payload: ActionPayload) -> str:
    """
    ACTION: a summary of the confirmed tool result ONLY. No analysis, no
    blockers, no recommendations, no workflow discussion.
    """

    if not payload.success:
        return f"❌ Action failed: {payload.result}"

    return f"✅ {payload.result}"


_FORMATTERS = {
    Intent.STATUS: _format_status,
    Intent.ANALYZE: _format_analysis,
    Intent.CHECK_BLOCKERS: _format_blockers,
    Intent.ACTION: _format_action,
}

_PAYLOAD_TYPES = {
    Intent.STATUS: StatusPayload,
    Intent.ANALYZE: AnalysisPayload,
    Intent.CHECK_BLOCKERS: BlockersPayload,
    Intent.ACTION: ActionPayload,
}


def format_response(intent: Intent, payload) -> str:
    """
    Turn a structured payload into the final user-facing text for the
    given intent. Raises TypeError on a payload/intent mismatch - a
    mismatch means the agent built the wrong payload for the classified
    intent, which must fail loudly rather than silently leak the wrong
    content to the user.
    """

    expected_type = _PAYLOAD_TYPES[intent]

    if not isinstance(payload, expected_type):
        raise TypeError(
            f"format_response expected a {expected_type.__name__} for "
            f"intent {intent.value!r}, got {type(payload).__name__}."
        )

    return _FORMATTERS[intent](payload)
