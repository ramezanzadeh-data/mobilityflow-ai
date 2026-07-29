ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_STAFF = "STAFF"
ROLE_VIEWER = "VIEWER"

VALID_ROLES = [ROLE_ADMIN, ROLE_MANAGER, ROLE_STAFF, ROLE_VIEWER]

# What an unrecognised or missing role is treated as.
#
# This was STAFF, which meant an unknown role silently received
# cases:edit, documents:edit, tasks:edit and ai:use - write access that
# nobody granted. The failure mode was a typo: a user intended as VIEWER
# but saved as "VIEWR" became a STAFF account with no error raised
# anywhere, so a read-only auditor quietly gained the ability to modify
# case data.
#
# VIEWER is the least-privileged role in the matrix. An unrecognised role
# is a configuration fault, and the safe response to a fault in an
# authorisation decision is to grant the minimum, never a middle tier.
#
# This is a fallback, not the fix: create_user() now rejects unknown
# roles outright (db.database.create_user), so a role should never reach
# here unrecognised. This is the second layer, for rows that predate the
# validation or arrive through some path that bypasses it.
FALLBACK_ROLE = ROLE_VIEWER


def normalize_role(role):

    if not role:
        return FALLBACK_ROLE

    normalized = role.strip().upper()

    if normalized in VALID_ROLES:
        return normalized

    return FALLBACK_ROLE


def is_admin(user):

    if not user:
        return False

    return normalize_role(user.get("role")) == ROLE_ADMIN


def has_permission(user, permission_name):
    """
    The real RBAC check - looks the role up against the enterprise
    permission matrix (db.database._ROLE_PERMISSIONS) rather than only
    ever asking "is this an admin?". Kept here (not just in the API
    dependency) so both the API and the Streamlit app share one source
    of truth for what each role can do.
    """

    if not user:
        return False

    from db.database import role_has_permission

    return role_has_permission(normalize_role(user.get("role")), permission_name)


def can_delete_case(user):

    return has_permission(user, "cases:delete")


def can_manage_email_templates(user):

    return has_permission(user, "templates:manage")


def can_export_reports(user):

    return has_permission(user, "reports:export")


def can_view_security_audit_log(user):

    return has_permission(user, "audit:view")


def can_manage_users(user):

    return has_permission(user, "users:manage")


def can_manage_webhooks(user):

    return has_permission(user, "webhooks:manage")
