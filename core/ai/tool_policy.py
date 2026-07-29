"""
Tool Policy layer.

Single source of truth for:

    "Which intents are allowed to execute tools?"

Every tool execution MUST pass through authorize()
immediately before execution.

The LLM never decides permission.
Intent classification + this policy decide permission.
"""

from dataclasses import dataclass

from core.ai.intent import Intent, OPERATIONAL_INTENTS


# Decision codes - lets callers distinguish *why* something was denied
# without parsing the human-readable reason string.
DECISION_OK = "OK"
DECISION_AUTH_REQUIRED = "AUTH_REQUIRED"   # no current_user at all (401-equivalent)
DECISION_FORBIDDEN = "FORBIDDEN"           # current_user present, role lacks permission (403-equivalent)
DECISION_NOT_OPERATIONAL = "NOT_OPERATIONAL"
DECISION_UNKNOWN_TOOL = "UNKNOWN_TOOL"
DECISION_TOOL_INTENT_MISMATCH = "TOOL_INTENT_MISMATCH"
DECISION_TOOL_NOT_IMPLEMENTED = "TOOL_NOT_IMPLEMENTED"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    code: str = DECISION_OK

    def __bool__(self):
        return self.allowed


class ToolPolicyViolation(Exception):
    """
    Raised when a tool execution is denied by policy.
    """
    pass


# ==================================================
# Enterprise action intents
# ==================================================

# Single source of truth for "which intents are operational" lives in
# core.ai.intent (next to the classifier that produces these values),
# imported here rather than re-declared so the Intent Router and the
# Tool Policy can never drift out of sync on this list.
_OPERATIONAL_INTENTS = OPERATIONAL_INTENTS

# Every operational intent must additionally be gated by the role
# permission matrix in db.database (the single source of truth for
# "what can each role do" - see auth/permissions.py). Without this,
# classifying an intent as "operational" was sufficient by itself to
# let the AI agent run it, regardless of which user (or which role)
# was actually asking - e.g. a VIEWER could ask the agent to approve
# a case even though VIEWER has no case-editing permission anywhere
# else in the app.
#
# Every entry here must correspond to a real permission name seeded in
# db.database._ALL_PERMISSIONS - cases:reject, cases:close,
# cases:archive, and tasks:assign were added there alongside these
# four new operational intents so the RBAC matrix and the Intent
# Router are completed together, not left half-wired.
_REQUIRED_PERMISSION_FOR_INTENT = {
    Intent.CREATE_TASK: "tasks:edit",
    Intent.ASSIGN_TASK: "tasks:assign",
    Intent.ADVANCE_WORKFLOW: "cases:edit",
    Intent.APPROVE_CASE: "cases:approve",
    Intent.REJECT_CASE: "cases:reject",
    Intent.DELETE_CASE: "cases:delete",
    Intent.CLOSE_CASE: "cases:close",
    Intent.ARCHIVE_CASE: "cases:archive",
    Intent.DOCUMENT_ACTION: "documents:edit",
    # GENERIC_ACTION covers an operational verb that didn't match any
    # more specific intent above - treated as a general case mutation
    # for permission purposes until it is split into its own typed
    # intent with its own tool.
    Intent.GENERIC_ACTION: "cases:edit",
}

