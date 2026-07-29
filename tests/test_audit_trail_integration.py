import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.ai import agent
from core.ai.intent import Intent


def _fake_context():
    return {
        "case": {"id": 1, "status": "IN_PROGRESS"},
        "workflow": {"current_state": "DOCUMENT_COLLECTION"},
        "documents": {"missing_documents": [], "risk_factors": []},
        "recommendation": {"blocking_items": [], "reason": None},
    }


_ADMIN = {"id": 1, "role": "ADMIN", "company": "Default Company"}


def _role_has_permission_factory(granted: set):
    def fake_role_has_permission(role, permission_name):
        return permission_name in granted
    return fake_role_has_permission


# ---------------------------------------------------------------------
# Test 1: ADMIN creates a task -> case_events + security_audit_log both
# get AI_TASK_CREATED.
# ---------------------------------------------------------------------

def test_admin_create_task_writes_both_audit_records():
    fake_chat_response = {
        "message": {
            "tool_calls": [
                {
                    "function": {
                        "name": "create_task_for_case",
                        "arguments": {"case_id": 1, "title": "Commune Registration Form"},
                    }
                }
            ]
        }
    }

    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=Intent.CREATE_TASK), \
         patch("db.database.role_has_permission", _role_has_permission_factory({"ai:use", "tasks:edit"})), \
         patch("core.ai.agent.tool_execution.chat", return_value=fake_chat_response), \
         patch(
             "core.ai.agent.tool_execution.AVAILABLE_TOOLS",
             {"create_task_for_case": lambda case_id, title: f"Task '{title}' created for case {case_id}."},
         ), \
         patch("core.ai.agent.audit.log_case_event") as mock_log_case_event, \
         patch("core.ai.agent.audit.log_security_event") as mock_log_security_event:

        result = agent.run_agent(
            "Create a task for the missing document.",
            case_id=1,
            current_user=_ADMIN,
        )

    assert result["answer"].startswith("✅")

    mock_log_case_event.assert_called_once()
    case_args = mock_log_case_event.call_args.args
    assert case_args[0] == 1
    assert case_args[1] == "AI_TASK_CREATED"

    mock_log_security_event.assert_called_once()
    sec_args = mock_log_security_event.call_args.args
    sec_kwargs = mock_log_security_event.call_args.kwargs
    assert sec_args[0] == "1"  # falls back to id: _ADMIN has no "username" key
    assert sec_args[1] == "AI_TASK_CREATED"
    assert sec_kwargs.get("success") is True


# ---------------------------------------------------------------------
# Test 2: ADMIN requests a workflow review/advance -> compliance rules
# (blockers) are still respected, and AI_WORKFLOW_REVIEWED is audited.
# ---------------------------------------------------------------------

def test_admin_advance_workflow_is_audited_as_reviewed_not_advanced():
    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=Intent.ADVANCE_WORKFLOW), \
         patch("db.database.role_has_permission", _role_has_permission_factory({"ai:use", "cases:edit"})), \
         patch(
             "core.ai.agent.orchestrator.recommend_workflow_advance",
             return_value="Blocking documents remain - a human should confirm before advancing.",
         ), \
         patch("core.ai.agent.audit.log_case_event") as mock_log_case_event, \
         patch("core.ai.agent.audit.log_security_event") as mock_log_security_event:

        result = agent.run_agent(
            "Advance this case to SUBMITTED.",
            case_id=1,
            current_user=_ADMIN,
        )

    assert "answer" in result
    # No blocker-bypass: the recommendation tool is still the only
    # thing that ever runs for this intent - nothing here mutates state.
    mock_log_security_event.assert_called_once()
    sec_args = mock_log_security_event.call_args.args
    assert sec_args[1] == "AI_WORKFLOW_REVIEWED"


# ---------------------------------------------------------------------
# Test 3: VIEWER attempts a forbidden action -> denied, AI_ACTION_DENIED
# audited with success=False.
# ---------------------------------------------------------------------

def test_viewer_delete_is_denied_and_audited():
    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=Intent.DELETE_CASE), \
         patch("db.database.role_has_permission", _role_has_permission_factory(set())), \
         patch("core.ai.agent.audit.log_case_event") as mock_log_case_event, \
         patch("core.ai.agent.audit.log_security_event") as mock_log_security_event:

        result = agent.run_agent(
            "Delete this case.",
            case_id=1,
            current_user={"id": 2, "role": "VIEWER", "company": "Default Company"},
        )

    assert result["answer"].startswith("Action denied:")

    # Denials never touch the case timeline - only the security log.
    mock_log_case_event.assert_not_called()

    mock_log_security_event.assert_called_once()
    sec_args = mock_log_security_event.call_args.args
    sec_kwargs = mock_log_security_event.call_args.kwargs
    assert sec_args[1] == "AI_ACTION_DENIED"
    assert sec_kwargs.get("success") is False


def test_unauthenticated_action_is_not_audited():
    # No authenticated identity exists to attribute an audit record to.
    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=Intent.DELETE_CASE), \
         patch("core.ai.agent.audit.log_case_event") as mock_log_case_event, \
         patch("core.ai.agent.audit.log_security_event") as mock_log_security_event:

        result = agent.run_agent(
            "Delete this case.", case_id=1, current_user=None
        )

    assert result["answer"] == "Authentication required."
    mock_log_case_event.assert_not_called()
    mock_log_security_event.assert_not_called()


# ---------------------------------------------------------------------
# Test 4: audit logging failure must never break an already-succeeded
# business action (best-effort, non-blocking).
# ---------------------------------------------------------------------

def test_audit_logging_failure_never_breaks_a_successful_action():
    fake_chat_response = {
        "message": {
            "tool_calls": [
                {
                    "function": {
                        "name": "create_task_for_case",
                        "arguments": {"case_id": 1, "title": "Follow up"},
                    }
                }
            ]
        }
    }

    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=Intent.CREATE_TASK), \
         patch("db.database.role_has_permission", _role_has_permission_factory({"ai:use", "tasks:edit"})), \
         patch("core.ai.agent.tool_execution.chat", return_value=fake_chat_response), \
         patch(
             "core.ai.agent.tool_execution.AVAILABLE_TOOLS",
             {"create_task_for_case": lambda case_id, title: f"Task '{title}' created for case {case_id}."},
         ), \
         patch("core.ai.agent.audit.log_case_event", side_effect=RuntimeError("DB is down")), \
         patch("core.ai.agent.audit.log_security_event", side_effect=RuntimeError("DB is down")):

        result = agent.run_agent(
            "Create a task to follow up.", case_id=1, current_user=_ADMIN
        )

    # The real, already-completed tool action still reaches the user
    # normally - audit logging is best-effort and never surfaces here.
    assert result["answer"].startswith("✅")
