import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.ai import agent
from core.ai.intent import Intent


def _fake_context(
    case_status="IN_PROGRESS",
    workflow_state="DOCUMENT_COLLECTION",
    blocking_items=None,
    missing_documents=None,
    risk_factors=None,
    reason=None,
):
    return {
        "case": {"id": 42, "status": case_status},
        "workflow": {"current_state": workflow_state},
        "documents": {
            "missing_documents": missing_documents or [],
            "risk_factors": risk_factors or [],
        },
        "recommendation": {
            "blocking_items": blocking_items or [],
            "reason": reason,
        },
    }


def _run(user_goal, case_id=42, current_user=None, context=None, chat_return=None,
          classified_intent=None):
    ctx = context if context is not None else _fake_context()

    patches = [
        patch("core.ai.agent.orchestrator.build_agent_context", return_value=ctx),
    ]

    if classified_intent is not None:
        patches.append(
            patch("core.ai.agent.orchestrator.classify_intent", return_value=classified_intent)
        )

    if chat_return is not None:
        # chat() is called from two different route modules depending
        # on which intent is dispatched (tool_execution for ACTION,
        # read_only for ANALYZE) - only one is ever actually invoked
        # per test, so patching both is safe and keeps this helper
        # agnostic to which route a given test exercises.
        patches.append(patch("core.ai.agent.tool_execution.chat", return_value=chat_return))
        patches.append(patch("core.ai.agent.read_only.chat", return_value=chat_return))
    else:
        # If chat() is ever called when it shouldn't be, fail loudly
        # rather than silently returning a Mock.
        def _unexpected_chat_call(*args, **kwargs):
            raise AssertionError(
                "chat() was called but this test expected a fully "
                "deterministic path with no LLM involvement."
            )
        patches.append(patch("core.ai.agent.tool_execution.chat", side_effect=_unexpected_chat_call))
        patches.append(patch("core.ai.agent.read_only.chat", side_effect=_unexpected_chat_call))

    started = [p.start() for p in patches]
    try:
        return agent.run_agent(
            user_goal, case_id=case_id, current_user=current_user
        )
    finally:
        for p in patches:
            p.stop()


# ==========================
# 1. Hallucination control - STATUS / CHECK_BLOCKERS never call the LLM
# ==========================

def test_status_never_calls_the_llm():
    ctx = _fake_context(case_status="APPROVED", workflow_state="FINAL_REVIEW")
    result = _run(
        "What is the status of this case?",
        context=ctx,
        classified_intent=Intent.STATUS,
    )
    assert "APPROVED" in result["answer"]
    assert "FINAL_REVIEW" in result["answer"]


def test_check_blockers_never_calls_the_llm():
    ctx = _fake_context(
        blocking_items=["Missing signature"],
        missing_documents=["Passport copy"],
    )
    result = _run(
        "What is blocking this case?",
        context=ctx,
        classified_intent=Intent.CHECK_BLOCKERS,
    )
    assert "Missing signature" in result["answer"]
    assert "Passport copy" in result["answer"]


# ==========================
# 1. Hallucination control - ANALYZE grounds every field except
#    recommended_next_steps in verified context
# ==========================

def test_analyze_ignores_hallucinated_blockers_from_the_model():
    # Verified context has NO blockers/missing documents/risk factors.
    ctx = _fake_context()

    # The model hallucinates a blocker and a missing document that do
    # not exist anywhere in the verified context.
    fake_chat_response = {
        "message": {
            "content": (
                '{"blockers": ["Court order pending"], '
                '"missing_documents": ["Fabricated Form X"], '
                '"risk_factors": ["Invented risk"], '
                '"recommended_next_steps": ["Call the embassy immediately"]}'
            )
        }
    }

    result = _run(
        "Analyze this case.",
        context=ctx,
        classified_intent=Intent.ANALYZE,
        chat_return=fake_chat_response,
    )

    assert "Court order pending" not in result["answer"]
    assert "Fabricated Form X" not in result["answer"]
    assert "Invented risk" not in result["answer"]
    # Nothing to remediate in verified context -> next steps forced empty
    # even though the model suggested one.
    assert "Call the embassy" not in result["answer"]


def test_analyze_reports_real_context_even_if_model_output_is_garbage():
    ctx = _fake_context(
        blocking_items=["Missing employer signature"],
        missing_documents=["Commune Registration Form"],
        risk_factors=["Short permit validity"],
    )

    # Model returns unparseable garbage.
    fake_chat_response = {"message": {"content": "not valid json at all"}}

    result = _run(
        "Analyze this case.",
        context=ctx,
        classified_intent=Intent.ANALYZE,
        chat_return=fake_chat_response,
    )

    assert "Missing employer signature" in result["answer"]
    assert "Commune Registration Form" in result["answer"]
    assert "Short permit validity" in result["answer"]


def test_analyze_keeps_grounded_next_steps_when_there_is_something_to_remediate():
    ctx = _fake_context(missing_documents=["Commune Registration Form"])

    fake_chat_response = {
        "message": {
            "content": '{"recommended_next_steps": ["Obtain the Commune Registration Form"]}'
        }
    }

    result = _run(
        "Analyze this case.",
        context=ctx,
        classified_intent=Intent.ANALYZE,
        chat_return=fake_chat_response,
    )

    assert "Obtain the Commune Registration Form" in result["answer"]


# ==========================
# 3. Authentication / RBAC
# ==========================