# The ONE tool each LLM-mediated operational intent is allowed to
# execute. Exposing the full tool catalog to every operational intent
# (the previous behaviour) meant a CREATE_TASK request could, if the
# model got confused, end up authorized to call update_document_status
# instead - a real, wrong tool would fire under the wrong intent.
# Restricting both tool exposure (tools_for_intent) and authorization
# (authorize) to exactly this map closes that off entirely.
#
# APPROVE_CASE and ADVANCE_WORKFLOW are NOT LLM-mediated at all -
# core.ai.agent.run_agent calls approve_case()/recommend_workflow_advance()
# directly and deterministically, since neither needs any free-text
# parameter extracted from the user's message (only case_id, which the
# agent already has verified). Routing them through LLM tool-calling
# would add a hallucination surface for zero benefit. They are listed
# here only so this map is a complete, explicit record of what
# implements every operational intent.
#
# REJECT_CASE, DELETE_CASE, CLOSE_CASE, ARCHIVE_CASE, ASSIGN_TASK, and
# GENERIC_ACTION map to None: the Intent Router already recognizes and
# RBAC-gates these requests correctly, but no backing tool/workflow
# function exists for them yet (this was NOT part of the original
# codebase and must not be invented here - see resolve_tool_for_intent
# and core.ai.agent.unimplemented.run_unimplemented_action for how this is
# surfaced honestly to the user as "not yet implemented", entirely
# through the Action Policy layer, instead of silently no-opping or
# being answered by the analytical/LLM path).
_TOOL_FOR_INTENT = {
    Intent.CREATE_TASK: "create_task_for_case",
    Intent.DOCUMENT_ACTION: "update_document_status",
    Intent.ADVANCE_WORKFLOW: "recommend_workflow_advance",  # handled directly, not via tool-calling
    Intent.APPROVE_CASE: "approve_case",                    # handled directly, not via tool-calling
    Intent.REJECT_CASE: None,
    Intent.DELETE_CASE: None,
    Intent.CLOSE_CASE: None,
    Intent.ARCHIVE_CASE: None,
    Intent.ASSIGN_TASK: None,
    Intent.GENERIC_ACTION: None,
}

# Baseline permission required to use the AI agent for ANY operational
# action, on top of the action-specific permission above.
_AI_USE_PERMISSION = "ai:use"


def is_operational(intent: Intent) -> bool:
    """
    Returns True when an intent represents
    an operational action.

    These intents may execute tools.
    """

    return intent in _OPERATIONAL_INTENTS


def resolve_tool_for_intent(intent: Intent) -> str | None:
    """
    Returns the single tool name mapped to this operational intent, or
    None if the intent is recognized/RBAC-gated but has no backing
    tool implemented yet. Callers (core.ai.agent) use this to decide
    whether an operational request can proceed to tool-calling at all,
    strictly before ever consulting the LLM.
    """

    return _TOOL_FOR_INTENT.get(intent)


def tool_availability_decision(intent: Intent) -> "PolicyDecision":
    """
    Policy-level decision for "does a tool exist for this operational
    intent at all?" - independent of RBAC (call
    check_operational_permission first) and independent of the LLM's
    own tool choice (call authorize() at execution time for that).

    This exists so that the exact user-facing wording for "this action
    is recognized but not implemented yet" lives in ONE place (the
    Tool Policy layer) rather than being hard-coded inline in
    core.ai.agent - keeping the Action Policy the single source of
    truth for every operational-intent response, success or failure.
    """

    if not is_operational(intent):
        return PolicyDecision(
            allowed=False,
            reason=f"Intent '{intent.value}' is not operational.",
            code=DECISION_NOT_OPERATIONAL,
        )

    if resolve_tool_for_intent(intent) is None:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"The action '{intent.value}' is recognized but no tool "
                "is implemented for it yet. No action was executed."
            ),
            code=DECISION_TOOL_NOT_IMPLEMENTED,
        )

    return PolicyDecision(allowed=True, reason="Tool available.", code=DECISION_OK)


def check_operational_permission(
    intent: Intent,
    current_user: dict | None,
) -> PolicyDecision:
    """
    Authorize a user to perform an operational intent through the AI
    agent. This is the RBAC gate that must run before an operational
    intent is ever acted on - independent of, and in addition to, the
    tool-vs-catalog check in authorize() below.

    Rules:

    1. Non-operational intents (ANALYZE, STATUS, CHECK_BLOCKERS) are
       always allowed through this gate - they never execute a tool.
    2. Operational intents require an authenticated user.
    3. The user's role must have the 'ai:use' permission.
    4. The user's role must have the specific permission required for
       this intent (see _REQUIRED_PERMISSION_FOR_INTENT).
    """

    if not is_operational(intent):
        return PolicyDecision(
            allowed=True,
            reason="Not an operational intent; no permission required.",
            code=DECISION_OK,
        )

    if current_user is None:
        return PolicyDecision(
            allowed=False,
            reason="Authentication required.",
            code=DECISION_AUTH_REQUIRED,
        )

    role = current_user.get("role")

    # Local import to avoid a circular import at module load time
    # (db.database does not import core.ai, but importing at module
    # scope here would still tie this module's import order to the
    # database layer's; keeping it local matches the existing style
    # in auth/permissions.py).
    from db.database import role_has_permission

    if not role_has_permission(role, _AI_USE_PERMISSION):
        return PolicyDecision(
            allowed=False,
            reason="This role is not permitted to use AI features.",
            code=DECISION_FORBIDDEN,
        )

    required_permission = _REQUIRED_PERMISSION_FOR_INTENT.get(intent)

    if required_permission and not role_has_permission(role, required_permission):
        return PolicyDecision(
            allowed=False,
            reason=(
                f"This role lacks the '{required_permission}' "
                f"permission required for '{intent.value}'."
            ),
            code=DECISION_FORBIDDEN,
        )

    return PolicyDecision(allowed=True, reason="Authorized.", code=DECISION_OK)



