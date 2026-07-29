import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.ai.intent import Intent
from core.ai import tool_policy


def _permissions_for(role_permissions: dict):
    """Build a fake role_has_permission(role, permission) callable."""

    def fake_role_has_permission(role, permission_name):
        return permission_name in role_permissions.get(role, set())

    return fake_role_has_permission


def test_read_only_intents_never_need_permission():
    for intent in (Intent.ANALYZE, Intent.STATUS, Intent.CHECK_BLOCKERS):
        decision = tool_policy.check_operational_permission(intent, current_user=None)
        assert decision.allowed


def test_operational_intent_denied_when_no_user():
    decision = tool_policy.check_operational_permission(
        Intent.APPROVE_CASE, current_user=None
    )
    assert not decision.allowed


def test_viewer_role_cannot_approve_case():
    fake = _permissions_for({"VIEWER": set()})

    with patch("db.database.role_has_permission", fake):
        decision = tool_policy.check_operational_permission(
            Intent.APPROVE_CASE, current_user={"role": "VIEWER"}
        )

    assert not decision.allowed


def test_manager_role_can_approve_case():
    fake = _permissions_for({"MANAGER": {"ai:use", "cases:approve"}})

    with patch("db.database.role_has_permission", fake):
        decision = tool_policy.check_operational_permission(
            Intent.APPROVE_CASE, current_user={"role": "MANAGER"}
        )

    assert decision.allowed


def test_staff_role_has_ai_use_but_not_approve():
    # STAFF can use the AI agent for reasoning/create_task, but the
    # permission matrix does not grant cases:approve to STAFF.
    fake = _permissions_for({"STAFF": {"ai:use", "tasks:edit"}})

    with patch("db.database.role_has_permission", fake):
        create_task_decision = tool_policy.check_operational_permission(
            Intent.CREATE_TASK, current_user={"role": "STAFF"}
        )
        approve_decision = tool_policy.check_operational_permission(
            Intent.APPROVE_CASE, current_user={"role": "STAFF"}
        )

    assert create_task_decision.allowed
    assert not approve_decision.allowed


def test_role_without_ai_use_is_denied_regardless_of_specific_permission():
    # Even if a role somehow had cases:approve without ai:use, the
    # baseline ai:use check must still block it.
    fake = _permissions_for({"ODDROLE": {"cases:approve"}})

    with patch("db.database.role_has_permission", fake):
        decision = tool_policy.check_operational_permission(
            Intent.APPROVE_CASE, current_user={"role": "ODDROLE"}
        )

    assert not decision.allowed