def test_read_intents_never_require_authentication():
    for intent in (Intent.STATUS, Intent.CHECK_BLOCKERS):
        result = _run(
            "read only request",
            current_user=None,
            classified_intent=intent,
        )
        assert result["answer"] != "Authentication required."

    result = _run(
        "Analyze this case.",
        current_user=None,
        classified_intent=Intent.ANALYZE,
        chat_return={"message": {"content": "{}"}},
    )
    assert result["answer"] != "Authentication required."


def test_action_intent_without_current_user_returns_exact_auth_message():
    result = _run(
        "Create a task to collect a document.",
        current_user=None,
        classified_intent=Intent.CREATE_TASK,
    )
    assert result["answer"] == "Authentication required."


def test_action_intent_with_insufficient_role_is_forbidden_not_unauthenticated():
    with patch(
        "db.database.role_has_permission",
        # VIEWER has no permissions at all in this fake matrix.
        side_effect=lambda role, perm: False,
    ):
        result = _run(
            "Approve this case.",
            current_user={"role": "VIEWER"},
            classified_intent=Intent.APPROVE_CASE,
        )

    assert result["answer"] != "Authentication required."
    assert result["answer"].startswith("Action denied:")


def test_authenticated_authorized_user_executes_action_normally():
    with patch(
        "db.database.role_has_permission",
        side_effect=lambda role, perm: perm in {"ai:use", "cases:approve"},
    ), patch("core.ai.agent.orchestrator.approve_case", return_value={"message": "Case approved."}):
        result = _run(
            "Approve this case.",
            current_user={"role": "MANAGER"},
            classified_intent=Intent.APPROVE_CASE,
        )

    assert result["answer"] == "Case approved."


# ==========================
# 2. Action Formatter - deterministic, tool result only
# ==========================

def test_action_formatter_contains_only_tool_result_no_extra_commentary():
    with patch(
        "db.database.role_has_permission",
        side_effect=lambda role, perm: perm in {"ai:use", "tasks:edit"},
    ), patch(
        "core.ai.agent.tool_execution.AVAILABLE_TOOLS",
        {"create_task_for_case": lambda case_id, title: f"Task '{title}' created for case {case_id}."},
    ):
        result = _run(
            "Create a task to follow up.",
            case_id=42,
            current_user={"role": "STAFF"},
            classified_intent=Intent.CREATE_TASK,
            chat_return={
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "create_task_for_case",
                                "arguments": {"case_id": 999, "title": "Follow up"},
                            }
                        }
                    ]
                }
            },
        )

    assert result["answer"] == "✅ Task 'Follow up' created for case 42."
    # Never any analysis/recommendation/blocker language appended.
    for forbidden in ("risk", "recommend", "blocker", "compliance", "workflow"):
        assert forbidden not in result["answer"].lower()


def test_action_formatter_never_trusts_the_models_case_id():
    """
    The model's tool call above claims case_id=999, but the agent was
    invoked for case_id=42 (the user's actual, verified case). The
    executed tool must always receive 42, never the model's 999 -
    otherwise a hallucinated or malformed case_id could mutate a
    completely different case than the one the user was authorized for.
    """
    captured = {}

    def fake_create_task(case_id, title):
        captured["case_id"] = case_id
        return f"Task '{title}' created for case {case_id}."

    with patch(
        "db.database.role_has_permission",
        side_effect=lambda role, perm: perm in {"ai:use", "tasks:edit"},
    ), patch(
        "core.ai.agent.tool_execution.AVAILABLE_TOOLS",
        {"create_task_for_case": fake_create_task},
    ):
        _run(
            "Create a task to follow up.",
            case_id=42,
            current_user={"role": "STAFF"},
            classified_intent=Intent.CREATE_TASK,
            chat_return={
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "create_task_for_case",
                                "arguments": {"case_id": 999, "title": "Follow up"},
                            }
                        }
                    ]
                }
            },
        )

    assert captured["case_id"] == 42


def test_action_formatter_shows_failure_not_false_success():
    with patch(
        "db.database.role_has_permission",
        side_effect=lambda role, perm: perm in {"ai:use", "documents:edit"},
    ), patch(
        "core.ai.agent.tool_execution.AVAILABLE_TOOLS",
        {
            "update_document_status": lambda case_id, document_name, status: (
                f"No document named '{document_name}' found for case {case_id}."
            )
        },
    ):
        result = _run(
            "Mark the Nonexistent Form as received.",
            case_id=42,
            current_user={"role": "STAFF"},
            classified_intent=Intent.DOCUMENT_ACTION,
            chat_return={
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "update_document_status",
                                "arguments": {
                                    "case_id": 42,
                                    "document_name": "Nonexistent Form",
                                    "status": "RECEIVED",
                                },
                            }
                        }
                    ]
                }
            },
        )

    assert result["answer"].startswith("❌")


# ==========================
# Tool/intent mismatch (hallucination via wrong tool call)
# ==========================

def test_tool_intent_mismatch_is_blocked_even_if_model_tries_it():
    # Model classified as CREATE_TASK but (hypothetically, if it were
    # ever exposed) tries to call update_document_status instead.
    with patch(
        "db.database.role_has_permission",
        side_effect=lambda role, perm: perm in {"ai:use", "tasks:edit"},
    ):
        result = _run(
            "Create a task to follow up.",
            case_id=42,
            current_user={"role": "STAFF"},
            classified_intent=Intent.CREATE_TASK,
            chat_return={
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "update_document_status",
                                "arguments": {
                                    "case_id": 42,
                                    "document_name": "X",
                                    "status": "RECEIVED",
                                },
                            }
                        }
                    ]
                }
            },
        )

    assert result["answer"].startswith("❌")
    assert "Blocked by tool policy" in result["answer"] or "does not match intent" in result["answer"]