def authorize(
    intent: Intent,
    tool_name: str,
    tools_list: list
) -> PolicyDecision:
    """
    Central permission check.

    Every tool execution must call this.

    Rules:

    1. Non operational intents cannot run tools.
    2. Tool must exist in the allowed catalog.
    3. Tool must be THE specific tool mapped to this intent
       (_TOOL_FOR_INTENT) - not merely any tool present somewhere in
       the catalog. Without this, a CREATE_TASK request could end up
       authorized to run update_document_status (or vice versa)
       simply because both tools exist in the same tools_list.
    """

    if not is_operational(intent):

        return PolicyDecision(
            allowed=False,
            reason=(
                f"Intent '{intent.value}' is not operational. "
                "Tools are disabled for analysis intents."
            ),
            code=DECISION_NOT_OPERATIONAL,
        )


    known_tools = {
        tool.get("function", {}).get("name")
        for tool in tools_list
    }


    if tool_name not in known_tools:

        return PolicyDecision(
            allowed=False,
            reason=(
                f"Tool '{tool_name}' is not available "
                "for this action."
            ),
            code=DECISION_UNKNOWN_TOOL,
        )

    expected_tool = _TOOL_FOR_INTENT.get(intent)

    # No tool is mapped to this intent at all (e.g. REJECT_CASE,
    # DELETE_CASE, GENERIC_ACTION) - deny unconditionally. Without this
    # explicit branch, `tool_name != expected_tool` would never be
    # True when expected_tool is None (since expected_tool is never a
    # real tool_name string), which would silently authorize ANY tool
    # call for an intent that is supposed to have none available.
    if expected_tool is None:

        return PolicyDecision(
            allowed=False,
            reason=(
                f"No tool is implemented for intent '{intent.value}' "
                "yet. No action was executed."
            ),
            code=DECISION_TOOL_NOT_IMPLEMENTED,
        )

    if tool_name != expected_tool:

        return PolicyDecision(
            allowed=False,
            reason=(
                f"Tool '{tool_name}' does not match intent "
                f"'{intent.value}'. Only '{expected_tool}' is "
                "permitted for this intent."
            ),
            code=DECISION_TOOL_INTENT_MISMATCH,
        )


    return PolicyDecision(
        allowed=True,
        reason="Authorized.",
        code=DECISION_OK,
    )



def enforce_tool_permission(
    intent: Intent,
    tool_name: str,
    tools_list: list
) -> None:
    """
    Same authorization check but raises exception.
    """

    decision = authorize(
        intent,
        tool_name,
        tools_list
    )


    if not decision.allowed:
        raise ToolPolicyViolation(
            decision.reason
        )



def tools_for_intent(
    intent: Intent,
    tools_list: list
) -> list | None:
    """
    Controls which tools are exposed to the LLM.

    Enterprise rule:

    Operational intent:
        -> ONLY the single tool mapped to this intent in
           _TOOL_FOR_INTENT is exposed, never the full catalog. This
           means the model cannot even attempt to call a mismatched
           tool for the classified intent - there is nothing else on
           offer.

    Analysis intent:
        -> tools disabled entirely (returns None).
    """

    if not is_operational(intent):
        return None

    expected_tool = _TOOL_FOR_INTENT.get(intent)

    if expected_tool is None:
        return []

    return [
        tool
        for tool in tools_list
        if tool.get("function", {}).get("name") == expected_tool
    ]