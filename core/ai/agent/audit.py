"""
Enterprise Audit Trail integration for AI Agent actions.

Reuses the two audit helpers that already exist in db.database
(log_case_event, log_security_event) - both already resolve tenant_id
internally (from case_id or from the username's own record) and are
already used elsewhere in the app (auth/service.py,
core/case/repository.py, core/ai/operator.py). No new audit tables, no
new schema, no duplicated logging system: this module is only the
call from the AI Agent's own execution points into that existing
infrastructure.
"""

from db.database import log_case_event, log_security_event


def audit_username(current_user: dict) -> str:
    # log_security_event's `username` column is how it looks up the
    # tenant_id to attach to the row (see db.database.log_security_event).
    # current_user is guaranteed non-None here (every call site using
    # this module runs only after the RBAC gate has already required a
    # real authenticated caller), but "username" is not itself a
    # documented required key of current_user (run_agent's contract
    # only guarantees "role") - so this falls back to "id", then to a
    # clearly-marked placeholder, rather than raising or silently
    # attributing the action to the wrong identity.
    return str(
        current_user.get("username")
        or current_user.get("id")
        or "unknown-ai-caller"
    )


def audit_ai_action(
    current_user: dict,
    case_id: int,
    event_type: str,
    description: str,
    success: bool,
) -> None:
    """
    Records one AI Agent action as an immutable audit event, using the
    existing audit infrastructure only:

      - case_events: the case-level timeline. Only written on success -
        an attempt that changed nothing is not a case event.
      - security_audit_log: the compliance/traceability log. Always
        written, success or failure, since "the AI attempted this and
        it was/was not allowed to happen" is exactly what compliance,
        GDPR-oriented accountability, and HR review need to be able to
        reconstruct.

    Audit logging is best-effort and must never be able to break or
    mask an already-completed business action: if either underlying
    helper raises (e.g. a transient DB error), that failure is
    swallowed here rather than propagated, exactly like the existing
    webhook-dispatch failure handling inside log_case_event itself.
    """

    username = audit_username(current_user)

    try:
        if success:
            log_case_event(case_id, event_type, description)
    except Exception:
        pass

    try:
        log_security_event(username, event_type, description, success=success)
    except Exception:
        pass
