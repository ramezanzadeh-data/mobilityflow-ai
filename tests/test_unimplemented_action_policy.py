import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.ai import agent, tool_policy
from core.ai.intent import Intent


def _fake_context():
    return {
        "case": {"id": 42, "status": "IN_PROGRESS"},
        "workflow": {"current_state": "DOCUMENT_COLLECTION"},
        "documents": {"missing_documents": [], "risk_factors": []},
        "recommendation": {"blocking_items": [], "reason": None},
    }


def _run(user_goal, classified_intent, current_user=None, role_permissions=None):
    role_permissions = role_permissions or {}

    def fake_role_has_permission(role, permission_name):
        return permission_name in role_permissions.get(role, set())

    def _unexpected_chat_call(*args, **kwargs):
        raise AssertionError(
            "core.ai.agent.chat was called for an intent with no "
            "backing tool - the LLM must never be consulted here."
        )

    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=classified_intent), \
         patch("core.ai.agent.tool_execution.chat", side_effect=_unexpected_chat_call), \
         patch("core.ai.agent.read_only.chat", side_effect=_unexpected_chat_call), \
         patch("db.database.role_has_permission", fake_role_has_permission):
        return agent.run_agent(user_goal, case_id=42, current_user=current_user)


_UNIMPLEMENTED_INTENTS = (
    Intent.REJECT_CASE,
    Intent.DELETE_CASE,
    Intent.CLOSE_CASE,
    Intent.ARCHIVE_CASE,
    Intent.ASSIGN_TASK,
    Intent.GENERIC_ACTION,
)


def test_unimplemented_action_never_calls_the_llm_and_fails_via_action_policy():
    permission_by_intent = {
        Intent.REJECT_CASE: "cases:reject",
        Intent.DELETE_CASE: "cases:delete",
        Intent.CLOSE_CASE: "cases:close",
        Intent.ARCHIVE_CASE: "cases:archive",
        Intent.ASSIGN_TASK: "tasks:assign",
        Intent.GENERIC_ACTION: "cases:edit",
    }

    for intent in _UNIMPLEMENTED_INTENTS:
        result = _run(
            "Do the operational thing.",
            classified_intent=intent,
            current_user={"role": "MANAGER"},
            role_permissions={
                "MANAGER": {"ai:use", permission_by_intent[intent]}
            },
        )

        assert result["answer"].startswith("❌"), intent
        assert "no tool is implemented" in result["answer"].lower()
        # Never analytical language leaking into a failed action reply.
        for forbidden in ("risk factor", "recommend", "blocker", "workflow issue"):
            assert forbidden not in result["answer"].lower()


def test_unimplemented_action_still_requires_authentication_first():
    # Authentication must be enforced BEFORE "no tool implemented" is
    # ever revealed - an anonymous caller gets the generic auth denial,
    # not a hint about which actions exist.
    for intent in _UNIMPLEMENTED_INTENTS:
        result = _run(
            "Do the operational thing.",
            classified_intent=intent,
            current_user=None,
        )
        assert result["answer"] == "Authentication required."


def test_unimplemented_action_still_requires_the_right_permission():
    for intent in _UNIMPLEMENTED_INTENTS:
        result = _run(
            "Do the operational thing.",
            classified_intent=intent,
            current_user={"role": "VIEWER"},
            role_permissions={"VIEWER": set()},
        )
        assert result["answer"].startswith("Action denied:")


def test_authorize_denies_any_tool_when_none_is_mapped_to_the_intent():
    # Regression test: an intent with _TOOL_FOR_INTENT[...] is None must
    # deny EVERY tool_name, not silently allow whichever one is passed
    # in (the mismatch check alone is not enough once None is a valid
    # map value).
    fake_tools_list = [
        {"type": "function", "function": {"name": "create_task_for_case"}},
        {"type": "function", "function": {"name": "update_document_status"}},
    ]

    for intent in _UNIMPLEMENTED_INTENTS:
        # Tool names that DO exist somewhere in the catalog must still
        # be denied because no tool is mapped to this intent at all.
        for tool_name in ("create_task_for_case", "update_document_status"):
            decision = tool_policy.authorize(intent, tool_name, fake_tools_list)
            assert not decision.allowed, (intent, tool_name)
            assert decision.code == tool_policy.DECISION_TOOL_NOT_IMPLEMENTED

        # A tool name that isn't in the catalog at all is correctly
        # denied for the more fundamental reason (unknown tool) - the
        # invariant that matters here is simply "never allowed".
        decision = tool_policy.authorize(intent, "anything", fake_tools_list)
        assert not decision.allowed, intent
        assert decision.code == tool_policy.DECISION_UNKNOWN_TOOL
