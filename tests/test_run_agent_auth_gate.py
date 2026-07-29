import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.ai import agent
from core.ai.intent import Intent


def _fake_context():
    return {
        "case": {"id": 42, "status": "IN_PROGRESS"},
        "workflow": {"current_state": "DOCUMENT_COLLECTION"},
        "documents": {"missing_documents": [], "risk_factors": []},
        "recommendation": {"blocking_items": [], "reason": None},
    }


def test_on_step_is_keyword_only_so_current_user_cannot_be_swallowed_by_it():
    """
    Regression test for the actual authentication-gate bug: on_step
    used to sit between case_id and current_user in run_agent's
    signature, so a caller passing current_user as the 3rd positional
    argument (a very natural reading of "goal, case, who's asking")
    would silently have it absorbed by on_step instead, leaving
    current_user at its None default and causing every authenticated
    ACTION request to fail with "Authentication required.".

    on_step is now keyword-only, so that mistake is a loud TypeError
    instead of a silent auth failure.
    """

    signature = inspect.signature(agent.run_agent)
    parameters = list(signature.parameters.values())

    current_user_param = signature.parameters["current_user"]
    on_step_param = signature.parameters["on_step"]

    assert on_step_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert current_user_param.kind != inspect.Parameter.KEYWORD_ONLY

    # current_user must come before on_step in declaration order, so
    # `run_agent(goal, case_id, current_user)` (3 positional args) maps
    # current_user correctly even if on_step were ever made positional
    # again in the future.
    assert parameters.index(current_user_param) < parameters.index(on_step_param)

    # A 4th positional argument (attempting to pass on_step
    # positionally, the old broken pattern) is now a loud TypeError
    # instead of a silent auth failure, since on_step is keyword-only.
    with pytest.raises(TypeError):
        agent.run_agent("goal", 42, {"role": "MANAGER"}, lambda step: None)


def test_authenticated_action_executes_the_real_tool_when_passed_positionally():
    """
    The primary contract this fix restores: calling run_agent with
    current_user as the 3rd positional argument (goal, case_id,
    current_user) - the exact pattern the old signature silently
    broke - must reach the real tool, not "Authentication required.".
    """

    with patch(
        "core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()
    ), patch(
        "core.ai.agent.orchestrator.classify_intent", return_value=Intent.CREATE_TASK
    ), patch(
        "db.database.role_has_permission",
        side_effect=lambda role, perm: perm in {"ai:use", "tasks:edit"},
    ), patch(
        "core.ai.agent.tool_execution.AVAILABLE_TOOLS",
        {"create_task_for_case": lambda case_id, title: f"Task '{title}' created for case {case_id}."},
    ), patch(
        "core.ai.agent.tool_execution.chat",
        return_value={
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "create_task_for_case",
                            "arguments": {"case_id": 42, "title": "Follow up"},
                        }
                    }
                ]
            }
        },
    ):
        result = agent.run_agent(
            "Create a task to follow up.", 42, {"role": "STAFF"}
        )

    assert result["answer"] == "✅ Task 'Follow up' created for case 42."
    assert result["answer"] != "Authentication required."


def test_unauthenticated_action_still_returns_authentication_required():
    with patch("core.ai.agent.orchestrator.build_agent_context", return_value=_fake_context()), \
         patch("core.ai.agent.orchestrator.classify_intent", return_value=Intent.CREATE_TASK):
        result = agent.run_agent(
            "Create a task to follow up.", case_id=42, current_user=None
        )

    assert result["answer"] == "Authentication required."
